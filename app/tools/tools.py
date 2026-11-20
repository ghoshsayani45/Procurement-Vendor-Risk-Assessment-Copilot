"""The five copilot tools (Week 3). Each takes plain JSON arguments and returns a ToolResult (app.schemas).

vendor_search             resolve a vendor name or id; profile + document inventory (no answer fields)
document_search           hybrid / BM25 passage search with a vendor filter (app.rag); optional safety scan of the vendor's documents
compliance_checker        deterministic rubric engine: tier, checklist, findings, score, band, knockouts, recommendation, approvers
financial_risk_calculator financial statements by year, ratios against policy thresholds, financial findings and dimension points
vendor_compare            same-group check, engine assessment per vendor, ranking (band first, then score)

Scores, bands, dates and thresholds are computed here, in code; the LLM never computes them (decision D2).
"""
from __future__ import annotations

import re
import time
from datetime import date
from functools import lru_cache

from app.schemas import ReviewType, ToolResult
from app.scoring.engine import BAND_ORDER, assess, effective_contract, load_rubric
from app.tools import documents, register, safety

POLICY_DOC = "POLICY-TPRM-001-v3"
_STOP = {"pvt", "ltd", "llc", "inc", "pte", "plc", "limited", "the", "and", "services", "systems", "solutions", "cloud", "technologies"}


def _iso(d) -> str | None:
    return d.isoformat() if isinstance(d, date) else d


def cite(ref: str, vmap: dict[str, str]) -> dict:
    """Engine reference (evidence id, amendment id, PERF-Vxxx, policy id) -> Citation dict pointing at a corpus document."""
    doc_id = vmap.get(ref, ref)
    d = documents.get(doc_id)
    if d is None:
        return dict(source_id=f"tool:{ref}", doc_id=None, title=None, document_date=None, snippet=None)
    return dict(source_id=doc_id, doc_id=doc_id, title=(d.get("title") or "")[:200] or None, document_date=_iso(d.get("document_date")), snippet=None)


# ------------------------------------------------------------------ vendor_search
def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in _STOP and len(t) > 2}


def resolve(query: str) -> list[dict]:
    """Vendors matching an id ('V009') or name tokens ('Kestrion', 'Kestrion Customer Cloud'). Exact id wins; then the first
    distinctive name token; ranked by token overlap."""
    q = query.strip()
    rows = register.directory()
    ids = {r["id"] for r in rows}
    found_ids = [i for i in re.findall(r"\bV\d{3}\b", q.upper()) if i in ids]
    if found_ids:
        return [r for r in rows if r["id"] in found_ids]
    qt = _tokens(q)
    scored = []
    for r in rows:
        nt = _tokens(r["name"])
        first = re.findall(r"[a-z0-9]+", r["name"].lower())[0]
        if first in qt or re.search(rf"\b{re.escape(first)}", q.lower()):
            scored.append((10 + len(qt & nt), r))
        elif len(qt & nt) >= 2:
            scored.append((len(qt & nt), r))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored]


def vendor_search(query: str = "", vendor_id: str | None = None, **_) -> dict:
    matches = [r for r in register.directory() if r["id"] == vendor_id] if vendor_id else resolve(query)
    out = dict(query=query or vendor_id, matches=[dict(vendor_id=r["id"], name=r["name"], category=r["category"], status=r["status"],
                                                       comparison_group=r["comparison_group"]) for r in matches[:5]])
    if len(matches) == 1:
        f = register.facts(matches[0]["id"])
        out["profile"] = dict(vendor_id=f.vendor_id, legal_name=f.legal_name, category=f.category, comparison_group=f.comparison_group,
                              review_type=f.review_type.value, data_access=f.data_access.value, business_critical=f.business_critical,
                              annual_value_inr=f.annual_value_inr, business_owner=f.business_owner)
        out["documents"] = [dict(doc_id=d["doc_id"], title=d.get("title"), doc_type=d.get("doc_type"), document_date=_iso(d.get("document_date")),
                                 not_evidence=d["not_evidence"]) for d in sorted(documents.vendor_docs(f.vendor_id), key=lambda d: d["doc_id"])]
    return out


