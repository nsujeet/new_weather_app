"""
pipeline/processing.py

Data processing pipeline — notebook Cell 23.
Four sequential steps, each producing a named DataFrame:

  df_original    — df6 set to hourly index, outliers clipped
  df_resample    — hourly mean resample, sensor-freeze values removed
  df_replacement — gap-fill from donor years (only if month >10% missing)
  df_interpolated — linear interpolation, sliced to 10-year window
  df_winterization — same interpolation, sliced to 15-year window

Your notebook variable names are preserved exactly throughout.

Returns a ProcessingResult dataclass with all DataFrames + QA stats.
"""

import calendar
import numpy as np
import pandas as pd
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────
#  Result dataclass
# ─────────────────────────────────────────────────────────────

@dataclass
class ProcessingResult:
    # DataFrames — notebook variable names
    df_original:      pd.DataFrame = field(default_factory=pd.DataFrame)
    df_resample:      pd.DataFrame = field(default_factory=pd.DataFrame)
    df_replacement:   pd.DataFrame = field(default_factory=pd.DataFrame)
    df_interpolated:  pd.DataFrame = field(default_factory=pd.DataFrame)
    df_winterization: pd.DataFrame = field(default_factory=pd.DataFrame)

    # arrays for psychrometrics (notebook names)
    hourly_temperature_2m: np.ndarray = field(default_factory=lambda: np.array([]))
    hourly_dew_point_2m:   np.ndarray = field(default_factory=lambda: np.array([]))
    date:                  np.ndarray = field(default_factory=lambda: np.array([]))

    # missing % tables at each step
    missing_original:     pd.DataFrame = field(default_factory=pd.DataFrame)
    missing_resample:     pd.DataFrame = field(default_factory=pd.DataFrame)
    missing_replacement:  pd.DataFrame = field(default_factory=pd.DataFrame)
    missing_interpolation:pd.DataFrame = field(default_factory=pd.DataFrame)

    # replacement log
    replacement_log: list = field(default_factory=list)
    total_filled:    dict = field(default_factory=dict)

    # window bounds
    start_10: pd.Timestamp = None
    start_15: pd.Timestamp = None
    end_date: pd.Timestamp = None

    # QA
    qa: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────
#  Main entry point
# ─────────────────────────────────────────────────────────────

