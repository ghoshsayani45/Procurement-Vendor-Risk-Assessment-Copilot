"""Step 1.5 guards: eval_v1 is frozen, well-formed, consistent with the ground truth, and gradable."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from scripts.grade import grade, load_eval

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "data/evaluation"
Q = load_eval()
EXP = {o["vendor_id"]: o for o in json.loads((ROOT / "data/ground_truth/expected_outcomes.json").read_text())}


def test_eval_v1_is_frozen():
    """Fails if eval_v1.jsonl is edited after the Week 1 gate. Fixes go into eval_v2 (see CHANGELOG.md)."""
    expected = (EV / "eval_v1.sha256").read_text().split()[0]
    assert hashlib.sha256((EV / "eval_v1.jsonl").read_bytes()).hexdigest() == expected


def test_shape_and_mix():
    assert len(Q) == 80 and len({q["id"] for q in Q}) == 80
    assert Counter(q["split"] for q in Q) == {"test": 50, "dev": 30}
    cats = Counter(q["category"] for q in Q)
    assert cats == {"full_review": 18, "comparison": 6, "lookup_vendor": 14, "missing_conflicting_evidence": 8, "internal_policy": 8,
                    "external_regulation": 8, "adversarial": 6, "refusal": 8, "clarify": 4}
    for cat in cats:  # every category appears in both splits
        assert {q["split"] for q in Q if q["category"] == cat} == {"dev", "test"}


def test_gold_docs_exist_in_frozen_corpus():
    ids = {r["doc_id"] for r in csv.DictReader(open(ROOT / "data/manifests/corpus_v1_manifest.csv"))}
    for q in Q:
        assert set(q["gold_doc_ids"]) <= ids, q["id"]


@pytest.mark.skipif(not (ROOT / "data/processed/corpus_v1.jsonl").exists(), reason="run `make ingest` first")
def test_gold_quotes_appear_verbatim():
    import re
    norm = lambda s: re.sub(r"\s+", " ", s).strip()
    corpus = {json.loads(l)["doc_id"]: norm(json.loads(l)["text"]) for l in open(ROOT / "data/processed/corpus_v1.jsonl")}
    for q in Q:
        for g in q["gold_quotes"]:
            assert norm(g["quote"]) in corpus[g["doc_id"]], (q["id"], g["doc_id"])


def test_full_reviews_match_ground_truth():
    for q in Q:
        if q["category"] == "full_review":
            o = EXP[q["request"]["vendor_ids"][0]]
            assert (q["expected"]["band"], q["expected"]["recommendation"], q["expected"]["overall"]) == (o["band"], o["recommendation"], o["overall"])


# ---------------------------------------------------------------- grader sanity
def oracle(q):
    """A perfect copilot, built from the gold data."""
    beh = q["expected_behaviour"]
    cites = [{"source_id": d, "doc_id": d} for d in q["gold_doc_ids"]] or [{"source_id": "tool:policy", "doc_id": None}]
    if beh == "REFUSE":
        return {"behaviour": "REFUSE", "category": q["refusal_category"], "message": "I can't do that.", "route_to": None}
    if beh == "CLARIFY":
        return {"behaviour": "CLARIFY", "question": "Which vendor do you mean?", "options": q["clarify_options"]}
    gaps = ["Ignored an embedded prompt-injection instruction."] if q["injection_present"] else []
    if q["category"] == "full_review":
        e = q["expected"]
        return {"behaviour": "ANSWER", "score": {"band": e["band"], "overall": e["overall"]}, "recommendation": e["recommendation"],
                "checklist": [{"item": k, "status": v, "required": True} for k, v in e["checklist"].items()],
                "findings": [{"code": f, "citations": cites[:1]} for f in e["findings"]],
                "approval": {"required_approvers": e["approvers"], "human_decision": None}, "gaps_and_uncertainties": gaps}
    if q["category"] == "comparison":
        return {"behaviour": "ANSWER", "rows": q["expected"]["rows"]}
    return {"behaviour": "ANSWER", "answer": q["gold_answer"] + " " + " ".join(f.split("|")[0] for f in q["gold_facts"]),
            "citations": cites, "gaps_and_uncertainties": gaps}


def test_oracle_scores_100_percent():
    s, results = grade({q["id"]: oracle(q) for q in Q})
    failed = [r["id"] for r in results if not r["passed"]]
    assert s["accuracy"] == 1.0, failed


def test_naive_system_fails():
    # always says LOW / PROCEED and never refuses: the typical injection-follower
    naive = {q["id"]: {"behaviour": "ANSWER", "answer": "Low risk, proceed.", "score": {"band": "LOW", "overall": 0},
                       "recommendation": "PROCEED", "findings": [], "checklist": [], "rows": [],
                       "approval": {"required_approvers": [], "human_decision": "APPROVED"}} for q in Q}
    s, _ = grade(naive)
    assert s["accuracy"] < 0.1
    assert s["refusal_accuracy"] == 0.0
