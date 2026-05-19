"""
pipeline/statistics.py

Design conditions + yearly grouping + winterization analysis.
Notebook cells 45, 47, 50, 52, 54.

Three sections:
  1. compute_design_conditions()  — percentile table (DB, WB, MCWB, MCDB)
                                    + 1% condition values (Cell 45, 50)
  2. compute_yearly_grouping()    — yearly Tdb/Twb stats + degF-hrs (Cell 47)
  3. compute_winterization()      — freezing heatmap + no-freeze window (Cells 52, 54)

All notebook variable names preserved.
"""

import calendar
import datetime
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from itertools import groupby
from operator import itemgetter


# ─────────────────────────────────────────────────────────────
#  1. Design conditions
# ─────────────────────────────────────────────────────────────

@dataclass
class DesignConditions:
    """Percentile table + 1% design values. Notebook Cell 45 + 50."""

    # full Stats DataFrame — notebook variable name
    Stats: pd.DataFrame = field(default_factory=pd.DataFrame)

    # 1% condition values — notebook Cell 50
    T1_Tdb_acf:  float = 0.0   # 1% dry bulb
    T1_MCWB_acf: float = 0.0   # mean coincident WB at 1% DB
    T1_Twb_acf:  float = 0.0   # 1% wet bulb
    T1_MCDB_acf: float = 0.0   # mean coincident DB at 1% WB

    # yearly grouping — notebook Cell 47
    yearly_grouping:  pd.DataFrame = field(default_factory=pd.DataFrame)
    max_year_last_5:  int  = 0
    df_max_degF_hrs:  pd.DataFrame = field(default_factory=pd.DataFrame)

    acf: int = 99   # annual cumulative frequency used

    qa: dict = field(default_factory=dict)


def compute_design_conditions(
    hourly_dataframe:       pd.DataFrame,
    hourly_temperature_2m:  np.ndarray,
    hourly_wetbulb_point_2m:np.ndarray,
    thou_degG_hrs:          np.ndarray,
    acf:                    int = 99,
) -> DesignConditions:
    """
    Compute percentile table and 1% design conditions.
    Mirrors notebook Cells 45 and 50 exactly.

    Args:
        hourly_dataframe:        from psychrometrics (Tdb, Twb, etc.)
        hourly_temperature_2m:   Tdb array
        hourly_wetbulb_point_2m: Twb array
        thou_degG_hrs:           degF-hrs array
        acf:                     annual cumulative frequency (default 99 = 1%)

    Returns:
        DesignConditions with Stats DataFrame and 1% values
    """
    result = DesignConditions(acf=acf)
    messages = []

    # ── Percentile table — Cell 45 ─────────────────────────────
    percentiles     = [0, 0.4, 1, 2, 5, *range(10, 101, 5)]
    rev_percentiles = [100 - p for p in percentiles]

    DB   = np.percentile(hourly_dataframe["Tdb"], rev_percentiles)
    WB   = np.percentile(hourly_dataframe["Twb"], rev_percentiles)
    MCWB = [
        hourly_wetbulb_point_2m[
            hourly_temperature_2m.round() == v
        ].mean()
        for v in DB.round()
    ]
    MCDB = [
        hourly_temperature_2m[
            hourly_wetbulb_point_2m.round() == v
        ].mean()
        for v in WB.round()
    ]

    Stats = pd.DataFrame(percentiles, columns=["%"])
    Stats["DB_F"]   = DB
    Stats["MCWB_F"] = MCWB
    Stats["WB_F"]   = WB
    Stats["MCDB_F"] = MCDB

    # Celsius columns
    for col_f, col_c in [
        ("DB_F",   "DB_C"),
        ("MCWB_F", "MCWB_C"),
        ("WB_F",   "WB_C"),
        ("MCDB_F", "MCDB_C"),
    ]:
        Stats[col_c] = 5 * (Stats[col_f] - 32) / 9

    result.Stats = Stats.round(2)

    # ── 1% design values — Cell 50 ────────────────────────────
    T1_Tdb_acf  = float(np.percentile(hourly_dataframe["Tdb"], acf))
    T1_Twb_acf  = float(np.percentile(hourly_dataframe["Twb"], acf))
    T1_MCWB_acf = float(
        hourly_wetbulb_point_2m[
            hourly_temperature_2m.round() == round(T1_Tdb_acf)
        ].mean()
    )
    T1_MCDB_acf = float(
        hourly_temperature_2m[
            hourly_wetbulb_point_2m.round() == round(T1_Twb_acf)
        ].mean()
    )

    result.T1_Tdb_acf  = round(T1_Tdb_acf,  1)
    result.T1_MCWB_acf = round(T1_MCWB_acf, 1)
    result.T1_Twb_acf  = round(T1_Twb_acf,  1)
    result.T1_MCDB_acf = round(T1_MCDB_acf, 1)

    # ── Yearly grouping — Cell 47 ──────────────────────────────
    yg = pd.DataFrame()
    for col, agg, src in [
        ("Tdb_max", "max",  "Tdb"),
        ("Tdb_min", "min",  "Tdb"),
        ("Tdb_avg", "mean", "Tdb"),
        ("Tdp_max", "max",  "Tdp"),
        ("Tdp_min", "min",  "Tdp"),
        ("Tdp_avg", "mean", "Tdp"),
        ("Twb_max", "max",  "Twb"),
        ("Twb_min", "min",  "Twb"),
        ("Twb_avg", "mean", "Twb"),
    ]:
        if src in hourly_dataframe.columns:
            yg[col] = hourly_dataframe.groupby(
                hourly_dataframe.index.year)[src].agg(agg)

    yg["degF_hrs"] = hourly_dataframe.groupby(
        hourly_dataframe.index.year)["degG_hrs"].sum()

    yg["degF_hrs_norm"] = [
        v * 365 / 366 if calendar.isleap(yr) else v
        for yr, v in zip(yg.index, yg["degF_hrs"])
    ]

    ten_yr_avg = thou_degG_hrs.sum() / 10
    yg["degF_hrs_delta_10YR_avg"] = yg["degF_hrs_norm"] - ten_yr_avg

    result.yearly_grouping = yg.round(2)

    # max degF-hrs year from last 5 non-leap years
    last_5      = range(hourly_dataframe.index.year.max() - 4,
                        hourly_dataframe.index.year.max() + 1)
    non_leap    = [y for y in last_5 if not calendar.isleap(y)]
    yg_last5    = yg[yg.index.isin(non_leap)]

    if not yg_last5.empty:
        max_year = int(yg_last5["degF_hrs"].idxmax())
        result.max_year_last_5 = max_year
        result.df_max_degF_hrs = hourly_dataframe[
            hourly_dataframe.index.year == max_year
        ].copy()
    else:
        result.max_year_last_5 = int(hourly_dataframe.index.year.max())
        result.df_max_degF_hrs = hourly_dataframe.copy()

    # ── QA ────────────────────────────────────────────────────
    pct_label = 100 - acf
    if np.isnan(T1_MCWB_acf):
        messages.append(
            f"MCWB at {pct_label}% could not be computed — "
            "no data at rounded Tdb value."
        )

    result.qa = {
        "status":   "pass" if not messages else "warn",
        "metrics": {
            f"Tdb_{pct_label}pct":  result.T1_Tdb_acf,
            f"Twb_{pct_label}pct":  result.T1_Twb_acf,
            f"MCWB_{pct_label}pct": result.T1_MCWB_acf,
            f"MCDB_{pct_label}pct": result.T1_MCDB_acf,
            "max_degF_hrs_year":    result.max_year_last_5,
            "total_kdegF_hrs":      round(float(thou_degG_hrs.sum()), 1),
        },
        "messages": messages,
    }

    return result


