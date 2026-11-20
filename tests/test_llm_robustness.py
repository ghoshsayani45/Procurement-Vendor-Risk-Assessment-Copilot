"""The course model (Qwen3-8B) does not always reply in the requested JSON shape. Every shape seen or likely must give a
cited answer or a clean 'insufficient evidence', never a crash (regression: claims returned as plain strings, 2026-11-20)."""
import json

import pytest

from app import llm_client
from app.rag.chunking import RagChunk
from app.rag.generator import generate
from app.rag.index import Hit


def _hits():
    c1 = RagChunk(chunk_id="POLICY-DPS-004#r000", doc_id="POLICY-DPS-004", seq=0, title="Data Protection Standard",
                  text="[Data Protection Standard | POLICY-DPS-004]\nVendors must notify a personal data breach within 48 hours.")
    c2 = RagChunk(chunk_id="POLICY-DOA-002#r000", doc_id="POLICY-DOA-002", seq=0, title="Delegation of Authority",
                  text="[Delegation of Authority | POLICY-DOA-002]\nContracts up to INR 25 lakh are approved by the Category Manager.")
    return [Hit(c1, 1.0, "test"), Hit(c2, 0.9, "test")]


def _reply(monkeypatch, raw):
    monkeypatch.setattr(llm_client, "chat", lambda *a, **k: raw if isinstance(raw, str) else json.dumps(raw))
    monkeypatch.setattr(llm_client, "LAST_CALL", {}, raising=False)
    return generate("How fast must a vendor notify a breach?", _hits())


@pytest.mark.parametrize("raw", [
    {"claims": [{"text": "Vendors must notify within 48 hours.", "kind": "observation", "sources": ["S1"]}]},   # asked shape
    {"claims": ["Vendors must notify within 48 hours [S1]."]},                                                   # the crash
    ["Vendors must notify within 48 hours [S1]."],                                                               # bare list
    {"text": "Vendors must notify within 48 hours.", "sources": "S1"},                                           # one object
    {"claims": [{"claim": "Vendors must notify within 48 hours.", "source": "[S1]"}]},                           # other keys
    {"answer": "Vendors must notify within 48 hours [S1]."},                                                      # answer field
    '```json\n{"claims": ["Vendors must notify within 48 hours [S1]."]}\n```',                                   # fenced
])
def test_reply_shapes_give_a_cited_answer(monkeypatch, raw):
    ans = _reply(monkeypatch, raw)
    assert not ans.insufficient_evidence and "48 hours" in ans.answer
    assert [c["doc_id"] for c in ans.citations] == ["POLICY-DPS-004"]
    assert "[S1]." not in ans.claims[0].text                       # inline marker removed from the claim text


@pytest.mark.parametrize("raw", [
    {"claims": ["Vendors must notify within 48 hours."]},           # no citation -> rejected
    {"claims": [{"text": "Notify within 48 hours.", "sources": ["S9"]}]},   # cites a source that was not shown
    {"claims": [42, None]},
    "Sorry, I cannot answer that.",
    "[]",
])
def test_unusable_replies_become_insufficient_evidence(monkeypatch, raw):
    ans = _reply(monkeypatch, raw)
    assert ans.insufficient_evidence and not ans.claims


def test_model_failure_never_crashes_a_request(monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", "off")
    import app.rag.generator as gen
    monkeypatch.setattr(gen, "generate", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("endpoint down")))
    from app.agents.copilot import run
    out = run(dict(request_kind="QUESTION", vendor_ids=[], question="What is the maximum time a vendor can take to notify us of a breach?",
                   requester_role="risk_reviewer", as_of="2026-11-01"), llm="endpoint")
    r = out["response"]
    assert r["behaviour"] in ("ANSWER", "PARTIAL") and r["citations"]
    assert "could not be used (ConnectionError)" in r["answer"]
    assert "LLM_ANSWER_FAILED" in out["trace"]["events"]


@pytest.mark.parametrize("q", [
    "What is the maximum time a vendor can take to notify us of a personal data breach?",
    "Who has to approve an INR 3 crore renewal rated MEDIUM that has a contract finding?",
])
def test_policy_questions_never_retrieve_vendor_documents(q):
    """Regression (live run 2026-11-20): a vendor contract's 96-hour clause answered a question about the 48-hour policy."""
    from app.tools import documents
    from app.tools.tools import document_search
    r = document_search(q)
    assert r["scope"] == "policies_and_regulations" and r["hits"]
    assert all(not (documents.get(h["doc_id"]) or {}).get("vendor_id") for h in r["hits"])


