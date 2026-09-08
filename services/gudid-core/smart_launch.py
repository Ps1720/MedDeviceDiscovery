"""
SMART App Launch v2 — EHR launch + standalone launch (Build.md Phase 6).

Public client + PKCE, no client secret. Implemented with `requests` + stdlib
only (no extra dependency). Tested against the SMART Health IT sandbox launcher
at https://launch.smarthealthit.org.

Flow
----
  EHR launch:   GET /launch?iss=<fhir base>&launch=<opaque>
  standalone:   GET /launch/standalone
                 -> discover {iss}/.well-known/smart-configuration
                 -> 302 to authorization_endpoint (with PKCE challenge, state)
  callback:     GET /smart/callback?code=...&state=...
                 -> POST token_endpoint (code + PKCE verifier)
                 -> stash {access_token, patient, ...} in the Flask session
                 -> 302 to /scan-to-chart?patient_id=<patient>

The rest of the app stays FHIR-server-agnostic: app.py reads
`session_fhir_context()` on every request and, when a SMART session is active,
points scan_to_chart's reads/writes at the launched FHIR server with the bearer
token.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Optional
from urllib.parse import quote, urlencode, urlparse

import requests
from flask import (
    Blueprint,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)

from config import Config

smart_bp = Blueprint("smart", __name__)

_DISCOVERY_TTL = 600  # seconds
_discovery_cache: dict[str, tuple[float, dict]] = {}
_HTTP_TIMEOUT = 15

# ---------------------------------------------------------------------------
# Token store
#
# Access/refresh tokens are SMART JWTs and routinely run 700-1500 chars each.
# Putting both in the Flask session pushes the signed cookie past the 4093-byte
# browser limit, and browsers drop an oversized cookie *silently* — the OAuth
# dance appears to succeed and then the app has no session. So the cookie holds
# only a random handle and the tokens live here, in-process.
#
# This assumes a single application process (Dockerfile runs gunicorn with
# --workers 1). With multiple workers a launch would only be visible to the
# worker that handled the callback; swap this for Redis or a DB table first.
# ---------------------------------------------------------------------------
_TOKEN_STORE: dict[str, dict] = {}
_STORE_TTL = 12 * 3600  # drop abandoned sessions after 12h


def _store_put(smart: dict) -> str:
    _store_gc()
    sid = secrets.token_urlsafe(24)
    _TOKEN_STORE[sid] = smart
    return sid


def _store_get(sid: Optional[str]) -> Optional[dict]:
    if not sid:
        return None
    return _TOKEN_STORE.get(sid)


def _store_drop(sid: Optional[str]) -> None:
    if sid:
        _TOKEN_STORE.pop(sid, None)


def _store_gc() -> None:
    cutoff = int(time.time()) - _STORE_TTL
    for sid, entry in list(_TOKEN_STORE.items()):
        if entry.get("launched_at", 0) < cutoff:
            _TOKEN_STORE.pop(sid, None)

# openFDA-style oauth-uris extension used by servers without a
# .well-known/smart-configuration document (older HAPI, some sandboxes).
_OAUTH_URIS_EXT = (
    "http://fhir-registry.smarthealthit.org/StructureDefinition/oauth-uris"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _safe_next(nxt: Optional[str]) -> str:
    """
    Post-login landing path. `next` arrives as a query param, so restrict it to
    a same-site absolute path — otherwise it is an open redirect.
    """
    if not nxt:
        return ""
    if not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt:
        return ""
    return nxt


def _sim_launch_param(iss: str) -> Optional[str]:
    """
    Launch-context parameter for a standalone launch, when the target needs one.

    A conformant standalone launch sends no `launch` parameter — the app asks
    for launch/patient and the auth server picks the context. The SMART Health
    IT sandbox is not conformant here: its authorize endpoint always decodes a
    `launch` value as base64url JSON "launch options", so omitting it fails with
    "Invalid launch options: SyntaxError: Unexpected end of JSON input".

    So supply the sandbox's simulation options when, and only when, the target
    is that sandbox. Every other server gets a standard standalone launch.
    """
    if not Config.SMART_SIM_HOSTS:
        return None
    host = (urlparse(iss).hostname or "").lower()
    if host not in {h.strip().lower() for h in Config.SMART_SIM_HOSTS.split(",") if h.strip()}:
        return None
    opts = json.dumps({"launch_type": Config.SMART_SIM_LAUNCH_TYPE})
    return _b64url(opts.encode("utf-8"))


def _redirect_uri() -> str:
    """
    Absolute URL of /smart/callback. Must be byte-identical in the authorize
    request and the token request, so it is computed once and stored in the tx.
    """
    if Config.APP_BASE_URL:
        return f"{Config.APP_BASE_URL}/smart/callback"
    # request.url_root already ends with "/"
    return request.url_root.rstrip("/") + url_for("smart.callback")


def _discover(iss: str) -> dict:
    """
    Resolve authorization_endpoint / token_endpoint for a FHIR base URL.
    Tries .well-known/smart-configuration, falls back to the CapabilityStatement.
    """
    iss = iss.rstrip("/")
    cached = _discovery_cache.get(iss)
    if cached and (time.time() - cached[0]) < _DISCOVERY_TTL:
        return cached[1]

    conf: dict = {}
    try:
        r = requests.get(
            f"{iss}/.well-known/smart-configuration",
            headers={"Accept": "application/json"},
            timeout=_HTTP_TIMEOUT,
        )
        if r.ok:
            body = r.json()
            conf = {
                "authorization_endpoint": body.get("authorization_endpoint"),
                "token_endpoint": body.get("token_endpoint"),
                "scopes_supported": body.get("scopes_supported"),
                "capabilities": body.get("capabilities"),
            }
    except (requests.RequestException, ValueError):
        conf = {}

    if not conf.get("authorization_endpoint") or not conf.get("token_endpoint"):
        # Fallback: CapabilityStatement -> rest[0].security.extension(oauth-uris)
        try:
            r = requests.get(
                f"{iss}/metadata",
                headers={"Accept": "application/fhir+json"},
                timeout=_HTTP_TIMEOUT,
            )
            r.raise_for_status()
            cap = r.json()
            for rest in cap.get("rest", []):
                for ext in (rest.get("security") or {}).get("extension", []):
                    if ext.get("url") != _OAUTH_URIS_EXT:
                        continue
                    for sub in ext.get("extension", []):
                        if sub.get("url") == "authorize":
                            conf["authorization_endpoint"] = sub.get("valueUri")
                        elif sub.get("url") == "token":
                            conf["token_endpoint"] = sub.get("valueUri")
        except (requests.RequestException, ValueError, KeyError):
            pass

    if not conf.get("authorization_endpoint") or not conf.get("token_endpoint"):
        raise RuntimeError(
            f"Could not discover SMART authorization/token endpoints for {iss}"
        )

    _discovery_cache[iss] = (time.time(), conf)
    return conf


def _decode_jwt_claims(token: Optional[str]) -> dict:
    """Best-effort, unverified decode of a JWT payload (for the fhirUser claim)."""
    if not token or token.count(".") < 2:
        return {}
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return {}


def _begin_launch(iss: str, launch: Optional[str], scope: str, nxt: str):
    """Shared authorize-redirect builder for EHR and standalone launches."""
    try:
        conf = _discover(iss)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    redirect_uri = _redirect_uri()

    session["smart_tx"] = {
        "state": state,
        "code_verifier": verifier,
        "iss": iss.rstrip("/"),
        "token_endpoint": conf["token_endpoint"],
        "redirect_uri": redirect_uri,
        "scope": scope,
        "next": nxt,
    }
    session.permanent = True

    params = {
        "response_type": "code",
        "client_id": Config.SMART_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "aud": iss.rstrip("/"),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if launch:
        params["launch"] = launch
    return redirect(f"{conf['authorization_endpoint']}?{urlencode(params)}")


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
@smart_bp.route("/launch")
def launch():
    """EHR launch entry point. The EHR calls this with `iss` and `launch`."""
    iss = (request.args.get("iss") or "").strip()
    launch_param = (request.args.get("launch") or "").strip() or None
    if not iss:
        return jsonify({"error": "missing iss parameter"}), 400
    return _begin_launch(
        iss, launch_param, Config.SMART_SCOPES, nxt=request.args.get("next") or ""
    )


@smart_bp.route("/launch/standalone")
def launch_standalone():
    """Standalone launch — no EHR context; auth server prompts for a patient."""
    iss = (request.args.get("iss") or Config.SMART_DEFAULT_ISS).strip()
    return _begin_launch(
        iss,
        _sim_launch_param(iss),
        Config.SMART_STANDALONE_SCOPES,
        nxt=request.args.get("next") or "",
    )


@smart_bp.route("/smart/callback")
def callback():
    """OAuth2 redirect target: exchange the code for tokens + patient context."""
    tx = session.get("smart_tx")
    err = request.args.get("error")
    if err:
        detail = request.args.get("error_description") or err
        return jsonify({"error": f"authorization failed: {detail}"}), 400
    if not tx:
        return jsonify({"error": "no launch in progress (session expired?)"}), 400
    if request.args.get("state") != tx.get("state"):
        return jsonify({"error": "state mismatch"}), 400

    code = request.args.get("code")
    if not code:
        return jsonify({"error": "missing authorization code"}), 400

    try:
        resp = requests.post(
            tx["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": tx["redirect_uri"],
                "client_id": Config.SMART_CLIENT_ID,
                "code_verifier": tx["code_verifier"],
            },
            headers={"Accept": "application/json"},
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        return jsonify({"error": f"token request failed: {exc}"}), 502

    if not resp.ok:
        return (
            jsonify({"error": "token exchange rejected", "detail": resp.text[:500]}),
            502,
        )

    tok = resp.json()
    claims = _decode_jwt_claims(tok.get("id_token"))
    now = int(time.time())
    smart = {
        "iss": tx["iss"],
        "token_endpoint": tx["token_endpoint"],
        "access_token": tok.get("access_token"),
        "refresh_token": tok.get("refresh_token"),
        "token_type": tok.get("token_type") or "Bearer",
        "scope": tok.get("scope") or tx["scope"],
        "expires_at": now + int(tok.get("expires_in") or 3600),
        "patient": tok.get("patient"),
        "encounter": tok.get("encounter"),
        "fhir_user": claims.get("fhirUser") or claims.get("profile"),
        "launched_at": now,
        "patient_name": None,
    }
    if not smart["access_token"]:
        return jsonify({"error": "token response contained no access_token"}), 502

    # Best-effort: resolve the patient's display name for the UI banner.
    if smart["patient"]:
        try:
            pr = requests.get(
                f"{smart['iss']}/Patient/{smart['patient']}",
                headers={
                    "Accept": "application/fhir+json",
                    "Authorization": f"{smart['token_type']} {smart['access_token']}",
                },
                timeout=_HTTP_TIMEOUT,
            )
            if pr.ok:
                smart["patient_name"] = _patient_display(pr.json())
        except requests.RequestException:
            pass

    session.pop("smart_tx", None)
    _store_drop(session.get("smart_sid"))
    session["smart_sid"] = _store_put(smart)
    session.permanent = True

    nxt = _safe_next(tx.get("next"))
    if not nxt:
        nxt = "/scan-to-chart"
        if smart["patient"]:
            nxt += f"?patient_id={quote(str(smart['patient']), safe='')}"
    return redirect(nxt)


@smart_bp.route("/smart/status")
def status():
    """JSON view of the current SMART session (for the UI banner / debugging)."""
    ctx = current_smart()
    return jsonify(ctx or {"connected": False})


@smart_bp.route("/smart/logout", methods=["GET", "POST"])
def logout():
    """Drop the SMART session (does not revoke the token at the auth server)."""
    _store_drop(session.pop("smart_sid", None))
    session.pop("smart_tx", None)
    if request.method == "GET":
        return redirect("/")
    return jsonify({"connected": False})


@smart_bp.route("/.well-known/smart-configuration")
def well_known():
    """
    Advertise this app's SMART capabilities. PeriopUDI is a client app, not a
    FHIR server, so this is informational — useful for competition conformance
    checks and for humans inspecting the deployment.
    """
    return jsonify(
        {
            "issuer": Config.APP_BASE_URL or request.url_root.rstrip("/"),
            "grant_types_supported": ["authorization_code"],
            "scopes_supported": Config.SMART_SCOPES.split(),
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
            # Only what this app actually implements (Build.md §5: never claim a
            # capability the demo doesn't touch). No authorize-post: the client
            # redirects with GET query params, not a form POST.
            "capabilities": [
                "launch-ehr",
                "launch-standalone",
                "client-public",
                "context-ehr-patient",
                "permission-patient",
            ],
        }
    )


# ---------------------------------------------------------------------------
# public API used by app.py
# ---------------------------------------------------------------------------
def _patient_display(patient: dict) -> Optional[str]:
    names = patient.get("name") or []
    if names:
        n = names[0]
        if n.get("text"):
            return n["text"]
        full = f"{' '.join(n.get('given', []) or [])} {n.get('family', '')}".strip()
        if full:
            return full
    return patient.get("id")


def _refresh_if_needed(smart: dict) -> Optional[dict]:
    """Refresh the access token when it is within 60s of expiry. Returns the
    updated dict, or None if the session is dead and cannot be refreshed."""
    if int(time.time()) < smart.get("expires_at", 0) - 60:
        return smart
    if not smart.get("refresh_token"):
        return None
    try:
        resp = requests.post(
            smart["token_endpoint"],
            data={
                "grant_type": "refresh_token",
                "refresh_token": smart["refresh_token"],
                "client_id": Config.SMART_CLIENT_ID,
                "scope": smart.get("scope") or Config.SMART_SCOPES,
            },
            headers={"Accept": "application/json"},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        tok = resp.json()
    except (requests.RequestException, ValueError):
        return None

    smart["access_token"] = tok.get("access_token", smart["access_token"])
    if tok.get("refresh_token"):
        smart["refresh_token"] = tok["refresh_token"]
    smart["expires_at"] = int(time.time()) + int(tok.get("expires_in") or 3600)
    return smart


def _live_session() -> Optional[dict]:
    """The active SMART session (token-store entry), refreshed if near expiry."""
    sid = session.get("smart_sid")
    smart = _store_get(sid)
    if not smart or not smart.get("access_token"):
        return None
    if _refresh_if_needed(smart) is None:
        _store_drop(sid)
        session.pop("smart_sid", None)
        return None
    return smart


def current_smart() -> Optional[dict]:
    """Summary of the active SMART session for templates, or None."""
    smart = _live_session()
    if smart is None:
        return None
    return {
        "connected": True,
        "patient": smart.get("patient"),
        "patient_name": smart.get("patient_name") or smart.get("patient"),
        "encounter": smart.get("encounter"),
        "fhir_user": smart.get("fhir_user"),
        "iss": smart.get("iss"),
        "scope": smart.get("scope"),
        "expires_in": max(0, smart.get("expires_at", 0) - int(time.time())),
    }


def session_fhir_context() -> Optional[tuple[str, dict]]:
    """
    (fhir_base_url, headers) for the launched FHIR server, or None when there is
    no live SMART session. Called by app.py on every request.
    """
    smart = _live_session()
    if smart is None:
        return None
    return (
        smart["iss"],
        {"Authorization": f"{smart.get('token_type', 'Bearer')} {smart['access_token']}"},
    )
