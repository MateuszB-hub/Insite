"""Adzuna -- live postings, top hiring companies, salary distribution/history.

This is the source that answers the look-back half of the question directly:

  /jobs/{country}/top_companies  -> biggest hirers for a keyword
  /jobs/{country}/histogram      -> salary distribution for a keyword
  /jobs/{country}/history        -> average advertised salary over time

Free tier after registration (app id + key).

    https://developer.adzuna.com/  (registration)
"""

import asyncio
import logging
import os
import re

import httpx

from .base import (
    Employer,
    LaborDataError,
    MarketSnapshot,
    MarketSource,
    SalaryBand,
)

logger = logging.getLogger(__name__)


def _redact(text: str) -> str:
    """Strip credentials from anything we log.

    Adzuna takes app_id/app_key as query parameters, and httpx puts the full
    URL into its exception messages. Logging one raw would write the key to
    disk, so every error string passes through here first.
    """
    return re.sub(r"(app_id|app_key)=[^&\s]+", r"\1=REDACTED", str(text))

BASE_URL = "https://api.adzuna.com/v1/api"
COUNTRY = os.getenv("ADZUNA_COUNTRY", "us")


class AdzunaSource(MarketSource):
    name = "adzuna"
    label = "Adzuna"
    signup_url = "https://developer.adzuna.com/"

    def __init__(self) -> None:
        self.app_id = os.getenv("ADZUNA_APP_ID", "")
        self.app_key = os.getenv("ADZUNA_APP_KEY", "")
        self.country = COUNTRY

    def configured(self) -> tuple[bool, str | None]:
        if not (self.app_id and self.app_key):
            return False, "ADZUNA_APP_ID / ADZUNA_APP_KEY not set"
        return True, None

    def _auth(self) -> dict[str, str]:
        return {"app_id": self.app_id, "app_key": self.app_key}

    async def _get(self, path: str, params: dict, attempts: int = 3) -> dict:
        """GET with a short retry.

        Adzuna returns transient 503s on endpoints that succeed moments later
        (observed: top_companies failed once, then succeeded three times in a
        row). Retrying briefly turns a flaky endpoint into a reliable one.
        """
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(
                        f"{BASE_URL}{path}", params={**self._auth(), **params}
                    )
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as exc:
                last = exc
                # Only retry server-side faults; a 401 will never fix itself.
                if exc.response.status_code < 500:
                    raise
            except httpx.HTTPError as exc:
                last = exc
            if attempt < attempts - 1:
                await asyncio.sleep(0.6 * (attempt + 1))
        raise last if last else RuntimeError("adzuna request failed")

    async def snapshot(self, query: str, location: str | None = None) -> MarketSnapshot:
        ok, reason = self.configured()
        if not ok:
            raise LaborDataError(reason or "Adzuna not configured")

        snapshot = MarketSnapshot(query=query)
        base_params: dict[str, str] = {"what": query}
        if location:
            base_params["where"] = location

        # Each endpoint is optional -- a failure in one should not lose the rest.
        try:
            top = await self._get(f"/jobs/{self.country}/top_companies", base_params)
            for row in (top.get("leaderboard") or [])[:10]:
                snapshot.top_employers.append(
                    Employer(
                        name=row.get("canonical_name") or row.get("display_name", ""),
                        postings=int(row.get("count", 0) or 0),
                        average_salary=row.get("average_salary"),
                    )
                )
        except Exception as exc:
            logger.warning("adzuna top_companies failed: %s", _redact(exc))

        try:
            hist = await self._get(f"/jobs/{self.country}/histogram", base_params)
            buckets = hist.get("histogram") or {}
            edges = sorted(int(k) for k in buckets)
            for i, lower in enumerate(edges):
                upper = edges[i + 1] if i + 1 < len(edges) else None
                snapshot.salary_distribution.append(
                    SalaryBand(
                        lower=float(lower),
                        upper=float(upper) if upper is not None else None,
                        count=int(buckets[str(lower)]),
                    )
                )
        except Exception as exc:
            logger.warning("adzuna histogram failed: %s", _redact(exc))

        try:
            history = await self._get(f"/jobs/{self.country}/history", base_params)
            snapshot.salary_history = {
                month: float(value)
                for month, value in (history.get("month") or {}).items()
            }
        except Exception as exc:
            logger.warning("adzuna history failed: %s", _redact(exc))

        try:
            search = await self._get(
                f"/jobs/{self.country}/search/1", {**base_params, "results_per_page": "1"}
            )
            snapshot.total_postings = search.get("count")
        except Exception as exc:
            logger.warning("adzuna search count failed: %s", _redact(exc))

        return snapshot


class AdzunaFallback(MarketSource):
    """Empty snapshot rather than invented employers.

    Naming companies that are not actually hiring would be worse than saying
    nothing, so the fallback returns structure with no rows.
    """

    name = "adzuna"
    label = "Adzuna (not configured)"
    signup_url = "https://developer.adzuna.com/"

    def configured(self) -> tuple[bool, str | None]:
        return False, "ADZUNA_APP_ID / ADZUNA_APP_KEY not set; hiring data omitted"

    async def snapshot(self, query: str, location: str | None = None) -> MarketSnapshot:
        return MarketSnapshot(query=query)


def get_market_source() -> MarketSource:
    live = AdzunaSource()
    return live if live.live else AdzunaFallback()
