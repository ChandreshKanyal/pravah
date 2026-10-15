from fastapi.testclient import TestClient

from app.api import health
from app.main import app


def test_health_shape_and_all_must_pass(monkeypatch):
    monkeypatch.setattr(health.earth_engine, "ping", lambda: 1)
    monkeypatch.setattr(health.gemini, "generate", lambda *a, **k: "ok")
    monkeypatch.setattr(health.firestore, "ping", lambda: False)
    r = TestClient(app).get("/api/health").json()
    assert r == {"ok": False, "ee": True, "vertex": True, "firestore": False}
