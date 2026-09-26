"""Job search with honest provenance labelling.

Job boards lose trust in two specific ways, both measured against live Adzuna
data before this was written:

  SALARY   Of 250 sampled US postings, only 14% carried an employer-stated
           salary. The other 86% were Adzuna's own *predictions*, returned in
           the same `salary_min`/`salary_max` fields with a separate
           `salary_is_predicted` flag that most consumers ignore. So filtering
           by salary silently returns jobs where nobody ever stated pay.

  REMOTE   Searching "remote software engineer" returned 50 postings that all
           mention remote in the text, but whose locations were specific towns
           (Dayton OH, Beavercreek OH). "Remote" in the text does not mean the
           job is remote.

The response to both is the same: never discard the provenance. Every posting
carries how its salary was obtained and how confident the remote claim is, and
the filters operate on those classifications rather than on the raw numbers.
A filter that cannot be honest returns fewer results rather than wrong ones.
"""

import asyncio
import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from itertools import chain, zip_longest
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.adzuna.com/v1/api"


def _age_days(created: str | None) -> int | None:
    """How old the advert claims to be."""
    if not created:
        return None
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except ValueError:
        return None


def _observed_days(first_seen) -> int:
    """How long WE have actually been seeing this advert."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if first_seen.tzinfo is None:
        first_seen = first_seen.replace(tzinfo=timezone.utc)
    return (now - first_seen).days
COUNTRY = os.getenv("ADZUNA_COUNTRY", "us")


class SalarySource(str, Enum):
    stated = "stated"        # the employer published it
    estimated = "estimated"  # the aggregator guessed it
    absent = "absent"        # nobody said


class RemoteClaim(str, Enum):
    remote = "remote"        # claims remote and is not pinned to one town
    conflicted = "conflicted"  # claims remote but names a specific location
    onsite = "onsite"        # no remote claim
    unknown = "unknown"


#: Location strings that indicate nationwide rather than a specific place.
_BROAD_LOCATIONS = {"us", "usa", "united states", "nationwide", "anywhere", "remote"}

_REMOTE_PATTERN = re.compile(
    r"\b(fully|100%|work from home|wfh|telecommut\w*|remote[- ]first|remote)\b",
    re.IGNORECASE,
)
_ONSITE_CONTRADICTION = re.compile(
    r"\b(on[- ]?site|in[- ]?office|in[- ]?person|hybrid|must reside|"
    r"relocat\w+|commut\w+)\b",
    re.IGNORECASE,
)


#: Words too common in job ads to carry identity.
_FINGERPRINT_STOP = re.compile(r"\b(the|and|for|with|you|our|are|this|that|will|from)\b")


def fingerprint(title: str, description: str) -> str:
    """Content fingerprint that survives a repost.

    Numbers (dates, salaries, requisition ids) and URLs are stripped because
    they are exactly what changes when an advert is re-upped. What remains is
    the prose, which agencies and employers reuse verbatim.

    Measured on a live 50-result page: 30 postings collapsed into 8 clusters,
    one employer having posted an identical advert across 10 states.
    """
    text = f"{title} {description}".lower()
    text = re.sub(r"http\S+", " ", text)
    text = re.sub(r"\d+", " ", text)
    text = _FINGERPRINT_STOP.sub(" ", text)
    text = re.sub(r"[^a-z ]", " ", text)
    words = [w for w in text.split() if len(w) > 3]
    return hashlib.sha256(" ".join(words[:60]).encode()).hexdigest()[:32]


@dataclass
class JobPosting:
    id: str
    title: str
    company: str | None
    location: str | None
    url: str
    created: str | None = None
    description: str = ""
    contract_time: str | None = None
    #: Adzuna's other type field: "permanent" | "contract" | None.
    contract_type: str | None = None

    salary_min: float | None = None
    salary_max: float | None = None
    #: How the salary above was obtained. Never dropped.
    salary_source: SalarySource = SalarySource.absent

    remote_claim: RemoteClaim = RemoteClaim.unknown
    #: Plain-English reason for the classification, shown in the UI.
    remote_note: str | None = None

    #: Content fingerprint; identical adverts share one.
    fingerprint: str = ""
    #: How many identical adverts this entry stands for in these results.
    duplicate_count: int = 1
    #: The other places the same advert appeared.
    duplicate_locations: list[str] = field(default_factory=list)
    #: When WE first saw this advert text, regardless of its claimed date.
    first_seen: str | None = None
    #: True when we have seen this advert materially earlier than it claims.
    is_repost: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "company": self.company,
            "location": self.location, "url": self.url, "created": self.created,
            "contract_time": self.contract_time,
            "contract_type": self.contract_type,
            "job_types": sorted(job_types(self)),
            "salary_min": self.salary_min, "salary_max": self.salary_max,
            "salary_source": self.salary_source.value,
            "remote_claim": self.remote_claim.value,
            "remote_note": self.remote_note,
            "fingerprint": self.fingerprint,
            "duplicate_count": self.duplicate_count,
            "duplicate_locations": self.duplicate_locations,
            "first_seen": self.first_seen,
            "is_repost": self.is_repost,
        }


@dataclass
class SearchResult:
    postings: list[JobPosting] = field(default_factory=list)
    total_available: int | None = None
    #: What the filters removed, so the UI can explain a short list.
    excluded_estimated_salary: int = 0
    excluded_no_salary: int = 0
    excluded_not_remote: int = 0
    excluded_below_salary: int = 0
    #: Adverts folded into another entry because the text was identical.
    collapsed_duplicates: int = 0
    #: Places searched, and any whose lookup failed (the rest still return).
    locations_searched: list[str] = field(default_factory=list)
    failed_locations: list[str] = field(default_factory=list)
    #: With a salary floor: adverts whose ESTIMATED pay clears it, kept apart
    #: from employer-stated matches so the two are never confused.
    estimated_matches: list["JobPosting"] = field(default_factory=list)
    pages_fetched: int = 0
    #: Job-type filter: adverts that didn't state a type / stated another.
    excluded_type_unstated: int = 0
    excluded_other_type: int = 0
    #: How the query was matched: "title" (every word in the job title) or
    #: "words" (anywhere in the advert).
    match: str = "title"
    #: With title matching: adverts that only mention the words somewhere,
    #: fetched when title matches run short. Shown apart and labelled, never
    #: mixed in -- this is where off-topic results come from.
    loose_matches: list["JobPosting"] = field(default_factory=list)


def classify_salary(raw: dict[str, Any]) -> SalarySource:
    """Distinguish an employer's figure from the aggregator's guess."""
    has_figure = bool(raw.get("salary_min") or raw.get("salary_max"))
    if not has_figure:
        return SalarySource.absent
    # Adzuna returns this as 1/"1"/True depending on the endpoint.
    predicted = str(raw.get("salary_is_predicted", "0")).strip().lower()
    if predicted in {"1", "true", "yes"}:
        return SalarySource.estimated
    return SalarySource.stated


def classify_remote(raw: dict[str, Any]) -> tuple[RemoteClaim, str | None]:
    """Judge a remote claim against the location the posting actually names."""
    text = f"{raw.get('title', '')} {raw.get('description', '')}"
    location = (raw.get("location") or {}).get("display_name", "") or ""
    claims_remote = bool(_REMOTE_PATTERN.search(text))

    if not claims_remote:
        return RemoteClaim.onsite, None

    area = location.split(",")[0].strip().lower()
    is_broad = (not area) or area in _BROAD_LOCATIONS

    if is_broad:
        return RemoteClaim.remote, None

    contradiction = _ONSITE_CONTRADICTION.search(text)
    if contradiction:
        return RemoteClaim.conflicted, (
            f"Says remote but also mentions "
            f"'{contradiction.group(0).lower()}' and is listed in {location}."
        )
    return RemoteClaim.conflicted, (
        f"Says remote but is listed in {location}, not as a nationwide role."
    )


#: The job-type filter's choices.
JOB_TYPES = ("full_time", "part_time", "contract", "permanent")

#: A title that says it plainly ("QA Lead (W2 Contract)", "C2C", "1099").
#: Titles only: descriptions mention "contract" in too many other senses.
_CONTRACT_IN_TITLE = re.compile(r"\b(contract(or)?|c2c|corp[- ]to[- ]corp|1099)\b", re.I)


def job_types(posting: "JobPosting") -> set[str]:
    """The types a posting states, from Adzuna's two fields and its title.

    Most adverts state neither (116 "QA lead" adverts: 34 said full-time,
    8 contract), so an empty set means "didn't say", never "not this type".
    Full-time and contract can both be true: a full-time contract role.
    """
    types: set[str] = set()
    if posting.contract_time in ("full_time", "part_time"):
        types.add(posting.contract_time)
    if posting.contract_type in ("contract", "permanent"):
        types.add(posting.contract_type)
    if _CONTRACT_IN_TITLE.search(posting.title or ""):
        types.add("contract")
    return types


def to_posting(raw: dict[str, Any]) -> JobPosting:
    claim, note = classify_remote(raw)
    return JobPosting(
        fingerprint=fingerprint(raw.get("title", ""), raw.get("description", "")),
        id=str(raw.get("id", "")),
        title=raw.get("title", "") or "",
        company=(raw.get("company") or {}).get("display_name"),
        location=(raw.get("location") or {}).get("display_name"),
        url=raw.get("redirect_url", "") or "",
        created=raw.get("created"),
        description=(raw.get("description") or "")[:600],
        contract_time=raw.get("contract_time"),
        contract_type=raw.get("contract_type"),
        salary_min=raw.get("salary_min"),
        salary_max=raw.get("salary_max"),
        salary_source=classify_salary(raw),
        remote_claim=claim,
        remote_note=note,
    )


def _record_sightings(postings: list[JobPosting]) -> dict[str, dict[str, Any]]:
    """Persist first-seen dates and return what we already knew.

    This is what makes re-upping visible: the advert claims to be new, but if
    we saw the same text three months ago, we say so. Best-effort -- a
    database hiccup must not break search.
    """
    from app.db.base import SessionLocal
    from app.db.models import JobSighting, utcnow

    known: dict[str, dict[str, Any]] = {}
    try:
        now = utcnow()
        with SessionLocal() as db:
            # A result set can contain the same advert many times (that is the
            # point). Insert each fingerprint at most once per batch or the
            # primary key is violated and the whole batch is lost.
            for posting in _unique_by_fingerprint(postings):
                row = db.get(JobSighting, posting.fingerprint)
                if row is None:
                    db.add(JobSighting(
                        fingerprint=posting.fingerprint,
                        sample_title=posting.title[:300],
                        sample_company=(posting.company or "")[:200] or None,
                    ))
                    known[posting.fingerprint] = {"first_seen": now, "times_seen": 1}
                else:
                    row.last_seen = now
                    row.times_seen += 1
                    first = row.first_seen
                    if first.tzinfo is None:
                        from datetime import timezone
                        first = first.replace(tzinfo=timezone.utc)
                    known[posting.fingerprint] = {
                        "first_seen": first, "times_seen": row.times_seen,
                    }
            db.commit()
    except Exception as exc:
        logger.warning("could not record job sightings: %s", exc)
    return known


def _unique_by_fingerprint(postings: list[JobPosting]) -> list[JobPosting]:
    seen: set[str] = set()
    out: list[JobPosting] = []
    for posting in postings:
        if posting.fingerprint in seen:
            continue
        seen.add(posting.fingerprint)
        out.append(posting)
    return out


def _collapse_duplicates(postings: list[JobPosting]) -> tuple[list[JobPosting], int]:
    """Fold identical adverts into one entry.

    A page showing the same advert in ten states is ten rows of one job. The
    survivor records where else it appeared so nothing is hidden.
    """
    seen: dict[str, JobPosting] = {}
    collapsed = 0
    for posting in postings:
        first = seen.get(posting.fingerprint)
        if first is None:
            seen[posting.fingerprint] = posting
            continue
        first.duplicate_count += 1
        if posting.location and posting.location not in first.duplicate_locations:
            first.duplicate_locations.append(posting.location)
        # Prefer a stated salary over an estimate when merging.
        if (first.salary_source is not SalarySource.stated
                and posting.salary_source is SalarySource.stated):
            first.salary_min, first.salary_max = posting.salary_min, posting.salary_max
            first.salary_source = SalarySource.stated
        collapsed += 1
    return list(seen.values()), collapsed


#: Adzuna takes one place per query, so several places cost one request each.
MAX_LOCATIONS = 3


def normalize_locations(locations: str | list[str] | None) -> list[str]:
    """Trim, drop blanks and case-insensitive repeats, cap at MAX_LOCATIONS."""
    if locations is None:
        return []
    if isinstance(locations, str):
        locations = [locations]
    seen: set[str] = set()
    out: list[str] = []
    for place in locations:
        place = place.strip()
        if place and place.lower() not in seen:
            seen.add(place.lower())
            out.append(place)
    return out[:MAX_LOCATIONS]


def _interleave(pages: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Round-robin across places so the first city cannot crowd out the rest
    when the result limit is reached."""
    return [raw for raw in chain.from_iterable(zip_longest(*pages)) if raw is not None]


