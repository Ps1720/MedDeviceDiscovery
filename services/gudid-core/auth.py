"""
Access gate.

The rule: no route serves patient data without a session, and the session
decides which FHIR server that data comes from. Absence of a session is never a
data source — it is a 401.

Two ways to get a session:

  SMART App Launch   the EHR authenticates the clinician and scopes the token;
                     the session's FHIR target is the launched server
                     (see smart_launch.py)

  Local sign-in      a shared passcode for the synthetic-data deployment; the
                     session's FHIR target is the local HAPI server

A shared passcode is deliberate, not a shortcut. This is a single-tenant
demo/pilot over synthetic data; standing up a user table with password hashes
would be more code and weaker security than delegating real identity to SMART.
Anything touching real patients goes through the EHR.

Endpoints are gated by default. `PUBLIC_ENDPOINTS` is an explicit allowlist, so
a newly added route is closed until someone decides otherwise.
"""

from __future__ import annotations

import hmac
import time
from typing import Optional

from flask import jsonify, redirect, request, session, url_for

from config import Config

# Endpoint names (Flask `request.endpoint`), not URL paths.
PUBLIC_ENDPOINTS = {
    # health / conformance — must stay reachable for monitoring and for a
    # reverse proxy's upstream check
    "health_check",
    "smart.well_known",
    # the SMART handshake itself must be reachable before a session exists
    "smart.launch",
    "smart.launch_standalone",
    "smart.callback",
    "smart.status",
    "smart.logout",
    # local sign-in
    "auth.login",
    "auth.logout",
    # static assets
    "static",
}

_SESSION_KEY = "local_auth"


def is_public(endpoint: Optional[str]) -> bool:
    return endpoint is None or endpoint in PUBLIC_ENDPOINTS


def enabled() -> bool:
    """Whether the gate is enforced. Off only for local development."""
    return Config.REQUIRE_AUTH


def local_session() -> Optional[dict]:
    """The local (non-SMART) session, if one is live."""
    data = session.get(_SESSION_KEY)
    if not data:
        return None
    if data.get("expires_at", 0) < int(time.time()):
        session.pop(_SESSION_KEY, None)
        return None
    return data


def sign_in(passcode: str) -> bool:
    """Validate the shared passcode and start a local session."""
    expected = Config.DEMO_PASSCODE or ""
    if not expected:
        return False
    # constant-time comparison so the check does not leak the passcode's prefix
    if not hmac.compare_digest(passcode or "", expected):
        return False
    session[_SESSION_KEY] = {
        "kind": "local",
        "started_at": int(time.time()),
        "expires_at": int(time.time()) + Config.SESSION_TTL_SECONDS,
    }
    session.permanent = True
    return True


def sign_out() -> None:
    session.pop(_SESSION_KEY, None)


def wants_json() -> bool:
    """True when an unauthenticated caller should get JSON rather than a redirect."""
    if request.path.startswith("/api/"):
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def deny():
    """The response for an unauthenticated request to a gated endpoint."""
    if wants_json():
        return (
            jsonify(
                {
                    "error": "authentication required",
                    "detail": "Launch this app from your EHR (SMART App Launch), "
                    "or sign in at /login for the synthetic-data deployment.",
                    "launch_url": "/launch/standalone",
                    "login_url": "/login",
                }
            ),
            401,
        )
    return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
