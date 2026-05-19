"""
api/routes.py — all endpoints

Stages:
  POST /site/confirm        → elevation, pressure, Open-Meteo quick estimate
  GET  /stations            → ranked NOAA + ASHRAE stations for a lat/lon
  GET  /availability        → which years exist on NOAA for a station
  POST /fetch               → SSE stream: download NOAA years
  POST /process             → merge → filter → metadata → psychrometrics
  GET  /results/{token}     → return stored ProcessResult
  GET  /chart/psychrometric → render psychrometric PNG for a process result
"""

import asyncio
import json
import os
import time
import io
import base64
from typing import AsyncGenerator

# In-memory NOAA year cache: key = "STATION_YEAR", lives for the server process.
# No disk I/O — data is re-fetched from NOAA on server restart.
import pandas as _pd_cache
_years_cache: dict[str, _pd_cache.DataFrame] = {}

import numpy as np
import pandas as pd

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse, JSONResponse

from auth import get_current_user

from api.models import (
    SiteConfirmRequest,
    StationsRequest,
    AvailabilityRequest,
    FetchRequest,
    ProcessRequest,
    DesignConditionsRequest,
)

router = APIRouter()


def _resolve_email(request: Request | None) -> str:
    """
    Return the authenticated email for logging.
    Falls back to 'anonymous@<IP>' when the session is missing (e.g. after
    a server restart that wiped the in-memory session store).
    Never returns an empty string so Sheets rows are always identifiable.
    """
    if not request:
        return "unknown"
    email = get_current_user(request)
    if email:
        return email
    ip = (
        request.headers.get("x-forwarded-for", "")
        .split(",")[0].strip()
        or (request.client.host if request.client else "?")
    )
    return f"anonymous@{ip}"


# ── simple in-process result store (keyed by token) ──────────────
# Replace with Redis or DB for multi-worker prod deployment
_result_store: dict[str, dict] = {}

# ── per-user chat token budget (resets on server restart) ────────
# Prevents a single user from running up large API bills.
_CHAT_TOKEN_LIMIT = int(os.getenv("CHAT_TOKEN_LIMIT", "50000"))  # ~$0.05 at Haiku pricing
_user_tokens: dict[str, int] = {}   # email → cumulative input tokens used


# ─────────────────────────────────────────────────────────────────
#  /site/confirm  — elevation + pressure + Open-Meteo
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
#  /chat  — AI Q&A with weather analysis context
# ─────────────────────────────────────────────────────────────────

@router.post("/chat")
def chat_endpoint(request: dict, req: Request = None):
    import os
    import requests as _req

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not configured"}, status_code=503)

    message  = request.get("message", "")
    history  = request.get("history", [])   # [{role, content}]
    context  = request.get("context", {})
    stage    = context.get("stage", "unknown")

    try:
        from utils.logger import log_chat
        email = _resolve_email(req)
    except Exception:
        email = "unknown"

    # ── per-user token budget check ───────────────────────────────
    used = _user_tokens.get(email, 0)
    if used >= _CHAT_TOKEN_LIMIT:
        admin_email = os.getenv("ADMIN_EMAIL", "nsujeet@gmail.com")
        return JSONResponse(
            {"error": f"You've used your chat quota for this session. Please email {admin_email} to request more access."},
            status_code=429,
        )

    system = (
        "You are a technical assistant embedded in a weather analysis tool. "
        "You ONLY answer questions directly related to: weather data, NOAA stations, ASHRAE design conditions, "
        "psychrometrics, ERA5/Open-Meteo data, site elevation/pressure, data quality, freezing analysis, "
        "or how to use this specific app. "
        "If the user asks about ANYTHING else (coding, general knowledge, current events, other tools, etc.), "
        "respond with exactly: 'I can only help with weather analysis questions for this app.' "
        "Be concise — 2-4 sentences unless a technical explanation requires more.\n\n"
        f"Current app state: stage={stage}\n{json.dumps(context, indent=2, default=str)}"
    )

    messages = [*history[-8:], {"role": "user", "content": message}]

    def generator():
        reply_chunks = []
        tokens_used = 0
        try:
            resp = _req.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 512,
                    "system": system,
                    "messages": messages,
                    "stream": True,
                },
                stream=True,
                timeout=30,
            )
            for line in resp.iter_lines():
                if line and line.startswith(b"data: "):
                    data = line[6:]
                    try:
                        parsed = json.loads(data)
                        if parsed.get("type") == "content_block_delta":
                            text = parsed.get("delta", {}).get("text", "")
                            if text:
                                reply_chunks.append(text)
                                yield f"data: {json.dumps({'text': text})}\n\n"
                        elif parsed.get("type") == "message_delta":
                            # usage appears in the final message_delta event
                            usage = parsed.get("usage", {})
                            tokens_used = usage.get("output_tokens", 0)
                        elif parsed.get("type") == "message_start":
                            usage = parsed.get("message", {}).get("usage", {})
                            tokens_used += usage.get("input_tokens", 0)
                    except Exception:
                        pass
        except Exception as e:
            yield f"data: {json.dumps({'text': f'Error: {e}'})}\n\n"
        finally:
            # Update per-user token budget
            if tokens_used > 0:
                _user_tokens[email] = _user_tokens.get(email, 0) + tokens_used
            # Log Q&A to stdout + Sheets (chatbot tab)
            full_reply = "".join(reply_chunks)
            try:
                log_chat(email, stage, tokens_used, message, full_reply, context)
            except Exception:
                pass
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─────────────────────────────────────────────────────────────────
#  /geocode  — text search → lat/lon via Nominatim
# ─────────────────────────────────────────────────────────────────

