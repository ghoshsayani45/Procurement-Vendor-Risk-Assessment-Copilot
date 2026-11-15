"""Persistence for the copilot (Week 3-4): requests and responses, conversation turns, human decisions, append-only audit trail,
plus the reference tables (vendors, financial_metrics, documents metadata).

DATABASE_URL selects the database:
  postgresql://user:pass@host:5432/db   the docker compose `db` service (schema.sql creates the tables on first start)
  unset                                 SQLite file data/processed/copilot.sqlite (git-ignored), for laptops and tests
Tables mirror app/db/schema.sql. Audit events are append-only in both databases (Postgres rules / SQLite triggers).
The copilot never writes a human decision: only record_decision(), called by the API's approval endpoint with a named person.
"""
from __future__ import annotations

import csv
import hashlib
import os
import uuid
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import (JSON, BigInteger, Column, Date, DateTime, ForeignKey, Integer, MetaData, Numeric, String, Table, Text,
                        Uuid, create_engine, event, func, insert, select, text, update)
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE = ROOT / "data" / "processed" / "copilot.sqlite"
md = MetaData()

vendors = Table("vendors", md,
                Column("id", String, primary_key=True), Column("name", Text, nullable=False), Column("category", Text, nullable=False),
                Column("status", String, nullable=False), Column("owner", Text, nullable=False))
financial_metrics = Table("financial_metrics", md,
                          Column("vendor_id", String, ForeignKey("vendors.id"), primary_key=True), Column("period", String, primary_key=True),
                          Column("metric", String, primary_key=True), Column("value", Numeric, nullable=False), Column("source", Text, nullable=False))
documents = Table("documents", md,
                  Column("id", String, primary_key=True), Column("vendor_id", String, ForeignKey("vendors.id")), Column("source_id", String, nullable=False),
                  Column("slice", String, nullable=False), Column("type", String, nullable=False), Column("title", Text, nullable=False),
                  Column("version", String), Column("effective_date", Date), Column("access_class", String, nullable=False, default="internal"),
                  Column("licence", Text), Column("sha1", String, nullable=False))
reviews = Table("reviews", md,
                Column("id", Uuid, primary_key=True), Column("vendor_id", String, ForeignKey("vendors.id")), Column("review_type", String),
                Column("status", String, nullable=False, default="OPEN"), Column("as_of", Date, nullable=False),
                Column("score_json", JSON), Column("report_json", JSON), Column("created_at", DateTime(timezone=True), server_default=func.now()),
                Column("request_kind", String), Column("behaviour", String), Column("requested_by", Text), Column("requester_role", String),
                Column("request_json", JSON), Column("response_json", JSON), Column("trace_json", JSON),
                Column("decision", String), Column("decided_by", Text), Column("decided_role", Text), Column("decided_at", DateTime(timezone=True)),
                Column("decision_comment", Text))
conversation_turns = Table("conversation_turns", md,
                           Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
                           Column("review_id", Uuid, ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False),
                           Column("role", String, nullable=False), Column("content", JSON, nullable=False),
                           Column("created_at", DateTime(timezone=True), server_default=func.now()))
audit_events = Table("audit_events", md,
                     Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
                     Column("review_id", Uuid, ForeignKey("reviews.id")), Column("actor", Text, nullable=False), Column("action", String, nullable=False),
                     Column("decision", String), Column("detail", JSON), Column("created_at", DateTime(timezone=True), server_default=func.now()))

SQLITE_GUARDS = [
    "CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END",
]


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        DEFAULT_SQLITE.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{DEFAULT_SQLITE.as_posix()}"
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def engine(url: str | None = None) -> Engine:
    """One engine per database URL (DATABASE_URL is read on every call, so tests can point at a temporary file)."""
    return _engine(url or database_url())


@lru_cache(maxsize=8)
def _engine(url: str) -> Engine:
    eng = create_engine(url, future=True, pool_pre_ping=True)
    if eng.dialect.name == "sqlite":
        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    init_db(eng)
    return eng


