"""
pipeline/psychrometrics.py

Psychrometric calculations — notebook Cell 33.

Takes hourly_temperature_2m and hourly_dew_point_2m arrays from
processing.py and computes:
  - wet bulb temperature  (hourly_wetbulb_point_2m)
  - relative humidity     (hourly_relative_humidity_2m)
  - degree-F hours        (thou_degG_hrs)
  - hourly_dataframe      (indexed DataFrame with all columns)

Uses psychrolib in IP units (°F, psia).
All notebook variable names preserved.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field


@dataclass
class PsychroResult:
    """All outputs from the psychrometrics stage."""
    # arrays — notebook names
    hourly_temperature_2m:      np.ndarray = field(default_factory=lambda: np.array([]))
    hourly_dew_point_clamped:   np.ndarray = field(default_factory=lambda: np.array([]))
    hourly_wetbulb_point_2m:    np.ndarray = field(default_factory=lambda: np.array([]))
    hourly_relative_humidity_2m:np.ndarray = field(default_factory=lambda: np.array([]))
    thou_degG_hrs:              np.ndarray = field(default_factory=lambda: np.array([]))

    # dataframe — notebook name
    hourly_dataframe: pd.DataFrame = field(default_factory=pd.DataFrame)

    # QA
    qa: dict = field(default_factory=dict)


def compute_psychrometrics(
    hourly_temperature_2m: np.ndarray,
    hourly_dew_point_2m:   np.ndarray,
    date:                  np.ndarray,
    pressure_psi:          float,
) -> PsychroResult:
    """
    Compute wet bulb, RH, degF-hrs and build hourly_dataframe.
    Mirrors notebook Cell 33 exactly.

    Args:
        hourly_temperature_2m: dry bulb °F array (from processing)
        hourly_dew_point_2m:   dew point °F array (from processing)
        date:                  datetime index array (from processing)
        pressure_psi:          site pressure in psia (from metadata)

    Returns:
        PsychroResult with all arrays and hourly_dataframe
    """
    import psychrolib
    psychrolib.SetUnitSystem(psychrolib.IP)

    result = PsychroResult()
    messages = []

    # ── Cast to float64 and drop NaN rows ─────────────────────
    T_raw  = hourly_temperature_2m.astype(np.float64)
    Td_raw = hourly_dew_point_2m.astype(np.float64)
    D_raw  = np.asarray(date)

    valid  = ~(np.isnan(T_raw) | np.isnan(Td_raw))
    n_dropped = int(np.sum(~valid))
    if n_dropped > 0:
        messages.append(
            f"{n_dropped} hours dropped before psychrometrics (NaN temperature or dew point)."
        )

    T  = T_raw[valid]
    Td = Td_raw[valid]
    D  = D_raw[valid]
    P  = float(pressure_psi)

    result.hourly_temperature_2m = T

    # ── 1. Clamp dew point ≤ dry bulb ─────────────────────────
    Td = np.minimum(Td, T)
    n_clamped = int(np.sum(Td_raw[valid] > T))
    result.hourly_dew_point_clamped = Td

    if n_clamped > 0:
        messages.append(
            f"{n_clamped} hours had dew point > dry bulb — clamped to dry bulb."
        )

    # ── 2. Wet bulb — np.vectorize (fast, works on all versions) ─
    wb_failed_rows: list[dict] = []

    def _safe_wb(t, td):
        try:
            return psychrolib.GetTWetBulbFromTDewPoint(float(t), float(td), P)
        except Exception as exc:
            wb_failed_rows.append({
                "Tdb_F": round(float(t),  2),
                "Tdp_F": round(float(td), 2),
                "P_psi": round(P,         4),
                "error": str(exc),
            })
            return np.nan

    _get_wb = np.vectorize(_safe_wb, otypes=[np.float64])
    _get_humratio = np.vectorize(
        lambda td: psychrolib.GetHumRatioFromTDewPoint(td, P),
        otypes=[np.float64],
    )
    _get_rh = np.vectorize(
        lambda t, w: psychrolib.GetRelHumFromHumRatio(t, w, P),
        otypes=[np.float64],
    )

    wb_raw = np.round(_get_wb(T, Td), 2)

    # Drop rows where wet bulb computation failed (numerical instability)
    wb_ok = ~np.isnan(wb_raw)
    n_wb_failed = int(np.sum(~wb_ok))
    if n_wb_failed > 0:
        T  = T[wb_ok];  Td = Td[wb_ok];  D = D[wb_ok]
        wb_raw = wb_raw[wb_ok]
        messages.append(
            f"{n_wb_failed} hours dropped — wet bulb numerical instability."
        )

    result.hourly_wetbulb_point_2m    = wb_raw
    result.hourly_temperature_2m      = T
    result.hourly_dew_point_clamped   = Td

    # ── 3. Relative humidity ──────────────────────────────────
    W = _get_humratio(Td)
    result.hourly_relative_humidity_2m = np.clip(
        _get_rh(T, W) * 100.0, 0, 100
    )

    # ── 4. Degree-F hours above 50°F ─────────────────────────
    result.thou_degG_hrs = np.where(T - 50 > 0, (T - 50) / 1000, 0)

    # ── 5. Build hourly_dataframe ─────────────────────────────
    hourly_data = pd.DataFrame({
        "date":     D,
        "Tdb":      T,
        "Tdp":      Td,
        "Twb":      result.hourly_wetbulb_point_2m,
        "RH":       result.hourly_relative_humidity_2m,
        "psia":     pressure_psi,
        "degG_hrs": result.thou_degG_hrs,
    })
    result.hourly_dataframe = hourly_data.set_index("date")

    # ── QA ────────────────────────────────────────────────────
    n_total    = len(T)
    tdb_min    = float(np.min(T))
    tdb_max    = float(np.max(T))
    twb_min    = float(np.min(result.hourly_wetbulb_point_2m))
    twb_max    = float(np.max(result.hourly_wetbulb_point_2m))
    rh_min     = float(np.min(result.hourly_relative_humidity_2m))
    rh_max     = float(np.max(result.hourly_relative_humidity_2m))
    total_kdh  = float(np.sum(result.thou_degG_hrs))

    n_wb_gt_db = int(np.sum(result.hourly_wetbulb_point_2m > T + 0.1))
    if n_wb_gt_db > 0:
        messages.append(
            f"{n_wb_gt_db} hours have WB > DB — check pressure or data."
        )

    result.qa = {
        "status":   "pass" if not messages else "warn",
        "metrics": {
            "n_total":     n_total,
            "n_dropped":   n_dropped,
            "n_clamped":   n_clamped,
            "n_wb_failed": n_wb_failed,
            "tdb_min":     round(tdb_min, 1),
            "tdb_max":     round(tdb_max, 1),
            "twb_min":     round(twb_min, 1),
            "twb_max":     round(twb_max, 1),
            "rh_min":      round(rh_min,  1),
            "rh_max":      round(rh_max,  1),
            "total_kdh":   round(total_kdh, 1),
            "pressure_psi": pressure_psi,
        },
        "messages": messages,
        "wb_failed_rows": wb_failed_rows,   # list of {Tdb_F, Tdp_F, P_psi, error}
    }

    return result


# ─────────────────────────────────────────────────────────────
#  Self-test
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import numpy as np
    import pandas as pd

    print("=== psychrometrics.py self-test ===")

    n     = 8760
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    tdb   = np.random.normal(75, 20, n).astype(np.float32)
    tdp   = tdb - np.random.uniform(5, 30, n).astype(np.float32)

    result = compute_psychrometrics(
        hourly_temperature_2m=tdb,
        hourly_dew_point_2m=tdp,
        date=dates.to_numpy(),
        pressure_psi=12.64,
    )

    m = result.qa["metrics"]
    print(f"\nRows:           {m['n_total']:,}")
    print(f"Tdb range:      {m['tdb_min']}°F – {m['tdb_max']}°F")
    print(f"Twb range:      {m['twb_min']}°F – {m['twb_max']}°F")
    print(f"RH range:       {m['rh_min']}% – {m['rh_max']}%")
    print(f"Total k°F-hrs:  {m['total_kdh']:.1f}")
    print(f"Clamped:        {m['n_clamped']}")
    print(f"WB failed:      {m['n_wb_failed']}")
    print(f"QA:             {result.qa['status'].upper()}")
    print(f"\nhourly_dataframe head:")
    print(result.hourly_dataframe.head(3).round(2).to_string())
