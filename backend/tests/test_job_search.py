"""The honest filter.

Both classifiers are pure functions over a posting dict, so these run with no
network. The fixtures mirror shapes observed in live Adzuna responses.
"""

import pytest

from app.services.job_search import (
    RemoteClaim,
    SalarySource,
    classify_remote,
    classify_salary,
    to_posting,
)


def posting(**kw):
    base = {
        "id": "1", "title": "Software Engineer", "description": "Build things.",
        "location": {"display_name": "Austin, Travis County"},
        "company": {"display_name": "Acme"}, "redirect_url": "https://x",
    }
    base.update(kw)
    return base


# --- salary provenance -----------------------------------------------------

def test_employer_stated_salary():
    assert classify_salary(posting(salary_min=100000, salary_is_predicted="0")) \
        is SalarySource.stated


def test_aggregator_prediction_is_not_stated():
    """86% of live postings are predictions returned in the same fields."""
    assert classify_salary(posting(salary_min=100000, salary_is_predicted="1")) \
        is SalarySource.estimated


@pytest.mark.parametrize("flag", ["1", 1, True, "true", "True"])
def test_prediction_flag_variants(flag):
    assert classify_salary(posting(salary_min=9, salary_is_predicted=flag)) \
        is SalarySource.estimated


def test_no_salary_is_absent_not_zero():
    assert classify_salary(posting()) is SalarySource.absent


# --- remote claims ---------------------------------------------------------

def test_remote_with_nationwide_location_is_trusted():
    claim, note = classify_remote(posting(
        title="Remote Software Engineer", location={"display_name": "US"}))
    assert claim is RemoteClaim.remote
    assert note is None


def test_remote_pinned_to_a_town_is_conflicted():
    """Observed live: 'Remote Software Engineer' listed in Saint Bernard, Ohio."""
    claim, note = classify_remote(posting(
        title="Remote Software Engineer",
        location={"display_name": "Saint Bernard, Hamilton County"}))
    assert claim is RemoteClaim.conflicted
    assert "Saint Bernard" in note


def test_remote_claim_contradicted_by_body_text():
    claim, note = classify_remote(posting(
        title="Remote Engineer", description="Remote role, hybrid 3 days onsite.",
        location={"display_name": "Denver, Denver County"}))
    assert claim is RemoteClaim.conflicted
    assert "hybrid" in note.lower() or "onsite" in note.lower()


def test_no_remote_claim_is_onsite():
    claim, note = classify_remote(posting(title="Software Engineer"))
    assert claim is RemoteClaim.onsite
    assert note is None


@pytest.mark.parametrize("phrase", [
    "work from home", "fully remote", "100% remote", "telecommuting", "WFH",
])
def test_remote_phrasings_detected(phrase):
    claim, _ = classify_remote(posting(
        description=f"This is a {phrase} position.",
        location={"display_name": "US"}))
    assert claim is RemoteClaim.remote


def test_provenance_survives_into_the_posting():
    """The whole point: never drop how we know what we know."""
    p = to_posting(posting(salary_min=120000, salary_is_predicted="1",
                           title="Remote Engineer",
                           location={"display_name": "Austin, Travis County"}))
    assert p.salary_source is SalarySource.estimated
    assert p.remote_claim is RemoteClaim.conflicted
    assert p.remote_note
    d = p.to_dict()
    assert d["salary_source"] == "estimated"
    assert d["remote_claim"] == "conflicted"


# --- repost / duplicate detection ------------------------------------------

from app.services.job_search import (  # noqa: E402
    JobPosting, _collapse_duplicates, _unique_by_fingerprint, fingerprint,
)


def test_repost_with_new_id_and_date_has_the_same_fingerprint():
    """The core defence: re-upping an advert resets its date, not its text."""
    original = fingerprint("Software Engineer",
                           "Build payment systems. Req 10432. Posted 2025-01-04.")
    reposted = fingerprint("Software Engineer",
                           "Build payment systems. Req 88911. Posted 2026-09-20.")
    assert original == reposted


def test_genuinely_different_adverts_differ():
    assert fingerprint("Nurse", "Provide patient care on a busy ward.") \
        != fingerprint("Welder", "Fabricate structural steel assemblies.")


def test_urls_do_not_affect_the_fingerprint():
    a = fingerprint("Engineer", "Great role here https://jobs.example.com/a/1")
    b = fingerprint("Engineer", "Great role here https://jobs.example.com/z/9")
    assert a == b


def _p(fp, loc, salary=None, source=None):
    from app.services.job_search import SalarySource
    return JobPosting(id=loc, title="Software Engineer", company="Acme",
                      location=loc, url="https://x", fingerprint=fp,
                      salary_min=salary,
                      salary_source=source or SalarySource.absent)


def test_identical_adverts_collapse_into_one_row():
    """Observed live: one employer, the same advert across 10 states."""
    postings = [_p("aaa", f"State {i}") for i in range(10)] + [_p("bbb", "Austin")]
    collapsed, folded = _collapse_duplicates(postings)
    assert len(collapsed) == 2
    assert folded == 9
    biggest = max(collapsed, key=lambda p: p.duplicate_count)
    assert biggest.duplicate_count == 10
    assert len(biggest.duplicate_locations) == 9


def test_collapsing_keeps_a_stated_salary_over_an_estimate():
    from app.services.job_search import SalarySource
    postings = [
        _p("aaa", "Austin", 90000, SalarySource.estimated),
        _p("aaa", "Denver", 120000, SalarySource.stated),
    ]
    collapsed, _ = _collapse_duplicates(postings)
    assert collapsed[0].salary_source is SalarySource.stated
    assert collapsed[0].salary_min == 120000


def test_batch_insert_never_repeats_a_fingerprint():
    """Repeated fingerprints in one result set must not violate the PK."""
    postings = [_p("aaa", "A"), _p("aaa", "B"), _p("bbb", "C")]
    assert len(_unique_by_fingerprint(postings)) == 2
