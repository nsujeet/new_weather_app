"""
pipeline/filtering.py

Data cleaning + filter scoring + best filter selection.
Notebook cells 16, 18, 20.

Three steps:
  1. clean_and_shift()   — remove non-numeric temp/dew, shift to local timezone
                           produces df3 (your notebook variable name preserved)
  2. score_filters()     — build all 4 filter candidates, compute missing %
                           produces df_filtered_datasets + missing_data_results
  3. apply_filter()      — assign df6 from the chosen filter key

Your notebook variable names preserved inside functions:
  df, df1, df2, df3, df6
  df_filter_report_type, df_filter_minute_freq,
  df_filter_quality_temp, df_filter_minute_and_report
  df_filtered_datasets, missing_data_results
  best_filter, ALL_YEARS
"""

import calendar
import pandas as pd
import numpy as np
from datetime import timedelta
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────
#  Step 1 — clean and shift
# ─────────────────────────────────────────────────────────────

def clean_and_shift(
    merged_df: pd.DataFrame,
    delta_time: float,
    exclude_quality_codes: set = frozenset({"2", "3"}),
) -> tuple[pd.DataFrame, dict]:
    """
    Clean the raw merged DataFrame and shift timestamps to local time.
    Produces df3 — same as your notebook Cell 16.

    Steps (mirrors notebook exactly):
      df  → raw merged
      df1 → keep only rows with numeric temperature
      df2 → from df1, keep only rows with numeric dew point
      df3 → timezone-shifted DATE, TMP_F, DEW_F added,
             metadata columns passed through

    Args:
        merged_df:  raw merged DataFrame from download.py
        delta_time: UTC offset hours from metadata.py (cfg.delta_time)

    Returns:
        (df3, qa)
        df3 has columns: DATE (local time), TMP_F, DEW_F,
                         temperature, dew_point_temperature,
                         + all metadata pass-through columns
    """
    df = merged_df.copy()

    # ── Stage 1: keep rows with numeric temperature ───────────
    temp_num  = pd.to_numeric(df["temperature"], errors="coerce")
    mask_temp = temp_num.notna()
    df1       = df[mask_temp].copy()
    df1["temperature"] = temp_num.loc[df1.index].values

    dropped_temp = (~mask_temp).sum()

    # ── Stage 2: keep rows with numeric dew point ─────────────
    dew_num  = pd.to_numeric(df1["dew_point_temperature"], errors="coerce")
    mask_dew = dew_num.notna()
    df2      = df1[mask_dew].copy()
    df2["dew_point_temperature"] = dew_num.loc[df2.index].values

    dropped_dew = (~mask_dew).sum()

    # ── Stage 2b: drop sensor-flagged readings ────────────────
    dropped_flagged = 0
    if exclude_quality_codes and "temperature_Quality_Code" in df2.columns:
        bad = df2["temperature_Quality_Code"].astype(str).str.strip().isin(
            {str(c) for c in exclude_quality_codes}
        )
        dropped_flagged = int(bad.sum())
        df2 = df2[~bad].copy()

    # ── Stage 3: build df3 ────────────────────────────────────
    df3 = pd.DataFrame()
    df3["DATE"] = (
        pd.to_datetime(df2["DATE"], errors="coerce")
        + timedelta(hours=delta_time)
    )

    # Fahrenheit columns (your notebook names)
    df3["TMP_F"] = df2["temperature"].values * 9 / 5 + 32
    df3["DEW_F"] = df2["dew_point_temperature"].values * 9 / 5 + 32

    # keep Celsius originals too
    df3["temperature"]           = df2["temperature"].values
    df3["dew_point_temperature"] = df2["dew_point_temperature"].values

    # pass-through metadata columns
    for col in [
        "temperature_Quality_Code", "temperature_Report_Type",
        "temperature_Source_Code",  "temperature_Source_Station_ID",
        "Station_name", "STATION", "LATITUDE", "LONGITUDE",
        "Elevation", "station_level_pressure",
        "relative_humidity", "wet_bulb_temperature",
    ]:
        if col in df2.columns:
            df3[col] = df2[col].values

    # count how many have invalid DATE before dropping
    before_date_drop = len(df3)
    dropped_date     = int(df3["DATE"].isna().sum())
    df3 = df3.dropna(subset=["DATE"]).reset_index(drop=True)

    # ── Detailed diagnostics (before any filtering) ──────────
    sample_dates_raw = (
        df["DATE"].dropna().astype(str).head(5).tolist()
        if "DATE" in df.columns else []
    )

    # Count truly non-empty (non-blank) temperature values
    if "temperature" in df.columns:
        temp_col       = df["temperature"].astype(str).str.strip()
        temp_nonempty  = temp_col[temp_col != ""]
        temp_nonempty_count = len(temp_nonempty)
        # Sample from non-empty values (not just the first 5 rows)
        sample_temp_raw = temp_nonempty.head(10).tolist()
    else:
        temp_nonempty_count = 0
        sample_temp_raw     = []

    if "dew_point_temperature" in df.columns:
        dew_col      = df["dew_point_temperature"].astype(str).str.strip()
        dew_nonempty = dew_col[dew_col != ""]
        dew_nonempty_count = len(dew_nonempty)
        sample_dew_raw     = dew_nonempty.head(10).tolist()
    else:
        dew_nonempty_count = 0
        sample_dew_raw     = []

    all_columns = df.columns.tolist()

    # ── QA ────────────────────────────────────────────────────
    total_original = len(df)
    total_clean    = len(df3)

    qa = {
        "status":          "pass",
        "metrics": {
            "total_rows_raw":        total_original,
            "after_temp_filter":     total_original - int(dropped_temp),
            "after_dew_filter":      total_original - int(dropped_temp) - int(dropped_dew),
            "dropped_temp":          int(dropped_temp),
            "dropped_dew":           int(dropped_dew),
            "dropped_flagged":       dropped_flagged,
            "dropped_date":          dropped_date,
            "total_rows_clean":      total_clean,
            "pct_kept":              round(total_clean / total_original * 100, 1) if total_original else 0,
            "delta_time":            delta_time,
            "temp_nonempty_count":   temp_nonempty_count,
            "dew_nonempty_count":    dew_nonempty_count,
            "all_columns":           all_columns,
            "sample_dates_raw":      sample_dates_raw,
            "sample_temp_raw":       sample_temp_raw,
            "sample_dew_raw":        sample_dew_raw,
            "most_common_minute": (
                int(df3["DATE"].dt.minute.mode().iat[0])
                if "DATE" in df3.columns and not df3.empty
                   and not df3["DATE"].dt.minute.mode().empty
                else None
            ),
        },
        "messages": [],
    }

    pct_dropped = 100 - qa["metrics"]["pct_kept"]
    if pct_dropped > 20:
        qa["status"] = "warn"
        qa["messages"].append(
            f"{pct_dropped:.1f}% of rows dropped during cleaning — "
            "unusually high. Check raw data quality."
        )
    if dropped_date == before_date_drop and before_date_drop > 0:
        qa["messages"].append(
            f"All {before_date_drop:,} rows had unparseable DATE values. "
            f"Sample raw DATE: {sample_dates_raw}"
        )
    if int(dropped_temp) == total_original and total_original > 0:
        qa["messages"].append(
            f"Temperature column has {temp_nonempty_count:,} non-blank values "
            f"out of {total_original:,} rows, but none parsed as numeric. "
            f"Sample values: {sample_temp_raw[:5]}. "
            f"This station may not report temperature — "
            f"select a different NOAA station."
        )
    elif int(dropped_dew) >= (total_original - int(dropped_temp)) and (total_original - int(dropped_temp)) > 0:
        qa["messages"].append(
            f"All rows after temp filter dropped — dew_point column is "
            f"entirely non-numeric. "
            f"Sample raw dew point values: {sample_dew_raw}"
        )

    return df3, qa