# ------------------------------------------------------------------ document_search
@lru_cache(maxsize=1)
def _pipeline():
    """Saved hybrid index (Week 2) if present; otherwise an in-memory BM25 index over the document store."""
    from app.rag.config import settings
    from app.rag.index import HybridIndex
    from app.rag.pipeline import RagPipeline
    cfg = settings()
    try:
        idx, mode = HybridIndex.load(cfg.chunking, cfg=cfg), "hybrid+rerank"
    except Exception:
        docs = [dict(d, text=d["text"]) for d in documents.store().values()]
        idx, mode = HybridIndex.build(cfg.chunking, docs=docs, cfg=cfg, dense=False, progress=False), "bm25"
    if mode == "bm25":
        cfg.reranker = "none"
    return RagPipeline(idx, cfg), mode


POLICY_SCOPE = "__policies_and_regulations__"   # a vendor id no document has: the vendor filter then keeps only non-vendor documents


def document_search(query: str, vendor_id: str | None = None, k: int = 6, scan_vendor_documents: bool = False, **_) -> dict:
    """With a vendor: that vendor's documents plus policies and regulations. Without one (a policy or regulation question):
    policies and regulations only, so another vendor's contract clause can never answer a question about our policy
    (live run 2026-11-20, EVAL-048: '96 hours' taken from a vendor contract instead of the 48-hour policy)."""
    pipe, mode = _pipeline()
    ret = pipe.retrieve(query, vendor_ids=[vendor_id] if vendor_id else [POLICY_SCOPE], mode=mode, k=k)
    hits = [dict(chunk_id=h.chunk.chunk_id, doc_id=h.chunk.doc_id, title=h.chunk.title, doc_type=h.chunk.doc_type,
                 document_date=_iso(h.chunk.document_date), status=h.chunk.status, score=round(h.score, 4),
                 text=safety.mask_pii(h.chunk.parent_text or h.chunk.text),
                 injection=bool(safety.INJECTION_RE.search(h.chunk.parent_text or h.chunk.text)),
                 not_evidence=bool((documents.get(h.chunk.doc_id) or {}).get("not_evidence"))) for h in ret.final]
    out = dict(query=query, mode=mode, store=documents.source(), vendor_ids=[v for v in ret.vendor_ids if v != POLICY_SCOPE],
               scope="vendor" if vendor_id else "policies_and_regulations", hits=hits, note=ret.note)
    if scan_vendor_documents and vendor_id:
        flags = [safety.scan(d) for d in documents.vendor_docs(vendor_id)]
        out["scan"] = [f for f in flags if f["injection"] or f["not_evidence"] or f["pii"]]
    return out


# ------------------------------------------------------------------ compliance_checker
def _facts_for(vendor_id: str, review_type: str | None):
    f = register.facts(vendor_id)
    if review_type and review_type != f.review_type.value:
        f = f.model_copy(update={"review_type": ReviewType(review_type)})
    return f


def compliance_checker(vendor_id: str, as_of: str = "2026-11-01", review_type: str | None = None, **_) -> dict:
    f = _facts_for(vendor_id, review_type)
    a = assess(f, load_rubric(), date.fromisoformat(as_of))
    vmap = register.evidence_doc_map(f)
    for fd in a["findings"]:
        refs = fd["evidence_refs"] or ([f.contract.doc_id] if fd["dimension"] in ("contract_terms", "data_protection") and f.contract.doc_id else [])
        fd["citations"] = [cite(r, vmap) for r in refs] + [dict(source_id="tool:compliance_checker", doc_id=None, title=None, document_date=None, snippet=None)]
    for c in a["checklist"]:
        c["doc_ids"] = [vmap.get(e, e) for e in c["evidence_ids"]]
    if f.caiq and f.caiq.completed_date:
        caiq_doc = f"DOC-{vendor_id}-CAIQ-1"
        for c in a["checklist"]:
            if c["item"] == "CAIQ" and documents.get(caiq_doc):
                c["doc_ids"] = [caiq_doc]
    eff = effective_contract(f.contract, date.fromisoformat(as_of))
    a["contract"] = dict(doc_id=f.contract.doc_id, effective_amendments=[x.doc_id for x in f.contract.amendments if x.effective_date <= date.fromisoformat(as_of)],
                         pending_amendments=[x.doc_id for x in f.contract.amendments if x.effective_date > date.fromisoformat(as_of)],
                         terms=eff.model_dump(mode="json", exclude={"amendments"}))
    a["performance"] = f.performance.model_dump(mode="json") if f.performance else None
    a["performance_doc"] = f"DOC-{vendor_id}-PERF-1" if documents.get(f"DOC-{vendor_id}-PERF-1") else None
    a["annual_value_inr"] = f.annual_value_inr
    a["review_type"] = f.review_type.value
    a["superseded_evidence"] = [dict(evidence_id=e.evidence_id, doc_id=e.doc_id, superseded_by=e.superseded_by) for e in f.evidence if e.superseded_by]
    a["evidence"] = [dict(e.model_dump(mode="json"), current=not e.superseded_by) for e in f.evidence]
    a["caiq"] = f.caiq.model_dump(mode="json") if f.caiq else None
    a["legal_name"] = f.legal_name
    a["policy_doc"] = POLICY_DOC
    return a


