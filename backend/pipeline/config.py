"""
pipeline/config.py

All the inputs from notebook Cell 1 — now in one dataclass.
Your variable names are preserved exactly so the rest of the code
looks familiar.

Usage:
    from pipeline.config import WeatherConfig
    cfg = WeatherConfig()          # defaults from your notebook
    cfg.station = "USW00023019"
    cfg.site_lat = 31.9259
"""

from dataclasses import dataclass, field


@dataclass
class WeatherConfig:
    # ── Site location ──────────────────────────────────────────
    # Negative lon = west of Greenwich, negative lat = south of equator
    site_lat: float = 31.925864846669693
    site_lon: float = -106.71248240822992

    # ── NOAA station ───────────────────────────────────────────
    station: str = "USW00023019"

    # ── Plant information ──────────────────────────────────────
    GT_frame: str = ""          # turbine model
    num_train: int = 1
    gt_per_train: int = 1       # gas turbines per train
    num_st: int = 0             # steam turbines
    T2: float = 50.0            # desired inlet temperature °F
    Chiller_and_Heat_Rejection: str = ""
    fluid: str = "Water"

    # ── Operating mode ─────────────────────────────────────────
    chiller_operation: str = "Direct"   # DIRECT, FULL, PARTIAL
    peak_hours: int = 8

    # ── Units and thresholds ───────────────────────────────────
    units: str = "F"            # "F" or "C"
    freezing_threshold: float = 36.0
    acf: int = 99               # annual cumulative frequency (99 = 1% condition)

    # ── Year range ─────────────────────────────────────────────
    # StartYear / EndYear: used for NOAA download (YYYY-MM-DD or YYYY)
    # MinYear / MaxYear:   used for filtering window (integer)
    # MinYear should be StartYear-1 so the start year is included
    StartYear: str = "2011-01-01"
    EndYear: str = "2026-01-01"
    MinYear: int = 2010
    MaxYear: int = 2026

    # ── Weather source ─────────────────────────────────────────
    weather_source: str = "NOAA"        # NOAA, ASHRAE, or customer_supplied
    station_name_ashrae: str = ""
    Supplied_Design_Day_Tdb: str = "N/A"
    Supplied_Design_Day_Twb: str = "N/A"

    # ── Customer design day (optional override) ────────────────
    customer_data: bool = False
    TDB_customer: float = 104.0
    TWB_customer: float = 65.0

    # ── Word template ──────────────────────────────────────────
    Template: str = "NO"

    # ── Derived — computed after station data loads ────────────
    # These start empty and get filled in by metadata.py
    station_name: str = ""
    station_lat: float = 0.0
    station_lon: float = 0.0
    station_ele: float = 0.0    # metres
    delta_time: float = 0.0     # UTC offset hours (includes DST)
    pressure_psi: float = 14.696  # will be recalculated from elevation

    def year_range(self) -> list[int]:
        """Return list of integer years from StartYear to EndYear inclusive."""
        start = int(str(self.StartYear)[:4])
        end   = int(str(self.EndYear)[:4])
        return list(range(start, end + 1))

    def analysis_years(self) -> list[int]:
        """Years used for the analysis window (MinYear+1 to MaxYear)."""
        return list(range(self.MinYear + 1, self.MaxYear + 1))
