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
