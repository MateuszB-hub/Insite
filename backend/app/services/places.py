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
  unknown    not a place we know       "new yotrk"   -> suggestions: New York, NY
  invalid    no letters to go on       "3", "."      -> not searched

Only ok / ambiguous / state are searched, by their full name ("Austin, TX"),
so the board never has to guess.
"""

import difflib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data" / "places.json"

#: What people type that the Census doesn't call a place.
ALIASES = {
    "nyc": ("New York", "NY"), "new york city": ("New York", "NY"),
    "la": ("Los Angeles", "CA"), "sf": ("San Francisco", "CA"),
    "dc": ("Washington", "DC"), "washington dc": ("Washington", "DC"),
    "philly": ("Philadelphia", "PA"), "vegas": ("Las Vegas", "NV"),
}


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

    @property
    def searchable(self) -> bool:
        return self.status in {"ok", "ambiguous", "state"}


def _norm(text: str) -> str:
    """'St. Louis,  MO' -> 'st louis mo'; 'Saint Louis' -> 'st louis'."""
    words = re.findall(r"[a-z0-9]+", text.lower().replace("'", ""))
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
    if len(re.findall(r"[A-Za-z]", raw)) < 2:
        return Resolution(raw, "invalid")
    by_name, state_names, codes = _data()
    norm = _norm(raw)

    if norm in ALIASES:
        name, st = ALIASES[norm]
        return Resolution(raw, "ok", f"{name}, {st}")

    name, state = _split_state(norm)
    candidates = [p for p in by_name.get(name, []) if state is None or p.state == state]
    if candidates:
        best = candidates[0]
        others = [p.label for p in candidates[1:4]]
        # "New York": the city, but say the state is also an option. Offered
        # as "New York State" so choosing it can't resolve back to the city.
        if state is None and name in state_names:
            others.append(f"{codes[state_names[name]]} State")
        status = "ambiguous" if state is None and others else "ok"
        return Resolution(raw, status, best.label, others[:4])

    whole = norm[:-len(" state")] if norm.endswith(" state") else norm
    if state is None and whole in state_names:
        return Resolution(raw, "state", codes[state_names[whole]])
    if state is None and norm.upper() in codes and len(norm) == 2:
        return Resolution(raw, "state", codes[norm.upper()])

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
