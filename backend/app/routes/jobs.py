"""Job search with honest provenance."""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.deps import CurrentUser
from app.services.job_search import MAX_LOCATIONS, normalize_locations, search_jobs

logger = logging.getLogger(__name__)
router = APIRouter()


class JobOut(BaseModel):
    id: str
    title: str
    company: str | None = None
    location: str | None = None
    url: str
    created: str | None = None
    contract_time: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    #: "stated" (employer said so) | "estimated" (aggregator guessed) | "absent"
    salary_source: str
    #: "remote" | "conflicted" | "onsite" | "unknown"
    remote_claim: str
    #: Why a claim was judged conflicted, in plain English.
    remote_note: str | None = None
    #: Identical adverts share a fingerprint.
    fingerprint: str = ""
    #: How many identical adverts this entry stands for.
    duplicate_count: int = 1
    duplicate_locations: list[str] = []
    #: When we first saw this text, whatever date the advert claims.
    first_seen: str | None = None
    is_repost: bool = False


class JobSearchResponse(BaseModel):
    postings: list[JobOut]
    total_available: int | None = None
    #: What the honest filters removed, so a short list can be explained
    #: rather than looking like a broken search.
    excluded_estimated_salary: int = 0
    excluded_no_salary: int = 0
    excluded_not_remote: int = 0
    excluded_below_salary: int = 0
    #: Adverts folded into another row because the text was identical.
    collapsed_duplicates: int = 0
    locations_searched: list[str] = []
    #: With a salary floor: jobs whose pay was ESTIMATED by the job board at or
    #: above it. Kept apart from `postings` so they are never mistaken for
    #: employer-stated matches.
    estimated_matches: list[JobOut] = []
    pages_fetched: int = 0
    #: Places whose lookup failed; results for the others are still shown.
    failed_locations: list[str] = []


@router.get("/jobs/search", response_model=JobSearchResponse)
async def job_search(
    user: CurrentUser,
    q: str = Query(..., min_length=1, max_length=200),
    # Repeat the parameter for several places: ?where=Austin&where=Denver
    where: list[str] = Query([]),
    salary_min: float | None = Query(None, ge=0, le=10_000_000),
    require_stated_salary: bool = Query(False),
    remote_only: bool = Query(False),
    include_conflicted_remote: bool = Query(False),
    # Adverts older than about a week are usually already filled (tester
    # feedback); the UI defaults to 7. Omit for any age.
    max_days_old: int | None = Query(None, ge=1, le=365),
    limit: int = Query(30, ge=1, le=50),
):
    """Search postings, keeping every provenance signal intact.

    A salary floor only ever admits employer-stated figures, so the filter
    means what the user thinks it means. Remote claims are judged against the
    location the posting actually names.
    """
    if any(len(place) > 120 for place in where):
        raise HTTPException(422, "Each location must be 120 characters or fewer.")
    if len({p.strip().lower() for p in where if p.strip()}) > MAX_LOCATIONS:
        raise HTTPException(422, f"Search up to {MAX_LOCATIONS} locations at a time.")
    places = normalize_locations(where)

    try:
        result = await search_jobs(
            q, places,
            salary_min=salary_min,
            require_stated_salary=require_stated_salary,
            remote_only=remote_only,
            include_conflicted_remote=include_conflicted_remote,
            max_days_old=max_days_old,
            limit=limit,
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception:
        logger.exception("job search failed")
        raise HTTPException(502, "Job search is unavailable right now.")

    return JobSearchResponse(
        postings=[JobOut(**p.to_dict()) for p in result.postings],
        estimated_matches=[JobOut(**p.to_dict()) for p in result.estimated_matches],
        pages_fetched=result.pages_fetched,
        total_available=result.total_available,
        excluded_estimated_salary=result.excluded_estimated_salary,
        excluded_no_salary=result.excluded_no_salary,
        excluded_not_remote=result.excluded_not_remote,
        excluded_below_salary=result.excluded_below_salary,
        collapsed_duplicates=result.collapsed_duplicates,
        locations_searched=result.locations_searched,
        failed_locations=result.failed_locations,
    )
