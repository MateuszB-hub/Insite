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
import copy
import dataclasses
import logging
import os
import time
from typing import Any

from app.services.pathway_narrative import attach_narrative
from app.services.labor import learning, taxonomy
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
    if time.time() - stored_at > CACHE_TTL:
        _cache.pop(key, None)
        return None
    return value


def _cache_put(key: tuple, value: dict[str, Any]) -> None:
    if len(_cache) >= CACHE_MAX:
        # Drop the oldest entry; ordinary dicts preserve insertion order.
        _cache.pop(next(iter(_cache)), None)
    # Wall-clock, not monotonic: macOS pauses the monotonic clock while the
    # machine sleeps, which kept entries "fresh" for hours on the dev Mac.
    _cache[key] = (time.time(), value)


def clear_pathway_cache() -> None:
    _cache.clear()


def _pathway_key(current_role, industry, horizon_months, location,
                 include_narrative, provider_name, occupation_code=None) -> tuple:
    return (
        current_role.strip().lower(),
        (industry or "").strip().lower(),
        horizon_months,
        (location or "").strip().lower(),
        include_narrative,
        provider_name or "",
        occupation_code or "",
    )

#: Rough mapping from a horizon in months to how far a move can reasonably
#: stretch. O*NET Job Zone difference is the proxy: a year of experience
#: supports a lateral or one-zone move, not a three-zone leap.
def _reachable(horizon_months: int, occupation: Occupation) -> bool:
    if occupation.job_zone is None:
        return True
    if horizon_months >= 24:
        return True
    return occupation.job_zone <= 4


def _with_job_zone(occ: Occupation) -> Occupation:
    """Fill a missing O*NET Job Zone from the vendored taxonomy.

    Live O*NET "related" results carry no zone, and without one both the
    horizon filter and the readiness badge are guesses.
    """
    if occ.job_zone is not None or not occ.code:
        return occ
    entry = taxonomy.get(occ.code)
    zone = entry.get("job_zone") if entry else None
    return dataclasses.replace(occ, job_zone=zone) if zone is not None else occ


#: Skill shortfall (see taxonomy.skill_shortfall) that still counts as
#: ready / a stretch. Calibrated on real pairs: LPN from RN, bookkeeper from
#: accountant, tutor from teacher all 0; middle-school from secondary teacher
#: 1.4; sales manager from marketing manager 0.6, nurse practitioner from RN
#: 1.3 (the zone step makes that one a stretch); financial manager from
#: accountant 3.6; health services manager from RN 6.6, retail supervisor
#: from salesperson 12.8. O*NET skill levels do not capture seniority or
#: licensing, which is why the Job Zone check runs alongside.
READY_SHORTFALL = 2.0
STRETCH_SHORTFALL = 5.0

_SEVERITY = {"ready": 0, "stretch": 1, "long-term": 2}


def readiness(current: Occupation, target: Occupation, horizon_months: int) -> str | None:
    """Ready now / stretch / longer term, from O*NET data -- no model involved.

    Two independent signals, and the more demanding one wins:
      * Job Zone step (the level of preparation; zone 4 ~ a bachelor's,
        5 ~ a graduate degree): two levels up is longer term, one level up a
        stretch -- or longer term when the horizon is under a year.
      * Skill shortfall: how far the target's skill levels exceed the
        person's current role, which is what separates a sideways move from
        a promotion at the same zone (accountant to financial manager).
    Unknown on both counts: no badge rather than a guess.
    """
    by_zone = None
    if current.job_zone is not None and target.job_zone is not None:
        step = target.job_zone - current.job_zone
        if step >= 2:
            by_zone = "long-term"
        elif step == 1:
            by_zone = "stretch" if horizon_months >= 12 else "long-term"
        else:
            by_zone = "ready"

    by_skills = None
    shortfall = taxonomy.skill_shortfall(current.code, target.code) if current.code else None
    if shortfall is not None:
        if shortfall < READY_SHORTFALL:
            by_skills = "ready"
        elif shortfall < STRETCH_SHORTFALL:
            by_skills = "stretch"
        else:
            by_skills = "long-term"

    known = [r for r in (by_zone, by_skills) if r is not None]
    return max(known, key=_SEVERITY.__getitem__) if known else None


async def _resolve_occupations(source, current_role: str, occupation_code: str | None = None):
    """Resolve the role and its neighbours, degrading to the offline map.

    `occupation_code` is the person's own choice when the title was
    ambiguous ("QA lead": software QA, not materials inspection); it wins
    over any guess from the title.

    Returns (current, neighbours, source_actually_used) so `data_sources`
    reports what really answered, not what we hoped would.
    """
    chosen = taxonomy.get(occupation_code) if occupation_code else None
    for attempt, candidate in enumerate((source, OnetFallback())):
        try:
            if chosen is not None:
                current = Occupation(code=chosen["soc"], title=chosen["title"],
                                     description=chosen["description"],
                                     job_zone=chosen.get("job_zone"))
            else:
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


