"""Paid search is cached so repeat reports do not burn credits."""

import asyncio

import pytest

from app.services import search_service as ss


@pytest.fixture
def tavily(monkeypatch):
    calls = []

    async def fake(query):
        calls.append(query)
        return [{"title": "t", "content": "c", "source": "s", "url": "u"}]

    monkeypatch.setattr(ss, "SEARCH_PROVIDER", "tavily")
    monkeypatch.setattr(ss, "_tavily_search", fake)
    monkeypatch.setattr(ss, "_search_cache", {})
    return calls


def run(industry="Healthcare"):
    return asyncio.run(ss.search_industry_trends(industry))


def test_repeat_report_is_served_from_cache(tavily):
    first, second = run(), run()
    assert len(tavily) == 3  # three queries, billed once
    assert first == second


def test_cache_expires(tavily, monkeypatch):
    run()
    monkeypatch.setattr(ss, "SEARCH_CACHE_TTL", -1)
    run()
    assert len(tavily) == 6


def test_failures_are_not_cached(monkeypatch):
    calls = []

    async def flaky(query):
        calls.append(query)
        raise RuntimeError("503")

    monkeypatch.setattr(ss, "SEARCH_PROVIDER", "tavily")
    monkeypatch.setattr(ss, "_tavily_search", flaky)
    monkeypatch.setattr(ss, "_search_cache", {})
    run(), run()
    assert len(calls) == 6  # retried on the second report, not stuck on mock


def test_default_depth_is_the_one_credit_tier():
    assert ss.TAVILY_SEARCH_DEPTH == "basic"
