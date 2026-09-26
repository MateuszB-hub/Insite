"""Career pathway composition.

Answers the question the portal exists for:

    "Doing this kind of work, after N months, what roles open up for me or
     would I qualify for? Looking back, which companies have been hiring,
     and what does it pay?"

Composition order:

  1. O*NET  -- resolve the applicant's role to an occupation, then pull the
               adjacent occupations. This is the "what opens up" answer, and
               it comes from the occupation graph rather than a model's guess.
  2. BLS    -- attach official wage figures to each candidate destination.
  3. Adzuna -- attach live market evidence: who is posting, how many, and the
               advertised salary distribution and trend.
  4. Model  -- optional narrative over the assembled facts. It explains the
               data; it is not the source of it.

`data_sources` on the response records which of those were live, so the UI can
distinguish measured values from scaffolding.
"""

import asyncio
import logging
import os
import time
from typing import Any

from app.services.pathway_narrative import attach_narrative
from app.services.labor import taxonomy
from app.services.labor.onet import OnetFallback
from app.services.labor import (
    LaborDataError,
    Occupation,
    get_market_source,
    get_occupation_source,
    get_wage_source,
    labor_status,
)

logger = logging.getLogger(__name__)

# A local-model narrative costs ~20-25s, so identical queries are cached.
# Deliberately in-process and small: this is a dev-scale cache, not a
# substitute for a real one once there are multiple workers.
CACHE_TTL = float(os.getenv("PATHWAY_CACHE_TTL", "900"))
CACHE_MAX = int(os.getenv("PATHWAY_CACHE_MAX", "128"))
_cache: dict[tuple, tuple[float, dict[str, Any]]] = {}


def _cache_get(key: tuple) -> dict[str, Any] | None:
    hit = _cache.get(key)
    if not hit:
        return None
    stored_at, value = hit
    if time.monotonic() - stored_at > CACHE_TTL:
        _cache.pop(key, None)
        return None
    return value


def _cache_put(key: tuple, value: dict[str, Any]) -> None:
    if len(_cache) >= CACHE_MAX:
        # Drop the oldest entry; ordinary dicts preserve insertion order.
        _cache.pop(next(iter(_cache)), None)
    _cache[key] = (time.monotonic(), value)


def clear_pathway_cache() -> None:
    _cache.clear()

#: Rough mapping from a horizon in months to how far a move can reasonably
#: stretch. O*NET Job Zone difference is the proxy: a year of experience
#: supports a lateral or one-zone move, not a three-zone leap.
def _reachable(horizon_months: int, occupation: Occupation) -> bool:
    if occupation.job_zone is None:
        return True
    if horizon_months >= 24:
        return True
    return occupation.job_zone <= 4


async def _resolve_occupations(source, current_role: str):
    """Resolve the role and its neighbours, degrading to the offline map.

    Returns (current, neighbours, source_actually_used) so `data_sources`
    reports what really answered, not what we hoped would.
    """
    for attempt, candidate in enumerate((source, OnetFallback())):
        try:
            current = await candidate.resolve(current_role)
            if current is None:
                current = Occupation(code="", title=current_role)
            neighbours = await candidate.related(current.code) if current.code else []
            return current, neighbours, candidate
        except Exception as exc:
            if attempt == 0:
                logger.warning(
                    "occupation source %s failed (%s); using offline fallback",
                    getattr(candidate, "name", "?"), exc,
                )
                continue
            logger.warning("offline occupation fallback also failed: %s", exc)

    return Occupation(code="", title=current_role), [], OnetFallback()


async def _market_snapshot(market, current_role: str, current: Occupation, location):
    """Find hiring evidence, widening the query only as far as needed.

    Measured against the live Adzuna API:
      "Senior Backend Software Engineer Fintech" ->      0 postings
      "Senior Backend Software Engineer"         ->    520 postings
      "Software Developers"  (matched SOC title) -> 159,016 postings

    So appending the industry actively destroys the match. We try the specific
    role first because it is the most relevant answer, and fall back to the
    broader occupation title only when the specific query finds nothing.
    `snapshot.query` records which one actually answered, so the UI can say
    what was searched rather than implying a precision we do not have.
    """
    candidates = [current_role]
    if current.title and current.title.lower() != current_role.lower():
        candidates.append(current.title)

    last = None
    for query in candidates:
        try:
            snapshot = await market.snapshot(query, location=location)
        except LaborDataError as exc:
            logger.info("market source unavailable: %s", exc)
            return None
        except Exception as exc:
            logger.warning("market snapshot failed for %r: %s", query, exc)
            continue

        last = snapshot
        if snapshot.total_postings or snapshot.top_employers:
            return snapshot
        logger.info("no market data for %r; widening query", query)

    return last


