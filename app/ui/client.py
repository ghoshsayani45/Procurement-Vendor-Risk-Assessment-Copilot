"""Small API client for the UI. API_URL set -> HTTP (docker compose: http://api:8000). Unset -> the FastAPI app in-process,
so `streamlit run app/ui/streamlit_app.py` works on a laptop with no server and no Docker."""
from __future__ import annotations

import os
from functools import lru_cache


class ApiError(RuntimeError):
    def __init__(self, status: int, detail):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


@lru_cache(maxsize=1)
def _client():
    url = os.getenv("API_URL", "").strip()
    if url:
        import httpx
        return httpx.Client(base_url=url, timeout=120), url
    from fastapi.testclient import TestClient
    from app.api.main import app
    c = TestClient(app)
    c.__enter__()                      # runs the API start-up (reference data load)
    return c, "in-process"


def mode() -> str:
    return _client()[1]


def call(method: str, path: str, user: str = "", **kw):
    c, _ = _client()
    r = c.request(method, path, headers={"X-User": user} if user else {}, **kw)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise ApiError(r.status_code, detail)
    return r.json()
