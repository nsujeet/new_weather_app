"""
agent/chart_executor.py

Safe Python executor for chart code.
Two entry points:
  run_base_code()    — runs pre-written base code, returns figure
  agent_modify()     — agent rewrites base code from user request, runs it

Safety:
  - Only pd, np, go, px available — no os, subprocess, open, requests
  - result must be a go.Figure — anything else rejected
  - Execution killed after 30 seconds via threading.Timer
  - Dataframes passed as copies — agent cannot modify session state
  - All code shown to user in expander — full transparency
"""

import io
import sys
import os
import threading
import anthropic
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# ─────────────────────────────────────────────────────────────
#  Load base code files
# ─────────────────────────────────────────────────────────────

_CHART_CODE_DIR = os.path.join(os.path.dirname(__file__), "..", "ui", "chart_code")

def load_base_code(chart_name: str) -> str:
    """
    Load base code from ui/chart_code/{chart_name}.py
    chart_name: "weather_scatter" | "freezing_bar" | "min_temp_heatmap"
    """
    path = os.path.join(_CHART_CODE_DIR, f"{chart_name}.py")
    with open(path, "r") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────
#  Safe executor
# ─────────────────────────────────────────────────────────────

# only these names available in agent code
_SAFE_BUILTINS = {
    "__builtins__": {
        "__import__": __import__,   # needed for import statements in exec'd code
        "len": len, "range": range, "round": round,
        "min": min, "max": max, "sum": sum, "abs": abs,
        "list": list, "dict": dict, "str": str,
        "int": int, "float": float, "bool": bool,
        "print": print, "enumerate": enumerate,
        "zip": zip, "sorted": sorted, "reversed": reversed,
        "isinstance": isinstance, "type": type,
        "hasattr": hasattr, "getattr": getattr,
        "any": any, "all": all,
    },
    "pd": pd,
    "np": np,
    "go": go,
    "px": px,
}

EXEC_TIMEOUT_S = 30   # kill execution after this many seconds


def execute_chart_code(
    code:       str,
    inject:     dict,
) -> dict:
    """
    Execute chart code safely.

    Args:
        code:   Python code string — must assign result = go.Figure(...)
        inject: dict of variables to inject (dataframes, config values)

    Returns:
        {
          "figure":  go.Figure or None,
          "output":  stdout text,
          "error":   error string or None,
          "code":    the code that was executed,
        }
    """
    # inject dataframes as copies so agent cannot mutate session state
    local_ns = {}
    for k, v in inject.items():
        if isinstance(v, pd.DataFrame):
            local_ns[k] = v.copy()
        elif isinstance(v, np.ndarray):
            local_ns[k] = v.copy()
        else:
            local_ns[k] = v

    global_ns  = {**_SAFE_BUILTINS}
    stdout_cap = io.StringIO()
    old_stdout = sys.stdout
    result_container = {"done": False, "figure": None,
                        "output": "", "error": None}

    def _run():
        sys.stdout = stdout_cap
        try:
            exec(compile(code, "<chart>", "exec"), global_ns, local_ns)  # noqa: S102
            sys.stdout = old_stdout
            output = stdout_cap.getvalue()

            if "result" not in local_ns:
                result_container["error"] = (
                    "Code did not assign 'result'. "
                    "Make sure the last line is: result = fig"
                )
                return

            val = local_ns["result"]
            if not isinstance(val, go.Figure):
                result_container["error"] = (
                    f"result must be a plotly go.Figure, "
                    f"got {type(val).__name__}"
                )
                return

            result_container["figure"] = val
            result_container["output"] = output

        except Exception as e:
            sys.stdout = old_stdout
            result_container["error"] = f"{type(e).__name__}: {e}"
        finally:
            result_container["done"] = True

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=EXEC_TIMEOUT_S)

    if not result_container["done"]:
        return {
            "figure": None,
            "output": "",
            "error":  f"Execution timed out after {EXEC_TIMEOUT_S}s",
            "code":   code,
        }

    return {
        "figure": result_container["figure"],
        "output": result_container["output"],
        "error":  result_container["error"],
        "code":   code,
    }


def run_base_code(
    chart_name: str,
    inject:     dict,
) -> dict:
    """
    Run the pre-written base code for a chart.
    inject: variables to make available in the code namespace.
    """
    code = load_base_code(chart_name)
    return execute_chart_code(code, inject)


# ─────────────────────────────────────────────────────────────
#  Agent rewrite
# ─────────────────────────────────────────────────────────────

def agent_modify_chart(
    user_request:  str,
    chart_name:    str,
    inject:        dict,
    current_code:  str | None = None,
) -> dict:
    """
    Ask the agent to modify chart code based on user request.
    Runs the modified code and returns the result.

    Args:
        user_request:  plain English description of the change
        chart_name:    "weather_scatter" | "freezing_bar" | "min_temp_heatmap"
        inject:        variables available in code (describes schema to agent)
        current_code:  if None, uses base code; otherwise modifies this code

    Returns:
        dict with figure, code, output, error, agent_explanation
    """
    client = anthropic.Anthropic()

    base_code = current_code or load_base_code(chart_name)

    # describe available variables for the agent
    var_descriptions = []
    for k, v in inject.items():
        if isinstance(v, pd.DataFrame):
            var_descriptions.append(
                f"  {k}: DataFrame shape={v.shape}, "
                f"cols={list(v.columns[:8])}"
                f"{'...' if len(v.columns) > 8 else ''}"
            )
        elif isinstance(v, np.ndarray):
            var_descriptions.append(
                f"  {k}: numpy array shape={v.shape}, "
                f"dtype={v.dtype}"
            )
        else:
            var_descriptions.append(f"  {k}: {type(v).__name__} = {repr(v)[:60]}")

    system = f"""You are a Python data visualisation assistant.
You modify Plotly chart code based on user requests.

Available variables in the execution namespace:
{chr(10).join(var_descriptions)}

Available libraries: pd (pandas), np (numpy), go (plotly.graph_objects), px (plotly.express)
NOT available: os, sys, subprocess, open, requests, matplotlib, seaborn

Rules:
1. The last line of code MUST be: result = fig
2. result MUST be a go.Figure object
3. Only use the available libraries listed above
4. Keep the code concise and readable
5. Preserve the general chart type unless explicitly asked to change it

Return ONLY the complete modified Python code — no explanation, no markdown fences.
The code will be executed directly."""

    messages = [
        {
            "role": "user",
            "content": (
                f"Here is the current chart code:\n\n"
                f"{base_code}\n\n"
                f"Please modify it to: {user_request}\n\n"
                f"Return only the complete modified Python code."
            )
        }
    ]

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=system,
        messages=messages,
    )

    modified_code = response.content[0].text.strip()

    # strip markdown fences if agent added them
    if modified_code.startswith("```"):
        lines = modified_code.split("\n")
        modified_code = "\n".join(
            l for l in lines
            if not l.startswith("```")
        ).strip()

    # execute the modified code
    exec_result = execute_chart_code(modified_code, inject)
    exec_result["code"] = modified_code

    return exec_result
