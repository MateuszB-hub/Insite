"""Adzuna calls are paced, retried on refusals, and logged with the reason.

Live: "Couldn't search Seattle, New York just now" -- a three-city search sent
every request at once and the free plan's rate limit refused some.
"""

import asyncio

import httpx
import pytest

from app.services.labor import adzuna_http


@pytest.fixture(autouse=True)
def instant_waits(monkeypatch):
    waits = []

    async def sleep(seconds):
        waits.append(seconds)
    monkeypatch.setattr(adzuna_http, "_sleep", sleep)
    return waits


def serve(responses):
    """A client whose Nth request gets responses[N] (a status or an exception)."""
    calls = []

    def handler(request):
        item = responses[min(len(calls), len(responses) - 1)]
        calls.append(request)
        if isinstance(item, Exception):
            raise item
        status, headers = item if isinstance(item, tuple) else (item, {})
        return httpx.Response(status, json={"results": [], "count": 7}, headers=headers)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


def get(client):
    async def run():
        async with client:
            return await adzuna_http.get_json(client, "https://api.adzuna.test/x", {"q": "a"})
    return asyncio.run(run())


def test_a_refusal_is_retried_waiting_as_asked(instant_waits):
    client, calls = serve([(429, {"Retry-After": "2"}), 200])
    assert get(client)["count"] == 7
    assert len(calls) == 2
    assert instant_waits == [2.0]


def test_brief_server_faults_are_retried():
    client, calls = serve([503, 502, 200])
    assert get(client)["count"] == 7
    assert len(calls) == 3


def test_gives_up_after_three_and_says_why():
    client, calls = serve([429])
    with pytest.raises(httpx.HTTPStatusError) as exc:
        get(client)
    assert len(calls) == 3
    assert adzuna_http.describe(exc.value) == "429 Too Many Requests"


def test_real_errors_are_not_retried():
    client, calls = serve([401])
    with pytest.raises(httpx.HTTPStatusError):
        get(client)
    assert len(calls) == 1


def test_a_dropped_connection_is_retried():
    client, calls = serve([httpx.ConnectError("reset"), 200])
    assert get(client)["count"] == 7
    assert len(calls) == 2


def test_never_more_than_two_in_flight(monkeypatch):
    in_flight = peak = 0

    async def handler(request):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return httpx.Response(200, json={"results": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await asyncio.gather(*(adzuna_http.get_json(client, "https://api.adzuna.test/x", {})
                                   for _ in range(6)))

    asyncio.run(run())
    assert peak == adzuna_http.CONCURRENCY == 2
