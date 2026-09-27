"""One way to call Adzuna: paced, retried, and logged with the real reason.

A three-city search used to fire every request at once -- one per city,
plus spelling variants and loose matches when title matches ran short --
and the free plan's rate limit refused some ("Couldn't search Seattle, New
York just now"). The log only said "HTTPStatusError", so the cause couldn't
even be confirmed. Now:

  * at most ADZUNA_CONCURRENCY requests (default 2) are in flight at once,
    per event loop, across every search on the site;
  * a refusal (429) or a brief server fault (500/502/503/504) is retried,
    up to 3 attempts, waiting as long as Adzuna asks (Retry-After, capped)
    or a short, growing pause; real errors (401, 400) are not retried;
  * failures are logged by status code, never by URL -- the URL carries
    the API key.
"""

import asyncio
import logging
import os
import weakref
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CONCURRENCY = int(os.getenv("ADZUNA_CONCURRENCY", "2"))
ATTEMPTS = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_WAIT_S = 5.0

#: How to pause between attempts (tests make it instant).
_sleep = asyncio.sleep

#: One gate per event loop: asyncio primitives belong to the loop that first
#: uses them (the server has one; tests make a new one each time).
_gates: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary())


def _gate() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    gate = _gates.get(loop)
    if gate is None:
        gate = _gates[loop] = asyncio.Semaphore(CONCURRENCY)
    return gate


def describe(exc: BaseException) -> str:
    """A safe, useful one-line reason: '429 Too Many Requests', 'ReadTimeout'."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{exc.response.status_code} {exc.response.reason_phrase}".strip()
    return type(exc).__name__


def _wait(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        try:
            return min(float(response.headers.get("Retry-After", "")), MAX_WAIT_S)
        except ValueError:
            pass
    return min(0.8 * (attempt + 1), MAX_WAIT_S)


async def get_json(client: httpx.AsyncClient, url: str, params: dict[str, Any],
                   attempts: int = ATTEMPTS) -> dict[str, Any]:
    last: BaseException | None = None
    for attempt in range(attempts):
        response = None
        async with _gate():
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in RETRY_STATUSES:
                    raise
                last = exc
            except httpx.TransportError as exc:
                last = exc
        if attempt < attempts - 1:
            wait = _wait(response, attempt)
            logger.info("adzuna %s; retrying in %.1fs", describe(last), wait)
            await _sleep(wait)
    assert last is not None
    raise last
