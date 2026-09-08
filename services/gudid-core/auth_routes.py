"""Sign-in / sign-out routes for the local (synthetic-data) session."""

from __future__ import annotations

import time

from flask import Blueprint, redirect, render_template, request, url_for

import auth
from config import Config

auth_bp = Blueprint("auth", __name__)

# Crude per-process throttle on the shared passcode. Not a substitute for real
# rate limiting, but it makes an online guessing attack impractically slow on a
# single-worker deployment.
_ATTEMPTS: dict[str, list[float]] = {}
_WINDOW = 300  # seconds
_MAX_ATTEMPTS = 8


def _too_many_attempts(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _ATTEMPTS.get(ip, []) if now - t < _WINDOW]
    _ATTEMPTS[ip] = recent
    return len(recent) >= _MAX_ATTEMPTS


def _record_attempt(ip: str) -> None:
    _ATTEMPTS.setdefault(ip, []).append(time.time())


def _safe_next(nxt: str | None) -> str:
    """Only same-site absolute paths; anything else is an open redirect."""
    if not nxt or not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt:
        return "/"
    return nxt


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    nxt = _safe_next(request.args.get("next") or request.form.get("next"))
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()

    if request.method == "POST":
        if _too_many_attempts(ip):
            return (
                render_template(
                    "login.html",
                    error="Too many attempts. Wait a few minutes and try again.",
                    next=nxt,
                    passcode_configured=bool(Config.DEMO_PASSCODE),
                ),
                429,
            )
        if auth.sign_in(request.form.get("passcode", "")):
            return redirect(nxt)
        _record_attempt(ip)
        return (
            render_template(
                "login.html",
                error="Incorrect passcode.",
                next=nxt,
                passcode_configured=bool(Config.DEMO_PASSCODE),
            ),
            401,
        )

    return render_template(
        "login.html",
        error=None,
        next=nxt,
        passcode_configured=bool(Config.DEMO_PASSCODE),
    )


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    auth.sign_out()
    return redirect(url_for("auth.login"))
