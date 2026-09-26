"""Job-title abbreviations learned from O*NET titles, and their use in search."""

import asyncio

import httpx
import pytest

from app.services import job_search
from app.services.labor import abbreviations as ab


def test_pairs_teach_acronyms_whose_letters_match():
    pairs = ab.pairs_from_titles([
        ("Quality Assurance Analyst (QA Analyst)", "QA Analyst"),
        ("Registered Nurse (RN)", "RN"),
        ("CEO (Chief Executive Officer)", ""),
        ("Agency Owner", "n/a"),
        ("Head Chef (Chef)", ""),          # paraphrase, not an abbreviation
    ])
    table = ab.derive(pairs)
    assert table["qa"] == ["quality assurance"]
    assert table["rn"] == ["registered nurse"]
    assert table["ceo"] == ["chief executive officer"]
    assert "chef" not in table


def test_most_attested_meaning_comes_first():
    table = ab.derive([
        ("Project Manager Lead", "PM Lead"),
        ("Project Manager Assistant", "PM Assistant"),
        ("Preventive Maintenance Tech", "PM Tech"),
    ])
    assert table["pm"] == ["project manager", "preventive maintenance"]


@pytest.fixture
def table(monkeypatch):
    data = {
        "qa": ["quality assurance"],
        "rn": ["registered nurse", "registered nursing"],
        "pm": ["project manager", "preventive maintenance"],
    }
    monkeypatch.setattr(ab, "_table", lambda: data)
    ab._reverse.cache_clear()
    yield
    ab._reverse.cache_clear()


def test_variants_spell_out_and_abbreviate(table):
    assert ab.variants("QA lead") == ["quality assurance lead"]
    assert ab.variants("registered nurse") == ["rn"]
    assert ab.variants("welder") == []


def test_ambiguous_acronyms_are_spelled_out_but_never_used_as_a_short_form(table):
    # "project manager" -> "PM" would also find preventive-maintenance jobs.
    assert ab.variants("project manager") == []
    assert ab.variants("PM") == ["project manager", "preventive maintenance"]


def test_english_words_are_not_acronyms(monkeypatch):
    monkeypatch.setattr(ab, "_table", lambda: {"it": ["information technology"]})
    ab._reverse.cache_clear()
    assert ab.variants("IT support") == []
    ab._reverse.cache_clear()


# --- search: variants only when title matches run short --------------------

def _serve(monkeypatch, by_title, count_for):
    requests = []
    real = httpx.AsyncClient

    def handler(request):
        params = dict(request.url.params)
        requests.append(params)
        key = params.get("title_only") or params.get("what")
        results = by_title.get(key, [])
        return httpx.Response(200, json={"count": count_for(key, results), "results": results})

    monkeypatch.setattr(job_search.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(job_search, "_record_sightings", lambda postings: {})
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    job_search.clear_search_cache()
    return requests


def _ad(i, title):
    return {"id": str(i), "title": title, "description": f"Advert number {title}.",
            "location": {"display_name": "Dallas"}, "company": {"display_name": "Acme"},
            "redirect_url": "https://x"}


def test_short_title_matches_also_search_the_spelled_out_form(monkeypatch, table):
    requests = _serve(monkeypatch, {
        "QA lead": [_ad(1, "QA Lead")],
        "quality assurance lead": [_ad(2, "Quality Assurance Lead")],
    }, lambda key, results: len(results))
    result = asyncio.run(job_search.search_jobs("QA lead", ["Dallas"], limit=5))
    assert [r.get("title_only") for r in requests][:2] == ["QA lead", "quality assurance lead"]
    # Both spellings land in the main results, as title matches.
    assert sorted(p.title for p in result.postings) == ["QA Lead", "Quality Assurance Lead"]
    assert result.also_searched == ["quality assurance lead"]


def test_well_served_search_tries_no_variants(monkeypatch, table):
    requests = _serve(monkeypatch, {
        "QA lead": [_ad(i, f"QA Lead {w}") for i, w in enumerate(["alpha", "bravo", "charlie"])],
    }, lambda key, results: 500)
    result = asyncio.run(job_search.search_jobs("QA lead", limit=3))
    assert len(requests) == 1
    assert result.also_searched == []
