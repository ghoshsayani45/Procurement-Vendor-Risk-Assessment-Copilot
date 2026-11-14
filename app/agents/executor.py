"""Executor node: runs the plan's tool calls with one retry each and a hard cap of MAX_TOOL_CALLS (spec 4: 10-step cap).
A failed or skipped step does not crash the run; the writer turns it into a PARTIAL answer with partial_reason."""
from __future__ import annotations

from app.schemas import Plan
from app.tools.tools import run_tool

MAX_TOOL_CALLS = 10


def execute(plan: Plan, max_calls: int = MAX_TOOL_CALLS) -> dict:
    results, calls, failures, skipped = [], 0, [], []
    for s in plan.steps:
        if calls >= max_calls:
            skipped.append(s.step)
            continue
        r = run_tool(s.tool, s.arguments)
        calls += 1
        if not r.ok and calls < max_calls:
            r = run_tool(s.tool, s.arguments)
            calls += 1
        results.append(dict(step=s.step, tool=s.tool, arguments=s.arguments, ok=r.ok, data=r.data, error=r.error, latency_ms=r.latency_ms))
        if not r.ok:
            failures.append(f"{s.tool} failed after retry: {r.error}")
    if skipped:
        failures.append(f"step cap of {max_calls} tool calls reached; steps {skipped} not run")
    return dict(results=results, calls=calls, failures=failures)


def first(execution: dict, tool: str) -> dict | None:
    return next((r["data"] for r in execution["results"] if r["tool"] == tool and r["ok"]), None)


def all_ok(execution: dict, tool: str) -> list[dict]:
    return [r["data"] for r in execution["results"] if r["tool"] == tool and r["ok"]]
