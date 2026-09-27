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
    apps = applicant.get("/api/applications").json()["items"]
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


# --- misclick recovery (tester feedback) -----------------------------------

def _tracked(client, n=0, **extra):
    fp = f"{n:032x}"
    return client.post("/api/applications/track", json={
        **JOB, "fingerprint": fp, "title": f"Job {n}", **extra}).json()


def _move(client, app_id, status):
    r = client.post(f"/api/applications/{app_id}/status", json={"status": status})
    assert r.status_code == 200, r.text
    return r.json()


def test_undo_reverses_a_misclick_and_keeps_the_timeline(applicant):
    a = _tracked(applicant)
    _move(applicant, a["id"], "in_review")
    after = _move(applicant, a["id"], "rejected")          # the misclick
    assert after["status"] == "rejected" and after["can_undo"]
    r = applicant.post(f"/api/applications/{a['id']}/undo")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "in_review"
    assert body["events"][-1]["is_undo"] is True          # recorded, not erased
    assert len(body["events"]) == 5                       # draft, submitted, review, rejected, undo
    # and it can move on normally afterwards
    assert _move(applicant, a["id"], "interview")["status"] == "interview"


def test_undo_twice_steps_back_twice(applicant):
    a = _tracked(applicant)
    _move(applicant, a["id"], "in_review")
    _move(applicant, a["id"], "interview")
    assert applicant.post(f"/api/applications/{a['id']}/undo").json()["status"] == "in_review"
    assert applicant.post(f"/api/applications/{a['id']}/undo").json()["status"] == "submitted"


def test_undo_back_to_not_applied_clears_the_submitted_date(applicant):
    a = _tracked(applicant)
    body = applicant.post(f"/api/applications/{a['id']}/undo").json()
    assert body["status"] == "draft"
    assert body["submitted_at"] is None
    assert body["can_undo"] is False
    assert applicant.post(f"/api/applications/{a['id']}/undo").status_code == 409


def test_status_response_includes_the_new_event(applicant):
    a = _tracked(applicant)
    body = _move(applicant, a["id"], "in_review")
    assert body["events"][-1]["to_status"] == "in_review"


def test_remove_deletes_and_frees_the_job_to_track_again(applicant):
    a = _tracked(applicant)
    assert applicant.delete(f"/api/applications/{a['id']}").status_code == 204
    assert applicant.get("/api/applications").json()["items"] == []
    assert applicant.get("/api/applications/tracked").json()["fingerprints"] == []
    assert applicant.post("/api/applications/track", json={
        **JOB, "fingerprint": f"{0:032x}", "title": "Job 0"}).status_code == 201


def test_cannot_undo_or_remove_someone_elses(applicant, other):
    a = _tracked(applicant)
    assert other.post(f"/api/applications/{a['id']}/undo").status_code == 404
    assert other.delete(f"/api/applications/{a['id']}").status_code == 404


# --- listing at scale (tester feedback) -------------------------------------

def test_tabs_counts_search_and_paging(applicant):
    ids = [_tracked(applicant, n)["id"] for n in range(30)]
    _move(applicant, ids[0], "in_review")
    _move(applicant, ids[0], "interview")
    _move(applicant, ids[1], "rejected")
    _tracked(applicant, 99, company="Globex")

    page = applicant.get("/api/applications").json()
    assert page["counts"] == {"active": 29, "interviewing": 1, "offers": 0,
                              "closed": 1, "all": 31}
    assert len(page["items"]) == 25 and page["total"] == 31
    rest = applicant.get("/api/applications", params={"offset": 25}).json()
    assert len(rest["items"]) == 6
    seen = {a["id"] for a in page["items"]} | {a["id"] for a in rest["items"]}
    assert len(seen) == 31                                 # no overlap, none missing

    tab = applicant.get("/api/applications", params={"group": "interviewing"}).json()
    assert [a["id"] for a in tab["items"]] == [ids[0]]

    found = applicant.get("/api/applications", params={"q": "globex"}).json()
    assert found["total"] == 1 and found["counts"]["all"] == 1


def test_most_recently_updated_first(applicant):
    first = _tracked(applicant, 1)
    _tracked(applicant, 2)
    _move(applicant, first["id"], "in_review")
    items = applicant.get("/api/applications").json()["items"]
    assert items[0]["id"] == first["id"]


def test_listing_only_shows_mine(applicant, other):
    _tracked(applicant)
    assert other.get("/api/applications").json() == {
        "items": [], "total": 0,
        "counts": {"active": 0, "interviewing": 0, "offers": 0, "closed": 0, "all": 0}}



# --- certifications and résumé import -----------------------------------------

