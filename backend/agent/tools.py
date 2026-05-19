"""
agent/tools.py

Agent tool definitions — thin wrappers around pipeline functions.
The agent (Claude API) calls these during the Stage 1 workflow.

Two types of tools:
  1. Native Anthropic tools  (web_search — handled by the API)
  2. Custom tools            (get_elevation, find_stations, execute_python)

Tool call flow:
  Agent decides it needs elevation → calls get_elevation tool
  → tool_executor() runs get_elevation_m() from geo_utils
  → result returned to agent as tool_result
  → agent continues with the elevation value

Nothing here imports Streamlit. The caller (app.py or agent/calls.py)
handles displaying results in the UI.
"""

import io
import sys
import json
import pandas as pd
import numpy as np
import math

from pipeline.geo_utils import get_elevation_m, calc_pressure_psi, meters_to_feet
from pipeline.stations import load_station_list, find_nearest_stations, recommend_station


# ─────────────────────────────────────────────────────────────
#  Tool definitions — passed to Claude API as tools=[]
# ─────────────────────────────────────────────────────────────

WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
}

GET_ELEVATION_TOOL = {
    "name": "get_elevation",
    "description": (
        "Get the elevation in metres and feet for a given latitude/longitude. "
        "Uses the Open-Elevation API. Call this after finding the site coordinates "
        "to get the exact site elevation needed for pressure calculation and "
        "station elevation comparison."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "latitude":  {"type": "number", "description": "Decimal degrees"},
            "longitude": {"type": "number", "description": "Decimal degrees"},
        },
        "required": ["latitude", "longitude"],
    },
}

FIND_STATIONS_TOOL = {
    "name": "find_stations",
    "description": (
        "Find the nearest NOAA GHCNh weather stations to a site. "
        "Uses a local station list CSV — no network call needed. "
        "Returns up to 5 stations ranked by combined distance and elevation match. "
        "Call this after confirming site coordinates and elevation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "site_lat":          {"type": "number", "description": "Site latitude"},
            "site_lon":          {"type": "number", "description": "Site longitude"},
            "site_elevation_m":  {"type": "number", "description": "Site elevation in metres"},
            "max_miles":         {
                "type": "number",
                "description": "Search radius in miles (default 75)",
                "default": 75,
            },
        },
        "required": ["site_lat", "site_lon", "site_elevation_m"],
    },
}

EXECUTE_PYTHON_TOOL = {
    "name": "execute_python",
    "description": (
        "Execute Python code against the user's weather dataframes. "
        "Use for calculations, aggregations, and data questions. "
        "Available: pd, np, math and any dataframe names passed in context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Python code to run. Use print() or assign to 'result'. "
                    "Available: pd, np, math and the named dataframes."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "One sentence — what this code computes.",
            },
        },
        "required": ["code", "reasoning"],
    },
}

# ── Tool sets for different agent contexts ─────────────────────
STATION_FINDER_TOOLS = [WEB_SEARCH_TOOL, GET_ELEVATION_TOOL, FIND_STATIONS_TOOL]
CHAT_TOOLS           = [WEB_SEARCH_TOOL, EXECUTE_PYTHON_TOOL]
ALL_TOOLS            = [WEB_SEARCH_TOOL, GET_ELEVATION_TOOL,
                        FIND_STATIONS_TOOL, EXECUTE_PYTHON_TOOL]


# ─────────────────────────────────────────────────────────────
#  Tool executor — routes tool calls to actual functions
# ─────────────────────────────────────────────────────────────

def execute_tool(
    tool_name: str,
    tool_input: dict,
    dataframes: dict | None = None,
    stations_df: pd.DataFrame | None = None,
) -> str:
    """
    Execute a tool call and return the result as a string.
    Called by the agentic loop in agent/calls.py.

    Args:
        tool_name:   name of the tool to run
        tool_input:  dict of arguments from the agent
        dataframes:  optional dict of named DataFrames for execute_python
        stations_df: optional pre-loaded station list for find_stations

    Returns:
        String result to send back to the agent as tool_result content.
    """

    if tool_name == "get_elevation":
        return _run_get_elevation(
            tool_input["latitude"],
            tool_input["longitude"],
        )

    elif tool_name == "find_stations":
        return _run_find_stations(
            tool_input["site_lat"],
            tool_input["site_lon"],
            tool_input["site_elevation_m"],
            tool_input.get("max_miles", 75),
            stations_df,
        )

    elif tool_name == "execute_python":
        return _run_execute_python(
            tool_input["code"],
            tool_input.get("reasoning", ""),
            dataframes or {},
        )

    else:
        return f"Unknown tool: {tool_name}"