# ─────────────────────────────────────────────────────────────
#  Step 2 — score all 4 filters
# ─────────────────────────────────────────────────────────────

@dataclass
class FilterResult:
    """Score for one filter candidate."""
    key:            str
    label:          str
    df:             pd.DataFrame
    rows:           int
    coverage_pct:   float          # 100 - avg missing %
    total_missing:  float          # sum of missing % across all month/year cells
    missing_table:  pd.DataFrame   # 12 x N months/years missing %
    best_value:     str            # the value used to filter (e.g. "FM-15")
    is_recommended: bool = False


def score_filters(
    df3:      pd.DataFrame,
    min_year: int,
    max_year: int,
) -> tuple[dict[str, FilterResult], str]:
    """
    Build all 4 filter candidates, compute missing data percentages,
    and recommend the best one.

    Mirrors notebook Cell 18 exactly — same 4 filters, same scoring.

    Args:
        df3:      cleaned DataFrame from clean_and_shift()
        min_year: MinYear from config (exclusive lower bound)
        max_year: MaxYear from config (inclusive upper bound)

    Returns:
        (results_dict, best_filter_key)
        results_dict: { filter_key: FilterResult }
        best_filter_key: key of the recommended filter
    """
    df3 = df3.copy()
    df3["DATE"] = pd.to_datetime(df3["DATE"], errors="coerce")

    # year window — same as notebook: MinYear+1 to MaxYear inclusive
    ALL_YEARS = list(range(int(min_year) + 1, int(max_year) + 1))

    # ── Best values for each dimension ────────────────────────
    def _idxmax_safe(series):
        vc = series.value_counts()
        return vc.idxmax() if not vc.empty else None

    best_report  = _idxmax_safe(df3["temperature_Report_Type"]) \
                   if "temperature_Report_Type" in df3.columns else None
    best_minute  = _idxmax_safe(df3["DATE"].dt.minute)
    best_quality = _idxmax_safe(df3["temperature_Quality_Code"]) \
                   if "temperature_Quality_Code" in df3.columns else None

    # ── Build 4 filter DataFrames ─────────────────────────────
    def _year_filter(df):
        return df[
            (df["DATE"].dt.year > min_year) &
            (df["DATE"].dt.year <= max_year)
        ]

    candidates = {}

    # Filter 1: report type
    if best_report is not None:
        df_rt = df3[df3["temperature_Report_Type"] == best_report]
        candidates["report_type"] = (df_rt, f"Report type = {best_report}")

    # Filter 2: minute frequency
    if best_minute is not None:
        df_mf = df3[df3["DATE"].dt.minute == best_minute]
        candidates["minute_freq"] = (df_mf, f"Minute = :{best_minute:02d}")

    # Filter 3: minute + report type
    if best_report is not None and best_minute is not None:
        df_mr = df3[
            (df3["temperature_Report_Type"] == best_report) &
            (df3["DATE"].dt.minute == best_minute)
        ]
        candidates["minute_and_report"] = (
            df_mr,
            f"Minute = :{best_minute:02d} AND report = {best_report}"
        )

    # Filter 4: quality code
    if best_quality is not None:
        df_qt = df3[df3["temperature_Quality_Code"] == best_quality]
        candidates["quality_temp(all)"] = (
            df_qt,
            f"Quality code = {best_quality}"
        )

    # ── Score each filter ─────────────────────────────────────
    results: dict[str, FilterResult] = {}

    for key, (df_raw, label) in candidates.items():
        df_windowed = _year_filter(df_raw)
        missing_tbl = _calculate_missing_percentage(df_windowed, ALL_YEARS)
        total_miss  = float(missing_tbl.to_numpy().sum())
        n_cells     = missing_tbl.size
        coverage    = round(100 - (total_miss / n_cells), 1) if n_cells > 0 else 0

        # get best_value from the label
        bv = label.split("=")[-1].strip() if "=" in label else "—"

        results[key] = FilterResult(
            key=key, label=label,
            df=df_windowed, rows=len(df_windowed),
            coverage_pct=coverage,
            total_missing=total_miss,
            missing_table=missing_tbl,
            best_value=bv,
        )

    # ── Recommend best ────────────────────────────────────────
    available = [k for k, r in results.items() if not r.df.empty]
    if available:
        best_key = min(available, key=lambda k: results[k].total_missing)
        results[best_key].is_recommended = True
    else:
        best_key = list(results.keys())[0] if results else ""

    return results, best_key


