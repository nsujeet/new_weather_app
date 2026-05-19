"""
api/auth_routes.py — Google OAuth2 login/callback/me/logout endpoints.

Flow:
  GET /api/auth/login    → redirect to Google OAuth consent page
  GET /api/auth/callback → exchange code, set session cookie, redirect to /
  GET /api/auth/me       → return {email} or 401
  GET /api/auth/logout   → clear cookie + session, redirect to /
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from auth import (
    SESSION_COOKIE,
    create_session,
    delete_session,
    get_current_user,
    get_google_creds,
    is_allowed,
    verify_session,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth")

_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_INFO_URL  = "https://www.googleapis.com/oauth2/v3/userinfo"


def _redirect_uri(request: Request) -> str:
    override = os.getenv("REDIRECT_URI", "")
    if override:
        return override.rstrip("/")
    # Use forwarded headers so Railway's HTTPS proxy is detected correctly
    # (request.base_url gives http:// because internal traffic is plain HTTP)
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host  = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}/api/auth/callback"


@router.get("/login")
def login(request: Request):
    creds = get_google_creds()
    if not creds:
        raise HTTPException(status_code=503, detail="Google OAuth not configured")

    from authlib.integrations.requests_client import OAuth2Session
    oauth = OAuth2Session(
        client_id=creds["client_id"],
        redirect_uri=_redirect_uri(request),
        scope="openid email profile",
    )
    auth_url, _ = oauth.create_authorization_url(_AUTH_URL, access_type="offline")
    return RedirectResponse(auth_url)


@router.get("/callback")
def callback(request: Request, code: str = "", error: str = ""):
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")

    creds = get_google_creds()
    if not creds:
        raise HTTPException(status_code=503, detail="Google OAuth not configured")

    from authlib.integrations.requests_client import OAuth2Session
    oauth = OAuth2Session(
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
        redirect_uri=_redirect_uri(request),
    )
    try:
        oauth.fetch_token(_TOKEN_URL, code=code, grant_type="authorization_code")
        info  = oauth.get(_INFO_URL).json()
        email = info.get("email", "").lower()
        name  = info.get("name", email)
    except Exception as e:
        log.warning("OAuth callback failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Authentication failed: {e}")

    if not email:
        raise HTTPException(status_code=400, detail="No email returned from Google")

    if not is_allowed(email):
        raise HTTPException(status_code=403, detail=f"Access denied for {email}")

    session_token = create_session(email)

    try:
        from utils.logger import log_event
        log_event(email, "login", name)
    except Exception:
        pass

    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        httponly=True,
        samesite="lax",
        max_age=30 * 86400,
        path="/",
    )
    return response


@router.get("/me")
def me(request: Request):
    email = get_current_user(request)
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return {"email": email}


@router.get("/logout")
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE, "")
    delete_session(token)
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
