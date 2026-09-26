"""The pathway cache must not pin a report whose wage lookups failed.

A BLS timeout once got cached, and every later pathway for that role showed
no wages until the entry expired.
"""

import asyncio

import pytest

from app.services import career_service as cs
from app.services.labor import LaborDataError, Occupation
from app.services.labor.base import WageEstimate

CURRENT = Occupation(code="15-1252", title="Software Developers", job_zone=4)
NEIGHBOUR = Occupation(code="15-1251", title="Computer Programmers", job_zone=4)


class FakeWages:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    async def wages(self, code, title):
        self.calls += 1
        if self.error:
            raise self.error
        return WageEstimate(occupation_code=code, occupation_title=title,
                            source="BLS OEWS", annual_median=135980.0)


@pytest.fixture
def pathway(monkeypatch):
    """Patch every outside source; return a function that builds a pathway."""
    cs.clear_pathway_cache()

    async def resolve(source, role, occupation_code=None):
        return CURRENT, [NEIGHBOUR], source

    async def no_market(*args, **kwargs):
        return None

    monkeypatch.setattr(cs, "_resolve_occupations", resolve)
    monkeypatch.setattr(cs, "_market_snapshot", no_market)
    monkeypatch.setattr(cs, "get_occupation_source", lambda: None)
    monkeypatch.setattr(cs, "get_market_source", lambda: None)
    monkeypatch.setattr(cs, "_status_with", lambda source: [])
    monkeypatch.setattr(cs.taxonomy, "transferable", lambda code, limit=6: [])

    def build(wages: FakeWages):
        monkeypatch.setattr(cs, "get_wage_source", lambda: wages)
        return asyncio.run(cs.build_career_pathway(
            "Software Engineer", include_narrative=False))

    yield build
    cs.clear_pathway_cache()


def test_good_report_is_cached(pathway):
    wages = FakeWages()
    first = pathway(wages)
    assert first["current_occupation"]["wage"]["annual_median"] == 135980.0
    pathway(wages)
    assert wages.calls == 2  # current + neighbour, once -- second was a hit


def test_report_with_failed_wage_lookup_is_not_cached(pathway):
    first = pathway(FakeWages(error=TimeoutError()))
    assert first["current_occupation"]["wage"] is None

    # BLS recovers: the next request must fetch again and show wages.
    second = pathway(FakeWages())
    assert second["current_occupation"]["wage"]["annual_median"] == 135980.0


def test_wages_not_configured_is_still_cached(pathway):
    # No BLS key is a steady state, not a blip: caching it is fine.
    wages = FakeWages(error=LaborDataError("BLS_API_KEY not set"))
    pathway(wages)
    pathway(wages)
    assert wages.calls == 2
