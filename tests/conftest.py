"""Shared test fixtures: every test gets its own SQLite database and no audit file."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'copilot.sqlite').as_posix()}")
    monkeypatch.setenv("AUDIT_LOG_PATH", "off")
    monkeypatch.setenv("API_RATE_LIMIT", "1000/minute")


@pytest.fixture
def api():
    from fastapi.testclient import TestClient
    from app.api.main import app
    with TestClient(app) as c:
        yield c
