"""National wages and employment per occupation, from the BLS OEWS survey.

    python -m app.scripts.vendor_bls

Writes app/data/oews.json:
    {"year": "2025", "by_soc": {"15-1252": {"median": 135980, "mean": 148100,
                                            "employment": 1687890}, ...}}

OEWS is published once a year, so asking BLS on every page view bought
nothing and cost a lot: each Career Pathway made ~12 wage requests, and the
key's 500-a-day limit ran out in an afternoon of testing, leaving the live
site without pay figures. With this file the site makes no BLS calls at all;
re-run it when BLS publishes a new year (each spring).

Needs BLS_API_KEY (OEWS returns no data without one). BLS's bulk downloads
refuse scripted requests, so this uses the API: 3 series per occupation,
50 per request, ~53 requests -- about a tenth of a day's allowance. If BLS
refuses part-way (daily limit), nothing is written.
"""

import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.services.labor import taxonomy  # noqa: E402
from app.services.labor.bls import (  # noqa: E402
    DT_ANNUAL_MEAN,
    DT_ANNUAL_MEDIAN,
    DT_EMPLOYMENT,
    BlsSource,
    oews_series_id,
)

OUT = Path(__file__).resolve().parent.parent / "data" / "oews.json"
BATCH = 50
YEARS = ("2024", "2025")
FIELDS = {DT_EMPLOYMENT: "employment", DT_ANNUAL_MEDIAN: "median", DT_ANNUAL_MEAN: "mean"}


class BlsRefused(RuntimeError):
    """BLS answered but would not serve the request (e.g. the daily limit)."""


def parse(data: dict, ids: dict[str, tuple[str, str]], into: dict[str, dict]) -> str:
    """Fold one BLS response into `into`; return the latest year seen.

    `ids` maps series id -> (soc, field). Raises BlsRefused unless the
    request succeeded, so a half-refused run never gets written.
    """
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise BlsRefused("; ".join(data.get("message") or []) or str(data.get("status")))
    latest = ""
    for series in data.get("Results", {}).get("series", []):
        rows = series.get("data") or []
        if not rows or series.get("seriesID") not in ids:
            continue
        soc, field = ids[series["seriesID"]]
        try:
            value = float(rows[0]["value"].replace(",", ""))
        except (KeyError, ValueError):
            continue
        into.setdefault(soc, {})[field] = int(value) if field == "employment" else value
        latest = max(latest, rows[0].get("year", ""))
    return latest


async def main() -> None:
    source = BlsSource()
    ok, reason = source.configured()
    if not ok:
        raise SystemExit(f"BLS not configured: {reason}")

    codes = sorted({occ["soc"] for occ in taxonomy.all_occupations()})
    series = [(oews_series_id(code, dt), code, field) for code in codes for dt, field in FIELDS.items()]

    by_soc: dict[str, dict] = {}
    year = ""
    for start in range(0, len(series), BATCH):
        chunk = series[start:start + BATCH]
        ids = {sid: (code, field) for sid, code, field in chunk}
        try:
            year = max(year, parse(await source._fetch(list(ids), YEARS), ids, by_soc))
        except BlsRefused as exc:
            raise SystemExit(f"BLS refused the request, nothing written: {exc}")
        print(f"  {min(start + BATCH, len(series))}/{len(series)} series")

    with_pay = sum(1 for v in by_soc.values() if "median" in v or "mean" in v)
    OUT.write_text(json.dumps({"year": year, "by_soc": by_soc}, indent=0, sort_keys=True))
    print(f"  {len(by_soc)} occupations, {with_pay} with pay ({year}) -> {OUT.name}")


if __name__ == "__main__":
    asyncio.run(main())
