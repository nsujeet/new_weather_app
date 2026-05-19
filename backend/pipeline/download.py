"""
pipeline/download.py

Handles all three data source paths:
  A) Fetch from NOAA — parallel by default, optional disk cache
  B) Load from uploaded file (CSV or PSV)
  C) Load from a previously saved merged CSV

Disk cache (optional):
  If cache_dir is provided to fetch functions, each year is saved as
  a PSV file: {cache_dir}/{station}_{year}.psv
  Survives app restarts — reopening loads instantly from disk.

Parallel fetch:
  All missing years fetched concurrently via ThreadPoolExecutor.
  10 years sequential ~30s → parallel ~4s.
  Results yielded as they arrive so progress bar updates live.
"""

import io
import os
import threading
import requests
from requests.adapters import HTTPAdapter
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Generator

# ── NOAA base URL ──────────────────────────────────────────────
BASE = (
    "https://www.ncei.noaa.gov/oa/global-historical-climatology-network"
    "/hourly/access"
)

# ── Columns to keep ────────────────────────────────────────────
FINAL_COLS = [
    "DATE", "STATION", "Station_name",
    "temperature", "dew_point_temperature", "station_level_pressure",
    "LATITUDE", "LONGITUDE", "Elevation",
    "relative_humidity", "wet_bulb_temperature",
    "temperature_Quality_Code", "temperature_Report_Type",
    "temperature_Source_Code", "temperature_Source_Station_ID",
]

# ── Max parallel workers ───────────────────────────────────────
MAX_WORKERS = int(os.environ.get("NOAA_MAX_WORKERS", "5"))

# ── Thread-local HTTP session (one per worker thread) ─────────
_thread_local = threading.local()


def _get_session() -> requests.Session:
    """Return (or create) a per-thread Session with connection pooling."""
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.mount("https://", HTTPAdapter(pool_connections=2, pool_maxsize=4))
        _thread_local.session = s
    return _thread_local.session


# ─────────────────────────────────────────────────────────────
#  Disk cache helpers
# ─────────────────────────────────────────────────────────────

def _cache_path(cache_dir: str, station: str, year: int) -> str:
    """Path for one year's PSV file on disk."""
    return os.path.join(cache_dir, f"{station}_{year}.psv")


_CACHE_TTL_DAYS = 30   # evict files not accessed in this many days


def _evict_stale_cache(cache_dir: str) -> int:
    """
    Delete PSV files in cache_dir not accessed in _CACHE_TTL_DAYS.
    Called before writing a new file to keep the volume from filling up.
    Returns number of files deleted.
    """
    if not cache_dir or not os.path.exists(cache_dir):
        return 0
    import time
    cutoff = time.time() - _CACHE_TTL_DAYS * 86400
    deleted = 0
    for fname in os.listdir(cache_dir):
        if not fname.endswith(".psv"):
            continue
        fpath = os.path.join(cache_dir, fname)
        try:
            if os.path.getatime(fpath) < cutoff:
                os.remove(fpath)
                deleted += 1
        except Exception:
            pass
    return deleted


def _load_from_disk(cache_dir: str, station: str,
                    year: int) -> pd.DataFrame | None:
    """
    Load a year from disk cache if it exists and is non-empty.
    Touches the file on read so atime reflects last access (TTL clock).
    Returns DataFrame or None if not cached.
    """
    if not cache_dir:
        return None
    path = _cache_path(cache_dir, station, year)
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        try:
            data = open(path, "rb").read()
            os.utime(path, None)   # touch — reset atime to now
            return _parse_psv_bytes(data)
        except Exception:
            return None
    return None


def _save_to_disk(cache_dir: str, station: str,
                  year: int, raw_bytes: bytes) -> None:
    """Save raw PSV bytes to disk cache. Evicts stale files first."""
    if not cache_dir:
        return
    os.makedirs(cache_dir, exist_ok=True)
    _evict_stale_cache(cache_dir)   # clean up before writing
    path = _cache_path(cache_dir, station, year)
    with open(path, "wb") as f:
        f.write(raw_bytes)


