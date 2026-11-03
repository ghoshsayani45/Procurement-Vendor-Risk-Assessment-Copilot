"""Step 1.4 guards: policies match the rubric, synthetic documents state their facts, corpus v1 is in range."""
import csv
import json
from pathlib import Path

import pytest

from app.scoring.engine import load_rubric

ROOT = Path(__file__).resolve().parents[1]
R = load_rubric()
POL = ROOT / "data/synthetic/policy"
MANIFEST = ROOT / "data/manifests/corpus_v1_manifest.csv"


def test_policies_quote_rubric_numbers():
    tprm = (POL / "POLICY-TPRM-001-v3.md").read_text()
    for b in R["bands"]:
        assert f"{b['band']} from {b['min']}" in tprm
    assert f"within **{R['limits']['breach_notice_max_hours']} hours**" in (POL / "POLICY-DPS-004.md").read_text()
    doa = (POL / "POLICY-DOA-002.md").read_text()
    assert "INR 25 lakh" in doa and "INR 5 crore" in doa


def test_superseded_policy_is_marked():
    assert 'status: "SUPERSEDED"' in (POL / "POLICY-TPRM-001-v2.md").read_text()


def test_synthetic_documents_validate():
    from scripts import generate_synthetic_docs as g
    g.MANIFEST.clear()
    g.main()  # deterministic; raises SystemExit if any planned fact is missing


def test_corpus_manifest_in_range():
    rows = list(csv.DictReader(open(MANIFEST)))
    assert 800 <= len(rows) <= 2000
    assert len({r["doc_id"] for r in rows}) == len(rows)
    slices = {r["slice"] for r in rows}
    assert {"procurement_policy", "contracts", "compliance_evidence", "performance_purchase_records", "guidance", "adversarial"} <= slices


def test_every_ground_truth_evidence_doc_is_in_corpus():
    ids = {r["doc_id"] for r in csv.DictReader(open(MANIFEST))}
    plan = {r["doc_id"] for r in csv.DictReader(open(ROOT / "data/ground_truth/document_plan.csv"))}
    assert plan <= ids


@pytest.mark.skipif(not (ROOT / "data/processed/corpus_v1.jsonl").exists(), reason="run `make ingest` first")
def test_processed_corpus_matches_manifest():
    man = {r["doc_id"]: r["sha1"] for r in csv.DictReader(open(MANIFEST))}
    got = {json.loads(l)["doc_id"]: json.loads(l)["sha1"] for l in open(ROOT / "data/processed/corpus_v1.jsonl")}
    assert got == man