#: Extra pages fetched per place when filters leave too few results. Each
#: page is one Adzuna request, and the free tier is rate-limited.
MAX_PAGES = 3

#: How a query is matched against adverts, measured by app/scripts/search_eval.py
#: (12 role x place cases, mostly smaller places; on-topic / shown):
#:   words   every word anywhere in the advert       261/293  89%
#:   phrase  the exact phrase anywhere (removed)     246/262  94%
#:   title   every word in the job title, any order  245/245 100%
#: Matching anywhere in the advert is what let "QA lead" in a small market
#: return "lead" jobs whose description merely mentions QA; the title is
#: where an advert says what the job is. Words stay for the loose section.
STRATEGIES = ("words", "title")

#: Loose (word-anywhere) matches shown apart when title matches run short.
LOOSE_MAX = 10

#: Identical searches within this window reuse the result: the tester asked
#: for previous searches to be remembered, and every search spends Adzuna
#: quota. Wall-clock, in-process, small -- like the pathway cache.
SEARCH_CACHE_TTL = float(os.getenv("JOB_SEARCH_CACHE_TTL", "900"))
SEARCH_CACHE_MAX = 64
_search_cache: dict[tuple, tuple[float, "SearchResult"]] = {}


def clear_search_cache() -> None:
    _search_cache.clear()


