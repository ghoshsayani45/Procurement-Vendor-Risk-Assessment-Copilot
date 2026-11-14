"""Public entry point.

    from app.agents.copilot import run
    out = run({"request_kind": "FULL_REVIEW", "review_type": "RENEWAL", "vendor_ids": ["V009"], "question": "...",
               "requester_role": "risk_reviewer", "as_of": "2026-11-01"}, llm="none")
    out["response"]   # Report | ComparisonResult | Answer | Clarification | Refusal, as a dict
    out["trace"]      # route, plan, tool calls, failures, critic notes, latency

llm = "none" (no model calls; extractive fallback for open questions), "mock" (offline stand-in), "endpoint" (course model).
llm_summary = True lets the model write the report summary (checked by the critic; falls back to the template summary).
"""
from __future__ import annotations

import time

from app.agents.graph import invoke


def run(request: dict, *, llm: str = "none", llm_summary: bool = False, engine: str = "langgraph", max_tool_calls: int = 10) -> dict:
    t0 = time.time()
    s = invoke(request, llm=llm, llm_summary=llm_summary, engine=engine, max_tool_calls=max_tool_calls)
    rt, ex = s.get("route"), s.get("execution") or {}
    trace = dict(action=rt.action if rt else None, template=rt.template if rt else None, vendor_ids=rt.vendor_ids if rt else [],
                 declined=rt.declined if rt else [], plan=[st.model_dump() for st in s["plan"].steps] if s.get("plan") else [],
                 tool_calls=ex.get("calls", 0), tools=[dict(tool=r["tool"], ok=r["ok"], ms=r["latency_ms"], error=r["error"]) for r in ex.get("results", [])],
                 failures=ex.get("failures", []), critic=s.get("critic_notes", []), events=[e["event_type"] for e in s.get("events", [])],
                 latency_ms=int((time.time() - t0) * 1000))
    return dict(response=s["response"], trace=trace)
