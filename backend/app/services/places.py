"""Check a typed location against real US places before searching it.

The job board guesses at anything and says nothing when it can't match:
live, "new yotrk" returned no jobs without a word, "3" was read as Puerto Rico
and "." as Alabama, and a bare "Springfield" meant Massachusetts. So every
location is resolved here first, against the Census place list
(app/data/places.json, from app/scripts/vendor_places.py):

  ok         a known place             "austin tx"   -> Austin, TX
  ambiguous  a name several share      "springfield" -> Springfield, MO (largest)
                                        and the others offered
  state      a whole state             "texas"       -> Texas
  region     a metro area              "bay area"    -> San Francisco, Oakland, San Jose
  remote     not a place at all        "remote"      -> the Remote only filter instead
  unknown    not a place we know       "new yotrk"   -> suggestions: New York, NY
  invalid    no letters to go on       "3", "."      -> not searched

Only ok / ambiguous / state / region are searched, by their full names
("Austin, TX"), so the board never has to guess. A ZIP code is searched as
the place it lies in (78701 -> Austin, TX, from app/data/zips.json), and a
`note` says whenever what's searched differs from what was typed.
"""

import difflib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data" / "places.json"
_ZIPS = _DATA.with_name("zips.json")

#: What people type that the Census doesn't call a place.
ALIASES = {
    "nyc": ("New York", "NY"), "new york city": ("New York", "NY"),
    "la": ("Los Angeles", "CA"), "sf": ("San Francisco", "CA"),
    "dc": ("Washington", "DC"), "washington dc": ("Washington", "DC"),
    "philly": ("Philadelphia", "PA"), "vegas": ("Las Vegas", "NV"),
}

#: NYC boroughs aren't Census places, and each shares its name with small
#: towns elsewhere (Brooklyn, OH; Manhattan, KS). Job boards list them as
#: New York, NY.
BOROUGHS = {"brooklyn", "manhattan", "queens", "bronx", "the bronx", "staten island"}

#: Metro areas people search by name, as the cities a board can search.
#: Kept to well-known ones, three places at most (one request each).
REGIONS = {
    "bay area": ["San Francisco, CA", "Oakland, CA", "San Jose, CA"],
    "silicon valley": ["San Jose, CA", "Sunnyvale, CA", "Palo Alto, CA"],
    "dfw": ["Dallas, TX", "Fort Worth, TX"],
    "dallas ft worth": ["Dallas, TX", "Fort Worth, TX"],
    "twin cities": ["Minneapolis, MN", "St. Paul, MN"],
    "research triangle": ["Raleigh, NC", "Durham, NC"],
    "the triangle": ["Raleigh, NC", "Durham, NC"],
}
REGIONS.update({"sf bay area": REGIONS["bay area"], "san francisco bay area": REGIONS["bay area"]})

#: Typed into "Where" to mean "don't care where": the Remote filter's job.
REMOTE_WORDS = {"remote", "remote only", "fully remote", "remote us", "remote usa",
                "us remote", "remote united states", "wfh", "work from home",
                "anywhere", "telecommute", "virtual"}

#: Well-known places outside the US. Insite's sources are US-only, so these
#: are named as such instead of quietly becoming London, OH or a near-miss.
FOREIGN = {
    "london", "manchester", "edinburgh", "dublin", "paris", "berlin", "munich",
    "amsterdam", "brussels", "zurich", "geneva", "vienna", "prague", "warsaw",
    "madrid", "barcelona", "lisbon", "rome", "milan", "stockholm", "copenhagen",
    "oslo", "helsinki", "toronto", "vancouver", "montreal", "calgary", "ottawa",
    "mexico city", "sao paulo", "buenos aires", "bogota", "tokyo", "seoul",
    "beijing", "shanghai", "shenzhen", "hong kong", "singapore", "bangalore",
    "bengaluru", "mumbai", "delhi", "new delhi", "hyderabad", "pune", "chennai",
    "dubai", "tel aviv", "sydney", "melbourne", "auckland", "manila", "jakarta",
    "bangkok", "kuala lumpur", "lagos", "nairobi", "cape town", "johannesburg",
    "canada", "uk", "united kingdom", "england", "ireland", "germany", "france",
    "india", "australia", "mexico", "europe",
}
US_ONLY = "Insite lists US jobs only."
#: Canadian provinces, as typed after a city ("Toronto ON").
PROVINCES = {"on", "qc", "bc", "ab", "mb", "sk", "ns", "nb", "nl", "pei", "ontario",
             "quebec", "british columbia", "alberta"}

