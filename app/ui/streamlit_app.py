"""Reviewer UI (Streamlit). Run: streamlit run app/ui/streamlit_app.py
New request -> the copilot's report, answer, comparison, clarification or refusal; the approval panel is the ONLY place a human decision
is recorded, by a named approver whose role the report lists as required. Reviews tab -> history with the audit trail."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # make `app` importable when run by streamlit
from app.ui.client import ApiError, call, mode  # noqa: E402

BAND_ICON = dict(LOW="🟢", MEDIUM="🟡", HIGH="🟠", CRITICAL="🔴")
ROLES = ["procurement_analyst", "risk_reviewer", "category_manager", "legal_finance_reviewer"]

st.set_page_config(page_title="Vendor Risk Copilot", page_icon="🛡️", layout="wide")


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Reviewer")
    user = st.text_input("Your full name", key="user", placeholder="e.g. Asha Rao")
    role = st.selectbox("Your role", ROLES, key="role")
    st.divider()
    try:
        h = call("GET", "/health")
        st.caption(f"API: {mode()} · DB: {h['database']} · LLM: {h['llm']} · {h['vendors']} vendors")
    except Exception as e:  # noqa: BLE001
        st.error(f"API not reachable: {e}")
    st.caption("Decision support only. The copilot never approves; a named approver decides in the approval panel.")


@st.cache_data(ttl=300)
def vendors():
    return call("GET", "/v1/vendors")


def cites(cs):
    return ", ".join(dict.fromkeys(c.get("doc_id") or c.get("source_id") for c in cs or [] if c))


# ------------------------------------------------------------------ renderers
def render_report(r: dict):
    s = r["score"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tier", r["tier"])
    c2.metric("Overall score", f"{s['overall']:.1f} / 100")
    c3.metric("Band", f"{BAND_ICON.get(s['band'], '')} {s['band']}", None if s["raw_band"] == s["band"] else f"raised from {s['raw_band']}", delta_color="off")
    c4.metric("Recommendation", r["recommendation"].replace("_", " ").title())
    st.caption("Recommendation is advisory. Scores come from the deterministic rubric engine (rubric v" + s["rubric_version"] + ").")
    if r["behaviour"] == "PARTIAL":
        st.warning(f"Partial result: {r.get('partial_reason')}")
    st.write(r["summary"])
    if s["knockouts"]:
        st.error("Knockouts: " + ", ".join(s["knockouts"]))
    st.subheader("Evidence checklist")
    st.dataframe([dict(item=c["item"], required=c["required"], status=c["status"], evidence=", ".join(c["evidence_ids"]), reason=c["reason"])
                  for c in r["checklist"]], width='stretch', hide_index=True)
    st.subheader(f"Findings ({len(r['findings'])})")
    if r["findings"]:
        st.dataframe([dict(code=f["code"], dimension=f["dimension"], severity=f["severity"], statement=f["statement"],
                           legal=("yes" if f["needs_legal_review"] else ""), sources=cites(f["citations"])) for f in r["findings"]],
                     width='stretch', hide_index=True)
    with st.expander("Score by dimension"):
        st.dataframe([dict(dimension=d["dimension"], points=d["points"], weight=d["weight"], applicable=d["applicable"],
                           rules=", ".join(d["triggered_rules"])) for d in s["dimensions"]], width='stretch', hide_index=True)
    if r["conditions"]:
        st.subheader("Conditions")
        for c in r["conditions"]:
            st.markdown(f"- {c}")
    if r["gaps_and_uncertainties"]:
        st.subheader("Gaps, warnings and uncertainties")
        for g in r["gaps_and_uncertainties"]:
            (st.warning if ("injection" in g.lower() or g.startswith("Approval declined")) else st.info)(g)


def approval_panel(review_id: str, r: dict, decided: dict | None, where: str):
    st.subheader("Approval")
    req = r["approval"]["required_approvers"]
    st.write("Required approvers: " + ", ".join(req))
    if decided and decided.get("decision"):
        st.success(f"{decided['decision']} by {decided['decided_by']} ({decided['decided_role']}) on {decided['decided_at'][:16]}"
                   + (f": {decided['decision_comment']}" if decided.get("decision_comment") else ""))
        if decided["decision"] in ("APPROVED", "REJECTED"):
            return
    with st.form(f"decision-{where}-{review_id}"):
        name = st.text_input("Approver's full name", value=st.session_state.get("user", ""))
        arole = st.selectbox("Approving as", req)
        dec = st.radio("Decision", ["APPROVED", "REJECTED", "MORE_INFO"], horizontal=True)
        comment = st.text_area("Comment (conditions, reasons)")
        ok = st.form_submit_button("Record decision")
    if ok:
        try:
            call("POST", f"/v1/reviews/{review_id}/decision", user=name,
                 json=dict(decision=dec, decided_by=name, approver_role=arole, comment=comment))
            st.success("Decision recorded in the audit trail.")
            st.rerun()
        except ApiError as e:
            st.error(f"Not recorded: {e.detail}")


def render(review_id: str, resp: dict, stored: dict | None = None, where: str = "new"):
    b = resp.get("behaviour")
    if b == "REFUSE":
        st.error(f"Refused ({resp['category']}): {resp['message']}")
        if resp.get("route_to"):
            st.info(f"Route to: {resp['route_to']}")
    elif b == "CLARIFY":
        st.warning(resp["question"])
        for o in resp.get("options", []):
            st.markdown(f"- {o}")
    elif "score" in resp:
        render_report(resp)
        approval_panel(review_id, resp, stored, where)
    elif "rows" in resp:
        st.dataframe([dict(vendor=x["vendor_id"], tier=x["tier"], overall=x["overall"], band=f"{BAND_ICON.get(x['band'], '')} {x['band']}",
                           key_findings=", ".join(x["key_findings"])) for x in resp["rows"]], width='stretch', hide_index=True)
        for c in resp.get("caveats", []):
            (st.warning if "injection" in c.lower() else st.caption)(c)
    else:
        (st.warning if b == "PARTIAL" else st.write)(resp.get("answer", ""))
        st.caption("Sources: " + cites(resp.get("citations")))


# ------------------------------------------------------------------ pages
st.title("Procurement & Vendor Risk Assessment Copilot")
tab_new, tab_hist = st.tabs(["New request", "Reviews"])

with tab_new:
    vlist = vendors()
    label = {v["vendor_id"]: f"{v['vendor_id']} · {v['name']}" for v in vlist}
    kind = st.radio("Request", ["FULL_REVIEW", "COMPARISON", "QUESTION"], horizontal=True,
                    format_func=lambda k: dict(FULL_REVIEW="Full review", COMPARISON="Comparison", QUESTION="Question")[k])
    multi = kind == "COMPARISON"
    picked = st.multiselect("Vendors", list(label), format_func=label.get, max_selections=3 if multi else 1)
    rt = st.selectbox("Review type", ["(from vendor record)", "NEW_VENDOR", "RENEWAL"]) if kind == "FULL_REVIEW" else None
    q = st.text_area("Question or instruction", placeholder="e.g. What is the auto-renewal notice period?" if kind == "QUESTION" else "optional")
    as_of = st.date_input("Review date (as of)", value=date(2026, 11, 1))
    if st.button("Run copilot", type="primary"):
        if not user.strip():
            st.error("Enter your full name in the sidebar first.")
        else:
            body = dict(request_kind=kind, vendor_ids=picked, question=q or {"FULL_REVIEW": "Full risk assessment.", "COMPARISON": "Compare these vendors."}.get(kind, ""),
                        requester_role=role, as_of=as_of.isoformat())
            if rt and rt.startswith(("NEW", "REN")):
                body["review_type"] = rt
            with st.spinner("Running tools and checks..."):
                try:
                    st.session_state["last"] = call("POST", "/v1/requests", user=user, json=body)
                except ApiError as e:
                    st.error(f"Request failed: {e.detail}")
    last = st.session_state.get("last")
    if last:
        st.divider()
        st.caption(f"Review {last['review_id']} · {last['trace']['tool_calls']} tool calls · {last['trace']['latency_ms']} ms")
        render(last["review_id"], last["response"], call("GET", f"/v1/reviews/{last['review_id']}"))

with tab_hist:
    rows = call("GET", "/v1/reviews")
    if not rows:
        st.info("No requests yet.")
    else:
        st.dataframe([dict(created=r["created_at"][:16], kind=r["request_kind"], vendor=r["vendor_id"], outcome=r["behaviour"], status=r["status"],
                           requested_by=r["requested_by"], decision=r["decision"], decided_by=r["decided_by"], id=r["id"]) for r in rows],
                     width='stretch', hide_index=True)
        rid = st.selectbox("Open review", [r["id"] for r in rows], format_func=lambda i: next(f"{r['created_at'][:16]} · {r['request_kind']} · {r['vendor_id'] or '-'}" for r in rows if r["id"] == i))
        rec = call("GET", f"/v1/reviews/{rid}")
        render(rid, rec["response_json"], rec, where="history")
        with st.expander("Audit trail"):
            st.dataframe(call("GET", f"/v1/reviews/{rid}/audit"), width='stretch', hide_index=True)
