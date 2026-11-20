"""Copilot HTTP API (FastAPI). Run: uvicorn app.api.main:app --port 8000   (docs at /docs)

Endpoints
  GET  /health                               liveness + which database and LLM mode are in use
  GET  /v1/vendors                           vendor directory
  GET  /v1/vendors/{vendor_id}               profile + document inventory (no grading fields)
  POST /v1/requests                          run the copilot; stores request, response, turns and audit events
  GET  /v1/reviews?vendor_id=                recent requests
  GET  /v1/reviews/{review_id}               one stored request with its response and any human decision
  POST /v1/reviews/{review_id}/decision      a NAMED human approver records APPROVED / REJECTED / MORE_INFO
  GET  /v1/reviews/{review_id}/audit         the append-only audit trail

Identity: the caller's name comes from the X-User header (the UI sends it). This is a capstone stand-in for single sign-on and is
not authentication; see docs/app.md. The copilot itself never approves: only the decision endpoint writes a decision, and only for a
full-review report, a named person (never "copilot"), and an approver role that the report itself lists as required.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.agents.copilot import run
from app.db import store
from app.tools import register
from app.tools.tools import vendor_search

LLM_MODE = os.getenv("COPILOT_LLM", "none")          # none | mock | endpoint
RATE = os.getenv("API_RATE_LIMIT", "30/minute")
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    store.load_reference_data(store.engine())
    yield


app = FastAPI(title="Procurement & Vendor Risk Assessment Copilot", version="0.4.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class CopilotRequest(BaseModel):
    request_kind: Literal["FULL_REVIEW", "COMPARISON", "QUESTION"]
    review_type: Optional[Literal["NEW_VENDOR", "RENEWAL"]] = None
    vendor_ids: list[str] = Field(default_factory=list, max_length=3)
    question: str = Field(default="", max_length=2000)
    requester_role: Literal["procurement_analyst", "risk_reviewer", "category_manager", "legal_finance_reviewer"] = "procurement_analyst"
    as_of: date = date(2026, 11, 1)


class Decision(BaseModel):
    decision: Literal["APPROVED", "REJECTED", "MORE_INFO"]
    decided_by: str = Field(min_length=3, max_length=120)
    approver_role: str = Field(min_length=3, max_length=120)
    comment: str = Field(default="", max_length=2000)

    @field_validator("decided_by")
    @classmethod
    def named_person(cls, v: str) -> str:
        v = v.strip()
        if v.lower() in {"copilot", "assistant", "system", "ai", "bot"} or len(v.split()) < 2:
            raise ValueError("decided_by must be the full name of a human approver")
        return v


def _user(x_user: Optional[str]) -> str:
    u = (x_user or "").strip()
    return u[:120] if u else "anonymous"


@app.get("/health")
def health():
    url = store.database_url()
    return dict(status="ok", database=url.split(":", 1)[0], llm=LLM_MODE, vendors=len(register.directory()))


@app.get("/v1/vendors")
def list_vendors():
    return [dict(vendor_id=r["id"], name=r["name"], category=r["category"], status=r["status"], comparison_group=r["comparison_group"])
            for r in register.directory()]


@app.get("/v1/vendors/{vendor_id}")
def get_vendor(vendor_id: str):
    if vendor_id not in register.load_register():
        raise HTTPException(404, "unknown vendor")
    return vendor_search(vendor_id=vendor_id)


@app.post("/v1/requests")
@limiter.limit(RATE)
def create_request(request: Request, body: CopilotRequest, x_user: Optional[str] = Header(default=None)):
    req = body.model_dump(mode="json")
    out = run(req, llm=LLM_MODE)
    rid = store.save_run(req, out, user=_user(x_user), role=body.requester_role)
    t = out["trace"]
    return dict(review_id=rid, response=out["response"],
                trace=dict(action=t["action"], template=t["template"], tool_calls=t["tool_calls"], events=t["events"],
                           critic=t["critic"], latency_ms=t["latency_ms"]))


@app.get("/v1/reviews")
def reviews(vendor_id: Optional[str] = None, limit: int = 50):
    return store.list_reviews(vendor_id, min(max(limit, 1), 200))


@app.get("/v1/reviews/{review_id}")
def review(review_id: str):
    r = store.get_review(review_id)
    if not r:
        raise HTTPException(404, "review not found")
    return r


@app.post("/v1/reviews/{review_id}/decision")
@limiter.limit(RATE)
def decide(request: Request, review_id: str, body: Decision, x_user: Optional[str] = Header(default=None)):
    r = store.get_review(review_id)
    if not r:
        raise HTTPException(404, "review not found")
    resp = r["response_json"] or {}
    if "approval" not in resp:
        raise HTTPException(409, "only a full-review report can receive an approval decision")
    if r["decision"] in ("APPROVED", "REJECTED"):
        raise HTTPException(409, f"already decided: {r['decision']} by {r['decided_by']}")
    required = resp["approval"]["required_approvers"]
    if body.approver_role not in required:
        raise HTTPException(403, f"approver_role must be one of the required approvers: {required}")
    if x_user and x_user.strip() and x_user.strip().lower() != body.decided_by.lower():
        raise HTTPException(403, "decided_by must match the signed-in user (X-User)")
    return store.record_decision(review_id, decision=body.decision, decided_by=body.decided_by, decided_role=body.approver_role, comment=body.comment)


@app.get("/v1/reviews/{review_id}/audit")
def audit(review_id: str):
    if not store.get_review(review_id):
        raise HTTPException(404, "review not found")
    return store.audit_trail(review_id)