# ------------------------------------------------------------------ financial_risk_calculator
def financial_risk_calculator(vendor_id: str, as_of: str = "2026-11-01", **_) -> dict:
    f = register.facts(vendor_id)
    a = assess(f, load_rubric(), date.fromisoformat(as_of))
    fin = [x for x in a["findings"] if x["dimension"] == "financial_health"]
    dim = next(d for d in a["dimensions"] if d["dimension"] == "financial_health")
    years = [fy.model_dump(mode="json") for fy in sorted(f.financials, key=lambda x: x.fiscal_year)]
    th = load_rubric()["points"]["financial_health"]
    return dict(vendor_id=vendor_id, years=years, latest=years[-1] if years else None, dimension_points=dim["points"],
                weight=dim["weight"], findings=[dict(code=x["code"], statement=x["statement"], points=x["points"], doc_ids=x["evidence_refs"]) for x in fin],
                thresholds=dict(current_ratio=[1.0, 1.2], debt_to_equity=[2.0, 1.5], operating_margin_pct=0, revenue_growth_pct=-10),
                points_table=th, policy_doc=POLICY_DOC)


# ------------------------------------------------------------------ vendor_compare
def vendor_compare(vendor_ids: list[str], as_of: str = "2026-11-01", **_) -> dict:
    if not 2 <= len(vendor_ids) <= 3:
        raise ValueError("comparison needs 2-3 vendors")
    groups = {v: register.facts(v).comparison_group for v in vendor_ids}
    if len(set(groups.values())) > 1:
        return dict(comparable=False, groups=groups, rows=[], reason="vendors are in different comparison groups")
    rows = []
    for v in vendor_ids:
        a = compliance_checker(v, as_of)
        rows.append(dict(vendor_id=v, legal_name=register.facts(v).legal_name, tier=a["tier"], overall=a["overall"], band=a["band"],
                         raw_band=a["raw_band"], knockouts=a["knockouts"], recommendation=a["recommendation"],
                         dimension_points={d["dimension"]: d["points"] for d in a["dimensions"] if d["applicable"]},
                         key_findings=[x["code"] for x in sorted(a["findings"], key=lambda x: -x["points"])][:5],
                         citations=[c for x in a["findings"] for c in x["citations"] if c.get("doc_id")][:6]))
    ranking = [r["vendor_id"] for r in sorted(rows, key=lambda r: (BAND_ORDER.index(r["band"]), r["overall"]))]
    return dict(comparable=True, groups=groups, rows=rows, ranking=ranking)


TOOLS = dict(vendor_search=vendor_search, document_search=document_search, compliance_checker=compliance_checker,
             financial_risk_calculator=financial_risk_calculator, vendor_compare=vendor_compare)


def run_tool(name: str, arguments: dict) -> ToolResult:
    t0 = time.time()
    try:
        data = TOOLS[name](**arguments)
        return ToolResult(tool=name, ok=True, data=data, latency_ms=int((time.time() - t0) * 1000))
    except Exception as e:  # tool failures become PARTIAL answers, never crashes
        return ToolResult(tool=name, ok=False, error=f"{type(e).__name__}: {e}", latency_ms=int((time.time() - t0) * 1000))