async def _loose_matches(base, query, targets, *, fetch_page, taken, filtered) -> list["JobPosting"]:
    """One page of word-anywhere matches per place, minus the title matches.

    Only called when title matching found fewer adverts than a page shows,
    so a well-served search costs no extra request.
    """
    del base["title_only"]
    base["what"] = query
    async with httpx.AsyncClient(timeout=40.0) as client:
        outcomes = await asyncio.gather(
            *(fetch_page(client, t, 1) for t in targets), return_exceptions=True)
    raws = [o.get("results", []) for o in outcomes if not isinstance(o, BaseException)]
    postings = [to_posting(raw) for raw in _interleave(raws)]
    postings, _ = _collapse_duplicates(postings)
    fresh = [p for p in postings if p.fingerprint not in taken]
    return filtered(fresh).kept[:LOOSE_MAX]


@dataclass
class _Filtered:
    kept: list[JobPosting] = field(default_factory=list)
    estimated: list[JobPosting] = field(default_factory=list)
    excluded_estimated_salary: int = 0
    excluded_no_salary: int = 0
    excluded_not_remote: int = 0
    excluded_below_salary: int = 0
    excluded_type_unstated: int = 0
    excluded_other_type: int = 0


def _apply_filters(
    candidates: list[JobPosting],
    *,
    salary_min: float | None,
    require_stated_salary: bool,
    remote_only: bool,
    include_conflicted_remote: bool,
    limit: int,
    job_type: str | None = None,
) -> _Filtered:
    """Sort candidates into shown / shown-as-estimated / excluded (counted)."""
    out = _Filtered()
    for posting in candidates:
        if len(out.kept) >= limit and len(out.estimated) >= limit:
            break

        if job_type:
            types = job_types(posting)
            if not types:
                out.excluded_type_unstated += 1
                continue
            if job_type not in types:
                out.excluded_other_type += 1
                continue

        if remote_only:
            allowed = {RemoteClaim.remote}
            if include_conflicted_remote:
                allowed.add(RemoteClaim.conflicted)
            if posting.remote_claim not in allowed:
                out.excluded_not_remote += 1
                continue

        if require_stated_salary and posting.salary_source is not SalarySource.stated:
            if posting.salary_source is SalarySource.estimated:
                out.excluded_estimated_salary += 1
            else:
                out.excluded_no_salary += 1
            continue

        if salary_min is not None:
            if posting.salary_source is SalarySource.absent:
                out.excluded_no_salary += 1
                continue
            # Compare against the TOP of the advertised band: a job listed
            # at $100k-$150k can pay $120k, so excluding it would be the
            # mirror of the dishonesty we are fixing. The range is shown, so
            # the user judges it themselves.
            if (posting.salary_max or posting.salary_min or 0) < salary_min:
                out.excluded_below_salary += 1
                continue
            # Only an employer's figure can truly clear a floor. A board's
            # estimate that clears it is still useful -- employer-stated pay
            # is rare (2 of 50 for "software engineer") -- so it is shown in
            # its own, labelled list instead of being hidden or mixed in.
            if posting.salary_source is SalarySource.estimated:
                if len(out.estimated) < limit:
                    out.estimated.append(posting)
                continue

        if len(out.kept) < limit:
            out.kept.append(posting)
    return out