def test_vendor_questions_keep_the_vendor_documents():
    from app.tools.tools import document_search
    r = document_search("auto-renewal notice period", vendor_id="V009")
    assert r["scope"] == "vendor" and any(h["doc_id"].startswith("DOC-V009-") for h in r["hits"])


def test_citation_date_ignores_version_labels():
    """CUAD records carry 'v1 (2021)' in their date field; a citation must still validate (regression 2026-11-20)."""
    from app.tools.tools import _date_or_none
    assert _date_or_none("v1 (2021)") is None and _date_or_none("2026-01-31") == "2026-01-31" and _date_or_none(None) is None


PARTIAL = "data/processed/corpus_v1_partial.jsonl"


@pytest.mark.skipif(not __import__("pathlib").Path(PARTIAL).exists(), reason="needs the partial corpus built from data/raw")
def test_vendor_questions_with_the_full_library(monkeypatch):
    """With 400+ public reference documents loaded, a vendor question must still retrieve that vendor's own contract first,
    and a policy question must still find the policy (regression 2026-11-20)."""
    monkeypatch.setenv("CORPUS_PATH", PARTIAL)
    from app.tools import documents, tools
    documents.store.cache_clear()
    tools._pipeline.cache_clear()
    try:
        r = tools.document_search("auto-renewal notice period", vendor_id="V009")
        assert r["hits"][0]["doc_id"].startswith("DOC-V009-")
        assert not any(h["doc_id"].startswith(("CON-001-", "POL-0", "GUI-")) for h in r["hits"])
        p = tools.document_search("What is the maximum time a vendor can take to notify us of a personal data breach?")
        assert p["hits"][0]["doc_id"] == "POLICY-DPS-004"
    finally:
        documents.store.cache_clear()
        tools._pipeline.cache_clear()


@pytest.mark.parametrize("q,expected", [
    ("Who has to approve an INR 3 crore renewal rated MEDIUM that has a contract finding?",
     ["Head of Procurement", "Finance Controller", "Legal Counsel"]),
    ("Who approves a Rs 20 lakh purchase rated LOW?", ["Category Manager"]),
    ("Who must approve an INR 8 crore contract rated HIGH with a data protection finding?",
     ["Chief Financial Officer", "Procurement Committee", "Third-Party Risk Committee", "Data Protection Officer"]),
    ("Which approvers are needed for ₹1.5 crore with a conflict of interest?",
     ["Head of Procurement", "Finance Controller", "Ethics & Compliance Officer"]),
])
def test_policy_approver_questions_are_computed_from_the_rubric(q, expected):
    """Regression (live runs 2026-11-20): the 8B model dropped Legal Counsel in 2 of 3 runs; approvers now come from the rubric."""
    from app.agents.writer import policy_approvers_answer
    parts, docs = policy_approvers_answer(q)
    assert parts[0] == f"Required approvers: {', '.join(expected)}." and docs == ["POLICY-DOA-002"]


@pytest.mark.parametrize("q", ["Who approves vendors?", "What does the delegation of authority cover?", "Approve Kestrion."])
def test_approver_calculator_needs_an_amount_and_a_who_question(q):
    from app.agents.writer import policy_approvers_answer
    assert policy_approvers_answer(q) is None


def test_approver_question_end_to_end_without_the_model(monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", "off")
    from app.agents.copilot import run
    r = run(dict(request_kind="QUESTION", vendor_ids=[], question="Who has to approve an INR 3 crore renewal rated MEDIUM that has a contract finding?",
                 requester_role="risk_reviewer", as_of="2026-11-01"), llm="endpoint")["response"]
    assert "Legal Counsel" in r["answer"] and any(c.get("doc_id") == "POLICY-DOA-002" for c in r["citations"])


def test_citation_dates_with_a_time_are_cleaned():
    """Regression (live run 2026-11-20, EVAL-059): a source dated '2026-01-31T00:00:00' failed the citation schema."""
    from app.agents.writer import _clean_dates
    from app.schemas import Citation
    c = _clean_dates([dict(source_id="POL-001-S016", doc_id="POL-001-S016", document_date="2026-01-31T00:00:00"),
                      dict(source_id="CON-001-1", doc_id="CON-001-1", document_date="v1 (2021)")])
    assert [x["document_date"] for x in c] == ["2026-01-31", None]
    for x in c:
        Citation.model_validate(x)
