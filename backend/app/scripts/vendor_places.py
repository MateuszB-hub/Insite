"""Every US place a job search could name, from the Census Bureau.

    python -m app.scripts.vendor_places

Writes app/data/places.json: states, and every city, town, census-designated
place (Arlington, VA; Silver Spring, MD) and county, with 2023 population
where the Census publishes it -- so a location can be checked before it is
searched, typos can be caught ("new yotrk" -> New York, NY), and a name that
several places share lists the largest first (Springfield, MO before IL).

Why: the job board guesses at anything it is given and says nothing when it
can't match. Live, "new yotrk" returned no jobs without a word, "3" was read
as Puerto Rico and "." as Alabama.

Also writes app/data/zips.json: each 5-digit ZIP code (ZCTA) and the place it
lies in (78701 -> Austin, TX), or its county when no one place covers most of
it, so a ZIP can be searched as a place.

The 2023 estimates skip census-designated places and Puerto Rico -- a third
of all places -- so their 2010 census count stands in. It only ranks places
that share a name (San Juan, PR before San Juan, TX) and is never shown.

Public domain (US Census Bureau): the 2023 Gazetteer place and county files,
the Vintage 2023 population estimates, the 2010 Gazetteer files (2010 counts),
and the 2020 ZCTA relationship files.
"""

import csv
import io
import json
import re
import zipfile
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent.parent / "data" / "places.json"
ZIPS_OUT = OUT.with_name("zips.json")
UA = {"User-Agent": "Insite/0.1 (career research tool)"}

GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/"
PLACES_ZIP = GAZ + "2023_Gaz_place_national.zip"
COUNTIES_ZIP = GAZ + "2023_Gaz_counties_national.zip"
POPEST = "https://www2.census.gov/programs-surveys/popest/datasets/2020-2023/"
CITY_POP = POPEST + "cities/totals/sub-est2023.csv"
COUNTY_POP = POPEST + "counties/totals/co-est2023-alldata.csv"
GAZ_2010 = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
PLACES_2010_ZIP = GAZ_2010 + "Gaz_places_national.zip"
COUNTIES_2010_ZIP = GAZ_2010 + "Gaz_counties_national.zip"
REL = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
ZCTA_PLACE = REL + "tab20_zcta520_place20_natl.txt"
ZCTA_COUNTY = REL + "tab20_zcta520_county20_natl.txt"
#: A ZIP is searched as the place covering at least this share of its land;
#: otherwise as its county.
ZIP_PLACE_SHARE = 0.5

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico",
}
BY_STATE_NAME = {v: k for k, v in STATES.items()}

#: Census type words at the end of a place name ("Austin city", "Abanda CDP").
_TYPE = re.compile(
    r"\s+(?:city and borough|unified government|consolidated government|metro government|"
    r"metropolitan government|zona urbana|comunidad|CDP|city|town|village|borough|township|"
    r"municipality)$")
#: Consolidated city-counties, known by the city's name alone.
_CONSOLIDATED = {"Nashville-Davidson": "Nashville", "Butte-Silver Bow": "Butte",
                 "Lexington-Fayette": "Lexington", "Urban Honolulu": "Honolulu"}


def clean(raw: str) -> str:
    """'Austin city' -> 'Austin'; 'Louisville/Jefferson County metro government
    (balance)' -> 'Louisville'. Real hyphenated names (Winston-Salem) stay."""
    name = re.sub(r"\s*\(balance\)$", "", raw.strip())
    name = _TYPE.sub("", name)
    name = _CONSOLIDATED.get(name, name)
    if "/" in name:
        name = name.split("/")[0]
    m = re.match(r"^(.+?)-[A-Z][\w .]* County$", name)
    if m:
        name = m.group(1)
    return name.strip()


def _get(url: str) -> bytes:
    response = httpx.get(url, headers=UA, timeout=120, follow_redirects=True)
    response.raise_for_status()
    return response.content


def _gazetteer(url: str) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(_get(url))) as z:
        data = z.read(z.namelist()[0])
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:  # the 2010 files are Latin-1
        text = data.decode("latin-1")
    return [{k.strip(): (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(io.StringIO(text), delimiter="\t")]


def _popest(url: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(_get(url).decode("latin-1"))))


def _relationship(url: str) -> list[dict]:
    text = _get(url).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text), delimiter="|"))


