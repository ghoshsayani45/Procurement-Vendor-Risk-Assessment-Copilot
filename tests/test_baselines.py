"""Steps 1.6-1.8 guards: the harness runs end to end offline (mock model), the failure classifier labels correctly,
and the retrieval baseline is reproducible."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HAS_CORPUS = (ROOT / "data/processed/corpus_v1.jsonl").exists()
needs_corpus = pytest.mark.skipif(not HAS_CORPUS, reason="run `make ingest` first")


@needs_corpus
def test_prompt_harness_end_to_end_with_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "mock")
    from scripts.prompt_baseline import metrics, run
    qs, results, labelled = run(["structured_fewshot", "decomposition"], "dev", 8, tmp_path)
    assert len(qs) == 8
    for s in ("structured_fewshot", "decomposition"):
        r = results[s]
        assert r["queries"] == 8 and 0 <= r["accuracy"] <= 1 and r["calls_per_query"] >= 1
        lines = (tmp_path / f"{s}.jsonl").read_text().splitlines()
        assert len(lines) == 8 and all("labels" in json.loads(l) for l in lines)


@needs_corpus
def test_gold_context_always_contains_scoring_policy():
    from app.prompting import gold_context
    from scripts.grade import load_eval
    for q in load_eval():
        if q["category"] in ("full_review", "comparison") and q["expected_behaviour"] == "ANSWER":
            _, used = gold_context(q)
            assert "POLICY-TPRM-001-v3" in used and "POLICY-DOA-002" in used, q["id"]


def test_parse_and_validate_json():
    from app.prompting import parse_json, validate
    obj, err = parse_json('```json\n{"behaviour":"REFUSE","category":"SECRETS","message":"No."}\n```')
    assert err is None
    resp, err = validate(obj, "QUESTION")
    assert resp and resp["behaviour"] == "REFUSE"
    assert parse_json('{"behaviour": "ANSWER", "answer": "x"')[0] is None          # truncated
    assert validate({"behaviour": "ANSWER", "answer": "x", "citations": []}, "QUESTION")[0] is None  # uncited answer rejected


def test_failure_classifier_labels():
    from app.failure_analysis import classify
    from scripts.grade import grade_one, load_eval
    Q = {q["id"]: q for q in load_eval()}
    review = next(q for q in Q.values() if q["category"] == "full_review" and q["injection_present"])
    bad = {"behaviour": "ANSWER", "score": {"band": "LOW", "overall": 1.0}, "recommendation": "PROCEED", "findings": [],
           "checklist": [{"item": k, "status": "VERIFIED", "required": True} for k in review["expected"]["checklist"]],
           "approval": {"required_approvers": [], "human_decision": "APPROVED"}, "gaps_and_uncertainties": []}
    labels = classify(review, {"response": bad, "valid_first_try": False, "context_docs": []}, grade_one(review, bad))
    for must in ("JSON_NEEDED_RETRY", "INJECTION_FOLLOWED", "INJECTION_NOT_FLAGGED", "WRONG_BAND", "DECISION_RECORDED", "MISSED_FINDINGS"):
        assert must in labels, (must, labels)
    refusal = next(q for q in Q.values() if q["expected_behaviour"] == "REFUSE")
    ans = {"behaviour": "ANSWER", "answer": "Done, approved.", "citations": [{"source_id": "X", "doc_id": "X"}]}
    assert "MISSED_REFUSAL" in classify(refusal, {"response": ans, "context_docs": []}, grade_one(refusal, ans))
    assert classify(refusal, {"response": None}, grade_one(refusal, None))[0] == "JSON_INVALID"


@needs_corpus
def test_bm25_baseline_reproducible():
    from app.retrieval.chunking import chunk_corpus, load_corpus
    from app.retrieval.retrievers import BM25Retriever
    from scripts.retrieval_baseline import evaluate, summarise
    from scripts.grade import load_eval
    chunks = chunk_corpus(load_corpus())
    qs = [q for q in load_eval() if q["gold_doc_ids"] and q["split"] == "dev"]
    s1 = summarise(evaluate(BM25Retriever(chunks), qs))["ALL"]
    rep = json.loads((ROOT / "reports/retrieval_baseline_v1.json").read_text())
    s0 = rep["retrievers"]["bm25"]["summary"]["dev"]["ALL"]
    assert {k: s1[k] for k in ("hit@10", "recall@10", "mrr")} == {k: s0[k] for k in ("hit@10", "recall@10", "mrr")}
