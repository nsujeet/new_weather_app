"""
pipeline/ashrae.py

Fetch ASHRAE climatic design conditions from ashrae-meteo.info.
Copied verbatim from G:/My Drive/Agent/fetch_ashrae_data.py (the working TIAC implementation).
Free public API — no key required.
"""

import math
import json
import requests
from typing import Optional

_BASE_URL = "https://ashrae-meteo.info/v3.0"
_VERSIONS = ["2025", "2021", "2017", "2013", "2009"]
_HEADERS = {
    "User-Agent":   "Mozilla/5.0",
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer":      "https://ashrae-meteo.info/v3.0/",
}

def get_ashrae_wmo(
    lat: float,
    lon: float,
    n_stations: int = 5,
    ashrae_version: str = "2025",
) -> dict:
    """
    Find nearest ASHRAE weather stations for a lat/lon.
    Returns {"stations": [...]} or {"error": "...", "stations": []}.
    Same interface as fetch_ashrae_data.get_ashrae_wmo in the TIAC repo.
    """
    try:
        resp = requests.post(
            f"{_BASE_URL}/request_places.php",
            data=f"lat={lat:.3f}&long={lon:.3f}&number=10&ashrae_version={ashrae_version}",
            headers=_HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}", "stations": []}
        text = resp.text.lstrip("﻿").strip()
        if not text:
            return {"error": "Empty response from ASHRAE API", "stations": []}
        raw = json.loads(text).get("meteo_stations", [])[:n_stations]
        stations = []
        for s in raw:
            s_lat  = float(s.get("lat", 0))
            s_lon  = float(s.get("long", 0))
            elev_m = float(s.get("elev", 0))
            stations.append({
                "station":    s.get("place", ""),
                "wmo":        s["wmo"],
                "dist_miles": round(_haversine_mi(lat, lon, s_lat, s_lon), 1),
                "elev_ft":    int(elev_m * 3.28084),
                "lat":        round(s_lat, 4),
                "lon":        round(s_lon, 4),
            })
        return {"stations": stations}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "stations": []}


def fetch_ashrae_conditions(
    wmo: str,
    level: str = "1",
    si_ip: str = "IP",
    ashrae_version: str = "2025",
) -> Optional[dict]:
    """
    Fetch ASHRAE design conditions for one WMO station.
    level: "0.4", "1", or "2"
    Returns None on failure.
    """
    versions = [ashrae_version] + [v for v in _VERSIONS if v != ashrae_version]
    for ver in versions:
        try:
            resp = requests.post(
                f"{_BASE_URL}/request_meteo_parametres.php",
                data=f"wmo={wmo}&ashrae_version={ver}&si_ip={si_ip}",
                headers=_HEADERS,
                timeout=15,
            )
            if resp.status_code == 500:
                continue
            if resp.status_code != 200:
                return None
            text = resp.text.lstrip("﻿").strip()
            if not text:
                continue
            data_list = json.loads(text).get("meteo_stations", [])
            if not data_list:
                continue
            data = dict(data_list[0])
            cond = _extract_level(data, level)
            if cond["tdb"] is None:
                continue
            return {
                "station":        data.get("place", f"WMO {wmo}"),
                "wmo":            wmo,
                "exceedance":     f"{level}%",
                "lat":            _f(data.get("lat")),
                "lon":            _f(data.get("long")),
                "tdb":            cond["tdb"],
                "mcwb":           cond["mcwb"] or 0.0,
                "twb":            cond["twb"]  or 0.0,
                "mcdb":           cond["mcdb"] or 0.0,
                "pressure_psia":  _f(data.get("stdp")),
                "raw":            data,
                "ashrae_version": ver,
            }
        except Exception:
            continue
    return None


def conditions_for_level(ashrae_conditions: dict, level: str) -> dict:
    """Switch exceedance level using cached raw data — no new API call."""
    raw  = ashrae_conditions.get("raw", {})
    cond = _extract_level(raw, level)
    return {
        **ashrae_conditions,
        "exceedance": f"{level}%",
        "tdb":  cond["tdb"]  or ashrae_conditions.get("tdb",  0.0),
        "mcwb": cond["mcwb"] or ashrae_conditions.get("mcwb", 0.0),
        "twb":  cond["twb"]  or ashrae_conditions.get("twb",  0.0),
        "mcdb": cond["mcdb"] or ashrae_conditions.get("mcdb", 0.0),
    }


# ── helpers ───────────────────────────────────────────────────

def _extract_level(data: dict, level: str) -> dict:
    return {
        "tdb":  _f(data.get(f"cooling_DB_MCWB_{level}_DB")),
        "mcwb": _f(data.get(f"cooling_DB_MCWB_{level}_MCWB")),
        "twb":  _f(data.get(f"evaporation_WB_MCDB_{level}_WB")),
        "mcdb": _f(data.get(f"evaporation_WB_MCDB_{level}_MCDB")),
    }


def _f(val) -> Optional[float]:
    try:
        return float(val) if val not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None


def _haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))
