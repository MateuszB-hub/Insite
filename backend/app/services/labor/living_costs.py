"""Living costs by place: what a salary is worth somewhere else.

A mentor, on switching cities: "100k is basically 70k here." The BEA's
Regional Price Parities put each metro area and state against the US average
(100): San Francisco 115.6, Dallas 103.1, Austin 98.1 (2024). So $100k in San
Francisco buys about what $89k does in Dallas: pay x home index / job index.

Everything here is a lookup in app/data/col.json (app/scripts/vendor_col.py)
and arithmetic -- no model, no live call. A place outside any metro area gets
its state's average, and says so. It's an average of all living costs, most
of the difference is housing, and taxes aren't in it; the page says that too.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.services import places

_DATA = Path(__file__).resolve().parent.parent.parent / "data" / "col.json"
SOURCE = "BEA Regional Price Parities"
#: Differences smaller than this aren't worth a line on a job card.
MIN_DIFFERENCE = 0.03


@dataclass(frozen=True)
class Area:
    #: "Dallas-Fort Worth-Arlington, TX" or "Texas".
    name: str
    #: "metro" or "state": how precisely it's known.
    level: str
    #: All living costs, US average = 100.
    index: float
    housing: float | None
    year: str

    @property
    def short(self) -> str:
        """'Dallas' for a metro, 'Texas' for a state."""
        return self.name.split("-")[0].split(",")[0] if self.level == "metro" else self.name


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(_DATA.read_text())


def _metro(code: str | None) -> Area | None:
    d = _data()
    m = d["metros"].get(code or "")
    if not m:
        return None
    return Area(m["name"], "metro", m["all"], m.get("housing"), d["year"])


def _state(code: str | None) -> Area | None:
    d = _data()
    s = d["states"].get(code or "")
    if not s:
        return None
    name = places._data()[2].get(code, code)
    return Area(name, "state", s["all"], s.get("housing"), d["year"])


def area(state: str | None, city: str | None = None, county: str | None = None) -> Area | None:
    """The most precise area known: the city's metro, the county's, or the state."""
    if not state:
        return None
    d = _data()
    for table, name in (("places", city), ("counties", county)):
        if name:
            found = _metro(d[table].get(f"{state}|{name.strip().lower()}"))
            if found:
                return found
    return _state(state)


def area_for_place(text: str | None) -> Area | None:
    """Where someone lives, as typed in their profile: "Plano, TX", "78701", "Texas"."""
    if not text or not text.strip():
        return None
    resolved = places.resolve(text)
    if not resolved.searchable or not resolved.place:
        return None
    if resolved.note and places.US_ONLY in resolved.note:
        return None   # "London" is London, OH only as a search fallback, never as home
    label = resolved.place
    if resolved.status == "state":
        return _state(label if len(label) == 2 else places._data()[1].get(places._norm(label)))
    name, _, state = label.rpartition(", ")
    if name.endswith(" County"):
        return area(state, county=name)
    return area(state, city=name)


def area_for_posting(adzuna_area: list[str] | None) -> Area | None:
    """An advert's place from the board's own breakdown: ["US", "Texas", "Collin County", "Plano"]."""
    parts = [p for p in (adzuna_area or []) if p]
    if len(parts) < 2 or parts[0] != "US":
        return None
    state = places._data()[1].get(places._norm(parts[1]))
    if not state:
        return None
    city = parts[3] if len(parts) > 3 else None
    county = parts[2] if len(parts) > 2 else None
    if city:
        # Through the place check, so a borough is New York City's metro
        # ("Brooklyn" is no Census place) and aliases apply.
        found = area_for_place(f"{city}, {state}")
        if found and found.level == "metro":
            return found
    if county and not county.endswith(" County"):
        # The board's third level is sometimes a city region ("Dallas"), not a county.
        found = area(state, city=city, county=county + " County")
        if found and found.level == "metro":
            return found
        return area(state, city=city or county)
    return area(state, city=city, county=county)


def compare(low: float | None, high: float | None, job: Area | None, home: Area | None) -> dict | None:
    """What pay of `low`-`high` in the job's area is worth at home, or None
    when there's no pay, no known area, or no real difference."""
    if not (low or high) or not job or not home or job.name == home.name:
        return None
    ratio = home.index / job.index
    if abs(1 - ratio) < MIN_DIFFERENCE:
        return None
    return {
        # Rounded to $1,000: an index average can't support more precision.
        "equivalent_min": round((low or high) * ratio, -3),
        "equivalent_max": round((high or low) * ratio, -3),
        # Living costs there, relative to home: +12 means 12% higher there.
        "difference_pct": round((job.index / home.index - 1) * 100),
        "job_area": job.short, "job_level": job.level,
        "home_area": home.short, "home_level": home.level,
        "housing_difference_pct": (round((job.housing / home.housing - 1) * 100)
                                   if job.housing and home.housing else None),
        "source": f"{SOURCE}, {job.year}",
    }