async def search_jobs(
    query: str,
    locations: str | list[str] | None = None,
    *,
    salary_min: float | None = None,
    require_stated_salary: bool = False,
    remote_only: bool = False,
    include_conflicted_remote: bool = False,
    collapse_duplicates: bool = True,
    max_days_old: int | None = None,
    job_type: str | None = None,
    limit: int = 30,
    strategy: str = "title",
) -> SearchResult:
    """Search postings and apply filters that never fabricate certainty.

    With a salary floor, employer-stated pay at or above it is the main
    result; board estimates at or above it come back separately in
    `estimated_matches`, labelled. `require_stated_salary` drops estimates
    entirely. `max_days_old` keeps to recent adverts: testers found anything
    older than about a week is usually already filled.
    """
    app_id = os.getenv("ADZUNA_APP_ID", "")
    app_key = os.getenv("ADZUNA_APP_KEY", "")
    if not (app_id and app_key):
        raise RuntimeError("ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
    if job_type is not None and job_type not in JOB_TYPES:
        raise ValueError(f"unknown job type {job_type!r}")

    places = normalize_locations(locations)
    cache_key = (
        " ".join(query.lower().split()), tuple(p.lower() for p in places), salary_min,
        require_stated_salary, remote_only, include_conflicted_remote,
        collapse_duplicates, max_days_old, job_type, limit, strategy,
    )
    cached = _search_cache.get(cache_key)
    if cached and time.time() - cached[0] < SEARCH_CACHE_TTL:
        return cached[1]

    per_page = min(50, max(limit * 2, 20))
    # Mentor: "QA lead" found "lead" jobs with no QA in them. Adzuna's
    # title_only needs every word in the job title, in any order ("Lead QA
    # Engineer" counts); see STRATEGIES for how that was measured.
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}")
    base: dict[str, Any] = {
        "app_id": app_id, "app_key": app_key,
        "title_only" if strategy == "title" else "what": query,
        # Ask for more than we need: honest filtering discards a lot.
        "results_per_page": per_page,
    }
    if salary_min is not None:
        # Pre-narrow at the source so the page holds better-paid jobs.
        # Verified live: Adzuna keeps ranges that reach the floor ($70k-$120k
        # survives a $100k floor), so this hides nothing our own rule admits.
        base["salary_min"] = int(salary_min)
    if max_days_old is not None:
        base["max_days_old"] = max_days_old
    targets: list[str | None] = list(places) or [None]

    async def fetch(client: httpx.AsyncClient, place: str | None, page: int) -> dict[str, Any]:
        params = dict(base)
        if place:
            params["where"] = place
        response = await client.get(f"{BASE_URL}/jobs/{COUNTRY}/search/{page}", params=params)
        response.raise_for_status()
        return response.json()

    result = SearchResult(
        locations_searched=places,
        match=strategy)
    #: Raw adverts per place, in page order.
    pages: dict[str | None, list[dict[str, Any]]] = {}
    counts: dict[str | None, int] = {}

    def build() -> list[JobPosting]:
        merged = _interleave([pages[t] for t in targets if t in pages])
        postings = [to_posting(raw) for raw in merged]
        if collapse_duplicates:
            postings, result.collapsed_duplicates = _collapse_duplicates(postings)
        return postings

    def filtered(postings: list[JobPosting]) -> _Filtered:
        return _apply_filters(
            postings, salary_min=salary_min, require_stated_salary=require_stated_salary,
            remote_only=remote_only, include_conflicted_remote=include_conflicted_remote,
            limit=limit, job_type=job_type)

    async def first_pages(client: httpx.AsyncClient) -> None:
        pages.clear()
        counts.clear()
        result.failed_locations = []
        outcomes = await asyncio.gather(
            *(fetch(client, t, 1) for t in targets), return_exceptions=True)
        for target, outcome in zip(targets, outcomes):
            if isinstance(outcome, BaseException):
                # One bad place should not sink the others; say which one failed.
                logger.warning("job search failed for one location: %s", type(outcome).__name__)
                result.failed_locations.append(target or "")
                continue
            pages[target] = list(outcome.get("results", []))
            counts[target] = outcome.get("count") or 0
        if not pages:
            raise next(o for o in outcomes if isinstance(o, BaseException))

    async with httpx.AsyncClient(timeout=40.0) as client:
        await first_pages(client)
        result.pages_fetched = 1

        # Filters that discard most adverts get another page or two, but only
        # while places still have more to give.
        filtering = (salary_min is not None or require_stated_salary or remote_only
                     or job_type is not None)
        for page in range(2, MAX_PAGES + 1):
            if not filtering or len(filtered(build()).kept) >= limit:
                break
            more = [t for t in pages if counts[t] > len(pages[t]) and len(pages[t]) >= per_page * (page - 1)]
            if not more:
                break
            extra = await asyncio.gather(
                *(fetch(client, t, page) for t in more), return_exceptions=True)
            for target, outcome in zip(more, extra):
                if not isinstance(outcome, BaseException):
                    pages[target].extend(outcome.get("results", []))
            result.pages_fetched = page

    result.total_available = sum(counts.values()) if counts else None

    candidates = build()

    # Attach what we knew about each advert before today. Once per search:
    # every call counts as a sighting.
    known = _record_sightings(candidates)
    for posting in candidates:
        info = known.get(posting.fingerprint)
        if not info:
            continue
        posting.first_seen = info["first_seen"].isoformat()
        # Seen repeatedly across separate searches over time = re-upped.
        posting.is_repost = info["times_seen"] > 1 and (
            _age_days(posting.created) is not None
            and _age_days(posting.created) < _observed_days(info["first_seen"]) - 3
        )

    out = filtered(candidates)
    result.postings = out.kept
    result.estimated_matches = out.estimated
    result.excluded_estimated_salary = out.excluded_estimated_salary
    result.excluded_no_salary = out.excluded_no_salary
    result.excluded_not_remote = out.excluded_not_remote
    result.excluded_below_salary = out.excluded_below_salary
    result.excluded_type_unstated = out.excluded_type_unstated
    result.excluded_other_type = out.excluded_other_type

    # Title matches ran short: say what else merely mentions the words, apart.
    if strategy == "title" and len(result.postings) < limit:
        result.loose_matches = await _loose_matches(
            base, query, targets, fetch_page=fetch, taken={p.fingerprint for p in candidates},
            filtered=filtered)

    if len(_search_cache) >= SEARCH_CACHE_MAX:
        _search_cache.pop(next(iter(_search_cache)), None)
    _search_cache[cache_key] = (time.time(), result)
    return result
