"""Job search with honest provenance."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.deps import CurrentUser
from app.services import places as place_check
from app.services.job_search import JOB_TYPES, MAX_LOCATIONS, SORTS, normalize_locations, search_jobs

logger = logging.getLogger(__name__)
router = APIRouter()


#: Radius around each place, in miles (the board takes km). Mentor: "for
#: city you might also consider a distance range."
DISTANCES_MILES = (5, 10, 25, 50)


class JobOut(BaseModel):
    id: str
    title: str
    company: str | None = None
    location: str | None = None
    url: str
    created: str | None = None
    contract_time: str | None = None
    contract_type: str | None = None
    #: What the advert states: full_time / part_time / contract / permanent.
    job_types: list[str] = []
    salary_min: float | None = None
    salary_max: float | None = None
    #: "stated" (employer said so) | "estimated" (aggregator guessed) | "absent"
    salary_source: str
    #: Copies of this advert got different board estimates: lowest and highest.
    estimate_low: float | None = None
    estimate_high: float | None = None
    #: Only in `hidden`: which filter removed it, in plain words.
    hidden_reason: str | None = None
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


class PlaceCheck(BaseModel):
    #: What was typed.
    input: str
    #: ok | ambiguous | state | region | remote | unknown | invalid
    status: str
    #: What was searched, e.g. "Austin, TX" (none for unknown / invalid).
    place: str | None = None
    #: Other places with the same name, largest first ("Springfield, IL").
    alternatives: list[str] = []
    #: For an unknown place: did you mean ("New York, NY" for "new yotrk").
    suggestions: list[str] = []
    #: Why what's searched differs from what was typed ("Brooklyn is part of
    #: New York City…", "ZIP 78701 is in Austin, TX…", "US jobs only").
    note: str | None = None
    #: Everything searched for it: one place, or a region's cities.
    places: list[str] = []


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
    #: Job-type filter: adverts that didn't say their type / said another.
    excluded_type_unstated: int = 0
    excluded_other_type: int = 0
    #: "title" (every word in the job title) or "words" (anywhere).
    match: str = "title"
    #: Adverts that only mention the words somewhere; shown apart, labelled.
    loose_matches: list[JobOut] = []
    #: Older than posted_after by their own date (the board filters by day).
    excluded_too_old: int = 0
    #: How each typed location was understood. Unknown and invalid ones were
    #: not searched -- the board would otherwise guess ("3" -> Puerto Rico).
    place_checks: list[PlaceCheck] = []
    #: Places understood but left out: a search covers MAX_LOCATIONS places
    #: (one board request each), and a region can bring more than that.
    places_not_searched: list[str] = []
    #: "Remote" was typed as a place, so the Remote only filter was applied.
    remote_from_place: bool = False
    #: Other spellings of the title also searched, e.g. "quality assurance lead".
    also_searched: list[str] = []
    #: Nothing had every word of the title, so these were searched instead
    #: ("compliance specialist" for "VP EAC Compliance … Specialist").
    broadened_to: list[str] = []
    #: What the filters removed, each with `hidden_reason`, to show on request.
    hidden: list[JobOut] = []


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
    # full_time | part_time | contract | permanent. Filtered on what adverts
    # state; the ones that don't say are counted, not hidden silently.
    job_type: str | None = Query(None),
    # Exact cut-off, e.g. 24 hours ago or the start of a chosen day (ISO 8601
    # with an offset). Wins over max_days_old.
    posted_after: datetime | None = Query(None),
    # "relevance" (the board's order) or "date" (newest first).
    sort: str = Query("relevance"),
    distance: int | None = Query(None),
    #: Words the whole advert must contain ("software"), for titles that mean
    #: different work in different fields ("QA lead").
    mention: str | None = Query(None, max_length=60),
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
    # Check every place before the board sees it: it guesses at anything
    # ("." -> Alabama) and is silent when it can't match ("new yotrk").
    checks = [place_check.resolve(p) for p in normalize_locations(where)]
    understood: list[str] = []
    for check in checks:
        if check.searchable:
            understood += [p for p in check.places if p not in understood]
    # A region can bring more places than one search covers; name the rest
    # rather than letting them drop off.
    places, places_not_searched = understood[:MAX_LOCATIONS], understood[MAX_LOCATIONS:]
    # "Remote" typed as a place ("Remote", "Austin (remote)") means the
    # Remote only filter.
    remote_from_place = any(c.status == "remote" or c.remote for c in checks)
    remote_only = remote_only or remote_from_place
    place_checks = [PlaceCheck(**vars(c)) for c in checks]
    if job_type is not None and job_type not in JOB_TYPES:
        raise HTTPException(422, f"job_type must be one of: {', '.join(JOB_TYPES)}.")
    if distance is not None and distance not in DISTANCES_MILES:
        raise HTTPException(422, f"distance must be one of: {', '.join(map(str, DISTANCES_MILES))} (miles).")
    if sort not in SORTS:
        raise HTTPException(422, f"sort must be one of: {', '.join(SORTS)}.")
    if posted_after is not None:
        if posted_after.tzinfo is None:
            posted_after = posted_after.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if posted_after > now + timedelta(hours=1):
            raise HTTPException(422, "The posted date can't be in the future.")
        if posted_after < now - timedelta(days=365):
            raise HTTPException(422, "Pick a posted date within the last year.")

    if checks and not places and not remote_from_place:
        # Places were typed but none is real: searching the whole country
        # instead would look like an answer. Say what's wrong instead.
        # (Only "Remote" typed: a nationwide remote search is what was meant.)
        return JobSearchResponse(postings=[], place_checks=place_checks)

    try:
        result = await search_jobs(
            q, places,
            salary_min=salary_min,
            require_stated_salary=require_stated_salary,
            remote_only=remote_only,
            include_conflicted_remote=include_conflicted_remote,
            max_days_old=max_days_old,
            job_type=job_type,
            posted_after=posted_after,
            sort=sort,
            distance_km=round(distance * 1.609) if distance else None,
            must_mention=mention,
            limit=limit,
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception:
        logger.exception("job search failed")
        raise HTTPException(502, "Job search is unavailable right now.")

    return JobSearchResponse(
        place_checks=place_checks,
        places_not_searched=places_not_searched,
        remote_from_place=remote_from_place,
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
        excluded_type_unstated=result.excluded_type_unstated,
        excluded_other_type=result.excluded_other_type,
        match=result.match,
        loose_matches=[JobOut(**p.to_dict()) for p in result.loose_matches],
        also_searched=result.also_searched,
        broadened_to=result.broadened_to,
        hidden=[JobOut(**p.to_dict(), hidden_reason=reason) for p, reason in result.hidden],
        excluded_too_old=result.excluded_too_old,
    )


@router.get("/places", response_model=list[str])
async def place_suggestions(user: CurrentUser, q: str = Query(..., min_length=1, max_length=80)):
    """Places starting with what's typed so far, largest first ("sea" ->
    Seattle, WA), for the location box on Find Roles."""
    return place_check.complete(q)