def _pop_2010(url: str) -> dict[str, int]:
    """GEOID -> 2010 census count."""
    return {row["GEOID"]: int(row["POP10"] or 0) for row in _gazetteer(url)}


def _zips(places: list[dict], counties: list[dict], index: dict[tuple[str, str], int]) -> dict[str, int]:
    """ZIP -> index into the places list: the place covering most of it, or its county."""
    by_geoid = {row["GEOID"]: (clean(row["NAME"]), row["USPS"]) for row in places}
    by_geoid.update({row["GEOID"]: (row["NAME"], row["USPS"]) for row in counties})

    def best(url: str, geoid_col: str) -> dict[str, tuple[int, int, str]]:
        """ZIP -> (overlap, ZIP land, GEOID) for the largest overlap."""
        out: dict[str, tuple[int, int, str]] = {}
        for row in _relationship(url):
            zcta, geoid = row["GEOID_ZCTA5_20"], row[geoid_col]
            if not zcta or not geoid:
                continue
            part, land = int(row["AREALAND_PART"] or 0), int(row["AREALAND_ZCTA5_20"] or 0)
            if zcta not in out or part > out[zcta][0]:
                out[zcta] = (part, land, geoid)
        return out

    in_place = best(ZCTA_PLACE, "GEOID_PLACE_20")
    in_county = best(ZCTA_COUNTY, "GEOID_COUNTY_20")
    zips: dict[str, int] = {}
    for zcta in sorted(set(in_place) | set(in_county)):
        chosen = None
        if zcta in in_place:
            part, land, geoid = in_place[zcta]
            if land and part / land >= ZIP_PLACE_SHARE:
                chosen = by_geoid.get(geoid)
        if chosen is None and zcta in in_county:
            chosen = by_geoid.get(in_county[zcta][2])
        if chosen in index:
            zips[zcta] = index[chosen]
    return zips


def main() -> None:
    print("  places (gazetteer)…")
    places = _gazetteer(PLACES_ZIP)
    print("  counties (gazetteer)…")
    counties = _gazetteer(COUNTIES_ZIP)

    print("  2010 counts (for places the 2023 estimates skip)…")
    places_2010 = _pop_2010(PLACES_2010_ZIP)
    counties_2010 = _pop_2010(COUNTIES_2010_ZIP)

    print("  population estimates…")
    city_pop = {(r["STNAME"], r["NAME"]): int(r["POPESTIMATE2023"])
                for r in _popest(CITY_POP) if r["SUMLEV"] in {"162", "157", "061", "071"}}
    county_pop = {(r["STNAME"], r["CTYNAME"]): int(r["POPESTIMATE2023"])
                  for r in _popest(COUNTY_POP) if r["SUMLEV"] == "050"}

    out: dict[tuple[str, str], int] = {}
    for row in places:
        st = row["USPS"]
        if st not in STATES:
            continue
        name = clean(row["NAME"])
        pop = city_pop.get((STATES[st], row["NAME"]), 0) or places_2010.get(row["GEOID"], 0)
        key = (name, st)
        out[key] = max(out.get(key, 0), pop)
    for row in counties:
        st = row["USPS"]
        if st not in STATES:
            continue
        key = (row["NAME"], st)
        pop = county_pop.get((STATES[st], row["NAME"]), 0) or counties_2010.get(row["GEOID"], 0)
        out[key] = max(out.get(key, 0), pop)

    rows = sorted(([name, st, pop] for (name, st), pop in out.items()), key=lambda r: (-r[2], r[0]))
    OUT.write_text(json.dumps({"states": STATES, "places": rows}, separators=(",", ":")))
    with_pop = sum(1 for r in rows if r[2])
    print(f"  {len(rows)} places ({with_pop} with population) -> {OUT.name}, "
          f"{OUT.stat().st_size:,} bytes")

    print("  ZIP codes (2020 relationship files)…")
    index = {(name, st): i for i, (name, st, _) in enumerate(rows)}
    zips = _zips(places, counties, index)
    ZIPS_OUT.write_text(json.dumps(zips, separators=(",", ":")))
    print(f"  {len(zips)} ZIP codes -> {ZIPS_OUT.name}, {ZIPS_OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