# ─────────────────────────────────────────────────────────────
#  Single year fetch — used by parallel pool
# ─────────────────────────────────────────────────────────────

def _fetch_one_year(
    station: str,
    year: int,
    years_data: dict,
    cache_dir: str = "",
) -> dict:
    """
    Fetch one year. Checks memory → disk → NOAA in that order.

    Returns status dict:
        { year, status, rows, message, df (if successful) }
    """
    # 1. already in memory
    if year in years_data:
        rows = len(years_data[year])
        return {
            "year": year, "status": "memory",
            "rows": rows,
            "message": f"{rows:,} rows already in memory",
            "df": None,  # already there, no need to store again
        }

    # 2. on disk cache
    df_disk = _load_from_disk(cache_dir, station, year)
    if df_disk is not None:
        return {
            "year": year, "status": "disk",
            "rows": len(df_disk),
            "message": f"{len(df_disk):,} rows loaded from disk cache",
            "df": df_disk,
        }

    # 3. fetch from NOAA
    url = f"{BASE}/by-year/{year}/psv/GHCNh_{station}_{year}.psv"
    try:
        r = _get_session().get(url, timeout=(10, 60))  # 10s connect, 60s read
    except requests.exceptions.RequestException as e:
        return {
            "year": year, "status": "failed",
            "rows": 0, "message": str(e), "df": None,
        }

    if r.status_code != 200:
        return {
            "year": year, "status": "failed",
            "rows": 0,
            "message": f"HTTP {r.status_code}",
            "df": None,
        }

    df = _parse_psv_bytes(r.content)
    if df is None or df.empty:
        return {
            "year": year, "status": "failed",
            "rows": 0,
            "message": "Empty or unparseable response",
            "df": None,
        }

    # save to disk cache if enabled
    _save_to_disk(cache_dir, station, year, r.content)

    return {
        "year": year, "status": "fetched",
        "rows": len(df),
        "message": f"{len(df):,} rows downloaded",
        "df": df,
    }


# ─────────────────────────────────────────────────────────────
#  Public API — parallel fetch with progress yielding
# ─────────────────────────────────────────────────────────────

def fetch_years_incremental(
    station: str,
    years: list[int],
    years_data: dict,
    cache_dir: str = "",
    max_workers: int = MAX_WORKERS,
) -> Generator[dict, None, None]:
    """
    Fetch multiple years in parallel, yielding a result dict as
    each year completes. Already-loaded years (memory or disk) are
    returned instantly without network calls.

    Args:
        station:     NOAA station ID
        years:       list of integer years to fetch
        years_data:  session dict { year: DataFrame } — updated in place
        cache_dir:   optional path for disk cache (e.g. "cache/")
        max_workers: max simultaneous NOAA connections (default 5)

    Yields dicts: { year, status, rows, message }
    status: "memory" | "disk" | "fetched" | "failed"

    Usage in Streamlit:
        for result in fetch_years_incremental(station, years, years_data):
            st.write(f"{result['year']}: {result['message']}")
    """
    sorted_years = sorted(years)

    # split into already-available and needs-network
    instant = [y for y in sorted_years if y in years_data]
    needed  = [y for y in sorted_years if y not in years_data]

    # yield instant (memory) results first
    for yr in instant:
        rows = len(years_data[yr])
        yield {
            "year": yr, "status": "memory",
            "rows": rows,
            "message": f"{rows:,} rows already in memory",
        }

    if not needed:
        return

    # fetch needed years in parallel — poll every 0.5s so the caller can
    # yield heartbeat updates and keep the WebSocket alive on Railway.
    import time as _time
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        pending = {
            pool.submit(_fetch_one_year, station, yr, years_data, cache_dir): yr
            for yr in needed
        }
        last_beat = _time.monotonic()

        while pending:
            done_now = [f for f in pending if f.done()]

            for future in done_now:
                pending.pop(future)
                result = future.result()
                if result["df"] is not None:
                    years_data[result["year"]] = result["df"]
                yield {
                    "year":    result["year"],
                    "status":  result["status"],
                    "rows":    result["rows"],
                    "message": result["message"],
                }
                last_beat = _time.monotonic()

            if not done_now:
                _time.sleep(0.5)
                # heartbeat every 3 s so Railway proxy doesn't drop WebSocket
                if _time.monotonic() - last_beat >= 3:
                    yield {
                        "year":    0,
                        "status":  "waiting",
                        "rows":    0,
                        "message": f"{len(pending)} year(s) still downloading…",
                    }
                    last_beat = _time.monotonic()