def _title_choices(current_role: str, current: Occupation, *, chosen: bool) -> dict[str, Any]:
    """Other occupations the typed title could mean, and whether to ask.

    The pathway is built for the best match straight away; when the data
    says the title is genuinely ambiguous, the page asks which one is meant
    (mentor: "QA lead" can be software QA or checking parts as they arrive).
    Once the person has picked, it doesn't ask again.
    """
    found = taxonomy.candidates(current_role, limit=6)
    alternatives = [
        {
            "code": c["soc"], "title": c["title"], "description": c["description"],
            "employment": c.get("employment"), "via": c.get("via"),
        }
        for c in found if c["soc"] != current.code
    ][:4]
    top = next((c for c in found if c["soc"] == current.code), None)
    return {
        "alternatives": alternatives,
        "ambiguous": (not chosen) and taxonomy.is_ambiguous(found),
        "matched_via": (f'{top["match"]}: "{top["via"]}"' if top and top.get("via") else None),
    }


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
    occupation_code: str | None = None,
) -> dict[str, Any]:
    """Assemble a pathway report from every source that is available.

    Facts are gathered deterministically first. The narrative overlay is added
    last and is strictly optional -- a model failure still yields the facts.
    """
    key = _pathway_key(current_role, industry, horizon_months, location,
                       include_narrative, provider_name, occupation_code)
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
        occupations, current_role, occupation_code
    )

    current = _with_job_zone(current)
    neighbours = [_with_job_zone(occ) for occ in neighbours]
    neighbours = [occ for occ in neighbours if _reachable(horizon_months, occ)]

    # Wages for the current role and every destination, concurrently.
    # An unexpected failure (usually a BLS timeout) is transient, so a report
    # that hit one is not cached -- otherwise wages vanish until the TTL ends.
    wage_failed = False

    async def _wage(occ: Occupation):
        nonlocal wage_failed
        if not occ.code:
            return None
        try:
            return await wages.wages(occ.code, occ.title)
        except LaborDataError:
            return None
        except Exception as exc:
            wage_failed = True
            logger.warning("wage lookup failed for %s: %r", occ.code, exc)
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
                # Same rule as the pathway list, so one page never gives
                # two answers for the same occupation.
                "readiness": readiness(
                    current,
                    Occupation(code=match["soc"], title=match["title"],
                               job_zone=match.get("job_zone")),
                    horizon_months,
                ),
                "job_zone": match.get("job_zone"),
                "skill_gaps": match["skill_gaps"],
                "training": learning.training(match.get("job_zone")),
                "links": learning.links(match["soc"], match.get("onet"), match["title"]),
                "wage": _wage_dict(match_wage),
            })

    report = {
        "current_role": current_role,
        "industry": industry,
        "horizon_months": horizon_months,
        "current_occupation": _occ_dict(current, current_wage),
        "pathways": [
            {
                **_occ_dict(occ, wage),
                "readiness": readiness(current, occ, horizon_months),
                **_specifics(current, current_wage, occ, wage),
            }
            for occ, wage in zip(neighbours, neighbour_wages)
        ],
        "transferable": transferable,
        "hiring": _market_dict(snapshot),
        "data_sources": _status_with(occupations),
        **_title_choices(current_role, current, chosen=bool(occupation_code)),
        "narrative": None,
        "narrative_status": "not requested",
    }

    if include_narrative:
        report = await attach_narrative(report, provider_name=provider_name)

    if not wage_failed:
        _cache_put(key, report)
    return report


async def narrate_career_pathway(
    current_role: str,
    industry: str | None = None,
    horizon_months: int = 12,
    location: str | None = None,
    provider_name: str | None = None,
    occupation_code: str | None = None,
) -> dict[str, Any]:
    """The model-written layer, requested after the facts are on screen.

    The facts come from the cache the first request just filled, so this
    costs only the model call. The cached facts are never modified, and the
    narrated report shares its cache entry with include_narrative=True.
    """
    key = _pathway_key(current_role, industry, horizon_months, location,
                       True, provider_name, occupation_code)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    facts = await build_career_pathway(
        current_role=current_role,
        industry=industry,
        horizon_months=horizon_months,
        location=location,
        include_narrative=False,
        occupation_code=occupation_code,
    )
    report = await attach_narrative(copy.deepcopy(facts), provider_name=provider_name)
    # A failed model call is worth retrying, so only a finished summary is kept.
    if report.get("narrative"):
        _cache_put(key, report)
    return report


def _specifics(current: Occupation, current_wage, occ: Occupation, wage) -> dict[str, Any]:
    """What a move to `occ` means in facts: pay, training, skills, where to learn.

    Replaces the model's per-role prose, which testers found generic and which
    could contradict the readiness badge beside it.
    """
    pay_change = None
    if (current_wage and wage and current_wage.annual_median is not None
            and wage.annual_median is not None):
        pay_change = wage.annual_median - current_wage.annual_median
    return {
        "pay_change": pay_change,
        "training": learning.training(occ.job_zone),
        "skill_gaps": taxonomy.skill_gaps(current.code, occ.code) if current.code else [],
        "links": learning.links(occ.code, taxonomy.onet_code(occ.code), occ.title),
    }


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
