"""What living costs where: BEA Regional Price Parities, and which metro each
place and county belongs to.

    python -m app.scripts.vendor_col

Writes app/data/col.json:
  states   {"TX": {"all": 97.5, "housing": 99.9}}           the state average
  metros   {"19100": {"name": "Dallas-Fort Worth-Arlington, TX", "all": .., "housing": ..}}
  counties {"TX|collin county": "19100"}                     county -> metro
  places   {"TX|plano": "19100"}                             city -> metro

Why: a mentor asked for cost-of-living differences when switching cities
("100k is basically 70k here"). An index of 100 is the US average; pay is
compared as pay x (home index / job index). Facts from official data and
arithmetic -- no model, no live call: the parities are published once a year.

A city's metro comes from its county. The Census publishes no place-to-county
file, so each city takes the county it shares the most land with through the
ZIP code areas (2020 ZCTA relationship files) -- Plano goes to Collin County,
then to the Dallas metro.

Public domain: BEA Regional Price Parities (SARPP, MARPP; latest year), the
Census 2023 CBSA delineation (list 1) and 2023 Gazetteer, and the 2020 ZCTA
relationship files.
"""

import csv
import io
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree

from app.scripts.vendor_places import (
    COUNTIES_ZIP, PLACES_ZIP, STATES, ZCTA_COUNTY, ZCTA_PLACE, _gazetteer, _get, _relationship, clean,
)

OUT = Path(__file__).resolve().parent.parent / "data" / "col.json"
BEA = "https://apps.bea.gov/regional/zip/"
DELINEATION = ("https://www2.census.gov/programs-surveys/metro-micro/geographies/"
               "reference-files/2023/delineation-files/list1_2023.xlsx")
ALL_ITEMS, HOUSING = "1", "3"
_BY_NAME = {name: code for code, name in STATES.items()}


def _bea(name: str) -> tuple[str, dict[str, dict[str, float]], dict[str, str]]:
    """(year, {geofips: {"all": .., "housing": ..}}, {geofips: name}) from a BEA zip."""
    with zipfile.ZipFile(io.BytesIO(_get(BEA + f"{name}.zip"))) as z:
        member = next(n for n in z.namelist() if n.startswith(name) and n.endswith(".csv"))
        rows = list(csv.DictReader(io.StringIO(z.read(member).decode("latin-1"))))
    years = [c for c in rows[0] if c.isdigit()]
    year = max(years)
    values: dict[str, dict[str, float]] = defaultdict(dict)
    names: dict[str, str] = {}
    for row in rows:
        fips, line = (row.get("GeoFIPS") or "").strip().strip('"'), (row.get("LineCode") or "").strip()
        value = (row.get(year) or "").strip()
        if not fips or line not in (ALL_ITEMS, HOUSING) or not re.fullmatch(r"[\d.]+", value):
            continue
        values[fips]["all" if line == ALL_ITEMS else "housing"] = float(value)
        names[fips] = re.sub(r"\s*\(Metropolitan Statistical Area\)\s*", "", row["GeoName"]).strip()
    return year, values, names


def _xlsx_rows(data: bytes) -> list[list[str]]:
    """First sheet of an .xlsx as rows of text (standard library only)."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared = [
            "".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t"))
            for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns)]
        sheet = ElementTree.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.iter(f"{{{ns['m']}}}row"):
        cells: dict[int, str] = {}
        for c in row.findall("m:c", ns):
            col = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(re.match(r"[A-Z]+", c.get("r")).group())))
            v = c.find("m:v", ns)
            text = "" if v is None else (shared[int(v.text)] if c.get("t") == "s" else v.text or "")
            cells[col] = text
        rows.append([cells.get(i, "") for i in range(1, max(cells, default=0) + 1)])
    return rows


def _county_metros() -> dict[str, str]:
    """County FIPS (5 digits) -> metro CBSA code, metropolitan areas only."""
    rows = _xlsx_rows(_get(DELINEATION))
    header_at = next(i for i, r in enumerate(rows) if "CBSA Code" in r)
    header = rows[header_at]
    col = {name: header.index(name) for name in header if name}
    out = {}
    for r in rows[header_at + 1:]:
        if len(r) <= col["FIPS County Code"] or not r[col["CBSA Code"]]:
            continue
        if r[col["Metropolitan/Micropolitan Statistical Area"]] != "Metropolitan Statistical Area":
            continue
        out[r[col["FIPS State Code"]].zfill(2) + r[col["FIPS County Code"]].zfill(3)] = r[col["CBSA Code"]]
    return out


def main() -> None:
    print("  price parities (BEA)…")
    year, state_values, state_names = _bea("SARPP")
    _, metro_values, metro_names = _bea("MARPP")
    states = {}
    for fips, v in state_values.items():
        code = _BY_NAME.get(state_names[fips])
        if code and "all" in v:
            states[code] = v
    print("  metro counties (Census delineation)…")
    county_metro = _county_metros()

    print("  counties and places (gazetteer)…")
    counties = _gazetteer(COUNTIES_ZIP)
    county_key = {row["GEOID"]: f"{row['USPS']}|{row['NAME'].lower()}" for row in counties}
    place_key = {row["GEOID"]: f"{row['USPS']}|{clean(row['NAME']).lower()}" for row in _gazetteer(PLACES_ZIP)}

    print("  places to counties, through ZIP areas…")
    zcta_county: dict[str, tuple[int, str]] = {}
    for row in _relationship(ZCTA_COUNTY):
        zcta, geoid = row["GEOID_ZCTA5_20"], row["GEOID_COUNTY_20"]
        if zcta and geoid:
            part = int(row["AREALAND_PART"] or 0)
            if zcta not in zcta_county or part > zcta_county[zcta][0]:
                zcta_county[zcta] = (part, geoid)
    weight: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in _relationship(ZCTA_PLACE):
        zcta, geoid = row["GEOID_ZCTA5_20"], row["GEOID_PLACE_20"]
        if zcta in zcta_county and geoid:
            weight[geoid][zcta_county[zcta][1]] += int(row["AREALAND_PART"] or 0)

    metros = {code: {"name": metro_names[code], **v} for code, v in metro_values.items()
              if "all" in v and code in set(county_metro.values())}
    county_out = {county_key[g]: m for g, m in county_metro.items() if g in county_key and m in metros}
    places_out = {}
    for geoid, by_county in weight.items():
        county = max(by_county, key=by_county.get)
        metro = county_metro.get(county)
        if metro in metros and geoid in place_key:
            places_out.setdefault(place_key[geoid], metro)

    OUT.write_text(json.dumps({"year": year, "states": states, "metros": metros,
                               "counties": county_out, "places": places_out}, separators=(",", ":")))
    print(f"  {year}: {len(states)} states, {len(metros)} metros, {len(county_out)} counties, "
          f"{len(places_out)} places -> {OUT.name}, {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
