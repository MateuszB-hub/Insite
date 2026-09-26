"""Registration gating, for when the app is publicly reachable."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["INSECURE_COOKIES"] = "true"

from app.db.base import Base, engine  # noqa: E402
import app.routes.auth as auth_routes  # noqa: E402
from main import app  # noqa: E402

PW = "an invited passphrase"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


def register(client, code=None, email="invited@example.com"):
    body = {"email": email, "password": PW, "accept_terms": True}
    if code is not None:
        body["invite_code"] = code
    return client.post("/api/auth/register", json=body)


def test_open_registration_when_no_code_configured(monkeypatch):
    monkeypatch.setattr(auth_routes, "REGISTRATION_CODE", "")
    with TestClient(app) as c:
        assert register(c).status_code == 201


def test_registration_refused_without_the_code(monkeypatch):
    monkeypatch.setattr(auth_routes, "REGISTRATION_CODE", "let-me-in-2026")
    with TestClient(app) as c:
        r = register(c)
        assert r.status_code == 403
        assert "invite code" in r.json()["detail"].lower()


def test_registration_refused_with_a_wrong_code(monkeypatch):
    monkeypatch.setattr(auth_routes, "REGISTRATION_CODE", "let-me-in-2026")
    with TestClient(app) as c:
        assert register(c, code="guess").status_code == 403


def test_registration_succeeds_with_the_right_code(monkeypatch):
    monkeypatch.setattr(auth_routes, "REGISTRATION_CODE", "let-me-in-2026")
    with TestClient(app) as c:
        assert register(c, code="let-me-in-2026").status_code == 201


def test_login_is_unaffected_by_the_gate(monkeypatch):
    """Existing testers must not be locked out if the code changes."""
    monkeypatch.setattr(auth_routes, "REGISTRATION_CODE", "code-one")
    with TestClient(app) as c:
        register(c, code="code-one")
        c.post("/api/auth/logout")
    monkeypatch.setattr(auth_routes, "REGISTRATION_CODE", "code-two")
    with TestClient(app) as c:
        r = c.post("/api/auth/login",
                   json={"email": "invited@example.com", "password": PW})
        assert r.status_code == 200