def init_db(eng: Engine) -> None:
    md.create_all(eng, checkfirst=True)
    if eng.dialect.name == "sqlite":
        with eng.begin() as c:
            for s in SQLITE_GUARDS:
                c.execute(text(s))


# ------------------------------------------------------------------ reference data
def load_reference_data(eng: Engine | None = None, with_documents: bool = True) -> dict:
    """Idempotent: vendors (data/seed/vendors.csv), financial_metrics (data/seed/financial_metrics.csv), documents metadata
    (the copilot's document store). Answer fields never enter the database."""
    eng = eng or engine()
    n = dict(vendors=0, financial_metrics=0, documents=0)
    with eng.begin() as c:
        have_v = {r[0] for r in c.execute(select(vendors.c.id))}
        for r in csv.DictReader(open(ROOT / "data/seed/vendors.csv", encoding="utf-8")):
            if r["id"] not in have_v:
                c.execute(insert(vendors).values(id=r["id"], name=r["name"], category=r["category"], status=r["status"], owner=r["owner"]))
                n["vendors"] += 1
        have_f = {(a, b, m) for a, b, m in c.execute(select(financial_metrics.c.vendor_id, financial_metrics.c.period, financial_metrics.c.metric))}
        for r in csv.DictReader(open(ROOT / "data/seed/financial_metrics.csv", encoding="utf-8")):
            if (r["vendor_id"], r["period"], r["metric"]) not in have_f:
                c.execute(insert(financial_metrics).values(vendor_id=r["vendor_id"], period=r["period"], metric=r["metric"], value=float(r["value"]), source=r["source"]))
                n["financial_metrics"] += 1
        if with_documents:
            from app.tools import documents as store
            have_d = {r[0] for r in c.execute(select(documents.c.id))}
            vids = {r[0] for r in c.execute(select(vendors.c.id))}
            for d in store.store().values():
                if d["doc_id"] in have_d:
                    continue
                eff = d.get("effective_date") or d.get("document_date")
                c.execute(insert(documents).values(
                    id=d["doc_id"], vendor_id=d.get("vendor_id") if d.get("vendor_id") in vids else None,
                    source_id=d.get("source_id") or d.get("source") or "SYNTHETIC", slice=d.get("slice") or "unknown",
                    type=d.get("doc_type") or d.get("type") or "unknown", title=(d.get("title") or d["doc_id"])[:500], version=d.get("version"),
                    effective_date=_as_date(eff), access_class=d.get("access_class") or "internal", licence=d.get("licence"),
                    sha1=hashlib.sha1((d.get("text") or "").encode("utf-8")).hexdigest()))
                n["documents"] += 1
    return n


def _as_date(v):
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


# ------------------------------------------------------------------ requests, turns, audit
def _audit(c, review_id, actor: str, action: str, decision: str | None = None, detail: dict | None = None):
    c.execute(insert(audit_events).values(review_id=review_id, actor=actor[:200], action=action, decision=decision, detail=detail or {}))


