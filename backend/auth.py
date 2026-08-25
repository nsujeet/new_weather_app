"""
auth.py — Google OAuth2 + HMAC sessions, persisted in Postgres.

Sessions survive deploys: Postgres is primary, in-memory dict is a fast cache.
Falls back gracefully when DATABASE_URL is absent (dev / no-DB environments).
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

# In-memory cache — avoids a DB round-trip on every request
_cache: dict[str, dict] = {}   # sid → {email, created}

# ── Postgres helpers ──────────────────────────────────────────────

def _db_conn():
    """Return a new psycopg2 connection or None if DATABASE_URL not set."""
    url = os.getenv("DATABASE_URL", "")
    if not url:
        return None
    try:
        import psycopg2
        return psycopg2.connect(url)
    except Exception as e:
        log.warning("Session DB connect failed: %s", e)
        return None


def _ensure_table() -> None:
    conn = _db_conn()
    if not conn:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS wa_sessions (
                        sid        TEXT PRIMARY KEY,
                        email      TEXT NOT NULL,
                        created_at BIGINT NOT NULL,
                        expires_at BIGINT NOT NULL
                    )
                """)
    except Exception as e:
        log.warning("Session table create failed: %s", e)
    finally:
        conn.close()


def _db_write(sid: str, email: str, created: int) -> None:
    conn = _db_conn()
    if not conn:
        return
    expires = created + _SESSION_DAYS * 86400
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO wa_sessions (sid, email, created_at, expires_at) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT (sid) DO NOTHING",
                    (sid, email, created, expires),
                )
    except Exception as e:
        log.warning("Session DB write failed: %s", e)
    finally:
        conn.close()


def _db_read(sid: str) -> Optional[dict]:
    conn = _db_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT email, created_at FROM wa_sessions WHERE sid = %s AND expires_at > %s",
                (sid, int(time.time())),
            )
            row = cur.fetchone()
            return {"email": row[0], "created": row[1]} if row else None
    except Exception as e:
        log.warning("Session DB read failed: %s", e)
        return None
    finally:
        conn.close()


def _db_delete(sid: str) -> None:
    conn = _db_conn()
    if not conn:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM wa_sessions WHERE sid = %s", (sid,))
    except Exception as e:
        log.warning("Session DB delete failed: %s", e)
    finally:
        conn.close()


def _db_purge_expired() -> None:
    conn = _db_conn()
    if not conn:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM wa_sessions WHERE expires_at < %s", (int(time.time()),))
    except Exception:
        pass
    finally:
        conn.close()


# Create table on import (runs once at startup)
try:
    _ensure_table()
except Exception:
    pass

# ── HMAC signing ─────────────────────────────────────────────────

def _sign(sid: str) -> str:
    return _hmac.new(_SESSION_SECRET.encode(), sid.encode(), _hashlib.sha256).hexdigest()


# ── Public API ───────────────────────────────────────────────────

def create_session(email: str) -> str:
    """Create a new session, persist to Postgres and cache. Returns signed token."""
    sid     = secrets.token_urlsafe(32)
    created = int(time.time())
    _cache[sid] = {"email": email, "created": created}
    _db_write(sid, email, created)
    _db_purge_expired()
    return f"{sid}.{_sign(sid)}"


def verify_session(token: str) -> Optional[str]:
    """Return email if token is valid, else None. Checks cache first, then DB."""
    try:
        sid, sig = token.rsplit(".", 1)
        if not _hmac.compare_digest(sig, _sign(sid)):
            return None
    except Exception:
        return None

    cutoff = int(time.time()) - _SESSION_DAYS * 86400

    # Fast path: in-memory cache
    entry = _cache.get(sid)
    if entry:
        if entry.get("created", 0) < cutoff:
            _cache.pop(sid, None)
            _db_delete(sid)
            return None
        return entry["email"]

    # Survived a deploy: not in memory, check Postgres
    entry = _db_read(sid)
    if not entry:
        return None
    _cache[sid] = entry   # warm the cache for subsequent requests
    return entry["email"]


def delete_session(token: str) -> None:
    try:
        sid, _ = token.rsplit(".", 1)
        _cache.pop(sid, None)
        _db_delete(sid)
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
        return parsed.get("web") or parsed
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
        return ""

    return verify_session(token) or ""
