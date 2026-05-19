"""
auth.py — Google OAuth2 + HMAC server-side sessions.

Session token stored in httpOnly cookie "wa_session".
Dev bypass: if GOOGLE_CREDENTIALS_JSON is not set, get_current_user returns "dev@local".
"""
from __future__ import annotations

import hashlib as _hashlib
import hmac as _hmac
import json as _json
import logging
import os
import secrets
import time
from typing import Optional

from fastapi import Request

log = logging.getLogger(__name__)

_SESSION_SECRET = os.getenv("SESSION_SECRET", "weather-default-secret")
_SESSION_DAYS   = 30
SESSION_COOKIE  = "wa_session"

# In-memory session store — process-lifetime
_sessions: dict[str, dict] = {}


def _sign(sid: str) -> str:
    return _hmac.new(_SESSION_SECRET.encode(), sid.encode(), _hashlib.sha256).hexdigest()


def create_session(email: str) -> str:
    """Create session entry; return signed token 'sid.hmac'."""
    sid = secrets.token_urlsafe(32)
    cutoff = int(time.time()) - _SESSION_DAYS * 86400
    expired = [k for k, v in _sessions.items() if v.get("created", 0) < cutoff]
    for k in expired:
        del _sessions[k]
    _sessions[sid] = {"email": email, "created": int(time.time())}
    return f"{sid}.{_sign(sid)}"


def verify_session(token: str) -> Optional[str]:
    """Return email if token valid and not expired, else None."""
    try:
        sid, sig = token.rsplit(".", 1)
        if not _hmac.compare_digest(sig, _sign(sid)):
            return None
        entry = _sessions.get(sid)
        if not entry:
            return None
        if int(time.time()) - entry.get("created", 0) > _SESSION_DAYS * 86400:
            _sessions.pop(sid, None)
            return None
        return entry["email"]
    except Exception:
        return None


def delete_session(token: str) -> None:
    try:
        sid, _ = token.rsplit(".", 1)
        _sessions.pop(sid, None)
    except Exception:
        pass


def is_allowed(email: str) -> bool:
    """Check ALLOWED_USERS env var. Empty = allow all Google accounts."""
    raw = os.getenv("ALLOWED_USERS", "")
    rules = {e.strip().lower() for e in raw.split(",") if e.strip()}
    if not rules:
        return True
    for rule in rules:
        if rule.startswith("@") and email.lower().endswith(rule):
            return True
        if email.lower() == rule:
            return True
    return False


def get_google_creds() -> Optional[dict]:
    """Parse GOOGLE_CREDENTIALS_JSON env var → dict with client_id, client_secret etc."""
    raw = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
    if not raw or not raw.startswith("{"):
        return None
    try:
        parsed = _json.loads(raw)
        return parsed.get("web") or parsed  # handle both {"web": {...}} and bare dict
    except Exception:
        return None


def get_current_user(request: Request) -> str:
    """
    FastAPI dependency: verify session cookie → return email.
    Dev bypass: if GOOGLE_CREDENTIALS_JSON not set → return 'dev@local'.
    """
    if not get_google_creds():
        return "dev@local"

    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        return ""  # caller decides whether to 401

    return verify_session(token) or ""
