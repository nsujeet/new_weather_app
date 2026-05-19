"""
pipeline/metadata.py

Station metadata extraction + site/station comparison.
Notebook Cell 12 — lifted into pure functions.

What this stage does:
  1. Extracts station name, lat/lon, elevation from the merged_df
  2. Gets site elevation from Open-Elevation API (or uses cached value)
  3. Computes UTC offset (delta_time) from site lat/lon — DST aware
  4. Calculates pressure at both site and station from elevation
  5. Computes distance between site and station (haversine)
  6. Returns a StationMeta dataclass with all values

Your notebook variable names are preserved as attributes:
  meta.station_id       → station_id
  meta.station_name     → station_name
  meta.station_lat      → station_lat
  meta.station_lon      → station_lon
  meta.station_ele      → station_ele  (metres)
  meta.delta_time       → delta_time   (UTC offset hours)
  meta.pressure_psi     → pressure_psi (site)
  meta.distance_miles   → distance between site and station
"""

import pandas as pd
from dataclasses import dataclass

from pipeline.geo_utils import (
    haversine_miles,
    get_elevation_m,
    calc_pressure_psi,
    get_timezone_name,
    get_utc_offset_hours,
    meters_to_feet,
)


# ─────────────────────────────────────────────────────────────
#  Result dataclass
# ─────────────────────────────────────────────────────────────

@dataclass
class StationMeta:
    """
    All metadata extracted from merged_df + derived values.
    Mirrors the notebook Cell 12 variable names exactly.
    """
    # from merged_df
    station_id:   str   = ""
    station_name: str   = ""
    station_lat:  float = 0.0
    station_lon:  float = 0.0
    station_ele:  float = 0.0    # metres — from merged_df Elevation column

    # from Open-Elevation API
    site_ele:     float = 0.0    # metres — fetched for site lat/lon
    station_ele_api: float = 0.0 # metres — fetched for station lat/lon

    # derived
    delta_time:          float = 0.0   # UTC offset hours (DST aware)
    timezone_name:       str   = ""    # e.g. "America/Denver"
    pressure_psi:        float = 0.0   # site atmospheric pressure
    station_pressure_psi: float = 0.0  # station atmospheric pressure
    distance_miles:      float = 0.0   # site ↔ station distance

    # QA
    elevation_delta_ft:  float = 0.0   # abs difference site vs station
    distance_warning:    bool  = False  # True if > 30 miles
    elevation_warning:   bool  = False  # True if delta > 500 ft

    def summary_table(self) -> list[list]:
        """
        Returns a list of rows matching your notebook tabulate output.
        Use with tabulate or st.dataframe.
        """
        return [
            [" ",              "Power plant",         "Weather station"],
            ["Name",           "—",                   self.station_name],
            ["Station ID",     "—",                   self.station_id],
            ["Latitude",       "—",                   f"{self.station_lat:.4f}"],
            ["Longitude",      "—",                   f"{self.station_lon:.4f}"],
            ["Elevation (m)",  f"{self.site_ele:.1f}", f"{self.station_ele_api:.1f}"],
            ["Elevation (ft)", f"{self.site_ele*3.28084:.0f}", f"{self.station_ele_api*3.28084:.0f}"],
            ["Pressure (psi)", f"{self.pressure_psi:.3f}", f"{self.station_pressure_psi:.3f}"],
            ["Distance (mi)",  f"{self.distance_miles:.1f}", "—"],
            ["Timezone (GMT)", f"{self.timezone_name} ({self.delta_time:+.1f}h)", "—"],
        ]


# ─────────────────────────────────────────────────────────────
#  Main extraction function
# ─────────────────────────────────────────────────────────────

