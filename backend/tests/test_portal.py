"""Applicant portal: ownership, status transitions, staff boundaries."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["INSECURE_COOKIES"] = "true"

from app.db.base import Base, SessionLocal, engine  # noqa: E402

from main import app  # noqa: E402

PW = "correct horse battery staple"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


def mkclient(email):
    c = TestClient(app)
    r = c.post("/api/auth/register", json={
        "email": email, "password": PW, "full_name": "T", "accept_terms": True})
    assert r.status_code == 201, r.text
    return c


@pytest.fixture
def applicant():
    return mkclient("applicant@example.com")


@pytest.fixture
def other():
    return mkclient("other@example.com")


# --- positions -------------------------------------------------------------





# --- applying --------------------------------------------------------------






# --- ownership -------------------------------------------------------------




# --- transition rules ------------------------------------------------------






# --- staff boundary --------------------------------------------------------




# --- profile ---------------------------------------------------------------

def test_profile_roundtrip(applicant):
    applicant.put("/api/me/profile", json={
        "current_role": "Backend Engineer", "industry": "Fintech",
        "years_experience": 7, "skills": ["Python", "Postgres"]})
    p = applicant.get("/api/me/profile").json()
    assert p["current_role"] == "Backend Engineer"
    assert p["skills"] == ["Python", "Postgres"]


# --- data rights cover the new tables --------------------------------------



# --- resilience of the labour-market layer ---------------------------------


# --- candidate-side status self-reporting ----------------------------------



def test_no_staff_routes_remain(applicant):
    for path in ["/api/staff/applications", "/api/staff/pipeline"]:
        assert applicant.get(path).status_code == 404



# --- tracking external jobs ------------------------------------------------

JOB = {
    "fingerprint": "abc123def456abc123def456abc12345",
    "title": "Senior Backend Engineer",
    "company": "Acme Corp",
    "location": "Austin, Travis County",
    "url": "https://example.com/job/1",
    "external_id": "adzuna-1",
    "salary_min": 140000,
    "salary_max": 180000,
}


def test_track_an_external_job(applicant):
    r = applicant.post("/api/applications/track", json=JOB)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["position_title"] == "Senior Backend Engineer"
    assert body["company"] == "Acme Corp"
    assert body["status"] == "submitted"
    assert body["source"] == "adzuna"


def test_cannot_track_the_same_job_twice(applicant):
    applicant.post("/api/applications/track", json=JOB)
    r = applicant.post("/api/applications/track", json=JOB)
    assert r.status_code == 409
    assert "already tracked" in r.json()["detail"].lower()


def test_repost_under_a_new_id_is_still_recognised(applicant):
    """The point of matching on fingerprint rather than advert id."""
    applicant.post("/api/applications/track", json=JOB)
    reposted = {**JOB, "external_id": "adzuna-9999", "url": "https://example.com/job/9999"}
    r = applicant.post("/api/applications/track", json=reposted)
    assert r.status_code == 409


def test_a_different_job_can_still_be_tracked(applicant):
    applicant.post("/api/applications/track", json=JOB)
    other = {**JOB, "fingerprint": "999888777666999888777666999888aa", "title": "Nurse"}
    assert applicant.post("/api/applications/track", json=other).status_code == 201


def test_tracked_fingerprints_lists_only_mine(applicant, other):
    applicant.post("/api/applications/track", json=JOB)
    mine = applicant.get("/api/applications/tracked").json()["fingerprints"]
    theirs = other.get("/api/applications/tracked").json()["fingerprints"]
    assert JOB["fingerprint"] in mine
    assert theirs == []


def test_tracked_job_appears_in_my_applications(applicant):
    applicant.post("/api/applications/track", json=JOB)
    apps = applicant.get("/api/applications").json()
    assert len(apps) == 1
    assert apps[0]["position_title"] == "Senior Backend Engineer"
    assert apps[0]["job_url"] == "https://example.com/job/1"


def test_tracked_job_supports_status_updates(applicant):
    a = applicant.post("/api/applications/track", json=JOB).json()
    r = applicant.post(f"/api/applications/{a['id']}/status", json={"status": "in_review"})
    assert r.status_code == 200
    assert r.json()["status"] == "in_review"


def test_tracking_as_draft_when_not_yet_applied(applicant):
    r = applicant.post("/api/applications/track", json={**JOB, "applied": False})
    assert r.json()["status"] == "draft"


def test_erasure_removes_tracked_jobs(applicant):
    applicant.post("/api/applications/track", json=JOB)
    applicant.delete("/api/me")
    from app.db.models import Application
    db = SessionLocal()
    try:
        assert db.query(Application).count() == 0
    finally:
        db.close()


def test_track_accepts_fractional_salaries(applicant):
    """Adzuna sends 66979.29. Declaring these as int 422'd every real posting."""
    r = applicant.post("/api/applications/track", json={
        **JOB,
        "fingerprint": "fractional00000000000000000000aa",
        "salary_min": 66979.29,
        "salary_max": 81234.56,
    })
    assert r.status_code == 201, r.text

    from app.db.models import Application
    db = SessionLocal()
    try:
        row = db.query(Application).filter(
            Application.fingerprint == "fractional00000000000000000000aa").one()
        assert row.salary_min == 66979      # rounded to the integer column
        assert row.salary_max == 81235
    finally:
        db.close()
