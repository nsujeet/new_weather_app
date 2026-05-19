"""
pipeline/openmeteo.py

Fetch hourly temperature + dew point from the Open-Meteo archive API
(ERA5 reanalysis) using the official openmeteo-requests SDK which
provides built-in retry and caching.

Returns a DataFrame compatible with the rest of the pipeline plus
the elevation reported by Open-Meteo for the coordinates.
"""

import pandas as pd
import requests_cache
from retry_requests import retry
import openmeteo_requests


_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def _make_client(cache_dir: str = ".cache", expire_after: int = 3600):
    session = requests_cache.CachedSession(cache_dir, expire_after=expire_after)
    retry_session = retry(session, retries=5, backoff_factor=0.2)
    return openmeteo_requests.Client(session=retry_session)


def fetch_openmeteo(
    lat: float,
    lon: float,
    start_year: int,
    end_year: int,
    timeout: int = 120,
) -> tuple[pd.DataFrame, float | None]:
    """
    Download hourly temperature, dew point and surface pressure for a
    coordinate range of years using the official Open-Meteo SDK.

    Returns:
        (df, elevation_m)
        df           — DataFrame compatible with the rest of the pipeline
        elevation_m  — site elevation in metres reported by Open-Meteo,
                       or None if unavailable
    """
    client = _make_client()

    params = {
        "latitude":         lat,
        "longitude":        lon,
        "start_date":       f"{start_year}-01-01",
        "end_date":         f"{end_year}-12-31",
        "hourly":           ["temperature_2m", "dewpoint_2m", "surface_pressure"],
        "temperature_unit": "celsius",
        "timezone":         "UTC",
    }

    responses = client.weather_api(_ARCHIVE_URL, params=params)
    response  = responses[0]

    # Elevation reported by Open-Meteo for these coordinates
    elevation_m = float(response.Elevation()) if response.Elevation() is not None else None

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
