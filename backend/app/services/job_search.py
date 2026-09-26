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


async def search_jobs(
    query: str,
    locations: str | list[str] | None = None,
    *,
    salary_min: float | None = None,
    require_stated_salary: bool = False,
    remote_only: bool = False,
    include_conflicted_remote: bool = False,
    collapse_duplicates: bool = True,
    limit: int = 30,
) -> SearchResult:
    """Search postings and apply filters that never fabricate certainty.

    `require_stated_salary` is the honest counterpart to a salary filter: it
    drops anything whose figure the aggregator guessed, so a salary floor
    means what the user thinks it means. Applying `salary_min` without it
    would filter on predicted numbers.
    """
    app_id = os.getenv("ADZUNA_APP_ID", "")
    app_key = os.getenv("ADZUNA_APP_KEY", "")
    if not (app_id and app_key):
        raise RuntimeError("ADZUNA_APP_ID / ADZUNA_APP_KEY not set")

    base: dict[str, Any] = {
        "app_id": app_id, "app_key": app_key,
        "what": query,
        # Ask for more than we need: honest filtering discards a lot.
        "results_per_page": min(50, max(limit * 2, 20)),
    }
    places = normalize_locations(locations)

    async def fetch(client: httpx.AsyncClient, place: str | None) -> dict[str, Any]:
        params = dict(base)
        if place:
            params["where"] = place
        response = await client.get(f"{BASE_URL}/jobs/{COUNTRY}/search/1", params=params)
        response.raise_for_status()
        return response.json()

    async with httpx.AsyncClient(timeout=40.0) as client:
        if places:
            outcomes = await asyncio.gather(
                *(fetch(client, place) for place in places), return_exceptions=True)
        else:
            outcomes = [await fetch(client, None)]

    payloads: list[dict[str, Any]] = []
    result = SearchResult(locations_searched=places)
    for place, outcome in zip(places or [None], outcomes):
        if isinstance(outcome, BaseException):
            # One bad place should not sink the others; say which one failed.
            logger.warning("job search failed for one location: %s", type(outcome).__name__)
            result.failed_locations.append(place or "")
            continue
        payloads.append(outcome)
    if not payloads:
        failure = next(o for o in outcomes if isinstance(o, BaseException))
        raise failure

    counts = [p.get("count") for p in payloads if p.get("count") is not None]
    result.total_available = sum(counts) if counts else None

    candidates = [to_posting(raw) for raw in _interleave([p.get("results", []) for p in payloads])]

    if collapse_duplicates:
        candidates, result.collapsed_duplicates = _collapse_duplicates(candidates)

    # Attach what we knew about each advert before today.
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

    for posting in candidates:

        if require_stated_salary and posting.salary_source is not SalarySource.stated:
            if posting.salary_source is SalarySource.estimated:
                result.excluded_estimated_salary += 1
            else:
                result.excluded_no_salary += 1
            continue

        if salary_min is not None:
            # Only a figure we trust can clear a floor. An absent or guessed
            # salary is not evidence the job pays enough.
            if posting.salary_source is not SalarySource.stated:
                result.excluded_no_salary += 1
                continue
            # Compare against the TOP of the advertised band: a job listed
            # at $100k-$150k can pay $120k, so excluding it would be the
            # mirror of the dishonesty we are fixing. The range is shown, so
            # the user judges it themselves.
            if (posting.salary_max or posting.salary_min or 0) < salary_min:
                result.excluded_below_salary += 1
                continue

        if remote_only:
            allowed = {RemoteClaim.remote}
            if include_conflicted_remote:
                allowed.add(RemoteClaim.conflicted)
            if posting.remote_claim not in allowed:
                result.excluded_not_remote += 1
                continue

        result.postings.append(posting)
        if len(result.postings) >= limit:
            break

    return result