# ─────────────────────────────────────────────────────────────
#  Step 3 — apply chosen filter → df6
# ─────────────────────────────────────────────────────────────

def apply_filter(
    results:    dict[str, FilterResult],
    chosen_key: str,
) -> pd.DataFrame:
    """
    Return df6 — the chosen filter's DataFrame.
    Mirrors notebook Cell 20:
        df6 = df_filtered_datasets[best_filter]

    Args:
        results:    dict from score_filters()
        chosen_key: which filter to use

    Returns:
        df6 DataFrame
    """
    if chosen_key not in results:
        raise KeyError(
            f"Filter key '{chosen_key}' not found. "
            f"Available: {list(results.keys())}"
        )
    return results[chosen_key].df.copy()


# ─────────────────────────────────────────────────────────────
#  Missing % helper — from notebook Cell 18
# ─────────────────────────────────────────────────────────────

def _calculate_missing_percentage(
    df:          pd.DataFrame,
    force_years: list[int],
) -> pd.DataFrame:
    """
    Returns a 12 x N DataFrame (months × years) with % missing hours.
    Identical to calculate_missing_percentage() in your notebook Cell 18.
    """
    if df is None or df.empty:
        return pd.DataFrame(
            100.0, index=range(1, 13), columns=force_years
        )

    local = df.copy()
    local["DATE"] = pd.to_datetime(local["DATE"], errors="coerce")
    local = local.dropna(subset=["DATE"])

    count_hrs = local.pivot_table(
        values="temperature",
        index=local["DATE"].dt.month,
        columns=local["DATE"].dt.year,
        aggfunc="count",
        fill_value=0,
    )

    count_hrs = count_hrs.reindex(index=range(1, 13), fill_value=0)
    count_hrs = count_hrs.reindex(columns=force_years, fill_value=0)

    max_hrs = pd.DataFrame(
        {y: [calendar.monthrange(y, m)[1] * 24 for m in range(1, 13)]
         for y in force_years},
        index=range(1, 13),
    )

    missing_pct = (1 - (count_hrs / max_hrs)).clip(0, 1) * 100
    return missing_pct.round(1)