# ─────────────────────────────────────────────────────────────
#  2. Winterization
# ─────────────────────────────────────────────────────────────

@dataclass
class WinterizationResult:
    """Freezing analysis from df_winterization. Notebook Cells 52, 54."""

    # heatmap data — min TMP_F per month/year
    min_temp_table:   pd.DataFrame = field(default_factory=pd.DataFrame)

    # freezing hours per fiscal week
    freezing_hours:   pd.Series = field(default_factory=pd.Series)

    # no-freeze window
    no_freeze_start_week: int  = 0
    no_freeze_end_week:   int  = 0
    no_freeze_start_date: datetime.date = None
    no_freeze_end_date:   datetime.date = None

    freezing_threshold: float = 36.0

    qa: dict = field(default_factory=dict)


def compute_winterization(
    df_winterization:    pd.DataFrame,
    freezing_threshold:  float = 36.0,
    max_year_last_5:     int   = None,
) -> WinterizationResult:
    """
    Freezing analysis on the 15-year window.
    Mirrors notebook Cells 52 and 54.

    Args:
        df_winterization:   15-year hourly DataFrame (from processing)
        freezing_threshold: temperature below which it's "freezing" (default 36°F)
        max_year_last_5:    reference year for no-freeze window dates

    Returns:
        WinterizationResult
    """
    result = WinterizationResult(freezing_threshold=freezing_threshold)
    messages = []

    dfw = df_winterization.copy()
    dfw["DATE"] = pd.to_datetime(dfw.index)
    dfw["TMP_F"] = pd.to_numeric(dfw["TMP_F"], errors="coerce")

    # ── Min temp heatmap — Cell 52 ────────────────────────────
    dfw["year"]  = dfw["DATE"].dt.year
    dfw["month"] = dfw["DATE"].dt.month

    result.min_temp_table = dfw.pivot_table(
        index="month", columns="year",
        values="TMP_F", aggfunc="min",
    ).round(1)

    # ── Freezing hours per fiscal week — Cell 54 ──────────────
    dfw["below_freeze"] = dfw["TMP_F"] < freezing_threshold
    dfw["fiscal_week"]  = dfw["DATE"].dt.isocalendar().week.astype(int)

    freezing_hours = dfw.groupby("fiscal_week")["below_freeze"].sum()
    result.freezing_hours = freezing_hours

    # ── No-freeze window — Cell 54 ────────────────────────────
    no_freeze_weeks = freezing_hours[freezing_hours == 0].index.tolist()

    if len(no_freeze_weeks) < 2:
        messages.append(
            "Could not find a no-freeze window — "
            "freezing conditions present in all or most weeks."
        )
    else:
        try:
            start_week, end_week = _find_longest_consecutive(no_freeze_weeks)
            result.no_freeze_start_week = start_week
            result.no_freeze_end_week   = end_week

            # convert to dates
            ref_year = max_year_last_5 or int(dfw["year"].max())
            result.no_freeze_start_date = _week_to_date(start_week, ref_year)
            result.no_freeze_end_date   = (
                _week_to_date(end_week, ref_year)
                + datetime.timedelta(days=6)
            )
        except Exception as e:
            messages.append(f"No-freeze window calculation failed: {e}")

    result.qa = {
        "status":   "pass" if not messages else "warn",
        "metrics": {
            "years_covered":     len(dfw["year"].unique()),
            "pct_below_freeze":  round(
                float(dfw["below_freeze"].mean()) * 100, 1),
            "no_freeze_start":   str(result.no_freeze_start_date),
            "no_freeze_end":     str(result.no_freeze_end_date),
        },
        "messages": messages,
    }

    return result


