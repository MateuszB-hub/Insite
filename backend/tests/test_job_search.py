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


# --- several locations -----------------------------------------------------

import asyncio  # noqa: E402

import httpx  # noqa: E402

from app.services import job_search  # noqa: E402
from app.services.job_search import normalize_locations, search_jobs  # noqa: E402


def test_locations_are_trimmed_deduplicated_and_capped():
    assert normalize_locations(None) == []
    assert normalize_locations("  Austin ") == ["Austin"]
    assert normalize_locations(["Austin", "austin", " ", "Denver", "Reno", "Boise"]) == [
        "Austin", "Denver", "Reno"]


@pytest.fixture(autouse=True)
def _fresh_search_cache():
    # Tests reuse queries against different fake responses.
    job_search.clear_search_cache()
    yield
    job_search.clear_search_cache()


def _fake_adzuna(monkeypatch, pages, fail=(), count=None, requests=None):
    """Serve `pages[where]` for each place, paged like Adzuna (/search/<n>).

    `count` overrides the reported total (default: 10x what is served).
    `requests` collects each request's query params and page number.
    """
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        where = request.url.params.get("where")
        page = int(request.url.path.rsplit("/", 1)[-1])
        per_page = int(request.url.params.get("results_per_page", 50))
        seen.append(where)
        if requests is not None:
            requests.append({**dict(request.url.params), "page": page})
        if where in fail:
            return httpx.Response(500)
        everything = pages[where]
        chunk = everything[(page - 1) * per_page: page * per_page]
        total = count if count is not None else len(everything) * 10
        return httpx.Response(200, json={"count": total, "results": chunk})

    real = httpx.AsyncClient
    monkeypatch.setattr(job_search.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(job_search, "_record_sightings", lambda postings: {})
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    return seen


_WORDS = ["alpha", "bravo", "charlie", "delta"]


def _job(i, city):
    # Fingerprints ignore digits (they change on reposts), so vary words.
    word = _WORDS[i]
    return posting(id=f"{city}-{i}", title=f"Engineer {city} {word}",
                   description=f"Unique advert {city} {word}.",
                   location={"display_name": city})


def test_each_place_is_searched_and_results_interleave(monkeypatch):
    seen = _fake_adzuna(monkeypatch, {
        "Austin": [_job(i, "Austin") for i in range(3)],
        "Denver": [_job(i, "Denver") for i in range(3)],
    })
    result = asyncio.run(search_jobs("engineer", ["Austin", "Denver"], limit=4))
    assert sorted(seen) == ["Austin", "Denver"]
    # Round-robin: the limit takes two from each city, not four from the first.
    assert [p.location for p in result.postings] == ["Austin", "Denver", "Austin", "Denver"]
    assert result.total_available == 60
    assert result.locations_searched == ["Austin", "Denver"]


def test_same_advert_in_two_cities_is_shown_once(monkeypatch):
    shared = dict(title="Staff Engineer", description="Identical advert text.")
    _fake_adzuna(monkeypatch, {
        "Austin": [posting(id="a", location={"display_name": "Austin"}, **shared)],
        "Denver": [posting(id="d", location={"display_name": "Denver"}, **shared)],
    })
    result = asyncio.run(search_jobs("engineer", ["Austin", "Denver"]))
    assert len(result.postings) == 1
    assert result.collapsed_duplicates == 1


def test_one_failing_place_does_not_sink_the_others(monkeypatch):
    _fake_adzuna(monkeypatch, {"Austin": [_job(0, "Austin")], "Denver": []}, fail={"Denver"})
    result = asyncio.run(search_jobs("engineer", ["Austin", "Denver"]))
    assert [p.location for p in result.postings] == ["Austin"]
    assert result.failed_locations == ["Denver"]


def test_no_location_searches_nationwide(monkeypatch):
    seen = _fake_adzuna(monkeypatch, {None: [_job(0, "US")]})
    result = asyncio.run(search_jobs("engineer", None))
    assert seen == [None]
    assert len(result.postings) == 1


# --- salary floor: stated first, estimates apart, never hidden -------------

def _paid(word, low, high, predicted):
    return posting(id=word, title=f"Engineer {word}", description=f"Advert {word}.",
                   salary_min=low, salary_max=high, salary_is_predicted=predicted,
                   location={"display_name": "US"})


def test_floor_separates_stated_from_estimated(monkeypatch):
    _fake_adzuna(monkeypatch, {None: [
        _paid("alpha", 110000, 130000, "0"),    # stated, clears
        _paid("bravo", 90000, 120000, "0"),     # stated range reaches the floor
        _paid("charlie", 60000, 80000, "0"),    # stated, below
        _paid("delta", 105000, 105000, "1"),    # estimated, clears
        _paid("echo", 50000, 50000, "1"),       # estimated, below
        posting(id="fox", title="Engineer foxtrot", description="Advert foxtrot."),  # no pay
    ]}, count=6)
    result = asyncio.run(search_jobs("engineer", salary_min=100000))
    assert [p.id for p in result.postings] == ["alpha", "bravo"]
    assert [p.id for p in result.estimated_matches] == ["delta"]
    assert result.excluded_below_salary == 2
    assert result.excluded_no_salary == 1


def test_stated_only_drops_estimates_entirely(monkeypatch):
    _fake_adzuna(monkeypatch, {None: [
        _paid("alpha", 110000, 130000, "0"), _paid("delta", 105000, 105000, "1"),
    ]}, count=2)
    result = asyncio.run(search_jobs("engineer", salary_min=100000, require_stated_salary=True))
    assert [p.id for p in result.postings] == ["alpha"]
    assert result.estimated_matches == []
    assert result.excluded_estimated_salary == 1


def test_floor_and_age_are_sent_to_adzuna(monkeypatch):
    requests = []
    _fake_adzuna(monkeypatch, {None: []}, count=0, requests=requests)
    asyncio.run(search_jobs("engineer", salary_min=100000, max_days_old=7))
    assert requests[0]["salary_min"] == "100000"
    assert requests[0]["max_days_old"] == "7"


def test_no_age_limit_unless_asked(monkeypatch):
    requests = []
    _fake_adzuna(monkeypatch, {None: []}, count=0, requests=requests)
    asyncio.run(search_jobs("engineer"))
    assert "max_days_old" not in requests[0]


_MANY = [f"word{c}{d}" for c in "abcdefghij" for d in "abcdefghij"]


def _estimated_page(n, start=0):
    return [_paid(_MANY[start + i], 120000, 120000, "1") for i in range(n)]


def test_too_few_stated_fetches_more_pages(monkeypatch):
    requests = []
    # 20 per page for limit=10; stated matches only appear on page 3.
    served = _estimated_page(40) + [_paid("zulu", 150000, 150000, "0")] + _estimated_page(19, 40)
    _fake_adzuna(monkeypatch, {None: served}, count=500, requests=requests)
    result = asyncio.run(search_jobs("engineer", salary_min=100000, limit=10))
    assert [r["page"] for r in requests] == [1, 2, 3]
    assert result.pages_fetched == 3
    assert [p.id for p in result.postings] == ["zulu"]


def test_no_extra_pages_without_filters(monkeypatch):
    requests = []
    _fake_adzuna(monkeypatch, {None: _estimated_page(60)}, count=500, requests=requests)
    asyncio.run(search_jobs("engineer", limit=10))
    assert [r["page"] for r in requests] == [1]


def test_no_extra_pages_when_the_source_is_exhausted(monkeypatch):
    requests = []
    _fake_adzuna(monkeypatch, {None: _estimated_page(5)}, count=5, requests=requests)
    asyncio.run(search_jobs("engineer", salary_min=100000, limit=10))
    assert [r["page"] for r in requests] == [1]


# --- phrase search: "QA lead" means QA leads, not every "lead" -------------

def test_multi_word_query_is_searched_as_a_phrase(monkeypatch):
    requests = []
    _fake_adzuna(monkeypatch, {None: [_job(0, "US")]}, count=100, requests=requests)
    result = asyncio.run(search_jobs("QA lead"))
    assert requests[0]["what_phrase"] == "QA lead"
    assert "what" not in requests[0]
    assert result.match == "phrase"


def test_one_word_query_is_searched_as_a_word(monkeypatch):
    requests = []
    _fake_adzuna(monkeypatch, {None: [_job(0, "US")]}, count=100, requests=requests)
    result = asyncio.run(search_jobs("engineer"))
    assert requests[0]["what"] == "engineer"
    assert result.match == "words"


def test_too_few_phrase_hits_fall_back_to_words(monkeypatch):
    requests = []
    _fake_adzuna(monkeypatch, {None: [_job(0, "US")]}, count=2, requests=requests)
    result = asyncio.run(search_jobs("backend dev lead"))
    assert [("what_phrase" in r, "what" in r) for r in requests] == [(True, False), (False, True)]
    assert result.match == "words"


# --- job type: filtered on what adverts state, the rest counted ------------

def _typed(word, **kw):
    return posting(id=word, title=kw.pop("title", f"Engineer {word}"),
                   description=f"Advert {word}.", location={"display_name": "US"}, **kw)


def test_job_types_from_both_fields_and_the_title():
    assert job_search.job_types(to_posting(_typed("a", contract_time="full_time"))) == {"full_time"}
    assert job_search.job_types(to_posting(_typed("b", contract_type="contract"))) == {"contract"}
    assert job_search.job_types(to_posting(_typed("c", title="QA Lead (W2 Contract)"))) == {"contract"}
    assert job_search.job_types(to_posting(_typed("d", title="QA Lead - C2C"))) == {"contract"}
    both = to_posting(_typed("e", contract_time="full_time", contract_type="contract"))
    assert job_search.job_types(both) == {"full_time", "contract"}
    assert job_search.job_types(to_posting(_typed("f"))) == set()


def test_job_type_filter_counts_what_it_removes(monkeypatch):
    _fake_adzuna(monkeypatch, {None: [
        _typed("alpha", contract_time="full_time"),
        _typed("bravo", title="QA Lead (Contract)"),
        _typed("charlie", contract_time="part_time"),
        _typed("delta"),                        # says nothing
    ]}, count=4)
    result = asyncio.run(search_jobs("engineer", job_type="contract"))
    assert [p.id for p in result.postings] == ["bravo"]
    assert result.excluded_other_type == 2
    assert result.excluded_type_unstated == 1


def test_unknown_job_type_is_refused(monkeypatch):
    _fake_adzuna(monkeypatch, {None: []}, count=0)
    with pytest.raises(ValueError):
        asyncio.run(search_jobs("engineer", job_type="gig"))


def test_posting_reports_its_types():
    got = to_posting(_typed("a", contract_time="full_time", contract_type="permanent")).to_dict()
    assert got["job_types"] == ["full_time", "permanent"]


# --- repeat searches are remembered for a while ----------------------------

def test_identical_search_is_served_from_the_cache(monkeypatch):
    requests = []
    _fake_adzuna(monkeypatch, {None: [_job(0, "US")]}, count=10, requests=requests)
    first = asyncio.run(search_jobs("engineer", max_days_old=7))
    again = asyncio.run(search_jobs("  Engineer ", max_days_old=7))
    other = asyncio.run(search_jobs("engineer", max_days_old=14))
    assert again is first
    assert other is not first
    assert len(requests) == 2