def process(
    df6:              pd.DataFrame,
    end_year:         int | str,
    clip_lower_f:     float = 5.0,
    clip_upper_f:     float | None = None,
    clip_lower_dew_f: float | None = None,
    clip_upper_dew_f: float | None = None,
) -> ProcessingResult:
    """
    Run the full processing pipeline on df6.

    Args:
        df6:              filtered DataFrame from filtering.apply_filter()
        end_year:         MaxYear / EndYear from config
        clip_lower_f:     clip TMP_F (dry bulb) below this → NaN (default 5°F)
        clip_upper_f:     clip TMP_F above this → NaN (None = no upper clip)
        clip_lower_dew_f: clip DEW_F below this → NaN (None = use clip_lower_f)
        clip_upper_dew_f: clip DEW_F above this → NaN (None = use clip_upper_f)

    Returns:
        ProcessingResult with all DataFrames and QA stats
    """
    result = ProcessingResult()
    messages = []

    dew_lower = clip_lower_dew_f if clip_lower_dew_f is not None else clip_lower_f
    dew_upper = clip_upper_dew_f if clip_upper_dew_f is not None else clip_upper_f

    # ── Step 1: Outlier clip + set index ──────────────────────
    df_original, count_orig, max_orig = _clip_and_index(
        df6, clip_lower_f, clip_upper_f, dew_lower, dew_upper
    )
    result.df_original     = df_original
    result.missing_original = _missing_pct(count_orig, max_orig)

    # ── Step 2: Resample to hourly ────────────────────────────
    df_resample, count_res, max_res = _resample(df_original)
    result.df_resample     = df_resample
    result.missing_resample = _missing_pct(count_res, max_res)

    # ── Step 3: Donor replacement ─────────────────────────────
    missing_pct_resample = _missing_pct(count_res, max_res)
    df_replacement, log, filled = _donor_replacement(
        df_resample, missing_pct_resample
    )
    result.df_replacement  = df_replacement
    result.replacement_log = log
    result.total_filled    = filled

    count_repl = _count_hrs(df_replacement)
    max_repl   = _max_hrs(df_replacement)
    result.missing_replacement = _missing_pct(count_repl, max_repl)

    # ── Step 4: Define windows + interpolate ──────────────────
    anchor   = _make_anchor(end_year)
    end_date = anchor - pd.Timedelta(hours=1)
    start_10 = anchor - pd.DateOffset(years=10)
    start_15 = anchor - pd.DateOffset(years=15)

    result.start_10 = start_10
    result.start_15 = start_15
    result.end_date = end_date

    df_interp_full = (
        df_replacement
        .interpolate(method="linear")
    )

    result.df_interpolated  = df_interp_full.loc[start_10:end_date].copy()
    result.df_winterization = df_interp_full.loc[start_15:end_date].copy()

    count_interp = _count_hrs(result.df_interpolated)
    max_interp   = _max_hrs(result.df_interpolated)
    result.missing_interpolation = _missing_pct(count_interp, max_interp)

    # ── Arrays for psychrometrics (notebook names) ─────────────
    result.hourly_temperature_2m = (
        result.df_interpolated["TMP_F"].to_numpy(dtype=np.float32)
    )
    result.hourly_dew_point_2m = (
        result.df_interpolated["DEW_F"].to_numpy(dtype=np.float32)
    )
    result.date = result.df_interpolated.index.to_numpy()

    # ── QA ────────────────────────────────────────────────────
    final_missing = float(result.missing_interpolation.to_numpy().mean())
    remaining_nan = int(result.df_interpolated["TMP_F"].isna().sum())

    if final_missing > 15:
        messages.append(
            f"Average missing after interpolation: {final_missing:.1f}% — "
            "consider reviewing year selection or filter choice."
        )
    if remaining_nan > 0:
        messages.append(
            f"{remaining_nan} NaN values remain after interpolation — "
            "likely at the edges of the date range."
        )

    result.qa = {
        "status":   "pass" if not messages else "warn",
        "metrics": {
            "rows_original":    len(df_original),
            "rows_resample":    len(df_resample),
            "rows_replacement": len(df_replacement),
            "rows_interpolated":len(result.df_interpolated),
            "rows_winterization":len(result.df_winterization),
            "filled_TMP_F":     filled.get("TMP_F", 0),
            "filled_DEW_F":     filled.get("DEW_F", 0),
            "remaining_nan":    remaining_nan,
            "avg_missing_pct":  round(final_missing, 1),
            "window_10y":       f"{start_10.date()} → {end_date.date()}",
            "window_15y":       f"{start_15.date()} → {end_date.date()}",
        },
        "messages": messages,
    }

    return result


# ─────────────────────────────────────────────────────────────
#  Step 1 — clip outliers + set datetime index
# ─────────────────────────────────────────────────────────────

