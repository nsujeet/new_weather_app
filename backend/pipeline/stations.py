"""
pipeline/stations.py

Station lookup and ranking from the local GHCNh station list CSV.
Pure Python — no Streamlit, no agent, no network calls.

The station CSV (ghcnh-station-list.csv) lives in the data/ folder.
Columns used: GHCN_ID, NAME, STATE, LATITUDE, LONGITUDE, ELEVATION, ISO_CODE

Used by:
  - app.py  (Step B of Stage 1)
  - agent/tools.py  (wrapped as find_stations tool)

Ranking logic:
  score = (dist_miles / 30) + (elev_delta_ft / 500)
  Lower score = better match.
  dist weight 30mi and elev weight 500ft are chosen so that
  a station 30mi away with perfect elevation scores the same as
  a station at the site with 500ft elevation difference.
  This reflects real-world experience: elevation matters more
  than distance for psychrometric accuracy.
"""

import os
import pandas as pd
import numpy as np
try:
    from pipeline.geo_utils import haversine_miles, meters_to_feet
except ModuleNotFoundError:
    from geo_utils import haversine_miles, meters_to_feet

# default path — can be overridden
DEFAULT_CSV = os.path.join(
    os.path.dirname(__file__), "..", "data", "ghcnh-station-list.csv"
)

# stations with elevation = -999.9 have unknown elevation — exclude
UNKNOWN_ELEVATION = -999.9

# thresholds for recommendation status
MAX_DIST_MILES     = 30.0   # beyond this → warn or ask user
MAX_ELEV_DELTA_FT  = 500.0  # beyond this → warn
EXPAND_DIST_MILES  = 75.0   # wider search radius if nothing in 30mi

# USW prefix = major US official stations (airports, NWS)
# These have the most complete hourly records
PREFERRED_PREFIX = "USW"


# ─────────────────────────────────────────────────────────────
#  Load station list
# ─────────────────────────────────────────────────────────────

def load_station_list(csv_path: str = DEFAULT_CSV) -> pd.DataFrame:
    """
    Load and clean the GHCNh station list CSV.

    Filters out:
      - Stations with unknown elevation (-999.9)
      - Rows with missing lat/lon

    Adds:
      - elevation_ft column
      - is_preferred flag (USW prefix stations)

    Returns:
        DataFrame with columns:
        GHCN_ID, NAME, STATE, ISO_CODE,
        LATITUDE, LONGITUDE, ELEVATION (metres), elevation_ft,
        is_preferred
    """
    df = pd.read_csv(csv_path, low_memory=False)

    # drop unknown elevations
    df = df[df["ELEVATION"] != UNKNOWN_ELEVATION].copy()

    # drop missing lat/lon
    df = df.dropna(subset=["LATITUDE", "LONGITUDE"])

    # add feet column
    df["elevation_ft"] = (df["ELEVATION"] * 3.28084).round(0)

    # flag preferred stations
    df["is_preferred"] = df["GHCN_ID"].str.startswith(PREFERRED_PREFIX)

    return df.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
#  Find and rank nearest stations
# ─────────────────────────────────────────────────────────────

def find_nearest_stations(
    site_lat: float,
    site_lon: float,
    site_elevation_m: float,
    stations_df: pd.DataFrame,
    max_miles: float = EXPAND_DIST_MILES,
    n: int = 5,
) -> pd.DataFrame:
    """
    Find the n nearest stations to a site, ranked by combined
    distance + elevation score.

    Always returns n stations — no hard radius cap. max_miles is kept
    for backwards compatibility but is no longer used as a filter.

    Args:
        site_lat:         site latitude (decimal degrees)
        site_lon:         site longitude (decimal degrees)
        site_elevation_m: site elevation in metres
        stations_df:      loaded station list from load_station_list()
        max_miles:        unused (kept for API compat)
        n:                number of results to return (default 5)

    Returns:
        DataFrame with n rows, columns:
        GHCN_ID, NAME, STATE, ISO_CODE,
        LATITUDE, LONGITUDE, ELEVATION, elevation_ft,
        dist_miles, elev_delta_m, elev_delta_ft,
        score, is_preferred, recommendation_status
    """
    df = stations_df.copy()

    site_ele_ft = meters_to_feet(site_elevation_m)

    # vectorised haversine using numpy
    df["dist_miles"] = _haversine_vectorised(
        site_lat, site_lon,
        df["LATITUDE"].values,
        df["LONGITUDE"].values,
    )

    # elevation delta
    df["elev_delta_m"]  = (df["ELEVATION"] - site_elevation_m).abs()
    df["elev_delta_ft"] = (df["elevation_ft"] - site_ele_ft).abs()

    # combined score — lower is better
    df["score"] = (
        df["dist_miles"]  / 30.0 +
        df["elev_delta_ft"] / 500.0
    )

    # sort by score, take top n
    df = df.sort_values("score").head(n).reset_index(drop=True)

    # add recommendation status per station
    df["recommendation_status"] = df.apply(
        lambda row: _station_status(row["dist_miles"], row["elev_delta_ft"]),
        axis=1,
    )

    # round display columns
    df["dist_miles"]   = df["dist_miles"].round(1)
    df["elev_delta_ft"] = df["elev_delta_ft"].round(0)
    df["score"]        = df["score"].round(2)

    return df[[
        "GHCN_ID", "NAME", "STATE", "ISO_CODE",
        "LATITUDE", "LONGITUDE", "ELEVATION", "elevation_ft",
        "dist_miles", "elev_delta_ft", "score",
        "is_preferred", "recommendation_status",
    ]]


