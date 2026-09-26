"""Occupation resolution over the vendored O*NET-SOC taxonomy.

Replaces the four-family hand-written map that only understood tech roles.
867 occupations, all 23 SOC major groups, no credentials and no network.

Matching is deliberately simple and explainable rather than clever:

  1. exact title match
  2. a known alias ("nurse" -> Registered Nurses)
  3. token overlap, scored, with a floor so a single weak word cannot match

Seniority words ("senior", "lead", "junior") are stripped first -- they say
nothing about occupation. When nothing clears the floor we return None, which
surfaces as "no SOC match" rather than a confidently wrong answer.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent.parent / "data" / "occupations.json"

#: Words that describe rank or employment terms, not the occupation itself.
_NOISE = {
    "senior", "sr", "junior", "jr", "lead", "principal", "staff", "chief",
    "head", "entry", "level", "i", "ii", "iii", "iv",
    "intern", "trainee", "apprentice", "full", "time", "part", "contract",
    "remote", "hybrid", "onsite", "the", "of", "and", "a", "an", "at", "for",
}

#: Common ways people describe their job that do not match an O*NET title.
_ALIASES: dict[str, str] = {
    "nurse": "29-1141", "rn": "29-1141",
    "developer": "15-1252", "programmer": "15-1252", "swe": "15-1252",
    "backend": "15-1252", "frontend": "15-1252", "fullstack": "15-1252",
    "devops": "15-1244", "sre": "15-1244",
    "data scientist": "15-2051", "ml engineer": "15-2051",
    "truck driver": "53-3032", "trucker": "53-3032",
    "teacher": "25-2031", "electrician": "47-2111",
    "plumber": "47-2152", "hvac": "49-9021",
    "accountant": "13-2011", "bookkeeper": "43-3031",
    "recruiter": "13-1071", "hr": "13-1071",
    "cook": "35-2014", "chef": "35-1011", "server": "35-3031",
    "cashier": "41-2011", "barista": "35-3023",
    "warehouse": "53-7062", "forklift": "53-7051",
    "security guard": "33-9032", "paralegal": "23-2011",
    "pharmacist": "29-1051", "dentist": "29-1021",
    "physical therapist": "29-1123", "social worker": "21-1029",
    "graphic designer": "27-1024", "copywriter": "27-3043",
    "project manager": "11-3021", "product manager": "11-2021",
    "sales rep": "41-4012", "account executive": "41-4012",
    "medical assistant": "31-9092", "dental hygienist": "29-1292",
    "store manager": "41-1011", "retail manager": "41-1011",
    "shift supervisor": "41-1011", "customer service": "43-4051",
    "administrative assistant": "43-6014", "receptionist": "43-4171",
    "delivery driver": "53-3033", "home health aide": "31-1121",
    "janitor": "37-2011", "landscaper": "37-3011",
    "welder": "51-4121", "machinist": "51-4041", "carpenter": "47-2031",
}


_RELATED_DATA = _DATA.parent / "related.json"


@lru_cache(maxsize=1)
def _payload() -> dict:
    with _DATA.open() as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _occupations() -> list[dict]:
    return _payload()["occupations"]


@lru_cache(maxsize=1)
def skill_names() -> list[str]:
    return _payload()["skill_names"]


@lru_cache(maxsize=1)
def _related_graph() -> dict[str, list[str]]:
    with _RELATED_DATA.open() as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _by_code() -> dict[str, dict]:
    return {o["soc"]: o for o in _occupations()}


@lru_cache(maxsize=1)
def _by_title() -> dict[str, dict]:
    return {o["title"].lower(): o for o in _occupations()}


def _singular(word: str) -> str:
    """Crude stemmer: enough to match singular queries to plural titles."""
    for suffix, replacement in (("ies", "y"), ("sses", "ss"), ("ches", "ch"),
                                ("shes", "sh"), ("xes", "x"), ("s", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)] + replacement
    return word


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {_singular(w) for w in words if w not in _NOISE and len(w) > 1}


def get(code: str) -> dict | None:
    return _by_code().get(code)


def all_occupations() -> list[dict]:
    return _occupations()


def resolve(title: str) -> dict | None:
    """Best occupation for a free-text job title, or None if nothing fits."""
    if not title or not title.strip():
        return None

    cleaned = title.lower().strip()

    exact = _by_title().get(cleaned)
    if exact:
        return exact

    # Longest alias wins, so "data scientist" beats a bare "data".
    for alias in sorted(_ALIASES, key=len, reverse=True):
        if alias in cleaned:
            hit = _by_code().get(_ALIASES[alias])
            if hit:
                return hit

    wanted = _tokens(cleaned)
    if not wanted:
        return None

    best, best_score = None, 0.0
    for occ in _occupations():
        have = _tokens(occ["title"])
        if not have:
            continue
        overlap = wanted & have
        if not overlap:
            continue
        # Reward covering the query and the candidate title alike, so
        # "Nurse Practitioners" does not beat "Registered Nurses" for "nurse".
        score = (len(overlap) / len(wanted)) * (len(overlap) / len(have))
        if score > best_score:
            best, best_score = occ, score

    # Floor: a single incidental word in common is not a match.
    return best if best_score >= 0.30 else None


def related(code: str, limit: int = 8) -> list[dict]:
    """Occupations O*NET itself lists as related to `code`.

    This is O*NET's published relatedness graph (15,933 edges), not a
    heuristic. It replaces an earlier title-similarity approximation that,
    among other things, offered a Registered Nurse a career as an oral
    surgeon.
    """
    codes = _related_graph().get(code, [])
    by_code = _by_code()
    return [by_code[c] for c in codes[:limit] if c in by_code]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def transferable(
    code: str,
    limit: int = 8,
    min_similarity: float = 0.97,
    cross_sector_only: bool = False,
    include_upskill: bool = True,
) -> list[dict]:
    """Occupations whose skill profile resembles this one.

    The question this answers is "what else do my current skills apply to",
    which is different from "what is the next rung up".

    Calibrated against the real distribution rather than guessed. Two findings
    shaped this:

      * Cosine similarity across all 763 occupations with skill data runs
        0.81 to 0.997, median 0.95 -- every job needs some reading and
        listening. So the floor has to be high (0.97) to mean anything.
      * An earlier version required the seed to meet or exceed the target on
        all 35 dimensions. That admitted 132 occupations, every one of them
        BELOW the seed's average level: it was finding jobs you are
        overqualified for, and told a nurse to become an archivist.

    Job Zone (O*NET's 1-5 training requirement) carries the honesty instead of
    a filter: `requires_more_training` is set when the target sits in a higher
    zone, so the UI can distinguish "you could do this now" from "this needs
    more study" rather than implying everything is within reach.
    """
    seed = _by_code().get(code)
    if seed is None or not seed.get("skills"):
        return []

    seed_zone = seed.get("job_zone")
    seed_major = code[:2]
    mine = seed["skills"]

    scored: list[tuple[float, dict]] = []
    for occ in _occupations():
        if occ["soc"] == code or not occ.get("skills"):
            continue
        if cross_sector_only and occ["soc"][:2] == seed_major:
            continue

        similarity = _cosine(mine, occ["skills"])
        if similarity < min_similarity:
            continue

        zone = occ.get("job_zone")
        needs_more = bool(seed_zone and zone and zone > seed_zone)
        if needs_more and not include_upskill:
            continue

        scored.append((similarity, {
            **occ,
            "similarity": round(similarity, 4),
            "requires_more_training": needs_more,
            "skill_gaps": _gaps(mine, occ["skills"]),
        }))

    scored.sort(key=lambda pair: -pair[0])
    return [occ for _, occ in scored[:limit]]


#: A skill counts toward the shortfall only when the target job really uses
#: it and the gap is bigger than O*NET's own measurement noise (standard
#: errors run ~0.3-0.5 on the 0-7 level scale). Summing every tiny gap let
#: skills a job barely needs ("Repairing" for a systems analyst) swamp the
#: ones that matter.
SHORTFALL_MIN_GAP = 0.5
SHORTFALL_MIN_LEVEL = 3.0


def skill_shortfall(from_code: str, to_code: str) -> float | None:
    """How far `to_code` needs more skill than `from_code` has, summed.

    Only the skills the target job uses (level >= SHORTFALL_MIN_LEVEL), and
    only gaps of at least SHORTFALL_MIN_GAP. Being better at something the
    target needs less of does not offset a real gap. None when either side
    has no skill data (O*NET has none for some occupations, e.g. most
    military).
    """
    mine = (_by_code().get(from_code) or {}).get("skills")
    theirs = (_by_code().get(to_code) or {}).get("skills")
    if not mine or not theirs:
        return None
    return sum(
        t - m for m, t in zip(mine, theirs)
        if t - m >= SHORTFALL_MIN_GAP and t >= SHORTFALL_MIN_LEVEL
    )


def _gaps(mine: list[float], theirs: list[float], top: int = 3) -> list[dict]:
    """Skills the target needs clearly more of, biggest first.

    The same filter as skill_shortfall: skills the job really uses, gaps above
    O*NET's measurement noise. Without it the list led with skills a job
    barely needs ("Repairing" for a systems analyst).
    """
    names = skill_names()
    short = [
        {"skill": names[i], "gap": round(theirs[i] - mine[i], 2)}
        for i in range(len(names))
        if theirs[i] - mine[i] >= SHORTFALL_MIN_GAP and theirs[i] >= SHORTFALL_MIN_LEVEL
    ]
    short.sort(key=lambda g: -g["gap"])
    return short[:top]


def skill_gaps(from_code: str, to_code: str, top: int = 3) -> list[dict]:
    """_gaps by SOC code; empty when either side has no skill data."""
    mine = (_by_code().get(from_code) or {}).get("skills")
    theirs = (_by_code().get(to_code) or {}).get("skills")
    if not mine or not theirs:
        return []
    return _gaps(mine, theirs, top)


def onet_code(code: str) -> str | None:
    """The full O*NET-SOC code (29-1171 -> 29-1171.00) for linking."""
    return (_by_code().get(code) or {}).get("onet")


def skill_profile(code: str) -> dict[str, float]:
    """The occupation's skill levels, highest first. For explaining a match."""
    occ = _by_code().get(code)
    if occ is None or not occ.get("skills"):
        return {}
    pairs = zip(skill_names(), occ["skills"])
    return dict(sorted(pairs, key=lambda kv: -kv[1]))
