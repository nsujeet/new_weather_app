"""
utils/logger.py

Two-tier logging:
  Tier 1 — stdout via Python logging (always on, Railway captures it)
  Tier 2 — Google Sheets append in a background thread (non-blocking, key events only)

Required env vars for Sheets tier:
    GOOGLE_SERVICE_ACCOUNT_JSON  — service account key JSON (full JSON string)
    USERS_SHEET_ID               — Google Sheet ID

Key events sent to Sheets: login, site_confirmed, station_confirmed, noaa_fetch, stage6_done
Chat events go to a separate tab: new_weather_app_chatbot
"""

import os
import json
import logging
import threading
from datetime import datetime

_logger   = logging.getLogger("weather_app")
_SHEET_ID = os.getenv("USERS_SHEET_ID", "1Vhrsi3ygKEMjanrD6p48MvIoTJNH8dfXXycoAEN1who")
_TAB      = "new_weather_app"
_CHAT_TAB = "new_weather_app_chatbot"
_HEADERS      = ["timestamp", "email", "action", "detail"]
_CHAT_HEADERS = ["timestamp", "email", "stage", "tokens_used", "question", "answer_preview", "context_brief"]
_SCOPES   = ["https://www.googleapis.com/auth/spreadsheets"]

_SHEETS_EVENTS = {"login", "site_confirmed", "station_confirmed", "noaa_fetch", "stage3_done", "stage6_done"}


def _get_service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        return None
    creds = Credentials.from_service_account_info(json.loads(raw), scopes=_SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _ensure_tab(service, tab: str, headers: list[str]):
    """Create the worksheet and write headers if it doesn't exist."""
    meta = service.spreadsheets().get(spreadsheetId=_SHEET_ID).execute()
    tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if tab not in tabs:
        service.spreadsheets().batchUpdate(
            spreadsheetId=_SHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=_SHEET_ID,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            body={"values": [headers]},
        ).execute()


def _sheets_append(email: str, action: str, detail: str):
    """Write one row to the main events tab. Runs in a background thread."""
    try:
        service = _get_service()
        if not service:
            return
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        _ensure_tab(service, _TAB, _HEADERS)
        service.spreadsheets().values().append(
            spreadsheetId=_SHEET_ID,
            range=f"{_TAB}!A:D",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [[now, email, action, detail[:300]]]},
        ).execute()
    except Exception as exc:
        _logger.warning("sheets log failed: %s", exc)


def _sheets_append_chat(
    email: str,
    stage: str,
    tokens_used: int,
    question: str,
    answer: str,
    context_brief: str,
):
    """Write one chat row to the chatbot tab. Runs in a background thread."""
    try:
        service = _get_service()
        if not service:
            return
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        _ensure_tab(service, _CHAT_TAB, _CHAT_HEADERS)
        service.spreadsheets().values().append(
            spreadsheetId=_SHEET_ID,
            range=f"{_CHAT_TAB}!A:G",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [[
                now,
                email,
                stage,
                tokens_used,
                question[:1000],
                answer[:500],
                context_brief[:300],
            ]]},
        ).execute()
    except Exception as exc:
        _logger.warning("sheets chat log failed: %s", exc)


def log_event(email: str, action: str, detail: str = ""):
    """
    Log an event.
    Always writes to stdout. For key business events, also appends to Google Sheets
    in a background thread (non-blocking).
    """
    _logger.info("user=%s action=%s detail=%s", email, action, detail)

    has_sa = bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip())
    if has_sa and action in _SHEETS_EVENTS:
        threading.Thread(
            target=_sheets_append,
            args=(email, action, detail),
            daemon=True,
        ).start()


def log_chat(
    email: str,
    stage: str,
    tokens_used: int,
    question: str,
    answer: str,
    context: dict,
):
    """
    Log a chat Q&A exchange to stdout and the chatbot Sheets tab.
    context dict is used to build a brief summary (station, years, filter).
    """
    context_brief = json.dumps({
        k: context.get(k)
        for k in ("stage", "selectedStation", "selectedYears", "design_conditions")
        if context.get(k) is not None
    }, default=str)

    _logger.info(
        "chat user=%s stage=%s tokens=%d q=%s a=%s",
        email, stage, tokens_used, question[:120], answer[:120],
    )

    has_sa = bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip())
    if has_sa:
        threading.Thread(
            target=_sheets_append_chat,
            args=(email, stage, tokens_used, question, answer, context_brief),
            daemon=True,
        ).start()