_ZIP = re.compile(r"^(?:(.*?)[\s,]+)?(\d{5})(?:-\d{4})?$")
#: Canadian (M5V 2T6) and UK (SW1A 1AA) postcodes.
_POSTCODE = re.compile(r"^(?:[A-Za-z]\d[A-Za-z][ -]?\d[A-Za-z]\d|[A-Za-z]{1,2}\d[A-Za-z\d]?\s*\d[A-Za-z]{2})$")
#: "Greater Boston area", "Denver metro": the city itself.
_METRO = re.compile(r"^(?:greater )?(.+?)(?: (?:metro|metropolitan))?(?: area)?$")


@dataclass(frozen=True)
class Place:
    name: str
    state: str
    population: int

    @property
    def label(self) -> str:
        return f"{self.name}, {self.state}"


@dataclass
class Resolution:
    input: str
    status: str                      # ok | ambiguous | state | unknown | invalid
    place: str | None = None         # what to search, e.g. "Austin, TX"
    alternatives: list[str] = field(default_factory=list)   # other places, same name
    suggestions: list[str] = field(default_factory=list)    # for unknown: did you mean
    note: str | None = None          # when what's searched isn't what was typed
    places: list[str] = field(default_factory=list)         # everything searched
    remote: bool = False             # "Austin (remote)": remote jobs wanted too

    def __post_init__(self) -> None:
        if self.place and not self.places:
            self.places = [self.place]

    @property
    def searchable(self) -> bool:
        return self.status in {"ok", "ambiguous", "state", "region"}


def _fold(text: str) -> str:
    """'San José' -> 'San Jose': people type accents both ways."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _norm(text: str) -> str:
    """'St. Louis,  MO' -> 'st louis mo'; 'Saint Louis' -> 'st louis'."""
    words = re.findall(r"[a-z0-9]+", _fold(text).lower().replace("'", ""))
    words = ["st" if w == "saint" else "ft" if w == "fort" else w for w in words]
    return " ".join(words)


@lru_cache(maxsize=1)
def _data() -> tuple[dict[str, list[Place]], dict[str, str], dict[str, str]]:
    """(name -> places, largest first), (state name -> code), (code -> name)."""
    raw = json.loads(_DATA.read_text())
    by_name: dict[str, list[Place]] = {}
    for name, state, pop in raw["places"]:
        by_name.setdefault(_norm(name), []).append(Place(name, state, pop))
    for places in by_name.values():
        places.sort(key=lambda p: -p.population)
    codes = raw["states"]
    return by_name, {_norm(n): c for c, n in codes.items()}, codes


def _foreign_tail(name: str) -> bool:
    """'paris france', 'toronto on', 'london uk': a city, then a country or province."""
    words = name.split()
    return any(len(words) > size and " ".join(words[-size:]) in FOREIGN | PROVINCES
               for size in (1, 2))


@lru_cache(maxsize=1)
def _zips() -> dict[str, str]:
    """ZIP -> the place it's in, e.g. '78701' -> 'Austin, TX'."""
    rows = json.loads(_DATA.read_text())["places"]
    return {z: f"{rows[i][0]}, {rows[i][1]}" for z, i in json.loads(_ZIPS.read_text()).items()}


def _split_state(norm: str) -> tuple[str, str | None]:
    """'austin tx' -> ('austin', 'TX'); 'new york new york' -> ('new york', 'NY')."""
    _, state_names, codes = _data()
    words = norm.split()
    for size in (3, 2, 1):
        if len(words) <= size:
            continue
        tail = " ".join(words[-size:])
        code = state_names.get(tail) or (tail.upper() if size == 1 and tail.upper() in codes else None)
        if code:
            return " ".join(words[:-size]), code
    return norm, None


def _suggest(name: str, state: str | None, limit: int = 3) -> list[str]:
    by_name, _, _ = _data()
    pool = [n for n in by_name if n[:1] == name[:1]] or list(by_name)
    close = difflib.get_close_matches(name, pool, n=12, cutoff=0.75)
    ranked: list[tuple[float, int, Place]] = []
    for n in close:
        score = difflib.SequenceMatcher(None, name, n).ratio()
        for p in by_name[n]:
            if state is None or p.state == state:
                ranked.append((score, p.population, p))
    ranked.sort(key=lambda r: (-round(r[0], 2), -r[1]))
    out: list[str] = []
    for _, _, p in ranked:
        if p.label not in out:
            out.append(p.label)
    return out[:limit]


