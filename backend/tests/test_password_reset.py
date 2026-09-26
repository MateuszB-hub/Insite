"""Password reset. The security properties, not the happy path.

Reset flows are a classic source of account-takeover bugs: enumeration
oracles, reusable tokens, tokens that outlive a password change, and resets
that leave hijacked sessions alive. Each of those has a test here.
"""

import os
import re
import tempfile

import pytest
from fastapi.testclient import TestClient

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["INSECURE_COOKIES"] = "true"

from app.db.base import Base, SessionLocal, engine  # noqa: E402
from app.db.models import PasswordResetToken, User, utcnow  # noqa: E402
from main import app  # noqa: E402

PW = "original long passphrase"
NEW = "brand new long passphrase"
EMAIL = "reset@example.com"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.post("/api/auth/register", json={
            "email": EMAIL, "password": PW, "full_name": "R", "accept_terms": True})
        c.post("/api/auth/logout")
        yield c


def request_reset(client, email=EMAIL):
    return client.post("/api/auth/forgot-password", json={"email": email})


def capture_token(capsys) -> str:
    """Pull the token out of the console email provider's output."""
    out = capsys.readouterr().out
    match = re.search(r"reset-password\?token=([A-Za-z0-9_\-]+)", out)
    assert match, f"no reset link in output:\n{out}"
    return match.group(1)


def test_request_returns_generic_ack(client):
    r = request_reset(client)
    assert r.status_code == 200
    assert "if an account exists" in r.json()["detail"].lower()


def test_unknown_email_is_indistinguishable(client):
    """No enumeration oracle."""
    known = request_reset(client, EMAIL)
    unknown = request_reset(client, "nobody@example.com")
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


def test_full_reset_flow(client, capsys):
    request_reset(client)
    token = capture_token(capsys)

    r = client.post("/api/auth/reset-password",
                    json={"token": token, "new_password": NEW})
    assert r.status_code == 204, r.text

    assert client.post("/api/auth/login",
                       json={"email": EMAIL, "password": PW}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"email": EMAIL, "password": NEW}).status_code == 200


def test_token_is_single_use(client, capsys):
    request_reset(client)
    token = capture_token(capsys)
    assert client.post("/api/auth/reset-password",
                       json={"token": token, "new_password": NEW}).status_code == 204
    again = client.post("/api/auth/reset-password",
                        json={"token": token, "new_password": "yet another passphrase"})
    assert again.status_code == 400


def test_raw_token_is_not_stored(client, capsys):
    request_reset(client)
    token = capture_token(capsys)
    with SessionLocal() as db:
        stored = db.query(PasswordResetToken).one().token_hash
    assert stored != token
    assert len(stored) == 64


def test_expired_token_rejected(client, capsys):
    from datetime import timedelta
    request_reset(client)
    token = capture_token(capsys)
    with SessionLocal() as db:
        row = db.query(PasswordResetToken).one()
        row.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    r = client.post("/api/auth/reset-password",
                    json={"token": token, "new_password": NEW})
    assert r.status_code == 400


def test_garbage_token_rejected(client):
    r = client.post("/api/auth/reset-password",
                    json={"token": "not-a-real-token", "new_password": NEW})
    assert r.status_code == 400


def test_requesting_again_invalidates_the_older_link(client, capsys):
    """Only the newest link should work."""
    import time
    request_reset(client)
    first = capture_token(capsys)
    with SessionLocal() as db:  # bypass the 60s throttle
        from datetime import timedelta
        db.query(PasswordResetToken).one().created_at = utcnow() - timedelta(minutes=5)
        db.commit()
    request_reset(client)
    second = capture_token(capsys)
    assert first != second
    assert client.post("/api/auth/reset-password",
                       json={"token": first, "new_password": NEW}).status_code == 400
    assert client.post("/api/auth/reset-password",
                       json={"token": second, "new_password": NEW}).status_code == 204


def test_reset_revokes_all_sessions(client, capsys):
    """A reset answers a possible compromise; live sessions must die."""
    signed_in = TestClient(app)
    signed_in.post("/api/auth/login", json={"email": EMAIL, "password": PW})
    assert signed_in.get("/api/auth/me").status_code == 200

    request_reset(client)
    token = capture_token(capsys)
    client.post("/api/auth/reset-password", json={"token": token, "new_password": NEW})

    assert signed_in.get("/api/auth/me").status_code == 401


def test_changing_password_burns_outstanding_reset_links(client, capsys):
    """A link mailed before a password change must not still work."""
    request_reset(client)
    token = capture_token(capsys)

    signed_in = TestClient(app)
    signed_in.post("/api/auth/login", json={"email": EMAIL, "password": PW})
    signed_in.post("/api/auth/change-password",
                   json={"current_password": PW, "new_password": NEW})

    r = client.post("/api/auth/reset-password",
                    json={"token": token, "new_password": "a third long passphrase"})
    assert r.status_code == 400


def test_weak_password_rejected_but_token_survives(client, capsys):
    request_reset(client)
    token = capture_token(capsys)
    bad = client.post("/api/auth/reset-password",
                      json={"token": token, "new_password": "short"})
    assert bad.status_code == 400
    # The user can retry with the same link rather than starting over.
    good = client.post("/api/auth/reset-password",
                       json={"token": token, "new_password": NEW})
    assert good.status_code == 204


def test_rapid_requests_are_throttled(client, capsys):
    """Second request within the window issues no new token."""
    request_reset(client)
    capture_token(capsys)
    request_reset(client)
    out = capsys.readouterr().out
    assert "reset-password?token=" not in out
    with SessionLocal() as db:
        assert db.query(PasswordResetToken).count() == 1


def test_reset_clears_lockout(client, capsys):
    for _ in range(5):
        client.post("/api/auth/login", json={"email": EMAIL, "password": "wrongwrongwrong"})
    assert client.post("/api/auth/login",
                       json={"email": EMAIL, "password": PW}).status_code == 429

    request_reset(client)
    token = capture_token(capsys)
    client.post("/api/auth/reset-password", json={"token": token, "new_password": NEW})

    assert client.post("/api/auth/login",
                       json={"email": EMAIL, "password": NEW}).status_code == 200


def test_email_is_sent_after_the_response(client, monkeypatch):
    """Inline sending made known addresses answer measurably slower."""
    from app.routes import auth as auth_routes

    captured = {}

    def fake_add_task(self, func, *args, **kwargs):
        captured["func"] = func

    monkeypatch.setattr("fastapi.BackgroundTasks.add_task", fake_add_task)
    sent = []
    monkeypatch.setattr(auth_routes, "send_email", lambda **kw: sent.append(kw))
    assert request_reset(client).status_code == 200
    assert captured["func"] is auth_routes._send_reset_email
    assert sent == []  # nothing sent while the request was being handled
