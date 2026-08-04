"""
guest_config.py — reads email/password pairs from Google Sheet.
Sheet columns: A=email, B=password. Cached 5 min.
Env vars: GOOGLE_SERVICE_ACCOUNT_JSON, GUEST_CONFIG_SHEET_ID
"""
import json, os, time
from typing import Optional

_cache: dict = {"users": None, "ts": 0.0}
_TTL = 300

_SHEET_ID = os.getenv("GUEST_CONFIG_SHEET_ID", "")
_RANGE    = "Sheet1!A:B"


def get_password_users() -> dict[str, str]:
    """Return {email: password} from sheet, cached 5 min."""
    now = time.time()
    if _cache["users"] is not None and now - _cache["ts"] < _TTL:
        return _cache["users"]

    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not creds_json or not _SHEET_ID:
        _cache.update({"users": {}, "ts": now})
        return {}

    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_service_account_info(
            json.loads(creds_json),
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )
        svc  = build("sheets", "v4", credentials=creds, cache_discovery=False)
        rows = (
            svc.spreadsheets().values()
            .get(spreadsheetId=_SHEET_ID, range=_RANGE)
            .execute()
            .get("values", [])
        )
        users = {
            r[0].strip().lower(): r[1].strip()
            for r in rows if len(r) >= 2 and r[0].strip()
        }
        _cache.update({"users": users, "ts": now})
        return users
    except Exception:
        _cache.update({"users": {}, "ts": now})
        return {}
