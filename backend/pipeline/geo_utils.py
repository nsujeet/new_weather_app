"""
pipeline/geo_utils.py

Pure geographic utility functions — no Streamlit, no agent, no side effects.
All functions take plain arguments and return plain values.

Lifted from notebook Cell 12 (elevation, timezone) and new (haversine, pressure).
Used by:
  - pipeline/stations.py  (haversine_miles, meters_to_feet)
  - pipeline/metadata.py  (get_elevation_m, calc_pressure_psi, get_timezone)
  - agent/tools.py        (wrapped as agent tools)
"""

import math
import requests


# ─────────────────────────────────────────────────────────────
#  Distance
# ─────────────────────────────────────────────────────────────

def haversine_miles(lat1: float, lon1: float,
                    lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two lat/lon points in miles.

    Haversine accounts for Earth's curvature — more accurate than
    Euclidean degree difference, especially over longer distances.
    This is the right metric for station selection because you want
    meteorological proximity, not road distance.

    Args:
        lat1, lon1: first point (decimal degrees)
        lat2, lon2: second point (decimal degrees)

    Returns:
        Distance in miles (float)
    """
    R = 3958.8  # Earth radius in miles

    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat   = math.radians(lat2 - lat1)
    dlon   = math.radians(lon2 - lon1)

    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2)

    return 2 * R * math.asin(math.sqrt(a))


def haversine_km(lat1: float, lon1: float,
                 lat2: float, lon2: float) -> float:
    """Same as haversine_miles but returns kilometres."""
    return haversine_miles(lat1, lon1, lat2, lon2) * 1.60934


# ─────────────────────────────────────────────────────────────
#  Elevation — from notebook Cell 12
# ─────────────────────────────────────────────────────────────

def get_elevation_m(latitude: float, longitude: float,
                    timeout: int = 10) -> float | None:
    """
    Get elevation in metres for a lat/lon using Open-Meteo elevation API.
    Free, no API key required, more reliable than open-elevation.com.

    Args:
        latitude:  decimal degrees
        longitude: decimal degrees
        timeout:   request timeout in seconds

    Returns:
        Elevation in metres, or None if the API call fails.
    """
    url = "https://api.open-meteo.com/v1/elevation"
    try:
        response = requests.get(
            url,
            params={"latitude": latitude, "longitude": longitude},
            timeout=timeout,
        )
        if response.status_code == 200:
            data = response.json()
            elev = data.get("elevation")
            if elev:
                return float(elev[0])
        return None
    except Exception:
        return None


def get_elevation_ft(latitude: float, longitude: float) -> float | None:
    """Get elevation in feet. Returns None if API call fails."""
    m = get_elevation_m(latitude, longitude)
    return meters_to_feet(m) if m is not None else None


# ─────────────────────────────────────────────────────────────
#  Pressure — barometric formula, no network call
# ─────────────────────────────────────────────────────────────

def calc_pressure_psi(elevation_m: float) -> float:
    """
    Calculate atmospheric pressure in psia from elevation in metres.
    Uses the international barometric formula (standard atmosphere).

    This is what your notebook uses for psychrolib calculations.
    No network call — pure math.

    Args:
        elevation_m: elevation above sea level in metres

    Returns:
        Pressure in psia (pounds per square inch absolute)
    """
    # International barometric formula
    # P = P0 * (1 - L*h/T0)^(g*M/R*L)
    # Simplified standard form:
    pressure_atm = (1 - elevation_m / 44330) ** 5.2561
    pressure_psi = pressure_atm * 14.696
    return round(pressure_psi, 4)


def calc_pressure_from_feet(elevation_ft: float) -> float:
    """Convenience wrapper — takes elevation in feet."""
    return calc_pressure_psi(feet_to_meters(elevation_ft))


# ─────────────────────────────────────────────────────────────
#  Unit conversions
# ─────────────────────────────────────────────────────────────

def meters_to_feet(m: float) -> float:
    return round(m * 3.28084, 1)

def feet_to_meters(ft: float) -> float:
    return round(ft / 3.28084, 2)

def celsius_to_fahrenheit(c: float) -> float:
    return c * 9 / 5 + 32

def fahrenheit_to_celsius(f: float) -> float:
    return (f - 32) * 5 / 9


# ─────────────────────────────────────────────────────────────
#  Timezone — from notebook Cell 12
# ─────────────────────────────────────────────────────────────

def get_timezone_name(latitude: float, longitude: float) -> str | None:
    """
    Get IANA timezone name for a lat/lon (e.g. 'America/Denver').
    Uses timezonefinder — local lookup, no network call.

    From notebook Cell 12.
    """
    try:
        from timezonefinder import TimezoneFinder
        tf = TimezoneFinder()
        return tf.timezone_at(lat=latitude, lng=longitude)
    except Exception:
        return None


def get_utc_offset_hours(latitude: float, longitude: float) -> float:
    """
    Get current UTC offset in hours for a lat/lon.
    Accounts for daylight saving time automatically.

    This is delta_time from notebook Cell 12.

    Returns:
        UTC offset as float (e.g. -7.0 for MDT, -6.0 for MST)
    """
    import datetime
    from zoneinfo import ZoneInfo

    tz_name = get_timezone_name(latitude, longitude)
    if tz_name is None:
        return 0.0  # ocean or unmapped coordinate — default to UTC

    timezone   = ZoneInfo(tz_name)
    local_time = datetime.datetime.now(timezone)
    offset     = local_time.utcoffset().total_seconds() / 3600
    return offset


# ─────────────────────────────────────────────────────────────
#  Quick self-test
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # El Paso site from notebook
    lat, lon = 31.925864846669693, -106.71248240822992

    print("=== geo_utils self-test ===")

    # haversine
    dist = haversine_miles(lat, lon, 31.8122, -106.3775)
    print(f"El Paso site → El Paso Intl AP: {dist:.1f} miles (expect ~21)")

    # pressure at El Paso elevation (~1144m)
    p = calc_pressure_psi(1144.0)
    print(f"Pressure at 1144m: {p} psia (expect ~12.5)")

    # timezone
    tz = get_timezone_name(lat, lon)
    offset = get_utc_offset_hours(lat, lon)
    print(f"Timezone: {tz}, offset: {offset}h")

    # elevation (network call)
    print("Fetching elevation from Open-Elevation...")
    ele = get_elevation_m(lat, lon)
    print(f"Site elevation: {ele}m = {meters_to_feet(ele):.0f}ft" if ele else "API unavailable")