def save_run(request: dict, out: dict, *, user: str, role: str, eng: Engine | None = None) -> str:
    """Store one copilot run: the request row, both conversation turns and the audit events (REQUEST, each TOOL_CALL, copilot events)."""
    eng = eng or engine()
    resp, trace = out["response"], out["trace"]
    rid = uuid.uuid4()
    vids = trace.get("vendor_ids") or request.get("vendor_ids") or []
    kind = request.get("request_kind")
    with eng.begin() as c:
        known = {r[0] for r in c.execute(select(vendors.c.id).where(vendors.c.id.in_(vids)))} if vids else set()
        vid = vids[0] if len(vids) == 1 and vids[0] in known else None
        is_report = "score" in resp
        c.execute(insert(reviews).values(
            id=rid, vendor_id=vid, review_type=resp.get("review_type") if is_report else request.get("review_type"),
            status="AWAITING_DECISION" if is_report else "CLOSED", as_of=_as_date(request.get("as_of")) or date(2026, 11, 1),
            score_json=resp.get("score") if is_report else None, report_json=resp if is_report else None,
            request_kind=kind, behaviour=resp.get("behaviour"), requested_by=user, requester_role=role,
            request_json=request, response_json=resp, trace_json=trace))
        c.execute(insert(conversation_turns).values(review_id=rid, role="user", content=request))
        c.execute(insert(conversation_turns).values(review_id=rid, role="assistant", content=resp))
        _audit(c, rid, user, "REQUEST", detail=dict(request_kind=kind, vendor_ids=vids, role=role))
        for t in trace.get("tools", []):
            _audit(c, rid, t["tool"], "TOOL_CALL", "OK" if t["ok"] else "FAILED", dict(ms=t["ms"], error=t["error"]))
        for ev in trace.get("events", []):
            _audit(c, rid, "copilot", ev, detail=dict(vendor_ids=vids))
        _audit(c, rid, "copilot", "RESPONSE", resp.get("behaviour"), dict(critic=trace.get("critic", []), latency_ms=trace.get("latency_ms")))
    return str(rid)


def _row(r) -> dict:
    d = dict(r._mapping)
    d["id"] = str(d["id"])
    for k in ("created_at", "decided_at", "as_of"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


def get_review(review_id: str, eng: Engine | None = None) -> dict | None:
    eng = eng or engine()
    try:
        rid = uuid.UUID(str(review_id))
    except ValueError:
        return None
    with eng.connect() as c:
        r = c.execute(select(reviews).where(reviews.c.id == rid)).first()
    return _row(r) if r else None


def list_reviews(vendor_id: str | None = None, limit: int = 50, eng: Engine | None = None) -> list[dict]:
    eng = eng or engine()
    q = select(reviews.c.id, reviews.c.vendor_id, reviews.c.request_kind, reviews.c.review_type, reviews.c.behaviour, reviews.c.status,
               reviews.c.requested_by, reviews.c.decision, reviews.c.decided_by, reviews.c.created_at).order_by(reviews.c.created_at.desc()).limit(limit)
    if vendor_id:
        q = q.where(reviews.c.vendor_id == vendor_id)
    with eng.connect() as c:
        return [_row(r) for r in c.execute(q)]


def record_decision(review_id: str, *, decision: str, decided_by: str, decided_role: str, comment: str = "", eng: Engine | None = None) -> dict:
    """The only write path for a human decision. Validation (named person, approver role, open review) is done by the caller."""
    eng = eng or engine()
    rid = uuid.UUID(str(review_id))
    now = datetime.now(timezone.utc)
    with eng.begin() as c:
        row = c.execute(select(reviews.c.response_json).where(reviews.c.id == rid)).first()
        resp = dict(row[0])
        resp["approval"] = dict(resp["approval"], human_decision=decision, decided_by=decided_by)
        c.execute(update(reviews).where(reviews.c.id == rid).values(
            decision=decision, decided_by=decided_by, decided_role=decided_role, decided_at=now, decision_comment=comment,
            status="DECIDED" if decision in ("APPROVED", "REJECTED") else "MORE_INFO_REQUESTED", response_json=resp, report_json=resp))
        _audit(c, rid, decided_by, "HUMAN_DECISION", decision, dict(role=decided_role, comment=comment))
    return get_review(str(rid), eng)


def audit_trail(review_id: str, eng: Engine | None = None) -> list[dict]:
    eng = eng or engine()
    rid = uuid.UUID(str(review_id))
    with eng.connect() as c:
        rows = c.execute(select(audit_events).where(audit_events.c.review_id == rid).order_by(audit_events.c.id)).all()
    out = []
    for r in rows:
        d = dict(r._mapping)
        d["review_id"] = str(d["review_id"])
        d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
        out.append(d)
    return out
