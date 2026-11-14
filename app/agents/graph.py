"""The copilot as a LangGraph state machine (falls back to a plain sequential runner if langgraph is not installed).

    route --refuse/clarify--> critic --> END
      +--run--> plan --> execute --> write --> critic --> END

Nodes are plain functions over a dict state, so each can be unit-tested on its own.
"""
from __future__ import annotations

import time
from typing import Any, TypedDict

from app.agents import critic, executor, planner, router, writer
from app.agents.audit import log_event


class State(TypedDict, total=False):
    request: dict
    options: dict
    route: Any
    plan: Any
    execution: dict
    draft: dict
    events: list
    response: dict
    critic_notes: list
    t0: float


def n_route(s: State) -> State:
    rt = router.route(s["request"])
    out: State = dict(route=rt, events=[])
    if rt.action == "refuse":
        out["draft"] = router.refusal_response(rt)
        out["events"] = [dict(event_type="REFUSAL", category=rt.refusal_category, vendor_ids=rt.vendor_ids, route_to=out["draft"]["route_to"])]
    elif rt.action == "clarify":
        out["draft"] = rt.clarification
        out["events"] = [dict(event_type="CLARIFICATION", question=rt.clarification["question"])]
    return out


def n_plan(s: State) -> State:
    rt = s["route"]
    return dict(plan=planner.make_plan(rt.template, rt.request, rt.vendor_ids))


def n_execute(s: State) -> State:
    return dict(execution=executor.execute(s["plan"], s["options"].get("max_tool_calls", executor.MAX_TOOL_CALLS)))


def n_write(s: State) -> State:
    rt, ex, o = s["route"], s["execution"], s["options"]
    if rt.template in ("new_vendor_full", "renewal_full"):
        w = writer.write_report(rt, ex, llm_summary=o.get("llm_summary", False))
    elif rt.template == "comparison":
        w = writer.write_comparison(rt, ex)
    else:
        w = writer.write_answer(rt, ex, llm=o.get("llm", "none"))
    return dict(draft=w["response"], events=s.get("events", []) + w["events"])


def n_critic(s: State) -> State:
    resp, notes = critic.review(s["draft"], s.get("execution"))
    for ev in s.get("events", []):
        log_event(**ev)
    return dict(response=resp, critic_notes=notes)


def _after_route(s: State) -> str:
    return "plan" if s["route"].action == "run" else "critic"


def build_graph():
    from langgraph.graph import END, StateGraph
    g = StateGraph(State)
    for name, fn in (("route", n_route), ("plan", n_plan), ("execute", n_execute), ("write", n_write), ("critic", n_critic)):
        g.add_node(name, fn)
    g.set_entry_point("route")
    g.add_conditional_edges("route", _after_route, {"plan": "plan", "critic": "critic"})
    g.add_edge("plan", "execute")
    g.add_edge("execute", "write")
    g.add_edge("write", "critic")
    g.add_edge("critic", END)
    return g.compile()


def _sequential(state: State) -> State:
    state.update(n_route(state))
    if state["route"].action == "run":
        for fn in (n_plan, n_execute, n_write):
            state.update(fn(state))
    state.update(n_critic(state))
    return state


_GRAPH = None


def invoke(request: dict, **options) -> State:
    global _GRAPH
    state: State = dict(request=request, options=options, t0=time.time())
    if options.get("engine", "langgraph") == "langgraph":
        try:
            if _GRAPH is None:
                _GRAPH = build_graph()
            return _GRAPH.invoke(state)
        except ImportError:
            pass
    return _sequential(state)
