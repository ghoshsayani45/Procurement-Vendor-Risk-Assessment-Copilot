"""Week 1 guards: the rubric engine is deterministic and the frozen ground truth still matches it.

Run: python -m pytest -q   (from repo root)
If a rubric change breaks these tests, the change must be logged in docs/decisions.md and the
ground truth rebuilt with `python -m scripts.build_vendors` before eval_v1 is frozen.
"""
import json
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from app.schemas import Report, VendorFacts
from app.scoring.engine import assess, effective_contract, load_rubric

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "data" / "ground_truth"
R = load_rubric()
VENDORS = [VendorFacts.model_validate(v) for v in json.loads((GT / "vendors.json").read_text())]
EXPECTED = {o["vendor_id"]: o for o in json.loads((GT / "expected_outcomes.json").read_text())}


def test_35_vendors_with_unique_ids():
    assert len(VENDORS) == 35
    assert len({v.vendor_id for v in VENDORS}) == 35


@pytest.mark.parametrize("v", VENDORS, ids=lambda v: v.vendor_id)
def test_engine_reproduces_frozen_outcome(v):
    assert assess(v, R) == EXPECTED[v.vendor_id]


@pytest.mark.parametrize("v", VENDORS, ids=lambda v: v.vendor_id)
def test_findings_equal_planted_issues(v):
    assert {f["code"] for f in EXPECTED[v.vendor_id]["findings"]} == set(v.planted_issues)


def test_deterministic_on_repeat():
    v = VENDORS[2]
    assert all(assess(v, R) == assess(v, R) for _ in range(20))


def test_band_mix_covers_all_bands():
    c = Counter(o["band"] for o in EXPECTED.values())
    assert set(c) == {"LOW", "MEDIUM", "HIGH", "CRITICAL"} and min(c.values()) >= 5


def test_comparison_groups():
    c = Counter(v.comparison_group for v in VENDORS)
    assert sum(n >= 2 for n in c.values()) == 16          # 16 comparable groups
    assert {g for g, n in c.items() if n == 1} == {"G11-COLLAB", "G15-ELEARN"}  # singletons: comparison must CLARIFY/refuse


def test_traps_resolve_correctly():
    by = {v.vendor_id: v for v in VENDORS}
    as_of = date.fromisoformat(R["review_as_of"])
    # superseded expired ISO must not produce a finding
    assert not any("ISO27001" in f["code"] for f in EXPECTED["V001"]["findings"])
    # past amendment raises cap 6 -> 12 months
    assert effective_contract(by["V004"].contract, as_of).vendor_liability_cap_months_fees == 12
    # future amendment is ignored
    assert effective_contract(by["V009"].contract, as_of).vendor_liability_cap_months_fees == by["V009"].contract.vendor_liability_cap_months_fees


def test_knockouts_floor_the_band():
    assert EXPECTED["V034"]["band"] == "CRITICAL" and EXPECTED["V034"]["raw_band"] == "MEDIUM"
    assert EXPECTED["V028"]["band"] == "HIGH" and EXPECTED["V028"]["raw_band"] == "LOW"


def test_copilot_never_records_a_decision():
    assert all(o["human_decision"] is None for o in EXPECTED.values())


def test_report_schema_rejects_uncited_finding():
    with pytest.raises(Exception):
        Report.model_validate({"behaviour": "ANSWER", "vendor_id": "V001", "review_type": "RENEWAL", "as_of": "2026-11-01",
                               "tier": 1, "summary": "x", "checklist": [], "recommendation": "PROCEED",
                               "approval": {"required_approvers": ["Category Manager"]},
                               "score": {"overall": 0, "band": "LOW", "raw_band": "LOW", "dimensions": []},
                               "findings": [{"code": "X", "dimension": "contract_terms", "severity": "LOW",
                                             "kind": "observation", "statement": "y", "citations": []}]})