def get_available_years(
    station_id: str,
    year_range,
    max_workers: int = 20,
    timeout: int = 8,
    cache_dir: str = "",
) -> list[int]:
    """
    Probe which years have data for a station via parallel HEAD requests.
    Result is cached to {cache_dir}/{station_id}_avail.json so repeat
    calls (station switch, page reload) are instant.
    Returns sorted list of years where the file exists (HTTP 200).
    """
    import json, time as _t

    # ── try disk cache first ──────────────────────────────────
    cache_path = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f"{station_id}_avail.json")
        if os.path.exists(cache_path):
            try:
                payload = json.loads(open(cache_path).read())
                # refresh once a week — NOAA rarely adds past-year files
                if _t.time() - payload.get("ts", 0) < 7 * 86400:
                    return payload["years"]
            except Exception:
                pass

    # ── fetch via HEAD requests ───────────────────────────────
    years = list(year_range)
    if not years:
        return []

    def _check(year: int):
        url = f"{BASE}/by-year/{year}/psv/GHCNh_{station_id}_{year}.psv"
        try:
            r = _get_session().head(url, timeout=timeout, allow_redirects=True)
            return year if r.status_code == 200 else None
        except Exception:
            return None

    n_workers = min(max_workers, len(years))
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        results = list(pool.map(_check, years))

    available = sorted(y for y in results if y is not None)

    # ── save to disk cache ────────────────────────────────────
    if cache_path:
        try:
            open(cache_path, "w").write(
                json.dumps({"years": available, "ts": int(_t.time())})
            )
        except Exception:
            pass

    return available


def fetch_year_to_memory(
    station: str,
    year: int,
    years_data: dict,
    cache_dir: str = "",
) -> dict:
    """
    Fetch a single year (convenience wrapper for one-at-a-time use).
    Checks memory → disk → NOAA.
    """
    result = _fetch_one_year(station, year, years_data, cache_dir)
    if result["df"] is not None:
        years_data[year] = result["df"]
    return {k: v for k, v in result.items() if k != "df"}


def remove_year(year: int, years_data: dict) -> None:
    """Remove a year from memory. Disk cache is NOT deleted."""
    years_data.pop(year, None)


def clear_disk_cache(cache_dir: str, station: str,
                     year: int | None = None) -> int:
    """
    Delete disk cache files.
    If year is given, delete just that year.
    If year is None, delete all years for this station.
    Returns number of files deleted.
    """
    if not cache_dir or not os.path.exists(cache_dir):
        return 0
    deleted = 0
    if year is not None:
        path = _cache_path(cache_dir, station, year)
        if os.path.exists(path):
            os.remove(path)
            deleted = 1
    else:
        for fname in os.listdir(cache_dir):
            if fname.startswith(f"{station}_") and fname.endswith(".psv"):
                os.remove(os.path.join(cache_dir, fname))
                deleted += 1
    return deleted


# ─────────────────────────────────────────────────────────────
#  Merge
# ─────────────────────────────────────────────────────────────

def build_merged(
    years_data: dict,
    selected_years: list[int] | None = None,
) -> pd.DataFrame:
    """
    Concatenate selected years from memory into one sorted DataFrame.
    """
    use_years = (
        selected_years if selected_years is not None
        else sorted(years_data.keys())
    )
    frames = [
        years_data[yr]
        for yr in sorted(use_years)
        if yr in years_data
    ]
    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True)

    if "DATE" in merged.columns:
        merged["DATE"] = (
            merged["DATE"].astype(str)
                          .str.strip()
                          .str.replace("T", " ", regex=False)
        )

    keep   = [c for c in FINAL_COLS if c in merged.columns]
    merged = merged[keep]
    merged = merged[
        merged.astype(str).agg("".join, axis=1).str.strip() != ""
    ]
    return merged.sort_values("DATE").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
