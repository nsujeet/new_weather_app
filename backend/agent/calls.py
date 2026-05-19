"""
agent/calls.py

All agentic loops — functions that call the Claude API with tools
and run until the agent produces a final answer.

Two entry points:
  find_stations_agent()  — rank nearest stations for confirmed site
  chat()                 — persistent chat sidebar with full pipeline context

All functions return plain dicts or strings — no Streamlit imports here.
The caller (app.py) decides how to display results.

Requires ANTHROPIC_API_KEY in environment.
"""

import json
import os
import pandas as pd

from agent.context import build_context, build_dataframes_context
from agent.tools import (
    STATION_FINDER_TOOLS,
    CHAT_TOOLS,
    execute_tool,
)
from pipeline.stations import load_station_list

def _client():
    import anthropic
    return anthropic.Anthropic()

# ── default station list path ──────────────────────────────────
_DEFAULT_STATION_CSV = os.path.join(
    os.path.dirname(__file__), "..", "data", "ghcnh-station-list.csv"
)

# cache station list in module scope — loaded once per session
_stations_df: pd.DataFrame | None = None

def _get_stations_df() -> pd.DataFrame:
    global _stations_df
    if _stations_df is None:
        _stations_df = load_station_list(_DEFAULT_STATION_CSV)
    return _stations_df


# ─────────────────────────────────────────────────────────────
#  Station finder — Step B
# ─────────────────────────────────────────────────────────────

def find_stations_for_site(
    site_lat: float,
    site_lon: float,
    site_elevation_m: float,
    state: dict,
    max_miles: float = 75.0,
) -> dict:
    """
    Agent finds nearest NOAA stations for a confirmed site location.

    Uses the find_stations tool (local CSV — no network).
    Returns ranked list + recommendation.

    Args:
        site_lat, site_lon:  confirmed site coordinates
        site_elevation_m:    confirmed site elevation
        state:               session_state for context
        max_miles:           search radius

    Returns dict with keys:
        stations  (list of dicts — ranked),
        recommendation (dict with station_id, status, message),
        error (if failed)
    """
    system = build_context(state) + """

Your task: find the best NOAA weather station for this site.

Call the find_stations tool with the provided coordinates.
Then return ONLY a JSON object:

{
  "stations": [<list from tool result>],
  "recommendation": {<recommendation from tool result>},
  "explanation": "<1-2 sentence plain English explanation of why
                   the recommended station is the best choice>"
}"""

    messages = [{
        "role": "user",
        "content": (
            f"Find the nearest NOAA GHCNh stations for:\n"
            f"  lat={site_lat}, lon={site_lon}, "
            f"elevation={site_elevation_m:.0f}m\n"
            f"Search radius: {max_miles} miles."
        ),
    }]

    return _run_agentic_loop(
        system=system,
        messages=messages,
        tools=STATION_FINDER_TOOLS,
        state=state,
        max_iterations=4,
        result_key="station_search",
        extra_tool_kwargs={
            "stations_df": _get_stations_df(),
        },
    )


# ─────────────────────────────────────────────────────────────
#  Chat — persistent sidebar
# ─────────────────────────────────────────────────────────────

def chat(
    user_message: str,
    history: list[dict],
    state: dict,
) -> tuple[str, list[dict]]:
    """
    One turn of the persistent chat sidebar.

    Agent has access to web_search and execute_python.
    It knows the full pipeline state from build_context().

    Args:
        user_message: the user's latest message
        history:      list of {"role": "user"|"assistant",
                               "content": str} — previous turns
        state:        session_state for context + dataframes

    Returns:
        (reply_text, updated_history)
        updated_history includes this turn appended.
    """
    system = build_context(state)

    # describe available dataframes
    dfs = build_dataframes_context(state)
    if dfs:
        df_desc = "\n".join(
            f"  {name}: shape={df.shape}, "
            f"cols={list(df.columns[:6])}{'...' if len(df.columns) > 6 else ''}"
            for name, df in dfs.items()
        )
        system += f"\n\nAvailable dataframes for code execution:\n{df_desc}"
        system += (
            "\n\nWhen the user asks a data question, use execute_python "
            "to compute the answer from the actual data. "
            "Show your reasoning briefly, then the result."
        )

    # build message list
    messages = _history_to_messages(history)
    messages.append({"role": "user", "content": user_message})

    reply = _run_agentic_loop(
        system=system,
        messages=messages,
        tools=CHAT_TOOLS,
        state=state,
        max_iterations=8,
        result_key="chat",
        extra_tool_kwargs={"dataframes": dfs},
    )

    # reply is a string for chat
    if isinstance(reply, dict):
        reply_text = reply.get("text", str(reply))
    else:
        reply_text = str(reply)

    updated_history = history + [
        {"role": "user",      "content": user_message},
        {"role": "assistant", "content": reply_text},
    ]

    return reply_text, updated_history