# ─────────────────────────────────────────────────────────────
#  Convenience — summary table for UI
# ─────────────────────────────────────────────────────────────

def filter_summary_table(
    results: dict[str, FilterResult],
) -> pd.DataFrame:
    """
    Returns a tidy DataFrame summarising all filter candidates.
    Suitable for st.dataframe() in the stage card.
    """
    _cols = ["Filter", "Description", "Rows", "Coverage (%)", "Recommended"]
    if not results:
        return pd.DataFrame(columns=_cols)
    rows = []
    for key, r in results.items():
        rows.append({
            "Filter":       key,
            "Description":  r.label,
            "Rows":         r.rows,
            "Coverage (%)": r.coverage_pct,
            "Recommended":  "★" if r.is_recommended else "",
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────
#  Self-test
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pandas as pd
    import numpy as np

    print("=== filtering.py self-test ===")

    # build a small synthetic merged_df
    np.random.seed(42)
    n = 5000
    dates = pd.date_range("2020-01-01", periods=n, freq="h")

    test_df = pd.DataFrame({
        "DATE":                      dates.strftime("%Y-%m-%d %H:%M:%S"),
        "STATION":                   ["USW00023080"] * n,
        "Station_name":              ["EL PASO"] * n,
        "temperature":               (np.random.normal(20, 8, n)).round(1).astype(str),
        "dew_point_temperature":     (np.random.normal(5, 5, n)).round(1).astype(str),
        "temperature_Report_Type":   np.random.choice(["FM-15", "FM-12", "SAO"], n,
                                                       p=[0.7, 0.2, 0.1]),
        "temperature_Quality_Code":  np.random.choice(["1", "5", "9"], n,
                                                       p=[0.8, 0.15, 0.05]),
        "LATITUDE":  ["31.8122"] * n,
        "LONGITUDE": ["-106.3775"] * n,
        "Elevation": ["1202.1"] * n,
    })
    # inject some non-numeric to test cleaning
    test_df.loc[10:15, "temperature"] = "M"
    test_df.loc[20:22, "dew_point_temperature"] = "9999"

    # step 1
    df3, qa1 = clean_and_shift(test_df, delta_time=-6.0)
    print(f"\nStep 1 — clean_and_shift:")
    print(f"  Raw rows:   {qa1['metrics']['total_rows_raw']}")
    print(f"  Clean rows: {qa1['metrics']['total_rows_clean']}")
    print(f"  Kept:       {qa1['metrics']['pct_kept']}%")
    print(f"  QA status:  {qa1['status'].upper()}")

    # step 2
    results, best = score_filters(df3, min_year=2019, max_year=2021)
    print(f"\nStep 2 — score_filters:")
    from tabulate import tabulate
    tbl = filter_summary_table(results)
    print(tabulate(tbl, headers="keys", tablefmt="grid", showindex=False))
    print(f"\nBest filter: {best}")

    # step 3
    df6 = apply_filter(results, best)
    print(f"\nStep 3 — apply_filter:")
    print(f"  df6 shape: {df6.shape}")
    print(f"  DATE range: {df6['DATE'].min()} → {df6['DATE'].max()}")
