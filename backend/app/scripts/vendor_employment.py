"""National employment per occupation, from the BLS OEWS survey.

    python -m app.scripts.vendor_employment

Writes app/data/employment.json: {"year": "2025", "by_soc": {"15-1252": 1687890, ...}}.
Used to put the most common occupation first when a title could mean several
("project manager": Project Management Specialists, 1.07M people, before
Architectural and Engineering Managers, 220k).

Needs BLS_API_KEY (OEWS returns no data without one). BLS's bulk download
refuses scripted requests, so this uses the API: 50 series per request,
about 18 requests for every occupation in occupations.json.
"""

import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.services.labor import taxonomy  # noqa: E402
from app.services.labor.bls import DT_EMPLOYMENT, BlsSource, oews_series_id  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "employment.json"
BATCH = 50
YEARS = ("2024", "2025")


async def main() -> None:
    source = BlsSource()
    ok, reason = source.configured()
    if not ok:
        raise SystemExit(f"BLS not configured: {reason}")

    codes = sorted({occ["soc"] for occ in taxonomy.all_occupations()})
    by_soc: dict[str, int] = {}
    latest_year = ""
    for start in range(0, len(codes), BATCH):
        chunk = codes[start:start + BATCH]
        ids = {oews_series_id(code, DT_EMPLOYMENT): code for code in chunk}
        data = await source._fetch(list(ids), YEARS)
        if data.get("status") != "REQUEST_SUCCEEDED":
            raise SystemExit(f"BLS error: {data.get('message')}")
        for series in data["Results"]["series"]:
            rows = series.get("data") or []
            if not rows:
                continue
            try:
                by_soc[ids[series["seriesID"]]] = int(float(rows[0]["value"].replace(",", "")))
            except (KeyError, ValueError):
                continue
            latest_year = max(latest_year, rows[0].get("year", ""))
        print(f"  {min(start + BATCH, len(codes))}/{len(codes)} occupations")

    OUT.write_text(json.dumps({"year": latest_year, "by_soc": by_soc}, indent=0, sort_keys=True))
    print(f"  employment for {len(by_soc)} of {len(codes)} occupations ({latest_year}) -> {OUT.name}")


if __name__ == "__main__":
    asyncio.run(main())