def resolve(text: str) -> Resolution:
    raw = " ".join(text.split())
    zip_code = _ZIP.match(raw)
    if zip_code:
        prefix, digits = zip_code.groups()
        place = _zips().get(digits)
        if place is not None:
            return Resolution(raw, "ok", place, note=f"ZIP {digits} is in {place}, so that's searched.")
        if not prefix:
            return Resolution(raw, "unknown", note=f"There's no US ZIP code {digits}.")
        # "Austin, TX 00000", "Suite 12345": not a ZIP, so go by the words.
        return _retyped(raw, resolve(prefix))
    if _POSTCODE.match(raw):
        return Resolution(raw, "invalid", note=f"That looks like a postcode outside the US. {US_ONLY}")
    if len(re.findall(r"[A-Za-z]", raw)) < 2:
        return Resolution(raw, "invalid")
    norm = _norm(raw)
    if norm in REMOTE_WORDS:
        return Resolution(raw, "remote", note="Remote isn't a place, so the Remote only filter is on instead.")
    for word in sorted(REMOTE_WORDS, key=len, reverse=True):
        # "Remote - Austin, TX", "Austin (remote)": the place, remote only.
        if norm.startswith(word + " ") or norm.endswith(" " + word):
            rest = norm[len(word) + 1:] if norm.startswith(word + " ") else norm[:-len(word) - 1]
            inner = _retyped(raw, resolve(rest))
            if inner.searchable:
                inner.remote = True
                inner.note = " ".join(filter(None, [
                    f"Searching {', '.join(inner.places)} with the Remote only filter on.", inner.note]))
            return inner
    resolution = _resolve_place(raw, norm)
    if resolution.status == "unknown":
        # "Greater Boston area", "Denver metro": try the city itself.
        core = _METRO.match(norm).group(1)
        if core != norm:
            inner = _resolve_place(raw, core)
            if inner.status != "unknown":
                return inner
    return resolution


def _retyped(raw: str, resolution: Resolution) -> Resolution:
    """A resolution of part of what was typed, reported against all of it."""
    resolution.input = raw
    return resolution


def _resolve_place(raw: str, norm: str) -> Resolution:
    by_name, state_names, codes = _data()
    if norm in ALIASES:
        name, st = ALIASES[norm]
        return Resolution(raw, "ok", f"{name}, {st}")
    name, state = _split_state(norm)
    if name in REGIONS and state in (None, REGIONS[name][0][-2:]):
        places = REGIONS[name]
        cities = ", ".join(p.split(",")[0] for p in places)
        return Resolution(raw, "region", places[0], places=places,
                          note=f"{raw} is searched as {cities}.")
    if name in BOROUGHS and state in (None, "NY"):
        return Resolution(raw, "ok", "New York, NY",
                          note=f"{name.title()} is part of New York City, which job boards list as New York, NY.")
    foreign = state is None and name in FOREIGN
    candidates = [p for p in by_name.get(name, []) if state is None or p.state == state]
    if candidates:
        best = candidates[0]
        others = [p.label for p in candidates[1:4]]
        # "New York": the city, but say the state is also an option -- first,
        # as it's often what's meant. Offered as "New York State" so choosing
        # it can't resolve back to the city.
        if state is None and name in state_names:
            others.insert(0, f"{codes[state_names[name]]} State")
        status = "ambiguous" if state is None and others else "ok"
        note = f"{US_ONLY} Showing {best.label}." if foreign else None
        return Resolution(raw, status, best.label, others[:4], note=note)

    whole = norm[:-len(" state")] if norm.endswith(" state") else norm
    if state is None and whole in state_names:
        return Resolution(raw, "state", codes[state_names[whole]])
    if state is None and norm.upper() in codes and len(norm) == 2:
        return Resolution(raw, "state", codes[norm.upper()])

    if foreign or _foreign_tail(name):
        return Resolution(raw, "unknown", note=US_ONLY)
    if state is not None and name in by_name:
        # "Austin, CA": a real name in the wrong state.
        elsewhere = by_name[name]
        return Resolution(raw, "unknown", suggestions=[p.label for p in elsewhere[:3]],
                          note=f"There's no {elsewhere[0].name} in {codes[state]}.")
    return Resolution(raw, "unknown", suggestions=_suggest(name, state))


def complete(prefix: str, limit: int = 8) -> list[str]:
    """Places starting with what's typed so far, largest first: 'sea' -> Seattle, WA."""
    norm = _norm(prefix)
    if len(norm) < 2:
        return []
    by_name, state_names, codes = _data()
    name, state = _split_state(norm)
    hits = [p for n, places in by_name.items() if n.startswith(name)
            for p in places if state is None or p.state == state]
    hits.sort(key=lambda p: -p.population)
    out = [f"{codes[c]} State" for n, c in state_names.items() if state is None and n.startswith(norm)]
    for p in hits:
        if p.label not in out:
            out.append(p.label)
    return out[:limit]
