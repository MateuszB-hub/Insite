"""Auth and data-rights behaviour.

Runs against a throwaway SQLite file so the suite needs no daemon.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

# Must be set before app.db.base imports and builds the engine.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["INSECURE_COOKIES"] = "true"  # TestClient speaks http

from app.db.base import Base, engine  # noqa: E402
from app.db.models import User, utcnow  # noqa: E402
from main import app  # noqa: E402

GOOD_PW = "correct horse battery staple"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def register(client, email="a@example.com", pw=GOOD_PW, terms=True):
    return client.post("/api/auth/register", json={
        "email": email, "password": pw, "full_name": "Test User",
        "accept_terms": terms,
    })


def test_register_then_me(client):
    r = register(client)
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "a@example.com"
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "a@example.com"


def test_register_requires_terms(client):
    assert register(client, terms=False).status_code == 400


def test_register_rejects_weak_password(client):
    r = register(client, pw="short")
    assert r.status_code == 400
    assert "at least" in r.json()["detail"]


def test_password_never_stored_in_plaintext(client):
    register(client)
    from sqlalchemy.orm import Session
    with Session(engine) as db:
        user = db.query(User).one()
    assert user.password_hash is not None
    assert GOOD_PW not in user.password_hash
    assert user.password_hash.startswith("$argon2id$")


def test_session_cookie_is_httponly(client):
    r = register(client)
    cookie_header = r.headers.get("set-cookie", "")
    assert "httponly" in cookie_header.lower()
    assert "samesite=lax" in cookie_header.lower()


def test_raw_token_is_not_stored(client):
    r = register(client)
    raw = client.cookies.get("insite_session")
    assert raw
    from sqlalchemy.orm import Session
    from app.db.models import UserSession
    with Session(engine) as db:
        stored = db.query(UserSession).one().token_hash
    assert stored != raw
    assert len(stored) == 64  # sha256 hex


def test_protected_route_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/me/export").status_code == 401


def test_login_wrong_password_is_generic(client):
    register(client)
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login",
                    json={"email": "a@example.com", "password": "wrongwrongwrong"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


def test_unknown_email_gives_same_error(client):
    """No user enumeration: identical response for unknown address."""
    r = client.post("/api/auth/login",
                    json={"email": "nobody@example.com", "password": "whatever12345"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


def test_duplicate_registration_does_not_confirm_existence(client):
    register(client)
    r = register(client)
    assert r.status_code == 409
    detail = r.json()["detail"]
    # Must guide the user without asserting the address exists.
    assert "if you already have one" in detail.lower()
    assert "already registered" not in detail.lower()
    assert "email exists" not in detail.lower()


def test_lockout_after_repeated_failures(client):
    register(client)
    client.post("/api/auth/logout")
    for _ in range(5):
        client.post("/api/auth/login",
                    json={"email": "a@example.com", "password": "badbadbadbad"})
    # 6th attempt, even with the CORRECT password, must be refused.
    r = client.post("/api/auth/login",
                    json={"email": "a@example.com", "password": GOOD_PW})
    assert r.status_code == 429


def test_logout_revokes_session(client):
    register(client)
    assert client.get("/api/auth/me").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_login_rotates_session(client):
    """The pre-login token must not survive authentication."""
    register(client)
    old = client.cookies.get("insite_session")
    client.post("/api/auth/login", json={"email": "a@example.com", "password": GOOD_PW})
    new = client.cookies.get("insite_session")
    assert old != new
    # Old token is dead even though it has not expired.
    c2 = TestClient(app)
    c2.cookies.set("insite_session", old)
    assert c2.get("/api/auth/me").status_code == 401


def test_export_returns_account_and_consents(client):
    register(client)
    data = client.get("/api/me/export").json()
    assert data["account"]["email"] == "a@example.com"
    kinds = {c["kind"] for c in data["consents"]}
    assert kinds == {"terms", "data_retention", "third_party_ai"}


def test_third_party_ai_consent_defaults_false(client):
    """Local-first: applicant data must not leave the box without consent."""
    register(client)
    consents = {c["kind"]: c["granted"] for c in client.get("/api/me/export").json()["consents"]}
    assert consents["third_party_ai"] is False
    assert consents["terms"] is True


def test_erasure_scrubs_identity_and_kills_session(client):
    register(client)
    r = client.delete("/api/me")
    assert r.status_code == 204
    assert client.get("/api/auth/me").status_code == 401

    from sqlalchemy.orm import Session
    with Session(engine) as db:
        user = db.query(User).one()
    assert user.email != "a@example.com"
    assert user.full_name is None
    assert user.password_hash is None
    assert user.deleted_at is not None


def test_erased_user_cannot_log_back_in(client):
    register(client)
    client.delete("/api/me")
    r = client.post("/api/auth/login", json={"email": "a@example.com", "password": GOOD_PW})
    assert r.status_code == 401


def test_audit_survives_erasure(client):
    """Erasure must be provable after the data is gone."""
    register(client)
    client.delete("/api/me")
    from sqlalchemy.orm import Session
    from app.db.models import AuditLog
    with Session(engine) as db:
        actions = [a.action for a in db.query(AuditLog).all()]
    assert "register" in actions
    assert "data.erasure" in actions


def test_retention_purge_erases_expired_users(client):
    register(client)
    from sqlalchemy.orm import Session
    from app.services.retention import purge_expired_data
    from datetime import timedelta
    with Session(engine) as db:
        user = db.query(User).one()
        user.retention_until = utcnow() - timedelta(days=1)
        db.commit()
        counts = purge_expired_data(db)
        db.commit()
        assert counts["users_erased"] == 1
        refreshed = db.query(User).one()
        assert refreshed.deleted_at is not None
        assert refreshed.email.startswith("erased-")


def test_retention_purge_is_idempotent(client):
    register(client)
    from sqlalchemy.orm import Session
    from app.services.retention import purge_expired_data
    from datetime import timedelta
    with Session(engine) as db:
        db.query(User).one().retention_until = utcnow() - timedelta(days=1)
        db.commit()
        purge_expired_data(db); db.commit()
        second = purge_expired_data(db); db.commit()
    assert second["users_erased"] == 0


# --- change password -------------------------------------------------------

NEW_PW = "a different long passphrase"


def test_change_password_requires_auth(client):
    r = client.post("/api/auth/change-password",
                    json={"current_password": GOOD_PW, "new_password": NEW_PW})
    assert r.status_code == 401


def test_change_password_happy_path(client):
    register(client)
    r = client.post("/api/auth/change-password",
                    json={"current_password": GOOD_PW, "new_password": NEW_PW})
    assert r.status_code == 204, r.text
    # still signed in here
    assert client.get("/api/auth/me").status_code == 200
    # old password no longer works
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login",
                       json={"email": "a@example.com", "password": GOOD_PW}).status_code == 401
    # new one does
    assert client.post("/api/auth/login",
                       json={"email": "a@example.com", "password": NEW_PW}).status_code == 200


def test_wrong_current_password_rejected(client):
    """A stolen cookie must not be enough to seize the account."""
    register(client)
    r = client.post("/api/auth/change-password",
                    json={"current_password": "not the password", "new_password": NEW_PW})
    assert r.status_code == 400
    assert "current password" in r.json()["detail"].lower()
    # password unchanged
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login",
                       json={"email": "a@example.com", "password": GOOD_PW}).status_code == 200


def test_weak_new_password_rejected(client):
    register(client)
    r = client.post("/api/auth/change-password",
                    json={"current_password": GOOD_PW, "new_password": "short"})
    assert r.status_code == 400
    assert "at least" in r.json()["detail"]


def test_new_password_must_differ(client):
    register(client)
    r = client.post("/api/auth/change-password",
                    json={"current_password": GOOD_PW, "new_password": GOOD_PW})
    assert r.status_code == 400
    assert "differ" in r.json()["detail"].lower()


def test_change_password_revokes_other_sessions(client):
    """A cookie captured before the change must stop working."""
    register(client)
    stolen = client.cookies.get("insite_session")

    attacker = TestClient(app)
    attacker.cookies.set("insite_session", stolen)
    assert attacker.get("/api/auth/me").status_code == 200   # valid before

    client.post("/api/auth/change-password",
                json={"current_password": GOOD_PW, "new_password": NEW_PW})

    assert attacker.get("/api/auth/me").status_code == 401   # dead after


def test_failed_change_is_audited(client):
    register(client)
    client.post("/api/auth/change-password",
                json={"current_password": "wrong", "new_password": NEW_PW})
    from sqlalchemy.orm import Session
    from app.db.models import AuditLog
    with Session(engine) as db:
        actions = [a.action for a in db.query(AuditLog).all()]
    assert "password.change.failed" in actions


def test_logout_actually_clears_the_cookie(client):
    """Revoking server-side is not enough; the browser must drop it too."""
    register(client)
    r = client.post("/api/auth/logout")
    assert r.status_code == 204
    # A cleared cookie comes back with an expiry in the past / empty value.
    header = r.headers.get("set-cookie", "")
    assert "insite_session=" in header
    assert ("Max-Age=0" in header or "expires=" in header.lower())


def test_change_password_issues_a_fresh_cookie(client):
    register(client)
    before = client.cookies.get("insite_session")
    r = client.post("/api/auth/change-password",
                    json={"current_password": GOOD_PW, "new_password": NEW_PW})
    assert r.status_code == 204
    assert "set-cookie" in {k.lower() for k in r.headers}
    assert client.cookies.get("insite_session") != before
