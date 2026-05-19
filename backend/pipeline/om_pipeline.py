"""
pipeline/om_pipeline.py

Condensed pipeline for Open-Meteo ERA5 data.
Skips Stages 2–3 (station metadata + filtering) — ERA5 is at exact site
coordinates with no gaps, so none of that is needed.

Flow:  om_df (°C) → df6 (°F) → process → psychrometrics → design_conditions → winterization
"""

import pandas as pd

from pipeline.processing     import process
from pipeline.psychrometrics import compute_psychrometrics
from pipeline.statistics     import compute_design_conditions, compute_winterization


def run_om_pipeline(
    om_df:               pd.DataFrame,
    end_year:            int,
    pressure_psi:        float,
    freezing_threshold:  float = 36.0,
    acf:                 int   = 99,
):
    """
    Run the condensed Open-Meteo pipeline and return all result objects.

    Args:
        om_df:             DataFrame from fetch_openmeteo() —
                           columns: DATE (UTC datetime), temperature (°C),
                           dew_point_temperature (°C)
        end_year:          Last year in the dataset (for process() window)
        pressure_psi:      Site pressure in psia
        freezing_threshold: Freeze threshold in °F (default 36)
        acf:               Annual cumulative frequency (99 → 1% condition)

    Returns:
        (processing_result, psychro_result, design_conditions, winterization)
    """
    df6 = _make_df6(om_df)

    proc = process(df6, end_year)

    psychro = compute_psychrometrics(
        proc.hourly_temperature_2m,
        proc.hourly_dew_point_2m,
        proc.date,
        pressure_psi,
    )

    dc = compute_design_conditions(
        hourly_dataframe        = psychro.hourly_dataframe,
        hourly_temperature_2m   = psychro.hourly_temperature_2m,
        hourly_wetbulb_point_2m = psychro.hourly_wetbulb_point_2m,
        thou_degG_hrs           = psychro.thou_degG_hrs,
        acf                     = acf,
    )

    wr = compute_winterization(
        df_winterization  = proc.df_winterization,
        freezing_threshold= freezing_threshold,
        max_year_last_5   = dc.max_year_last_5,
    )

    return proc, psychro, dc, wr


def _make_df6(om_df: pd.DataFrame) -> pd.DataFrame:
    """Convert Open-Meteo df (°C) to process()-compatible df6 (°F)."""
    df = om_df[["DATE", "temperature", "dew_point_temperature"]].copy()
    df["DATE"]  = pd.to_datetime(df["DATE"])
    df["TMP_F"] = df["temperature"].astype(float)           * 9 / 5 + 32
    df["DEW_F"] = df["dew_point_temperature"].astype(float) * 9 / 5 + 32
    return df[["DATE", "TMP_F", "DEW_F"]].dropna().reset_index(drop=True)
