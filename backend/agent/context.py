"""
agent/context.py

Builds a context string from session_state that gets injected into
every agent call. This is what gives the agent awareness of where
the user is in the pipeline without re-explaining every time.

Used by agent/calls.py for every Claude API call.
"""

from pipeline.config import WeatherConfig


def build_context(state: dict) -> str:
    """
    Snapshot current pipeline state as a plain-English string.
    Injected as system context into every agent call.

    Args:
        state: dict-like (st.session_state or plain dict for testing)

    Returns:
        Multi-line string describing current pipeline state.
    """
    cfg: WeatherConfig = state.get("config", WeatherConfig())

    # years loaded
    years_loaded = sorted(state.get("years_data", {}).keys())
    years_str = (
        f"{years_loaded[0]}–{years_loaded[-1]} "
        f"({len(years_loaded)} years)"
        if years_loaded else "none loaded yet"
    )

    # merged data
    merged = state.get("merged_df")
    merged_str = (
        f"{len(merged):,} rows" if merged is not None else "not built yet"
    )

    # station info
    station_meta = state.get("station_meta", {})
    station_str = (
        f"{cfg.station} — {station_meta.get('name', 'unknown name')}"
        if cfg.station else "not set"
    )

    # site info
    site_ele = state.get("site_elevation_m")
    site_str = (
        f"lat={cfg.site_lat:.4f}, lon={cfg.site_lon:.4f}, "
        f"elevation={site_ele:.0f}m"
        if site_ele else
        f"lat={cfg.site_lat:.4f}, lon={cfg.site_lon:.4f}"
    )

    # current stage
    stage = state.get("current_stage", "data_source")

    # qa results
    last_qa = state.get("last_qa")
    qa_str = (
        f"status={last_qa['status']}, "
        f"messages={last_qa.get('messages', [])}"
        if last_qa else "none yet"
    )

    return f"""You are an assistant embedded in a weather analysis pipeline
for gas turbine inlet cooling projects at Stellar Energy.

Current pipeline state:
  Stage:          {stage}
  Site:           {site_str}
  Station:        {station_str}
  Years loaded:   {years_str}
  Merged data:    {merged_str}
  Last QA:        {qa_str}

The pipeline processes NOAA GHCNh hourly weather data to compute
psychrometric design conditions (1% Tdb, Twb, MCWB) and winterization
analysis for gas turbine sites.

Be concise. Return structured JSON when asked for data.
When returning coordinates or numeric values, be precise."""


def build_dataframes_context(state: dict) -> dict:
    """
    Return a dict of available named DataFrames from session_state.
    Passed to execute_python tool so agent can query real data.
    """
    available = {}

    for key, label in [
        ("merged_df",       "merged_df"),
        ("df6",             "df6"),
        ("df_interpolated", "df_interpolated"),
        ("hourly_df",       "hourly_df"),
        ("yearly_grouping", "yearly_grouping"),
    ]:
        val = state.get(key)
        if val is not None and hasattr(val, "shape"):
            available[label] = val

    return available