# ─────────────────────────────────────────────────────────────
#  Individual tool runners
# ─────────────────────────────────────────────────────────────

def _run_get_elevation(lat: float, lon: float) -> str:
    """Call Open-Elevation and return a structured result string."""
    ele_m = get_elevation_m(lat, lon)

    if ele_m is None:
        return json.dumps({
            "error": "Open-Elevation API unavailable",
            "fallback": "User must enter elevation manually",
        })

    ele_ft  = meters_to_feet(ele_m)
    psi     = calc_pressure_psi(ele_m)

    return json.dumps({
        "elevation_m":   round(ele_m, 1),
        "elevation_ft":  round(ele_ft, 0),
        "pressure_psi":  psi,
        "latitude":      lat,
        "longitude":     lon,
    })


def _run_find_stations(
    site_lat: float,
    site_lon: float,
    site_elevation_m: float,
    max_miles: float,
    stations_df: pd.DataFrame | None,
) -> str:
    """Find nearest stations and return ranked results as JSON string."""
    if stations_df is None:
        # try loading from default path
        try:
            stations_df = load_station_list()
        except FileNotFoundError:
            return json.dumps({
                "error": (
                    "Station list CSV not found. "
                    "Place ghcnh-station-list.csv in the data/ folder."
                )
            })

    ranked = find_nearest_stations(
        site_lat, site_lon, site_elevation_m,
        stations_df, max_miles=max_miles, n=5,
    )

    if ranked.empty:
        return json.dumps({
            "error": f"No stations found within {max_miles} miles.",
            "suggestion": "Try expanding the search radius.",
        })

    rec = recommend_station(ranked)

    # convert DataFrame to list of dicts for JSON serialisation
    stations_list = ranked.to_dict(orient="records")

    return json.dumps({
        "stations":       stations_list,
        "recommendation": {
            "station_id":    rec["station_id"],
            "station_name":  rec["station_name"],
            "dist_miles":    rec["dist_miles"],
            "elev_delta_ft": rec["elev_delta_ft"],
            "status":        rec["status"],
            "message":       rec["message"],
        },
    }, default=str)


def _run_execute_python(
    code: str,
    reasoning: str,
    dataframes: dict,
) -> str:
    """
    Execute agent-written Python in a restricted namespace.
    Returns output as a string.
    """
    # safe globals — no os, subprocess, open, requests
    safe_globals = {
        "__builtins__": {
            "len": len, "range": range, "round": round,
            "min": min, "max": max, "sum": sum, "abs": abs,
            "list": list, "dict": dict, "str": str,
            "int": int, "float": float, "bool": bool,
            "print": print, "enumerate": enumerate,
            "zip": zip, "sorted": sorted,
            "isinstance": isinstance, "type": type,
        },
        "pd":   pd,
        "np":   np,
        "math": math,
    }

    local_ns = {**dataframes}
    stdout_capture = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout_capture

    try:
        exec(compile(code, "<agent>", "exec"), safe_globals, local_ns)  # noqa: S102
        sys.stdout = old_stdout
        output = stdout_capture.getvalue()

        if "result" in local_ns:
            val = local_ns["result"]
            if isinstance(val, pd.DataFrame):
                output += "\n" + val.to_string(max_rows=20)
            elif isinstance(val, pd.Series):
                output += "\n" + val.to_string(max_entries=20)
            else:
                output += "\n" + str(val)

        return output.strip() or "Done (no output)"

    except Exception as e:
        sys.stdout = old_stdout
        return f"ERROR — {type(e).__name__}: {e}"
