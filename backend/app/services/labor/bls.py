"""BLS Public Data API -- official wage data.

Verified behaviour against the live API (Sept 2026):

  * Keyless v2 requests succeed for CES / LNS series (we read a real
    unemployment rate and nonfarm payroll figure with no key).
  * The OEWS survey -- the occupation wage tables we actually want -- returns
    "No Data Available" for EVERY series without a registration key, including
    the series IDs published in BLS's own tutorial. So wages specifically
    require the (free, instant) key.

    https://data.bls.gov/registrationEngine/  (registration)

OEWS series ID is 25 chars:
    OE + U + areatype(1) + area(7) + industry(6) + occupation(6) + datatype(2)
e.g. OEUN000000000000015125213
     ^^ ^ ^ ^^^^^^^ ^^^^^^ ^^^^^^ ^^
     OE U N national all-ind 15-1252 median-annual
"""

import logging
import os

import httpx

from .base import LaborDataError, WageEstimate, WageSource

logger = logging.getLogger(__name__)

API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# OEWS data type codes.
DT_EMPLOYMENT = "01"
DT_ANNUAL_MEAN = "04"
DT_ANNUAL_MEDIAN = "13"

NATIONAL_AREA_TYPE = "N"
NATIONAL_AREA = "0000000"
ALL_INDUSTRIES = "000000"


def oews_series_id(
    soc_code: str,
    datatype: str,
    area_type: str = NATIONAL_AREA_TYPE,
    area: str = NATIONAL_AREA,
    industry: str = ALL_INDUSTRIES,
) -> str:
    """Build an OEWS series ID from an SOC code like '15-1252'."""
    occupation = soc_code.replace("-", "").zfill(6)
    series = f"OEU{area_type}{area}{industry}{occupation}{datatype}"
    if len(series) != 25:
        raise ValueError(f"malformed OEWS series id {series!r} ({len(series)} chars)")
    return series


class BlsSource(WageSource):
    name = "bls"
    label = "BLS Public Data API"
    signup_url = "https://data.bls.gov/registrationEngine/"

    def __init__(self) -> None:
        self.api_key = os.getenv("BLS_API_KEY", "")

    def configured(self) -> tuple[bool, str | None]:
        if not self.api_key:
            # Keyless requests work for some surveys but NOT for OEWS wages,
            # so for this source's purpose we are not configured.
            return False, (
                "BLS_API_KEY not set. Keyless requests work for CES/LNS series "
                "but OEWS wage tables return no data without a key."
            )
        return True, None

    async def _fetch(self, series_ids: list[str], years: tuple[str, str]) -> dict:
        payload: dict = {
            "seriesid": series_ids,
            "startyear": years[0],
            "endyear": years[1],
        }
        if self.api_key:
            payload["registrationkey"] = self.api_key

        async with httpx.AsyncClient(timeout=40.0) as client:
            response = await client.post(API_URL, json=payload)
            response.raise_for_status()
            return response.json()

    async def wages(self, code: str, title: str) -> WageEstimate | None:
        ok, reason = self.configured()
        if not ok:
            raise LaborDataError(reason or "BLS not configured")
        if not code:
            return None

        wanted = {
            oews_series_id(code, DT_ANNUAL_MEDIAN): "median",
            oews_series_id(code, DT_ANNUAL_MEAN): "mean",
            oews_series_id(code, DT_EMPLOYMENT): "employment",
        }

        data = await self._fetch(list(wanted), ("2023", "2025"))
        if data.get("status") != "REQUEST_SUCCEEDED":
            raise LaborDataError(f"BLS error: {data.get('message')}")

        estimate = WageEstimate(
            occupation_code=code, occupation_title=title, source="BLS OEWS"
        )
        for series in data.get("Results", {}).get("series", []):
            rows = series.get("data") or []
            if not rows:
                continue
            latest = rows[0]
            try:
                value = float(latest["value"].replace(",", ""))
            except (KeyError, ValueError):
                continue

            field = wanted.get(series["seriesID"])
            if field == "median":
                estimate.annual_median = value
            elif field == "mean":
                estimate.annual_mean = value
            elif field == "employment":
                estimate.employment = int(value)
            estimate.year = latest.get("year")

        if estimate.annual_median is None and estimate.annual_mean is None:
            return None
        return estimate


class BlsFallback(WageSource):
    """No wage data rather than invented wage data.

    Pay figures are the one thing an applicant is most likely to act on, so
    this returns None instead of a plausible-looking number.
    """

    name = "bls"
    label = "BLS (not configured)"
    signup_url = "https://data.bls.gov/registrationEngine/"

    def configured(self) -> tuple[bool, str | None]:
        return False, "BLS_API_KEY not set; wage figures omitted"

    async def wages(self, code: str, title: str) -> WageEstimate | None:
        return None


class StoredBlsWages(WageSource):
    """BLS OEWS wages from app/data/oews.json -- no network, no daily limit.

    OEWS is published once a year, so a stored copy is as current as asking
    BLS, and asking on every page view ran the key's 500-a-day limit out
    (live pages lost their pay figures). Refreshed by app/scripts/vendor_bls.py.
    """

    name = "bls"
    signup_url = "https://data.bls.gov/registrationEngine/"

    def __init__(self) -> None:
        from app.services.labor import taxonomy  # loaded lazily; it's large

        data = taxonomy.oews()
        self.year = data.get("year") or None
        self.by_soc = {
            soc: v for soc, v in data.get("by_soc", {}).items()
            if v.get("median") is not None or v.get("mean") is not None
        }
        self.label = f"BLS OEWS {self.year} (stored)" if self.year else "BLS OEWS (stored)"

    def configured(self) -> tuple[bool, str | None]:
        if not self.by_soc:
            return False, "No stored wages yet: run python -m app.scripts.vendor_bls"
        return True, None

    async def wages(self, code: str, title: str) -> WageEstimate | None:
        row = self.by_soc.get(code)
        if row is None:
            return None
        return WageEstimate(
            occupation_code=code, occupation_title=title, source="BLS OEWS",
            annual_median=row.get("median"), annual_mean=row.get("mean"),
            employment=row.get("employment"), year=self.year,
        )


def get_wage_source() -> WageSource:
    """Stored wages when there are any; else the live API; else none at all."""
    stored = StoredBlsWages()
    if stored.live:
        return stored
    live = BlsSource()
    return live if live.live else BlsFallback()