#  Load from upload / saved CSV
# ─────────────────────────────────────────────────────────────

def load_from_upload(
    file_bytes: bytes, filename: str
) -> tuple[pd.DataFrame, str]:
    """Parse an uploaded CSV or PSV. Returns (df, error_str)."""
    try:
        sep  = "|" if filename.lower().endswith(".psv") else ","
        text = file_bytes.decode("utf-8", errors="replace").lstrip("\ufeff")
        df   = pd.read_csv(
            io.StringIO(text), sep=sep, dtype=str, low_memory=False)
        df   = _clean_empty_rows(df)
        err  = _validate_columns(df)
        return (pd.DataFrame(), err) if err else (df, "")
    except Exception as e:
        return pd.DataFrame(), f"Parse error: {e}"


def load_from_saved_csv(
    file_bytes: bytes,
) -> tuple[pd.DataFrame, str]:
    """Load a previously exported merged CSV. Returns (df, error_str)."""
    try:
        text = file_bytes.decode("utf-8", errors="replace").lstrip("\ufeff")
        df   = pd.read_csv(io.StringIO(text), dtype=str, low_memory=False)
        df   = _clean_empty_rows(df)
        err  = _validate_columns(df)
        return (pd.DataFrame(), err) if err else (df, "")
    except Exception as e:
        return pd.DataFrame(), f"Parse error: {e}"


def merged_to_csv_bytes(merged_df: pd.DataFrame) -> bytes:
    """Serialise merged_df to UTF-8 CSV bytes for st.download_button."""
    return merged_df.to_csv(index=False).encode("utf-8")


# ─────────────────────────────────────────────────────────────
#  QA
# ─────────────────────────────────────────────────────────────

def download_qa(
    years_data: dict,
    selected_years: list[int],
) -> dict:
    """QA summary for the download stage card."""
    year_row_counts = {}
    years_ok        = []
    years_sparse    = []

    for yr in sorted(selected_years):
        if yr in years_data and not years_data[yr].empty:
            n = len(years_data[yr])
            year_row_counts[yr] = n
            if n < 4380:
                years_sparse.append(yr)
            else:
                years_ok.append(yr)
        else:
            year_row_counts[yr] = 0
            years_sparse.append(yr)

    total = sum(year_row_counts.values())
    messages = []
    if years_sparse:
        messages.append(
            f"Sparse or missing data for: {years_sparse}. "
            "Consider excluding or re-fetching."
        )

    n_bad = len(years_sparse)
    n_all = len(selected_years)
    if n_bad == 0:
        status = "pass"
    elif n_bad < n_all / 2:
        status = "warn"
    else:
        status = "fail"

    return {
        "total_rows":      total,
        "years_ok":        years_ok,
        "years_failed":    years_sparse,
        "year_row_counts": year_row_counts,
        "status":          status,
        "messages":        messages,
    }


# ─────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────

def _parse_psv_bytes(raw_bytes: bytes) -> pd.DataFrame | None:
    try:
        text = raw_bytes.decode("utf-8", errors="replace").lstrip("\ufeff")
        df   = pd.read_csv(
            io.StringIO(text), sep="|", dtype=str,
            keep_default_na=False, low_memory=False,
        )
        return _clean_empty_rows(df)
    except Exception:
        return None


def _clean_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mask = df.astype(str).agg("".join, axis=1).str.strip() == ""
    return df[~mask].reset_index(drop=True)


def _validate_columns(df: pd.DataFrame) -> str:
    required = {"DATE", "temperature", "dew_point_temperature"}
    missing  = required - set(df.columns)
    return f"Missing required columns: {sorted(missing)}" if missing else ""