async def build_career_pathway(
    current_role: str,
    industry: str | None = None,
    horizon_months: int = 12,
    location: str | None = None,
    include_narrative: bool = True,
    provider_name: str | None = None,
) -> dict[str, Any]:
    """Assemble a pathway report from every source that is available.

    Facts are gathered deterministically first. The narrative overlay is added
    last and is strictly optional -- a model failure still yields the facts.
    """
    key = (
        current_role.strip().lower(),
        (industry or "").strip().lower(),
        horizon_months,
        (location or "").strip().lower(),
        include_narrative,
        provider_name or "",
    )
    cached = _cache_get(key)
    if cached is not None:
        logger.info("pathway cache hit for %r", current_role)
        return cached

    occupations = get_occupation_source()
    wages = get_wage_source()
    market = get_market_source()

    # A live occupation source can fail for reasons outside our control: bad
    # credentials, an outage, a rate limit. None of those should take the whole
    # report down, so fall back rather than 502.
    current, neighbours, occupations = await _resolve_occupations(
        occupations, current_role
    )

    neighbours = [occ for occ in neighbours if _reachable(horizon_months, occ)]

    # Wages for the current role and every destination, concurrently.
    async def _wage(occ: Occupation):
        if not occ.code:
            return None
        try:
            return await wages.wages(occ.code, occ.title)
        except LaborDataError:
            return None
        except Exception as exc:
            logger.warning("wage lookup failed for %s: %s", occ.code, exc)
            return None

    wage_results = await asyncio.gather(
        _wage(current), *[_wage(occ) for occ in neighbours]
    )
    current_wage, neighbour_wages = wage_results[0], wage_results[1:]

    snapshot = await _market_snapshot(market, current_role, current, location)

    # "What else do my current skills apply to?" -- a different question from
    # relatedness, and the more useful one for most people: few are choosing
    # between two offers; many want to know where else they already fit.
    transferable = []
    if current.code:
        for match in taxonomy.transferable(current.code, limit=6):
            match_wage = await _wage(Occupation(code=match["soc"], title=match["title"]))
            transferable.append({
                "code": match["soc"],
                "title": match["title"],
                "description": match["description"],
                "similarity": match["similarity"],
                "requires_more_training": match["requires_more_training"],
                "job_zone": match.get("job_zone"),
                "skill_gaps": match["skill_gaps"],
                "wage": _wage_dict(match_wage),
            })

    report = {
        "current_role": current_role,
        "industry": industry,
        "horizon_months": horizon_months,
        "current_occupation": _occ_dict(current, current_wage),
        "pathways": [
            _occ_dict(occ, wage)
            for occ, wage in zip(neighbours, neighbour_wages)
        ],
        "transferable": transferable,
        "hiring": _market_dict(snapshot),
        "data_sources": _status_with(occupations),
        "narrative": None,
        "narrative_status": "not requested",
    }

    if include_narrative:
        report = await attach_narrative(report, provider_name=provider_name)

    _cache_put(key, report)
    return report


def _status_with(occupation_source) -> list[dict[str, Any]]:
    """labor_status(), but reporting the occupation source actually used."""
    rows = labor_status()
    for row in rows:
        if row["capability"] == "occupations":
            row.update(occupation_source.describe())
    return rows


def _wage_dict(wage) -> dict[str, Any] | None:
    if not wage:
        return None
    return {
        "annual_median": wage.annual_median,
        "annual_mean": wage.annual_mean,
        "employment": wage.employment,
        "year": wage.year,
        "area": wage.area,
        "source": wage.source,
    }


def _occ_dict(occ: Occupation, wage) -> dict[str, Any]:
    return {
        "code": occ.code,
        "title": occ.title,
        "description": occ.description,
        "skills": occ.skills,
        "job_zone": occ.job_zone,
        "wage": (
            {
                "annual_median": wage.annual_median,
                "annual_mean": wage.annual_mean,
                "employment": wage.employment,
                "year": wage.year,
                "area": wage.area,
                "source": wage.source,
            }
            if wage
            else None
        ),
    }


def _market_dict(snapshot) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {
        "query": snapshot.query,
        "total_postings": snapshot.total_postings,
        "top_employers": [
            {
                "name": e.name,
                "postings": e.postings,
                "average_salary": e.average_salary,
            }
            for e in snapshot.top_employers
        ],
        "salary_distribution": [
            {"lower": b.lower, "upper": b.upper, "count": b.count}
            for b in snapshot.salary_distribution
        ],
        "salary_history": snapshot.salary_history,
    }
