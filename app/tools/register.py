"""Evidence register: the copilot's system of record for structured vendor facts (decision D23).

In production this is the GRC / procurement database (certificates, contract terms, financial statements, performance records).
Here it is built from data/ground_truth/vendors.json with every ANSWER field removed, so no tool can read the grading key:
  planted_issues, traps, adversarial, notes  ->  dropped (these name the expected findings and test traps)
What remains are the facts a reviewer could read off the evidence documents themselves (dates, clauses, ratios, register entries).
Every fact keeps a pointer to the document that carries it, so tool output can be cited.
"""
from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path

from app.schemas import VendorFacts

ROOT = Path(__file__).resolve().parents[2]
VENDORS_JSON = ROOT / "data" / "ground_truth" / "vendors.json"
VENDORS_CSV = ROOT / "data" / "seed" / "vendors.csv"
ANSWER_FIELDS = ("planted_issues", "traps", "adversarial", "notes")


def _strip(rec: dict) -> dict:
    rec = {k: v for k, v in rec.items() if k not in ANSWER_FIELDS}
    rec.update({k: [] for k in ANSWER_FIELDS if k != "notes"})
    rec["notes"] = ""
    return rec


@lru_cache(maxsize=1)
def load_register() -> dict[str, VendorFacts]:
    raw = json.loads(VENDORS_JSON.read_text(encoding="utf-8"))
    raw = raw["vendors"] if isinstance(raw, dict) else raw
    return {r["vendor_id"]: VendorFacts.model_validate(_strip(r)) for r in raw}


@lru_cache(maxsize=1)
def directory() -> list[dict]:
    """Vendor directory rows: id, name, category, status, owner, comparison group."""
    reg = load_register()
    rows = list(csv.DictReader(open(VENDORS_CSV, encoding="utf-8")))
    for r in rows:
        f = reg.get(r["id"])
        r["comparison_group"] = f.comparison_group if f else ""
    return rows


def facts(vendor_id: str) -> VendorFacts:
    reg = load_register()
    if vendor_id not in reg:
        raise KeyError(f"unknown vendor_id {vendor_id}")
    return reg[vendor_id]


def evidence_doc_map(f: VendorFacts) -> dict[str, str]:
    """Map every internal reference the engine emits (evidence ids, amendment ids, PERF-Vxxx) to a corpus doc_id."""
    m: dict[str, str] = {}
    for e in f.evidence:
        if e.doc_id:
            m[e.evidence_id] = e.doc_id
    for a in f.contract.amendments:
        if a.doc_id:
            m[a.amendment_id] = a.doc_id
    m[f"PERF-{f.vendor_id}"] = f"DOC-{f.vendor_id}-PERF-1"
    return m