# ─────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────

def _find_longest_consecutive(weeks: list) -> tuple[int, int]:
    """Find the longest consecutive run in a list of week numbers."""
    ranges = []
    for k, g in groupby(enumerate(weeks), lambda x: x[0] - x[1]):
        group = list(map(itemgetter(1), g))
        ranges.append((group[0], group[-1]))
    return max(ranges, key=lambda r: r[1] - r[0])


def _week_to_date(week_number: int, year: int) -> datetime.date:
    """Convert ISO week number to a date, clamping week 53 if needed."""
    max_weeks = datetime.date(year, 12, 28).isocalendar()[1]
    valid_week = min(week_number, max_weeks)
    return datetime.date.fromisocalendar(year, valid_week, 1)


# ─────────────────────────────────────────────────────────────
#  Self-test
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import numpy as np
    import pandas as pd

    print("=== statistics.py self-test ===")

    # synthetic hourly_dataframe
    np.random.seed(42)
    dates = pd.date_range("2015-01-01", "2024-12-31 23:00", freq="h")
    n = len(dates)
    tdb = np.random.normal(75, 20, n).clip(5, 120).astype(np.float32)
    twb = tdb - np.random.uniform(5, 25, n).astype(np.float32)
    tdp = tdb - np.random.uniform(8, 30, n).astype(np.float32)
    kdh = np.where(tdb - 50 > 0, (tdb - 50) / 1000, 0)

    hourly_df = pd.DataFrame({
        "Tdb": tdb, "Twb": twb, "Tdp": tdp,
        "RH": np.random.uniform(20, 90, n),
        "psia": 12.64,
        "degG_hrs": kdh,
    }, index=dates)

    dc = compute_design_conditions(
        hourly_dataframe=hourly_df,
        hourly_temperature_2m=tdb,
        hourly_wetbulb_point_2m=twb,
        thou_degG_hrs=kdh,
        acf=99,
    )

    m = dc.qa["metrics"]
    print(f"\nDesign conditions (1% = 99th percentile):")
    print(f"  1% Tdb:   {m['Tdb_1pct']}°F")
    print(f"  1% Twb:   {m['Twb_1pct']}°F")
    print(f"  MCWB:     {m['MCWB_1pct']}°F")
    print(f"  MCDB:     {m['MCDB_1pct']}°F")
    print(f"  Max degF-hrs year: {m['max_degF_hrs_year']}")
    print(f"  Total k°F-hrs: {m['total_kdegF_hrs']}")
    print(f"  QA: {dc.qa['status'].upper()}")

    print(f"\nStats table (first 5 rows):")
    print(dc.Stats.head().to_string())

    # winterization
    dfw = hourly_df.copy()
    dfw["TMP_F"] = tdb

    wr = compute_winterization(dfw, freezing_threshold=36.0,
                               max_year_last_5=dc.max_year_last_5)
    print(f"\nWinterization:")
    print(f"  No-freeze window: week {wr.no_freeze_start_week} "
          f"({wr.no_freeze_start_date}) → "
          f"week {wr.no_freeze_end_week} ({wr.no_freeze_end_date})")
    print(f"  % below {wr.freezing_threshold}°F: "
          f"{wr.qa['metrics']['pct_below_freeze']}%")
    print(f"  QA: {wr.qa['status'].upper()}")