def test_certifications_roundtrip_and_export(applicant):
    certs = ["Certified Scrum Master, CSM", "BLS"]   # a comma inside a name survives
    r = applicant.put("/api/me/profile", json={"current_role": "Nurse", "certifications": certs})
    assert r.status_code == 200, r.text
    assert applicant.get("/api/me/profile").json()["certifications"] == certs
    assert applicant.get("/api/me/export").json()["profile"]["certifications"] == certs


def _pdf():
    from tests.pdf_fixtures import NURSE, make_pdf
    return {"file": ("resume.pdf", make_pdf(NURSE), "application/pdf")}


@pytest.fixture
def fake_resume(monkeypatch):
    from app.routes import portal
    from app.services import resume

    async def suggest(data):
        assert data.startswith(b"%PDF")
        return {"fields": {"current_role": "Registered Nurse", "skills": ["Triage"]},
                "sources": {"current_role": "résumé"}, "dropped": {"skills": 1},
                "jobs_found": 2, "pages": 1, "engine": "test"}
    monkeypatch.setattr(resume, "suggest_profile", suggest)
    portal._resume_uses.clear()
    yield
    portal._resume_uses.clear()


def test_resume_needs_sign_in():
    assert TestClient(app).post("/api/me/profile/resume", files=_pdf()).status_code == 401


def test_resume_suggests_and_saves_nothing(applicant, fake_resume):
    r = applicant.post("/api/me/profile/resume", files=_pdf())
    assert r.status_code == 200, r.text
    assert r.json()["fields"]["current_role"] == "Registered Nurse"
    assert r.json()["dropped"] == {"skills": 1}
    # Suggestions only: the profile is untouched until the person saves.
    assert applicant.get("/api/me/profile").json()["current_role"] is None


def test_resume_bad_file_gets_a_plain_reason(applicant):
    from app.routes import portal
    portal._resume_uses.clear()
    r = applicant.post("/api/me/profile/resume",
                       files={"file": ("cv.docx", b"PK\x03\x04 not a pdf", "application/octet-stream")})
    assert r.status_code == 422
    assert "isn't a PDF" in r.json()["detail"]


def test_resume_is_limited_per_hour(applicant, fake_resume):
    from app.routes import portal
    codes = [applicant.post("/api/me/profile/resume", files=_pdf()).status_code
             for _ in range(portal.RESUME_LIMIT + 1)]
    assert codes == [200] * portal.RESUME_LIMIT + [429]



# --- job search: date posted and sort are checked at the door ----------------

@pytest.mark.parametrize("query, reason", [
    ("posted_after=2999-01-01T00:00:00Z", "future"),
    ("posted_after=2001-01-01T00:00:00Z", "within the last year"),
    ("sort=salary", "sort must be one of"),
])
def test_job_search_refuses_bad_dates_and_sorts(applicant, query, reason):
    r = applicant.get(f"/api/jobs/search?q=nurse&{query}")
    assert r.status_code == 422
    assert reason in r.json()["detail"]



# --- job search: places are checked before the board sees them ---------------

def test_junk_places_are_not_searched_at_all(applicant, monkeypatch):
    from app.routes import jobs

    async def must_not_search(*args, **kwargs):
        raise AssertionError("searched although no place was real")
    monkeypatch.setattr(jobs, "search_jobs", must_not_search)

    r = applicant.get("/api/jobs/search?q=cloud%20engineer&where=new%20yotrk&where=3&where=.")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["postings"] == []
    checks = {c["input"]: c for c in body["place_checks"]}
    assert checks["new yotrk"]["status"] == "unknown"
    assert checks["new yotrk"]["suggestions"][0] == "New York, NY"
    assert checks["3"]["status"] == checks["."]["status"] == "invalid"


def test_real_places_are_searched_by_their_full_name(applicant, monkeypatch):
    from app.routes import jobs
    from app.services.job_search import SearchResult
    seen = {}

    async def fake_search(q, places, **kwargs):
        seen["places"] = places
        return SearchResult(locations_searched=places)
    monkeypatch.setattr(jobs, "search_jobs", fake_search)

    r = applicant.get("/api/jobs/search?q=nurse&where=austin%20tx&where=springfield&where=zzzz")
    assert r.status_code == 200, r.text
    assert seen["places"] == ["Austin, TX", "Springfield, MO"]
    statuses = [c["status"] for c in r.json()["place_checks"]]
    assert statuses == ["ok", "ambiguous", "unknown"]


def test_place_suggestions_as_you_type(applicant):
    r = applicant.get("/api/places?q=sea")
    assert r.status_code == 200
    assert r.json()[0] == "Seattle, WA"
    assert TestClient(app).get("/api/places?q=sea").status_code == 401