@router.get("/geocode")
def geocode(q: str):
    import requests as _req
    try:
        r = _req.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 5},
            headers={"User-Agent": "weather-app/1.0"},
            timeout=6,
        )
        r.raise_for_status()
        results = r.json()
        return {"results": [
            {"display_name": x["display_name"], "lat": float(x["lat"]), "lon": float(x["lon"])}
            for x in results
        ]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@router.post("/site/confirm")
def site_confirm(req: SiteConfirmRequest, request: Request = None):
    from pipeline.geo_utils import get_elevation_m, calc_pressure_psi, get_timezone_name, get_utc_offset_hours

    ele_m = get_elevation_m(req.lat, req.lon) or 0.0
    pressure_psi = calc_pressure_psi(ele_m)
    tz_name = get_timezone_name(req.lat, req.lon) or "Unknown"
    utc_offset = get_utc_offset_hours(req.lat, req.lon)

    try:
        from utils.logger import log_event
        email = _resolve_email(request)
        log_event(email, "site_confirmed", f"{req.lat:.4f},{req.lon:.4f}")
    except Exception:
        pass

    return {
        "elevation_m": round(ele_m, 1),
        "elevation_ft": round(ele_m * 3.28084, 0),
        "pressure_psi": round(pressure_psi, 4),
        "pressure_kpa": round(pressure_psi * 6.8948, 4),
        "timezone": tz_name,
        "utc_offset_h": utc_offset,
    }


# ─────────────────────────────────────────────────────────────────
#  /stations — ranked NOAA + ASHRAE stations
# ─────────────────────────────────────────────────────────────────

@router.get("/stations")
def get_stations(lat: float, lon: float, elevation_m: float = 0.0):
    from pipeline.stations import load_station_list, find_nearest_stations, recommend_station
    from pipeline.ashrae import get_ashrae_wmo

    sdf    = load_station_list()
    ranked = find_nearest_stations(lat, lon, elevation_m, sdf, n=10)
    rec    = recommend_station(ranked)
    ashrae = get_ashrae_wmo(lat, lon, n_stations=5).get("stations", [])

    return {
        "noaa": ranked.to_dict(orient="records"),
        "recommended_station_id": rec.get("station_id"),
        "recommendation_message": rec.get("message"),
        "ashrae": ashrae,
    }


# ─────────────────────────────────────────────────────────────────
#  /score-filters — merge + clean + score without full pipeline
#  Returns filter options with coverage % so user can pick
# ─────────────────────────────────────────────────────────────────

def _get_or_build_merged(stored: dict) -> pd.DataFrame:
    """Return cached merged DataFrame, building from year JSON only if needed."""
    merged = stored.get("_merged_df")
    if merged is not None:
        return merged
    from pipeline.download import build_merged
    years_data = {
        int(yr): pd.read_json(io.StringIO(js))
        for yr, js in stored["years_data"].items()
    }
    merged = build_merged(years_data)
    stored["_merged_df"] = merged   # cache as live object — no re-parse next call
    return merged


def _apply_filter_direct(df3: pd.DataFrame, filter_key: str, min_year: int, max_year: int) -> pd.DataFrame:
    """
    Apply a named filter to df3 WITHOUT running score_filters (no pivot_tables).
    Recomputes best_value from df3 the same way score_filters does.
    """
    year_mask = (df3["DATE"].dt.year > min_year) & (df3["DATE"].dt.year <= max_year)

    def _idxmax(series):
        vc = series.value_counts()
        return vc.idxmax() if not vc.empty else None

    if filter_key == "report_type":
        best = _idxmax(df3["temperature_Report_Type"]) if "temperature_Report_Type" in df3.columns else None
        if best is None:
            return df3[year_mask].copy()
        return df3[(df3["temperature_Report_Type"] == best) & year_mask].copy()

    if filter_key == "minute_freq":
        best = _idxmax(df3["DATE"].dt.minute)
        if best is None:
            return df3[year_mask].copy()
        return df3[(df3["DATE"].dt.minute == best) & year_mask].copy()

    if filter_key == "minute_and_report":
        best_min = _idxmax(df3["DATE"].dt.minute)
        best_rep = _idxmax(df3["temperature_Report_Type"]) if "temperature_Report_Type" in df3.columns else None
        mask = pd.Series(True, index=df3.index)
        if best_min is not None:
            mask = mask & (df3["DATE"].dt.minute == best_min)
        if best_rep is not None:
            mask = mask & (df3["temperature_Report_Type"] == best_rep)
        return df3[mask & year_mask].copy()

    if filter_key.startswith("quality_temp"):
        best = _idxmax(df3["temperature_Quality_Code"]) if "temperature_Quality_Code" in df3.columns else None
        if best is None:
            return df3[year_mask].copy()
        return df3[(df3["temperature_Quality_Code"] == best) & year_mask].copy()

    return df3[year_mask].copy()


@router.post("/score-filters")
def score_filters_endpoint(token: str = Query(...), exclude_quality_codes: list[str] = Query(default=["2", "3"])):
    stored = _result_store.get(token)
    if not stored or stored.get("type") != "fetch":
        return JSONResponse({"error": "Fetch token not found"}, status_code=404)

    from pipeline.filtering import score_filters, clean_and_shift

    merged_df = _get_or_build_merged(stored)
    exclude = frozenset(exclude_quality_codes)

    df3, clean_qa = clean_and_shift(merged_df, delta_time=0, exclude_quality_codes=exclude)

    min_year = min(stored["years"])
    max_year = max(stored["years"])
    filter_results, best_key = score_filters(df3, min_year=min_year, max_year=max_year)

    # Cache best key + exclude set so /process can skip re-scoring
    stored["_filter_best"] = best_key
    stored["_scored_exclude"] = exclude

    filters_out = [
        {
            "name":         name,
            "label":        fr.label,
            "rows":         fr.rows,
            "coverage_pct": round(fr.coverage_pct, 1),
            "recommended":  fr.is_recommended,
        }
        for name, fr in filter_results.items()
    ]

    qa_dict = clean_qa if isinstance(clean_qa, dict) else {}

    return {
        "filters": sorted(filters_out, key=lambda x: -x["coverage_pct"]),
        "recommended": best_key,
        "total_rows": len(merged_df),
        "clean_qa": qa_dict,
    }


# ─────────────────────────────────────────────────────────────────
#  /availability — which years exist on NOAA
# ─────────────────────────────────────────────────────────────────

@router.get("/availability")
def check_availability(station_id: str, year_start: int = 2000, year_end: int = 2025):
    from pipeline.download import get_available_years
    years = get_available_years(station_id, range(year_start, year_end + 1), cache_dir="")
    return {"station_id": station_id, "available_years": sorted(years)}


# ─────────────────────────────────────────────────────────────────
#  /fetch  — SSE stream: download NOAA years with progress
# ─────────────────────────────────────────────────────────────────

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _fetch_stream(req: FetchRequest) -> AsyncGenerator[str, None]:
    from pipeline.download import fetch_years_incremental

    # Pre-populate from in-memory cache so repeated downloads are instant
    years_data: dict[int, pd.DataFrame] = {
        yr: _years_cache[f"{req.station_id}_{yr}"]
        for yr in req.years
        if f"{req.station_id}_{yr}" in _years_cache
    }
    total = len(req.years)

    yield _sse("start", {"total": total, "years": req.years})

    for i, result in enumerate(
        fetch_years_incremental(req.station_id, req.years, years_data, cache_dir="")
    ):
        status = result.get("status", "")
        year = result.get("year")
        rows = result.get("rows", 0)

        yield _sse("progress", {
            "i": i + 1,
            "total": total,
            "year": year,
            "status": status,
            "rows": rows,
            "pct": round((i + 1) / total * 100),
        })
        await asyncio.sleep(0)   # yield control so SSE flushes

    # Save downloaded years to in-memory session cache
    for yr, df in years_data.items():
        _years_cache[f"{req.station_id}_{yr}"] = df

    # Serialise fetched data to a token the /process endpoint can use
    token = f"{req.station_id}_{int(time.time())}"
    _result_store[token] = {
        "type": "fetch",
        "station_id": req.station_id,
        "years": sorted(years_data.keys()),
        "years_data": {yr: df.to_json(date_format="iso") for yr, df in years_data.items()},
    }

    yield _sse("done", {"token": token, "years_loaded": sorted(years_data.keys())})


@router.post("/fetch")
async def fetch_years(req: FetchRequest, request: Request = None):
    try:
        from utils.logger import log_event
        email = _resolve_email(request)
        log_event(email, "noaa_fetch", f"{req.station_id} years={req.years}")
    except Exception:
        pass
    return StreamingResponse(
        _fetch_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─────────────────────────────────────────────────────────────────
#  /process — merge → filter → metadata → psychrometrics
# ─────────────────────────────────────────────────────────────────

@router.post("/process")
def process(req: ProcessRequest, token: str = Query(...), request: Request = None):
    stored = _result_store.get(token)
    if not stored or stored.get("type") != "fetch":
        return JSONResponse({"error": "Token not found or expired"}, status_code=404)

    # ── merge: reuse cached object, never re-parse year JSONs ──
    from pipeline.filtering import clean_and_shift, score_filters
    from pipeline.metadata import extract_metadata
    from pipeline.processing import process as run_process

    merged_df = _get_or_build_merged(stored)
    exclude = set(req.exclude_quality_codes)

    # ── metadata — need delta_time before final clean ──────────
    meta, meta_qa = extract_metadata(merged_df, req.lat, req.lon)

    # ── clean with correct timezone shift ─────────────────────
    df3, clean_qa = clean_and_shift(merged_df, delta_time=meta.delta_time, exclude_quality_codes=exclude)

    # ── apply filter — NO score_filters pivot_tables here ─────
    min_year = min(req.years) if req.years else int(min(stored["years"]))
    max_year = max(req.years) if req.years else int(max(stored["years"]))

    filter_key = req.filter_type or stored.get("_filter_best")
    if not filter_key:
        # fallback: score now (only if /score-filters was never called)
        filter_results, filter_key = score_filters(df3, min_year=min_year, max_year=max_year)
        from pipeline.filtering import apply_filter
        df6 = apply_filter(filter_results, filter_key)
    else:
        df6 = _apply_filter_direct(df3, filter_key, min_year, max_year)

    if df6.empty:
        return JSONResponse({"error": f"Filter '{filter_key}' produced no rows"}, status_code=422)

    req = req.model_copy(update={"filter_type": filter_key})

    # ── processing — clip, resample, interpolate ───────────────
    end_year = max(req.years) if req.years else 2025
    proc = run_process(df6, end_year=end_year, clip_lower_f=req.clip_lower_f, clip_upper_f=req.clip_upper_f)

    # ── psychrometrics ────────────────────────────────────────
    from pipeline.psychrometrics import compute_psychrometrics
    psychro = compute_psychrometrics(
        hourly_temperature_2m=proc.hourly_temperature_2m,
        hourly_dew_point_2m=proc.hourly_dew_point_2m,
        date=proc.date,
        pressure_psi=meta.pressure_psi,
    )

    # ── statistics ────────────────────────────────────────────
    from pipeline.statistics import compute_design_conditions, compute_winterization
    dc = compute_design_conditions(
        hourly_dataframe        = psychro.hourly_dataframe,
        hourly_temperature_2m   = psychro.hourly_temperature_2m,
        hourly_wetbulb_point_2m = psychro.hourly_wetbulb_point_2m,
        thou_degG_hrs           = psychro.thou_degG_hrs,
    )
    wr = compute_winterization(
        df_winterization  = proc.df_winterization,
        freezing_threshold= 36.0,
        max_year_last_5   = dc.max_year_last_5,
    )

    # ── store result ──────────────────────────────────────────
    result_token = f"result_{token}"
    _result_store[result_token] = {
        "type": "process",
        "meta": {
            "station_name": meta.station_name,
            "station_id": meta.station_id,
            "station_lat": meta.station_lat,
            "station_lon": meta.station_lon,
            "site_ele_m": meta.site_ele,
            "site_ele_ft": meta.site_ele * 3.28084,
            "pressure_psi": meta.pressure_psi,
            "distance_miles": meta.distance_miles,
            "delta_time": meta.delta_time,
            "timezone": meta.timezone_name,
            "elevation_delta_ft": meta.elevation_delta_ft,
        },
        "meta_qa": meta_qa,
        "clean_qa": clean_qa.__dict__ if hasattr(clean_qa, "__dict__") else clean_qa,
        "psychro_qa": psychro.qa,
        "design_conditions": {
            "Stats": dc.Stats.round(2).to_dict(orient="records"),
            "yearly_grouping": dc.yearly_grouping.reset_index().round(2).to_dict(orient="records"),
            "T1_Tdb_acf": dc.T1_Tdb_acf,
            "T1_MCWB_acf": dc.T1_MCWB_acf,
            "T1_Twb_acf": dc.T1_Twb_acf,
            "T1_MCDB_acf": dc.T1_MCDB_acf,
            "max_year_last_5": dc.max_year_last_5,
            "acf": dc.acf,
            "qa": dc.qa,
        },
        "filter_type": req.filter_type,
        "winterization": {
            "no_freeze_start": str(wr.no_freeze_start_date) if wr.no_freeze_start_date else None,
            "no_freeze_end":   str(wr.no_freeze_end_date)   if wr.no_freeze_end_date   else None,
        },
        "hourly_df_json": psychro.hourly_dataframe.reset_index().to_json(orient="records", date_format="iso"),
        "df_winterization_json": proc.df_winterization.reset_index().to_json(orient="records", date_format="iso"),
        "n_rows": len(psychro.hourly_dataframe),
    }

    try:
        from utils.logger import log_event
        email = _resolve_email(request)
        meta_s = _result_store[result_token]["meta"]
        log_event(email, "stage6_done", f"{meta_s.get('station_name','')} n={len(psychro.hourly_dataframe)}")
    except Exception:
        pass

    return {
        "result_token": result_token,
        "filter_used": req.filter_type,
        "n_rows": len(psychro.hourly_dataframe),
        "meta": _result_store[result_token]["meta"],
        "design_conditions": _result_store[result_token]["design_conditions"],
        "psychro_qa": psychro.qa,
        "processing_qa": proc.qa,
        "winterization": _result_store[result_token]["winterization"],
    }


# ─────────────────────────────────────────────────────────────────
#  /results/{token}  — fetch stored result
# ─────────────────────────────────────────────────────────────────

@router.get("/results/{token}")
def get_result(token: str):
    stored = _result_store.get(token)
    if not stored:
        return JSONResponse({"error": "Token not found"}, status_code=404)
    # Return everything except the large hourly DataFrame
    return {k: v for k, v in stored.items() if k != "hourly_df_json"}


# ─────────────────────────────────────────────────────────────────
#  /chart/psychrometric  — render psychrometric chart as PNG
# ─────────────────────────────────────────────────────────────────

@router.get("/chart/psychrometric")
def psychrometric_chart(token: str, units: str = "F"):
    stored = _result_store.get(token)
    if not stored or "hourly_df_json" not in stored:
        return JSONResponse({"error": "Token not found"}, status_code=404)

    df = pd.read_json(io.StringIO(stored["hourly_df_json"]), orient="records")
    df = df.rename(columns={"Tdb": "Tdb_F", "Twb": "Twb_F", "Tdp": "Tdp_F", "RH": "RH_percent"})

    from simple_psychrometric_chart import create_simple_psychrometric_chart
    meta = stored.get("meta", {})
    result = create_simple_psychrometric_chart(
        weather_data=df,
        elevation_ft=meta.get("site_ele_ft", 0),
        location_name=meta.get("station_name", ""),
        output_file=None,
        unit_system="SI" if units.upper() == "C" else "IP",
    )

    if result.get("plot_bytes"):
        img_b64 = base64.b64encode(result["plot_bytes"]).decode()
        return {"image_b64": img_b64, "format": "png"}
    return JSONResponse({"error": result.get("error", "chart failed")}, status_code=500)


# ─────────────────────────────────────────────────────────────────
#  /ashrae/conditions — parallel fetch for a list of WMO stations
# ─────────────────────────────────────────────────────────────────

@router.post("/ashrae/conditions")
async def ashrae_conditions(request: dict):
    """
    Fetch ASHRAE design conditions for multiple WMO stations in parallel.
    Body: { wmos: [...], edition: "2025", si_ip: "IP" }
    Returns conditions at 0.4%, 1%, 2% exceedance for each station.
    """
    import asyncio
    from pipeline.ashrae import fetch_ashrae_conditions, conditions_for_level

    wmos    = request.get("wmos", [])
    edition = request.get("edition", "2025")
    si_ip   = request.get("si_ip", "IP")

    async def _one(wmo: str) -> dict:
        try:
            d = await asyncio.to_thread(
                fetch_ashrae_conditions, wmo, level="1", si_ip=si_ip, ashrae_version=edition
            )
            if not d:
                return {"wmo": wmo, "error": "no data"}
            return {
                "wmo":          wmo,
                "station":      d.get("station", wmo),
                "ashrae_version": d.get("ashrae_version", edition),
                "pressure_psia": d.get("pressure_psia"),
                "levels": {
                    "0.4": {k: conditions_for_level(d, "0.4").get(k) for k in ("tdb","mcwb","twb","mcdb")},
                    "1":   {k: d.get(k) for k in ("tdb","mcwb","twb","mcdb")},
                    "2":   {k: conditions_for_level(d, "2").get(k) for k in ("tdb","mcwb","twb","mcdb")},
                },
            }
        except Exception as e:
            return {"wmo": wmo, "error": str(e)}

    results = await asyncio.gather(*[_one(w) for w in wmos])
    return {"results": list(results)}


# ─────────────────────────────────────────────────────────────────
#  Chart data endpoints — return aggregated JSON for frontend rendering
# ─────────────────────────────────────────────────────────────────

@router.get("/chart/scatter-data")
def scatter_data(token: str, units: str = "F"):
    """Return sampled hourly Tdb/Twb points for scatter chart."""
    stored = _result_store.get(token)
    if not stored or "hourly_df_json" not in stored:
        return JSONResponse({"error": "Token not found"}, status_code=404)

    df = pd.read_json(io.StringIO(stored["hourly_df_json"]), orient="records")
    tdb_col = "Tdb"
    twb_col = "Twb"
    if tdb_col not in df.columns:
        return JSONResponse({"error": "No Tdb column"}, status_code=500)

    if units.upper() == "C":
        df[tdb_col] = (df[tdb_col] - 32) * 5 / 9
        df[twb_col] = (df[twb_col] - 32) * 5 / 9

    # Sample down to ~300 points — prevents overlapping blob appearance
    sample = df[[tdb_col, twb_col]].dropna()
    if len(sample) > 300:
        sample = sample.sample(300, random_state=42)

    return {
        "points": sample.rename(columns={tdb_col: "x", twb_col: "y"}).to_dict(orient="records"),
        "units": units.upper(),
    }


@router.get("/chart/heatmap-data")
def heatmap_data(token: str, units: str = "F"):
    """Return min-temp-per-month pivot for heatmap (180 cells max)."""
    stored = _result_store.get(token)
    if not stored or "df_winterization_json" not in stored:
        return JSONResponse({"error": "Token not found"}, status_code=404)

    dfw = pd.read_json(io.StringIO(stored["df_winterization_json"]), orient="records")
    # orient="records" always produces a "DATE" column from reset_index()
    date_col = next((c for c in ("DATE", "date") if c in dfw.columns), None)
    if date_col:
        dfw[date_col] = pd.to_datetime(dfw[date_col], utc=True).dt.tz_localize(None)
        dfw = dfw.set_index(date_col)

    dfw["TMP_F"] = pd.to_numeric(dfw["TMP_F"] if "TMP_F" in dfw.columns else pd.Series(dtype=float), errors="coerce")
    dfw["year"]  = dfw.index.year
    dfw["month"] = dfw.index.month

    pivot = dfw.pivot_table(index="month", columns="year", values="TMP_F", aggfunc="min")
    if units.upper() == "C":
        pivot = (pivot - 32) * 5 / 9

    month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    cells = []
    for month_idx, mname in enumerate(month_names, start=1):
        if month_idx in pivot.index:
            row = pivot.loc[month_idx]
            for yr in row.index:
                v = row[yr]
                if not np.isnan(v):
                    cells.append({"month": mname, "year": int(yr), "value": round(float(v), 1)})

    return {"cells": cells, "units": units.upper()}


@router.get("/chart/freezing-data")
def freezing_data(token: str, threshold_f: float = 36.0):
    """Return freezing hours per ISO week."""
    stored = _result_store.get(token)
    if not stored or "df_winterization_json" not in stored:
        return JSONResponse({"error": "Token not found"}, status_code=404)

    dfw = pd.read_json(io.StringIO(stored["df_winterization_json"]), orient="records")
    date_col = next((c for c in ("DATE", "date") if c in dfw.columns), None)
    if date_col:
        dfw[date_col] = pd.to_datetime(dfw[date_col], utc=True).dt.tz_localize(None)
        dfw = dfw.set_index(date_col)

    dfw["TMP_F"] = pd.to_numeric(dfw["TMP_F"] if "TMP_F" in dfw.columns else pd.Series(dtype=float), errors="coerce")
    dfw["below"] = dfw["TMP_F"] < threshold_f
    dfw["week"]  = dfw.index.isocalendar().week.astype(int)

    by_week = dfw.groupby("week")["below"].sum().reset_index()
    by_week.columns = ["week", "hours"]

    # Fill all 52 weeks so chart always shows a full-year view (0-hour weeks = no freezing)
    all_weeks = pd.DataFrame({"week": range(1, 53)})
    by_week = all_weeks.merge(by_week, on="week", how="left").fillna(0)
    by_week["hours"] = by_week["hours"].astype(int)

    return {
        "bars": by_week.to_dict(orient="records"),
        "threshold_f": threshold_f,
    }


# ─────────────────────────────────────────────────────────────────
#  /openmeteo  — quick estimate for a lat/lon + year range
# ─────────────────────────────────────────────────────────────────

@router.get("/openmeteo")
def openmeteo_estimate(lat: float, lon: float, year_start: int = 2015, year_end: int = 2024, units: str = "F"):
    import traceback as _tb
    try:
        from pipeline.openmeteo import fetch_openmeteo
    except ImportError as e:
        return JSONResponse({"error": f"Missing package: {e}"}, status_code=500)

    try:
        from pipeline.om_pipeline import run_om_pipeline
        from pipeline.geo_utils import get_elevation_m, calc_pressure_psi
    except ImportError as e:
        return JSONResponse({"error": f"Import error: {e}"}, status_code=500)

    try:
        result = fetch_openmeteo(lat, lon, year_start, year_end)
    except Exception as e:
        return JSONResponse({"error": f"Open-Meteo API error: {e}"}, status_code=502)

    if result is None:
        return JSONResponse({"error": "Open-Meteo returned no data"}, status_code=502)

    raw, om_ele_m = result   # fetch_openmeteo returns (df, elevation_m)

    try:
        ele_m = om_ele_m or get_elevation_m(lat, lon) or 0.0
        pressure_psi = calc_pressure_psi(ele_m)
        proc, psychro, dc, wr = run_om_pipeline(
            om_df         = raw,
            end_year      = year_end,
            pressure_psi  = pressure_psi,
        )
    except Exception as e:
        return JSONResponse({"error": f"Pipeline error: {e}\n{_tb.format_exc()}"}, status_code=500)

    stats_rows = dc.Stats.round(2).to_dict(orient="records") if dc is not None else []

    # Add Celsius columns to stats if units == C
    if units.upper() == "C" and stats_rows:
        for row in stats_rows:
            for fk, ck in [("DB_F","DB_C"),("WB_F","WB_C"),("MCWB_F","MCWB_C"),("MCDB_F","MCDB_C")]:
                if fk in row and row[fk] is not None:
                    row[ck] = round((row[fk] - 32) * 5 / 9, 2)

    yearly_rows = []
    if dc is not None and not dc.yearly_grouping.empty:
        yearly_rows = dc.yearly_grouping.reset_index().round(2).to_dict(orient="records")

    # Store OM hourly + winterization data so chart endpoints can reuse it
    om_token = f"om_{lat}_{lon}_{year_start}_{year_end}"
    _result_store[om_token] = {
        "type": "om",
        "hourly_df_json": psychro.hourly_dataframe.reset_index().to_json(orient="records", date_format="iso"),
        "df_winterization_json": proc.df_winterization.reset_index().to_json(orient="records", date_format="iso"),
        "meta": {
            "station_name": f"ERA5 ({lat:.4f}, {lon:.4f})",
            "site_ele_ft": ele_m * 3.28084,
        },
    }

    return {
        "stats": stats_rows,
        "yearly": yearly_rows,
        "winterization": {
            "no_freeze_start": str(wr.no_freeze_start_date) if wr and wr.no_freeze_start_date else None,
            "no_freeze_end":   str(wr.no_freeze_end_date)   if wr and wr.no_freeze_end_date   else None,
        },
        "om_token": om_token,
    }


# ─────────────────────────────────────────────────────────────────
#  /download-csv  — merged raw NOAA data as CSV
# ─────────────────────────────────────────────────────────────────

@router.get("/download-csv")
def download_csv(token: str):
    stored = _result_store.get(token)
    if not stored or stored.get("type") != "fetch":
        return JSONResponse({"error": "Fetch token not found"}, status_code=404)

    from pipeline.download import build_merged
    years_data = {
        int(yr): pd.read_json(io.StringIO(js))
        for yr, js in stored["years_data"].items()
    }
    merged = build_merged(years_data)
    station_id = stored.get("station_id", "station")

    buf = io.StringIO()
    merged.to_csv(buf, index=True)
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{station_id}_merged.csv"'},
    )


# ─────────────────────────────────────────────────────────────────
#  /download-results  — Stats + yearly summary as CSV
# ─────────────────────────────────────────────────────────────────

@router.get("/download-results")
def download_results(token: str):
    stored = _result_store.get(token)
    if not stored or stored.get("type") != "process":
        return JSONResponse({"error": "Result token not found"}, status_code=404)

    dc   = stored.get("design_conditions", {})
    meta = stored.get("meta", {})
    station_id = meta.get("station_id", "station")

    stats_df   = pd.DataFrame(dc.get("Stats", []))
    yearly_df  = pd.DataFrame(dc.get("yearly_grouping", []))

    buf = io.StringIO()
    buf.write(f"# Station: {meta.get('station_name', '')} ({station_id})\n")
    buf.write(f"# Filter: {stored.get('filter_type', '')}\n")
    buf.write(f"# Pressure (psia): {meta.get('pressure_psi', '')}\n\n")
    buf.write("## Design Conditions (Stats)\n")
    stats_df.to_csv(buf, index=False)
    buf.write("\n## Yearly Summary\n")
    yearly_df.to_csv(buf, index=False)
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{station_id}_results.csv"'},
    )
