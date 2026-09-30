"""/api/health/ready: what an outside uptime monitor watches.

/api/health only says the process answers (it stayed "ok" with the database
down). Readiness asks the database and the local model.
"""

from fastapi.testclient import TestClient

from app.main import app


def _model(monkeypatch, up: bool):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200 if up else 503, json={"version": "test"})
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_ready_when_database_and_model_answer(monkeypatch):
    _model(monkeypatch, up=True)
    r = TestClient(app).get("/api/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok", "local_model": "ok"}


def test_degraded_but_up_without_the_model(monkeypatch):
    # Résumé reading and summaries stop; everything else works.
    _model(monkeypatch, up=False)
    r = TestClient(app).get("/api/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded" and r.json()["local_model"] == "off"


def test_down_without_the_database(monkeypatch):
    from app.db import base
    _model(monkeypatch, up=True)

    class Broken:
        def connect(self):
            raise RuntimeError("database gone")
    monkeypatch.setattr(base, "engine", Broken())
    r = TestClient(app).get("/api/health/ready")
    assert r.status_code == 503
    assert r.json() == {"status": "down", "database": "down", "local_model": "ok"}


def test_readiness_needs_no_sign_in_and_says_nothing_more(monkeypatch):
    _model(monkeypatch, up=True)
    r = TestClient(app).get("/api/health/ready")
    assert set(r.json()) == {"status", "database", "local_model"}