def _clip_and_index(
    df6:              pd.DataFrame,
    clip_lower_tmp:   float,
    clip_upper_tmp:   float | None,
    clip_lower_dew:   float | None,
    clip_upper_dew:   float | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Mirrors notebook Cell 23 — clip TMP_F/DEW_F separately, set DATE as index.
    Returns (df_original, count_hrs, max_hrs)
    """
    df = df6[["DATE", "TMP_F", "DEW_F"]].copy()
    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
    df = df.dropna(subset=["DATE"]).set_index("DATE")

    # ensure numeric — df6 may have string columns from merged_df
    df["TMP_F"] = pd.to_numeric(df["TMP_F"], errors="coerce")
    df["DEW_F"] = pd.to_numeric(df["DEW_F"], errors="coerce")

    # dry bulb clips
    if clip_lower_tmp is not None:
        df["TMP_F"] = df["TMP_F"].where(df["TMP_F"] >= clip_lower_tmp, np.nan)
    if clip_upper_tmp is not None:
        df["TMP_F"] = df["TMP_F"].where(df["TMP_F"] <= clip_upper_tmp, np.nan)
    # dew point clips
    if clip_lower_dew is not None:
        df["DEW_F"] = df["DEW_F"].where(df["DEW_F"] >= clip_lower_dew, np.nan)
    if clip_upper_dew is not None:
        df["DEW_F"] = df["DEW_F"].where(df["DEW_F"] <= clip_upper_dew, np.nan)

    count = _count_hrs(df)
    maxh  = _max_hrs(df)
    return df, count, maxh


# ─────────────────────────────────────────────────────────────
#  Step 2 — resample to hourly
# ─────────────────────────────────────────────────────────────

def _resample(
    df_original: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Resample to hourly mean. Remove sensor-freeze artefacts (32°F / 23°F).
    Returns (df_resample, count_hrs, max_hrs)
    """
    df_resample = df_original[["TMP_F", "DEW_F"]].resample("h").mean()

    # remove sensor-freeze values — same as notebook
    mask_freeze = (
        (
            np.isclose(df_resample["TMP_F"], 32.0, atol=1e-9) &
            np.isclose(df_resample["DEW_F"], 32.0, atol=1e-9)
        ) | (
            np.isclose(df_resample["TMP_F"], 23.0, atol=1e-9) &
            np.isclose(df_resample["DEW_F"], 23.0, atol=1e-9)
        )
    )
    df_resample.loc[mask_freeze, ["TMP_F", "DEW_F"]] = np.nan

    count = _count_hrs(df_resample)
    maxh  = _max_hrs(df_resample)
    return df_resample, count, maxh


# ─────────────────────────────────────────────────────────────
#  Step 3 — donor replacement
# ─────────────────────────────────────────────────────────────

def _donor_replacement(
    df_resample:      pd.DataFrame,
    missing_pct_in:   pd.DataFrame,
    columns:          list = None,
    thresholds:       list = None,
) -> tuple[pd.DataFrame, list, dict]:
    """
    Fill gaps from donor years. Only fills months with >10% missing.
    Donor must have <5% or <10% missing AND be better than target.

    Mirrors the replacement logic in notebook Cell 23 exactly.

    Returns (df_replacement, replacement_log, total_filled)
    """
    if columns is None:
        columns = ["TMP_F", "DEW_F"]
    if thresholds is None:
        thresholds = [5, 10]

    df_replacement  = df_resample.copy()
    replacement_log = []
    total_filled    = {col: 0 for col in columns}
    missing_pct     = missing_pct_in.copy()

    for month in range(1, 13):
        years_here = sorted(int(y) for y in
            df_replacement.index[df_replacement.index.month == month].year.unique()
        )

        if month not in missing_pct.index:
            continue
        month_row = missing_pct.loc[month].dropna()

        for year in years_here:
            target_mask = (
                (df_replacement.index.year  == year) &
                (df_replacement.index.month == month)
            )
            if not target_mask.any():
                continue

            target_block = df_replacement.loc[target_mask, columns]

            if not target_block.isna().any().any():
                replacement_log.append(
                    f"[{year}-{month:02d}] Skipped (no NaNs).")
                continue

            # target missing %
            try:
                target_miss = float(month_row.get(year, np.nan))
            except Exception:
                total_h = 24 * calendar.monthrange(year, month)[1]
                have_h  = int(target_block["TMP_F"].count())
                target_miss = 100 * (1 - have_h / max(1, total_h))

            # only replace if >10% missing
            if target_miss <= 10:
                replacement_log.append(
                    f"[{year}-{month:02d}] Skipped "
                    f"(missing {target_miss:.1f}% ≤ 10%).")
                continue

            # find best donor
            donor_year = None
            for th in thresholds:
                cands = month_row[
                    (month_row < th) & (month_row < target_miss)
                ].index.tolist()
                if not cands:
                    continue
                cands = sorted(int(c) for c in cands)[::-1]
                for ry in cands:
                    if (calendar.monthrange(year, month)[1] ==
                            calendar.monthrange(ry, month)[1]):
                        donor_year = ry
                        break
                if donor_year:
                    break

            if donor_year is None:
                replacement_log.append(
                    f"[{year}-{month:02d}] No suitable donor found.")
                continue

            # pull donor block
            donor_mask = (
                (df_resample.index.year  == donor_year) &
                (df_resample.index.month == month)
            )
            donor_block = df_resample.loc[donor_mask, columns]

            # align by day + hour position
            tgt = df_replacement.loc[target_mask, columns].copy()
            tgt_key = pd.MultiIndex.from_arrays(
                [tgt.index.day, tgt.index.hour])
            donor_key = pd.MultiIndex.from_arrays(
                [donor_block.index.day, donor_block.index.hour])
            tgt.index         = tgt_key
            donor_block_copy  = donor_block.copy()
            donor_block_copy.index = donor_key
            donor_aligned     = donor_block_copy.reindex(tgt.index)

            before_na = tgt.isna().sum()
            tgt       = tgt.where(~tgt.isna(), donor_aligned)
            after_na  = tgt.isna().sum()

            # write back
            orig_idx = df_replacement.loc[target_mask].index
            tgt      = tgt.set_index(orig_idx)
            df_replacement.loc[target_mask, columns] = tgt.values

            filled_counts = (before_na - after_na).astype(int)
            for col in columns:
                total_filled[col] += int(filled_counts[col])

            if filled_counts.sum() > 0:
                cs = ", ".join(
                    f"{col}:{filled_counts[col]}" for col in columns)
                replacement_log.append(
                    f"[{year}-{month:02d}] Filled {cs} from {donor_year} "
                    f"(target={target_miss:.1f}%, "
                    f"donor={month_row[donor_year]:.1f}%).")
            else:
                replacement_log.append(
                    f"[{year}-{month:02d}] Donor {donor_year}: "
                    f"no matching hours to fill.")

    return df_replacement, replacement_log, total_filled


# ─────────────────────────────────────────────────────────────
#  Shared helpers
# ─────────────────────────────────────────────────────────────

def _count_hrs(df: pd.DataFrame) -> pd.DataFrame:
    return df.pivot_table(
        values="TMP_F",
        index=df.index.month,
        columns=df.index.year,
        aggfunc="count",
        fill_value=0,
    )


def _max_hrs(df: pd.DataFrame) -> pd.DataFrame:
    years = df.index.year.unique()
    return pd.DataFrame(
        {y: [calendar.monthrange(y, m)[1] * 24 for m in range(1, 13)]
         for y in years},
        index=range(1, 13),
    )


def _missing_pct(
    count: pd.DataFrame,
    maxh:  pd.DataFrame,
) -> pd.DataFrame:
    """100 × (1 - count/max) — same formula as notebook Cell 30."""
    aligned_max = maxh.reindex(
        index=count.index, columns=count.columns, fill_value=0
    )
    pct = 100 * (1 - count / aligned_max.replace(0, np.nan))
    return pct.clip(0, 100).round(1)


def _make_anchor(end_year) -> pd.Timestamp:
    """Convert EndYear in any format to a Timestamp."""
    if isinstance(end_year, (int, np.integer)):
        return pd.Timestamp(int(end_year), 1, 1)
    s = str(end_year).strip()
    if len(s) == 4 and s.isdigit():
        return pd.Timestamp(int(s), 1, 1)
    return pd.Timestamp(pd.to_datetime(s).year, 1, 1)


# ─────────────────────────────────────────────────────────────
#  Self-test
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pandas as pd
    import numpy as np

    print("=== processing.py self-test ===")

    # build synthetic df6
    np.random.seed(42)
    dates = pd.date_range("2014-01-01", "2024-12-31 23:00", freq="h")
    n = len(dates)

    df6 = pd.DataFrame({
        "DATE":  dates,
        "TMP_F": np.random.normal(75, 20, n).astype(str),
        "DEW_F": np.random.normal(45, 15, n).astype(str),
    })
    # inject some bad values
    df6.loc[100:105, "TMP_F"] = "2"    # below clip threshold
    df6.loc[200:210, "TMP_F"] = np.nan

    result = process(df6, end_year=2025)

    m = result.qa["metrics"]
    print(f"\nRows at each step:")
    print(f"  df_original:      {m['rows_original']:,}")
    print(f"  df_resample:      {m['rows_resample']:,}")
    print(f"  df_replacement:   {m['rows_replacement']:,}")
    print(f"  df_interpolated:  {m['rows_interpolated']:,}")
    print(f"  df_winterization: {m['rows_winterization']:,}")
    print(f"\nGap filling:")
    print(f"  TMP_F filled: {m['filled_TMP_F']}")
    print(f"  DEW_F filled: {m['filled_DEW_F']}")
    print(f"  Remaining NaN: {m['remaining_nan']}")
    print(f"\nWindows:")
    print(f"  10-year: {m['window_10y']}")
    print(f"  15-year: {m['window_15y']}")
    print(f"\nQA: {result.qa['status'].upper()}")
    for msg in result.qa["messages"]:
        print(f"  ⚠ {msg}")

    print(f"\nhourly_temperature_2m: {result.hourly_temperature_2m[:5]}")
    print(f"hourly_dew_point_2m:   {result.hourly_dew_point_2m[:5]}")
