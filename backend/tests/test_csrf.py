"""CSRF: browser requests must come from our origin and carry the header."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["INSECURE_COOKIES"] = "true"

from app.db.base import Base, engine  # noqa: E402
from app.middleware.csrf import trusted_origins  # noqa: E402
from main import app  # noqa: E402

OURS = "http://localhost:5173"
EVIL = "https://evil.example"
BODY = {"email": "x@example.com", "password": "wrong password here"}


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def login(client, **headers):
    return client.post("/api/auth/login", json=BODY, headers=headers)


def test_cross_site_post_is_blocked(client):
    r = login(client, Origin=EVIL, **{"X-Insite-CSRF": "1"})
    assert r.status_code == 403
    assert "untrusted origin" in r.json()["detail"]


def test_same_origin_without_header_is_blocked(client):
    r = login(client, Origin=OURS)
    assert r.status_code == 403
    assert "CSRF header" in r.json()["detail"]


def test_same_origin_with_header_reaches_the_route(client):
    # 401 = wrong password: the request got past the CSRF check.
    assert login(client, Origin=OURS, **{"X-Insite-CSRF": "1"}).status_code == 401


def test_referer_is_the_fallback_for_origin(client):
    assert login(client, Referer=f"{EVIL}/page").status_code == 403
    r = login(client, Referer=f"{OURS}/login", **{"X-Insite-CSRF": "1"})
    assert r.status_code == 401


def test_null_origin_is_never_trusted(client):
    assert login(client, Origin="null", **{"X-Insite-CSRF": "1"}).status_code == 403


def test_non_browser_clients_pass_through(client):
    # No Origin and no Referer: curl, scripts, this test client.
    assert login(client).status_code == 401


def test_safe_methods_are_not_checked(client):
    assert client.get("/api/health", headers={"Origin": EVIL}).status_code == 200


def test_app_base_url_is_trusted(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://insite.dev/")
    assert "https://insite.dev" in trusted_origins()