# ─────────────────────────────────────────────────────────────
#  Core agentic loop — used by all three entry points
# ─────────────────────────────────────────────────────────────

def _run_agentic_loop(
    system: str,
    messages: list[dict],
    tools: list,
    state: dict,
    max_iterations: int = 6,
    result_key: str = "result",
    extra_tool_kwargs: dict | None = None,
) -> dict | str:
    """
    Run the agent until it produces a final answer or hits max_iterations.

    Handles:
      - Text responses → returned as-is
      - Tool calls → executed, result fed back, loop continues
      - JSON in text → parsed and returned as dict
      - Errors → returned as {"error": message}

    The loop terminates when:
      - stop_reason == "end_turn" (agent finished)
      - No tool calls in response
      - max_iterations reached
    """
    extra = extra_tool_kwargs or {}
    current_messages = list(messages)

    for iteration in range(max_iterations):
        try:
            response = _client().messages.create(
                model="claude-opus-4-6",
                max_tokens=2000,
                system=system,
                tools=tools,
                messages=current_messages,
            )
        except Exception as e:
            return {"error": f"API call failed: {e}"}

        # collect text and tool calls from response
        reply_text = ""
        tool_calls = []

        for block in response.content:
            if hasattr(block, "text"):
                reply_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(block)

        # no tool calls — agent is done
        if not tool_calls or response.stop_reason == "end_turn":
            # try to parse JSON from reply text
            if reply_text.strip():
                parsed = _try_parse_json(reply_text)
                if parsed is not None:
                    return parsed
            return reply_text.strip()

        # execute tool calls and collect results
        tool_results = []
        for tool_call in tool_calls:

            # web_search is handled natively by Anthropic API
            # we just pass the result through
            if tool_call.name == "web_search":
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tool_call.id,
                    "content":     "Search completed.",
                })
                continue

            # custom tools — execute locally
            result_content = execute_tool(
                tool_name=tool_call.name,
                tool_input=tool_call.input,
                dataframes=extra.get("dataframes"),
                stations_df=extra.get("stations_df"),
            )

            # log tool call to session state for UI display
            if "agent_tool_log" in state:
                state["agent_tool_log"].append({
                    "tool":    tool_call.name,
                    "input":   tool_call.input,
                    "result":  result_content[:500],  # truncate for display
                })

            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": tool_call.id,
                "content":     result_content,
            })

        # append assistant turn + tool results and continue loop
        current_messages.append({
            "role":    "assistant",
            "content": response.content,
        })
        current_messages.append({
            "role":    "user",
            "content": tool_results,
        })

    return {"error": f"Agent did not complete within {max_iterations} iterations."}


# ─────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────

def _try_parse_json(text: str) -> dict | None:
    """
    Try to extract and parse a JSON object from agent text output.
    Handles code fences and leading/trailing prose.
    """
    import re

    # strip markdown code fences
    text = re.sub(r"```(?:json)?", "", text).strip()

    # try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # try finding first { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def _history_to_messages(history: list[dict]) -> list[dict]:
    """
    Convert chat history to Claude API message format.
    Keeps last 10 turns to stay within context limits.
    """
    recent = history[-20:] if len(history) > 20 else history
    return [
        {"role": turn["role"], "content": turn["content"]}
        for turn in recent
        if turn.get("content")
    ]
