"""
utils/logger.py

Two-tier logging:
  Tier 1 — stdout via Python logging (always on, Railway captures it)
  Tier 2 — Google Sheets append in a background thread (non-blocking, key events only)

Required env vars for Sheets tier:
    GOOGLE_SERVICE_ACCOUNT_JSON  — service account key JSON (full JSON string)
    USERS_SHEET_ID               — Google Sheet ID

Key events sent to Sheets: login, site_confirmed, station_confirmed, noaa_fetch, stage6_done, agent_query
"""

import os
import json
import logging
import threading
from datetime import datetime

_logger   = logging.getLogger("weather_app")
_SHEET_ID = os.getenv("USERS_SHEET_ID", "1Vhrsi3ygKEMjanrD6p48MvIoTJNH8dfXXycoAEN1who")
_TAB      = "new_weather_app"
_HEADERS  = ["timestamp", "email", "action", "detail"]
_SCOPES   = ["https://www.googleapis.com/auth/spreadsheets"]

_SHEETS_EVENTS = {"login", "site_confirmed", "station_confirmed", "noaa_fetch", "stage3_done", "stage6_done", "agent_query"}


def _sheets_append(email: str, action: str, detail: str):
    """Write one row to Google Sheets. Runs in a background thread."""
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if not raw:
            return
        creds   = Credentials.from_service_account_info(json.loads(raw), scopes=_SCOPES)
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)

        now  = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        meta = service.spreadsheets().get(spreadsheetId=_SHEET_ID).execute()
        tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]
        if _TAB not in tabs:
            service.spreadsheets().batchUpdate(
                spreadsheetId=_SHEET_ID,
                body={"requests": [{"addSheet": {"properties": {"title": _TAB}}}]},
            ).execute()
            service.spreadsheets().values().update(
                spreadsheetId=_SHEET_ID,
                range=f"{_TAB}!A1",
                valueInputOption="RAW",
                body={"values": [_HEADERS]},
            ).execute()

        service.spreadsheets().values().append(
            spreadsheetId=_SHEET_ID,
            range=f"{_TAB}!A:D",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [[now, email, action, detail[:300]]]},
        ).execute()
    except Exception as exc:
        _logger.warning("sheets log failed: %s", exc)


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
