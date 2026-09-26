"""Web search layer.

Providers, in order of how much they cost and how reliable they are:

  mock    -- deterministic stand-ins. No network, no key. Default.
  ddg     -- DuckDuckGo via the `ddgs` package. Free, no key, but it is a
             SCRAPER, not an API: DuckDuckGo publishes no search API and no
             rate limits. Measured here at ~8% failure under a 12-query burst
             from one residential IP with no concurrency. Fine for local dev
             and demos; not something to put in front of real applicants.
  tavily  -- paid API built for LLM consumption. The production path.

Every provider returns the same normalized finding dict, so the synthesis
layer never changes.
"""

import asyncio
import logging
import os
import random
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "mock").strip().lower()

# DuckDuckGo throttles aggressively. Serialize queries and space them out
# rather than firing the whole fan-out at once.
DDG_MIN_INTERVAL = float(os.getenv("DDG_MIN_INTERVAL", "1.5"))
DDG_MAX_RETRIES = int(os.getenv("DDG_MAX_RETRIES", "3"))
DDG_RESULTS_PER_QUERY = int(os.getenv("DDG_RESULTS_PER_QUERY", "5"))
# `ddgs` bundles ~17 engines and, left unset, fans out across Google, Bing,
# Brave, Yandex and others -- scraping search engines you did not choose, some
# of which return 429/captcha. Pin to DuckDuckGo so behaviour matches the name.
# Set to "auto" to allow the full fan-out (more resilient, far more dubious).
DDG_BACKEND = os.getenv("DDG_BACKEND", "duckduckgo")

# Tavily bills per search: "basic" is 1 credit, "advanced" 2. A report runs
# 3-5 queries, so basic gets ~200 reports/month from the 1,000 free credits
# instead of ~100. Basic returns shorter content chunks, which is plenty for
# a trends summary.
TAVILY_SEARCH_DEPTH = os.getenv("TAVILY_SEARCH_DEPTH", "basic").strip().lower()

# Industry-trend results barely move within a day, and every repeat query is
# a billed credit. In-process, like the pathway cache: fine for the single
# worker we run; move to Postgres before scaling out (see TODO.md).
SEARCH_CACHE_TTL = float(os.getenv("SEARCH_CACHE_TTL_SECONDS", str(24 * 3600)))
_search_cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}

# Module-level lock: one outbound DDG query at a time per process.
_ddg_lock = asyncio.Lock()
_ddg_last_call = 0.0


async def search_industry_trends(
    industry: str,
    job_title: str | None = None,
) -> list[dict[str, Any]]:
    """Run the query fan-out for an industry and return flattened findings."""
    queries = build_queries(industry, job_title)

    if SEARCH_PROVIDER == "tavily":
        runner = _tavily_search
    elif SEARCH_PROVIDER in ("ddg", "duckduckgo"):
        runner = _ddg_search
    else:
        runner = _mock_search

    results: list[dict[str, Any]] = []
    for query in queries:
        key = (SEARCH_PROVIDER, query.lower())
        cached = _search_cache.get(key)
        if cached and time.monotonic() - cached[0] < SEARCH_CACHE_TTL:
            results.extend(cached[1])
            continue
        try:
            found = await runner(query)
            if found and runner is not _mock_search:
                _search_cache[key] = (time.monotonic(), found)
            results.extend(found)
        except Exception as exc:
            # One dead query should not sink the whole report.
            logger.warning("search failed for %r: %s", query, exc)

    if not results and SEARCH_PROVIDER != "mock":
        logger.warning(
            "search provider %r returned nothing; falling back to mock findings",
            SEARCH_PROVIDER,
        )
        for query in queries:
            results.extend(await _mock_search(query))

    return results


def build_queries(industry: str, job_title: str | None = None) -> list[str]:
    """Generate the search queries used to cover an industry."""
    queries = [
        f"{industry} industry trends",
        f"future of work in {industry}",
        f"{industry} emerging technologies and automation",
    ]
    if job_title:
        queries.append(f"{job_title} role evolution in {industry}")
        queries.append(f"{job_title} skills in demand {industry}")
    return queries


async def _mock_search(query: str) -> list[dict[str, Any]]:
    """Placeholder search. One normalized finding per query, no network."""
    return [
        {
            "title": f"Findings for: {query}",
            "content": (
                f"Placeholder result for '{query}'. Real search results will "
                "carry article text about workforce dynamics, technology "
                "adoption and shifting skill requirements."
            ),
            "source": "Mock Search Provider",
            "url": f"https://example.com/search?q={query.replace(' ', '+')}",
        }
    ]


async def _ddg_search(query: str) -> list[dict[str, Any]]:
    """DuckDuckGo via `ddgs`.

    Serialized and paced behind a lock, with backoff on throttling. `ddgs` is
    synchronous, so the blocking call goes to a worker thread to avoid
    stalling the event loop.
    """
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise RuntimeError(
            "SEARCH_PROVIDER=ddg but the `ddgs` package is not installed"
        ) from exc

    global _ddg_last_call

    def _blocking() -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"max_results": DDG_RESULTS_PER_QUERY}
        if DDG_BACKEND and DDG_BACKEND != "auto":
            kwargs["backend"] = DDG_BACKEND
        with DDGS() as ddgs:
            return list(ddgs.text(query, **kwargs))

    last_error: Exception | None = None

    for attempt in range(DDG_MAX_RETRIES):
        async with _ddg_lock:
            # Space calls out; DuckDuckGo blocks on burst, not on volume.
            elapsed = asyncio.get_running_loop().time() - _ddg_last_call
            if elapsed < DDG_MIN_INTERVAL:
                await asyncio.sleep(DDG_MIN_INTERVAL - elapsed)
            try:
                rows = await asyncio.to_thread(_blocking)
                _ddg_last_call = asyncio.get_running_loop().time()
            except Exception as exc:
                _ddg_last_call = asyncio.get_running_loop().time()
                last_error = exc
                rows = None

        if rows is not None:
            return [
                {
                    "title": r.get("title", ""),
                    "content": r.get("body", ""),
                    "source": r.get("title", "DuckDuckGo"),
                    "url": r.get("href", ""),
                }
                for r in rows
            ]

        # Exponential backoff with jitter before the next attempt.
        backoff = (2**attempt) + random.uniform(0, 1)
        logger.info(
            "ddg attempt %d/%d failed (%s); retrying in %.1fs",
            attempt + 1, DDG_MAX_RETRIES, last_error, backoff,
        )
        await asyncio.sleep(backoff)

    raise RuntimeError(f"DuckDuckGo failed after {DDG_MAX_RETRIES} attempts: {last_error}")


async def _tavily_search(query: str) -> list[dict[str, Any]]:
    """Real search via Tavily. Requires TAVILY_API_KEY."""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("SEARCH_PROVIDER=tavily but TAVILY_API_KEY is not set")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.tavily.com/search",
            # Header, not body: request bodies end up in more debugging
            # output than auth headers do.
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "query": query,
                "search_depth": TAVILY_SEARCH_DEPTH,
                "max_results": 5,
            },
        )
        response.raise_for_status()
        data = response.json()

    return [
        {
            "title": item.get("title", ""),
            "content": item.get("content", ""),
            "source": item.get("title", ""),
            "url": item.get("url", ""),
        }
        for item in data.get("results", [])
    ]
