"""
pipeline/openmeteo.py

Fetch hourly temperature + dew point from the Open-Meteo archive API
(ERA5 reanalysis) using the official openmeteo-requests SDK.

Large date ranges are split into 5-year chunks to avoid server-side
timeouts on the archive API.
"""

import pandas as pd
import requests_cache
from retry_requests import retry
import openmeteo_requests


_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
_CHUNK_YEARS = 5          # max years per API request
_REQUEST_TIMEOUT = 120    # seconds per chunk request


def _make_client(cache_dir: str = ".cache", expire_after: int = 3600):
    session = requests_cache.CachedSession(cache_dir, expire_after=expire_after)
    # Inject timeout on every underlying HTTP send
    _orig_send = session.send
    session.send = lambda req, **kw: _orig_send(req, timeout=_REQUEST_TIMEOUT, **kw)
    retry_session = retry(session, retries=5, backoff_factor=0.2)
    return openmeteo_requests.Client(session=retry_session)


def _fetch_chunk(client, lat: float, lon: float, start_year: int, end_year: int):
    """Fetch one chunk and return (df, elevation_m)."""
    params = {
        "latitude":         lat,
        "longitude":        lon,
        "start_date":       f"{start_year}-01-01",
        "end_date":         f"{end_year}-12-31",
        "hourly":           ["temperature_2m", "dewpoint_2m", "surface_pressure"],
        "temperature_unit": "celsius",
        "timezone":         "UTC",
    }
    response  = client.weather_api(_ARCHIVE_URL, params=params)[0]
    elevation = float(response.Elevation()) if response.Elevation() is not None else None

    hourly = response.Hourly()
    times  = pd.date_range(
        start     = pd.to_datetime(hourly.Time(),    unit="s", utc=True),
        end       = pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
        freq      = pd.Timedelta(seconds=hourly.Interval()),
        inclusive = "left",
    ).tz_localize(None)  # strip UTC tzinfo — rest of pipeline expects naive datetime

    df = pd.DataFrame({
        "DATE":                  times,
        "temperature":           hourly.Variables(0).ValuesAsNumpy(),
        "dew_point_temperature": hourly.Variables(1).ValuesAsNumpy(),
        "surface_pressure_hpa":  hourly.Variables(2).ValuesAsNumpy(),
    })
    return df, elevation


def fetch_openmeteo(
    lat: float,
    lon: float,
    start_year: int,
    end_year: int,
) -> tuple[pd.DataFrame, float | None]:
    """
    Download hourly temperature, dew point and surface pressure.
    Splits large date ranges into 5-year chunks to avoid API timeouts.

    Returns:
        (df, elevation_m)
    """
    client = _make_client()

    chunks: list[pd.DataFrame] = []
    elevation_m: float | None = None
    year = start_year

    while year <= end_year:
        chunk_end = min(year + _CHUNK_YEARS - 1, end_year)
        df_chunk, elev = _fetch_chunk(client, lat, lon, year, chunk_end)
        chunks.append(df_chunk)
        if elevation_m is None and elev is not None:
            elevation_m = elev
        year = chunk_end + 1

    df = pd.concat(chunks, ignore_index=True)

    # Metadata columns expected by downstream stages
    df["STATION"]                       = "OPENMETEO"
    df["Station_name"]                  = f"Open-Meteo {lat:.4f},{lon:.4f}"
    df["LATITUDE"]                      = str(lat)
    df["LONGITUDE"]                     = str(lon)
    df["Elevation"]                     = str(elevation_m) if elevation_m else ""
    df["station_level_pressure"]        = ""
    df["relative_humidity"]             = ""
    df["wet_bulb_temperature"]          = ""
    df["temperature_Quality_Code"]      = ""
    df["temperature_Report_Type"]       = ""
    df["temperature_Source_Code"]       = ""
    df["temperature_Source_Station_ID"] = ""

    return df, elevation_m