def recommend_station(ranked_df: pd.DataFrame) -> dict:
    """
    Given a ranked station DataFrame, return a recommendation dict.

    Returns:
        {
          "station_id":   str,
          "station_name": str,
          "dist_miles":   float,
          "elev_delta_ft": float,
          "status":       "green" | "yellow" | "red",
          "message":      str,
          "row":          pd.Series  (full row for the recommended station)
        }
    """
    if ranked_df.empty:
        return {
            "station_id":    None,
            "station_name":  None,
            "dist_miles":    None,
            "elev_delta_ft": None,
            "status":        "red",
            "message":       "No stations found within search radius.",
            "row":           None,
        }

    best = ranked_df.iloc[0]
    status = _station_status(best["dist_miles"], best["elev_delta_ft"])

    messages = {
        "green": (
            f"{best['NAME']} is {best['dist_miles']:.1f} mi away with "
            f"{best['elev_delta_ft']:.0f} ft elevation difference — good match."
        ),
        "yellow": (
            f"{best['NAME']} is {best['dist_miles']:.1f} mi away but "
            f"{best['elev_delta_ft']:.0f} ft elevation difference is notable. "
            f"Check if a closer-elevation station is acceptable."
        ),
        "red": (
            f"Best available station ({best['NAME']}) is "
            f"{best['dist_miles']:.1f} mi away. "
            f"Consider expanding the search radius or entering a station manually."
        ),
    }

    return {
        "station_id":    best["GHCN_ID"],
        "station_name":  best["NAME"],
        "dist_miles":    best["dist_miles"],
        "elev_delta_ft": best["elev_delta_ft"],
        "status":        status,
        "message":       messages[status],
        "row":           best,
    }


# ─────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────

def _haversine_vectorised(
    lat1: float, lon1: float,
    lat2: np.ndarray, lon2: np.ndarray,
) -> np.ndarray:
    """
    Vectorised haversine for one point vs an array of points.
    Much faster than calling haversine_miles() in a loop for 38k stations.
    """
    R = 3958.8
    lat1_r = np.radians(lat1)
    lat2_r = np.radians(lat2)
    dlat   = np.radians(lat2 - lat1)
    dlon   = np.radians(lon2 - lon1)

    a = (np.sin(dlat / 2) ** 2
         + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2) ** 2)

    return 2 * R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _station_status(dist_miles: float, elev_delta_ft: float) -> str:
    """
    Return green / yellow / red for a single station.

    green:  within 30mi AND elev delta < 500ft
    yellow: within 30mi but elev delta >= 500ft,
            OR outside 30mi but elev delta < 500ft
    red:    outside 30mi AND elev delta >= 500ft
    """
    close    = dist_miles   <= MAX_DIST_MILES
    elev_ok  = elev_delta_ft <= MAX_ELEV_DELTA_FT

    if close and elev_ok:
        return "green"
    if close or elev_ok:
        return "yellow"
    return "red"


# ─────────────────────────────────────────────────────────────
#  Quick self-test
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os

    csv_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "ghcnh-station-list.csv"
    )

    print("=== stations.py self-test ===")
    print("Loading station list...")
    stations = load_station_list(csv_path)
    print(f"Loaded {len(stations):,} stations ({stations['is_preferred'].sum()} preferred)")

    # El Paso site
    site_lat, site_lon = 31.925864846669693, -106.71248240822992
    site_ele_m = 1144.0

    print(f"\nFinding stations near El Paso site (ele={site_ele_m}m)...")
    ranked = find_nearest_stations(site_lat, site_lon, site_ele_m, stations)
    print(ranked[[
        "GHCN_ID","NAME","dist_miles","elevation_ft",
        "elev_delta_ft","score","is_preferred","recommendation_status"
    ]].to_string())

    rec = recommend_station(ranked)
    print(f"\nRecommendation: {rec['station_id']} — {rec['status'].upper()}")
    print(f"  {rec['message']}")
