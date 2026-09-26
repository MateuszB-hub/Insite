"""Download and compact the public O*NET data files we rely on.

O*NET's database text files are public; only the Web Services *API* requires
approval. Vendoring them means occupation resolution, relatedness, job zones
and skill matching all work offline with no credentials and no startup cost.

    python -m app.scripts.vendor_onet

Writes app/data/occupations.json (titles, descriptions, job zone, skills),
app/data/related.json (O*NET's own relatedness graph) and
app/data/abbreviations.json (job-title abbreviations learned from O*NET's
alternate and reported titles, e.g. QA <-> quality assurance).
"""

import csv
import io
import json
from pathlib import Path

import httpx

from app.services.labor import abbreviations

BASE = "https://www.onetcenter.org/dl_files/database/db_30_0_text/"
OUT = Path(__file__).resolve().parent.parent / "data"
UA = {"User-Agent": "Insite/0.1 (career pathway tool)"}

#: Only the skills we keep. All 35 are useful, but the level (LV) scale is
#: what answers "do I already meet the bar for this job".
SCALE = "LV"


def fetch(name: str) -> list[dict]:
    url = BASE + name.replace(" ", "%20")
    response = httpx.get(url, timeout=120, follow_redirects=True, headers=UA)
    response.raise_for_status()
    return list(csv.DictReader(io.StringIO(response.text), delimiter="\t"))


def base_soc(onet_code: str) -> str:
    """29-1141.00 -> 29-1141, the form BLS OEWS uses."""
    return onet_code.split(".")[0]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    print("  fetching occupations…")
    occupations, seen = [], set()
    for row in fetch("Occupation Data.txt"):
        onet = row["O*NET-SOC Code"]
        soc = base_soc(onet)
        if soc in seen and not onet.endswith(".00"):
            continue
        seen.add(soc)
        occupations.append({
            "soc": soc,
            "onet": onet,
            "title": row["Title"],
            "description": (row["Description"] or "")[:400],
        })
    by_soc = {o["soc"]: o for o in occupations}

    print("  fetching job zones…")
    zones: dict[str, int] = {}
    for row in fetch("Job Zones.txt"):
        soc = base_soc(row["O*NET-SOC Code"])
        try:
            zones.setdefault(soc, int(row["Job Zone"]))
        except (ValueError, KeyError):
            continue
    for occ in occupations:
        occ["job_zone"] = zones.get(occ["soc"])

    print("  fetching skills…")
    # skills[soc][skill name] = level 0-7
    skills: dict[str, dict[str, float]] = {}
    for row in fetch("Skills.txt"):
        if row.get("Scale ID") != SCALE:
            continue
        if row.get("Not Relevant") == "Y":
            continue
        soc = base_soc(row["O*NET-SOC Code"])
        if soc not in by_soc:
            continue
        try:
            value = float(row["Data Value"])
        except (TypeError, ValueError):
            continue
        skills.setdefault(soc, {})[row["Element Name"]] = round(value, 2)

    # Fixed ordering so every occupation is a comparable vector.
    names = sorted({n for per in skills.values() for n in per})
    for occ in occupations:
        per = skills.get(occ["soc"])
        occ["skills"] = [per.get(n, 0.0) for n in names] if per else None

    print("  fetching relatedness graph…")
    related: dict[str, list[str]] = {}
    for row in fetch("Related Occupations.txt"):
        src = base_soc(row["O*NET-SOC Code"])
        dst = base_soc(row["Related O*NET-SOC Code"])
        if src == dst or src not in by_soc or dst not in by_soc:
            continue
        bucket = related.setdefault(src, [])
        if dst not in bucket:
            bucket.append(dst)

    (OUT / "occupations.json").write_text(
        json.dumps({"skill_names": names, "occupations": occupations}, indent=0)
    )
    (OUT / "related.json").write_text(json.dumps(related, indent=0))

    print("  learning title abbreviations…")
    title_rows = [(r["Alternate Title"], r.get("Short Title") or "")
                  for r in fetch("Alternate Titles.txt")]
    title_rows += [(r["Reported Job Title"], "") for r in fetch("Sample of Reported Titles.txt")]
    abbrev = abbreviations.derive(abbreviations.pairs_from_titles(title_rows))
    (OUT / "abbreviations.json").write_text(json.dumps(abbrev, indent=0, sort_keys=True))

    with_skills = sum(1 for o in occupations if o["skills"])
    with_zone = sum(1 for o in occupations if o["job_zone"])
    print(f"\n  occupations      : {len(occupations)}")
    print(f"  with skills      : {with_skills}  ({len(names)} dimensions)")
    print(f"  with job zone    : {with_zone}")
    print(f"  relatedness graph: {len(related)} sources, "
          f"{sum(len(v) for v in related.values())} edges")
    print(f"  abbreviations    : {len(abbrev)}")
    for f in ("occupations.json", "related.json", "abbreviations.json"):
        print(f"  {f:22} {(OUT / f).stat().st_size:>9,} bytes")


if __name__ == "__main__":
    main()