def extract_metadata(
    merged_df:   pd.DataFrame,
    site_lat:    float,
    site_lon:    float,
    site_ele_m:  float | None = None,
) -> tuple["StationMeta", dict]:
    """
    Extract all metadata from the merged DataFrame.

    Args:
        merged_df:  the merged NOAA dataframe from download.py
        site_lat:   site latitude (from WeatherConfig)
        site_lon:   site longitude (from WeatherConfig)
        site_ele_m: site elevation in metres — if None, fetched from API

    Returns:
        (StationMeta, qa_dict)
        qa_dict keys: status ("pass"|"warn"|"fail"), metrics, messages
    """
    meta = StationMeta()
    messages = []

    # ── 1. Extract from merged_df ──────────────────────────────
    # Same as your notebook Cell 12 — mode() for ID/name, mean() for coords
    if "STATION" in merged_df.columns:
        meta.station_id = str(merged_df["STATION"].mode()[0])

    if "Station_name" in merged_df.columns:
        meta.station_name = str(merged_df["Station_name"].mode()[0])

    if "LATITUDE" in merged_df.columns:
        meta.station_lat = float(
            pd.to_numeric(merged_df["LATITUDE"], errors="coerce").mean()
        )

    if "LONGITUDE" in merged_df.columns:
        meta.station_lon = float(
            pd.to_numeric(merged_df["LONGITUDE"], errors="coerce").mean()
        )

    if "Elevation" in merged_df.columns:
        meta.station_ele = float(
            pd.to_numeric(merged_df["Elevation"], errors="coerce").mean()
        )

    # ── 2. Site elevation ──────────────────────────────────────
    # Use provided value (from Stage 1 confirm) or fetch from API
    if site_ele_m is not None and site_ele_m > 0:
        meta.site_ele = site_ele_m
    else:
        fetched = get_elevation_m(site_lat, site_lon)
        meta.site_ele = fetched if fetched is not None else meta.station_ele
        if fetched is None:
            messages.append(
                "Could not fetch site elevation from API — "
                "using station elevation as fallback. "
                "Enter manually if incorrect."
            )

    # ── 3. Station elevation from API (for accurate comparison) ─
    station_ele_api = get_elevation_m(meta.station_lat, meta.station_lon)
    meta.station_ele_api = (
        station_ele_api if station_ele_api is not None
        else meta.station_ele
    )

    # ── 4. Timezone + UTC offset (delta_time) ─────────────────
    # From your notebook Cell 12 — DST handled automatically
    try:
        meta.timezone_name = get_timezone_name(site_lat, site_lon) or ""
        meta.delta_time    = get_utc_offset_hours(site_lat, site_lon)
    except Exception as e:
        messages.append(f"Timezone lookup failed: {e}. Using UTC offset 0.")
        meta.delta_time    = 0.0
        meta.timezone_name = "Unknown"

    # ── 5. Pressure ────────────────────────────────────────────
    # calc_pressure_psi uses the barometric formula from geo_utils.py
    # Your notebook used psychrolib.GetStandardAtmPressure — same formula
    meta.pressure_psi         = calc_pressure_psi(meta.site_ele)
    meta.station_pressure_psi = calc_pressure_psi(meta.station_ele_api)

    # ── 6. Distance ────────────────────────────────────────────
    meta.distance_miles = haversine_miles(
        site_lat, site_lon,
        meta.station_lat, meta.station_lon,
    )

    # ── 7. QA checks ───────────────────────────────────────────
    meta.elevation_delta_ft = abs(
        meters_to_feet(meta.site_ele) - meters_to_feet(meta.station_ele_api)
    )

    if meta.distance_miles > 30:
        meta.distance_warning = True
        messages.append(
            f"Station is {meta.distance_miles:.1f} miles from site "
            f"(threshold: 30 mi). Results may not represent site conditions."
        )

    if meta.elevation_delta_ft > 500:
        meta.elevation_warning = True
        messages.append(
            f"Elevation difference is {meta.elevation_delta_ft:.0f} ft "
            f"(threshold: 500 ft). This affects wet bulb accuracy."
        )

    # ── QA status ──────────────────────────────────────────────
    n_warn = len(messages)
    if n_warn == 0:
        status = "pass"
    elif meta.distance_warning and meta.elevation_warning:
        status = "fail"
    else:
        status = "warn"

    qa = {
        "status": status,
        "metrics": {
            "station_name":      meta.station_name,
            "distance_miles":    round(meta.distance_miles, 1),
            "elevation_delta_ft": round(meta.elevation_delta_ft, 0),
            "delta_time":        meta.delta_time,
            "pressure_psi":      round(meta.pressure_psi, 3),
            "timezone":          meta.timezone_name,
        },
        "messages": messages,
    }

    return meta, qa


# ─────────────────────────────────────────────────────────────
#  Update config from metadata result
# ─────────────────────────────────────────────────────────────

def apply_metadata_to_config(meta: "StationMeta", cfg) -> None:
    """
    Write metadata results back into WeatherConfig.
    Called after extract_metadata() to update cfg in session_state.

    Updates: station_name, station_lat/lon/ele,
             delta_time, pressure_psi
    """
    cfg.station_name  = meta.station_name
    cfg.station_lat   = meta.station_lat
    cfg.station_lon   = meta.station_lon
    cfg.station_ele   = meta.station_ele
    cfg.delta_time    = meta.delta_time
    cfg.pressure_psi  = meta.pressure_psi


# ─────────────────────────────────────────────────────────────
#  Self-test
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pandas as pd

    # simulate a small merged_df from NOAA data
    test_df = pd.DataFrame({
        "STATION":      ["USW00023080"] * 5,
        "Station_name": ["EL PASO"] * 5,
        "LATITUDE":     ["31.8122"] * 5,
        "LONGITUDE":    ["-106.3775"] * 5,
        "Elevation":    ["1202.1"] * 5,
    })

    site_lat, site_lon = 31.925864846669693, -106.71248240822992

    print("=== metadata.py self-test ===")
    print("Extracting metadata (will call Open-Elevation API)...")

    meta, qa = extract_metadata(test_df, site_lat, site_lon)

    print(f"\nStation:         {meta.station_name} ({meta.station_id})")
    print(f"Station lat/lon: {meta.station_lat:.4f}, {meta.station_lon:.4f}")
    print(f"Station ele:     {meta.station_ele:.1f} m = {meta.station_ele*3.28084:.0f} ft")
    print(f"Site ele:        {meta.site_ele:.1f} m = {meta.site_ele*3.28084:.0f} ft")
    print(f"Elevation delta: {meta.elevation_delta_ft:.0f} ft")
    print(f"Distance:        {meta.distance_miles:.1f} miles")
    print(f"Timezone:        {meta.timezone_name} ({meta.delta_time:+.1f}h)")
    print(f"Pressure (site): {meta.pressure_psi:.3f} psia")
    print(f"\nQA status: {qa['status'].upper()}")
    for msg in qa["messages"]:
        print(f"  ⚠ {msg}")

    print("\nSummary table:")
    from tabulate import tabulate
    print(tabulate(meta.summary_table(), tablefmt="grid"))
