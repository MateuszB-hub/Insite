"""O*NET Web Services -- occupations, adjacency and skills.

O*NET is the right answer to "what would I qualify for": it publishes, for
~900 occupations, the related-occupation graph and the skills behind it. That
beats asking a model to guess neighbouring job titles.

Auth is HTTP Basic with a username/password issued at registration (free).
Until those exist, `OnetFallback` serves a small hand-built adjacency map so
the pathway endpoint returns a sane shape and the UI can be built.

    https://services.onetcenter.org/developer  (registration)
"""

import logging
import os

import httpx

from app.services.labor import taxonomy

from .base import LaborDataError, Occupation, OccupationSource

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("ONET_BASE_URL", "https://api-v2.onetcenter.org")


class OnetSource(OccupationSource):
    """Live O*NET Web Services v2.

    v2 differs from v1.9: an `X-API-Key` header instead of HTTP Basic, a new
    host, and sub-resources under `/summary/` rather than flat paths. The
    contract here follows the official samples:
    https://github.com/onetcenter/web-services-v2-samples

    The endpoints are discoverable -- an occupation document advertises its
    own sub-resource hrefs -- but they are pinned here so a shape change
    surfaces as a clear failure rather than silent degradation.
    """

    name = "onet"
    label = "O*NET Web Services"
    signup_url = "https://services.onetcenter.org/developer"

    def __init__(self) -> None:
        self.api_key = os.getenv("ONET_API_KEY", "").strip()

    def configured(self) -> tuple[bool, str | None]:
        if not self.api_key:
            return False, "ONET_API_KEY not set"
        return True, None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "X-API-Key": self.api_key,
                "Accept": "application/json",
                "User-Agent": "Insite/0.1 (career pathway tool)",
            },
            timeout=30.0,
        )

    @staticmethod
    def _onet_code(soc: str) -> str:
        """BLS uses 29-1141; O*NET wants 29-1141.00."""
        return soc if "." in soc else f"{soc}.00"

    @staticmethod
    def _soc(onet_code: str) -> str:
        return onet_code.split(".")[0]

    async def resolve(self, title: str) -> Occupation | None:
        ok, reason = self.configured()
        if not ok:
            raise LaborDataError(reason or "O*NET not configured")

        # Vendored taxonomy first. O*NET's keyword search is thrown by
        # qualifiers: "Senior Backend Software Engineer" ranks Biofuels
        # Product Development Managers top. The local resolver handles those
        # but misses some bare titles ("Software Engineer"), so live search
        # remains the fallback rather than the default.
        hit = taxonomy.resolve(title)
        if hit is not None:
            return Occupation(
                code=hit["soc"], title=hit["title"],
                description=hit["description"], job_zone=hit.get("job_zone"),
            )

        async with self._client() as client:
            response = await client.get(
                "/online/search", params={"keyword": title, "end": 1}
            )
            response.raise_for_status()
            payload = response.json()

        matches = payload.get("occupation") or []
        if not matches:
            return None
        top = matches[0]
        return Occupation(
            code=self._soc(top.get("code", "")),
            title=top.get("title", title),
            description=top.get("description", "") or "",
        )

    async def related(self, code: str, limit: int = 8) -> list[Occupation]:
        ok, reason = self.configured()
        if not ok:
            raise LaborDataError(reason or "O*NET not configured")

        onet = self._onet_code(code)
        async with self._client() as client:
            response = await client.get(
                f"/online/occupations/{onet}/summary/related_occupations"
            )
            response.raise_for_status()
            payload = response.json()

        # O*NET returns sub-specialties (29-1141.01 Acute Care Nurses,
        # .03 Critical Care Nurses ...) that all collapse to one SOC code.
        # Left as-is they render as duplicate rows carrying identical BLS
        # wages, so keep the first of each distinct SOC and drop the seed.
        seen: set[str] = {code}
        out: list[Occupation] = []
        for item in payload.get("occupation") or []:
            soc = self._soc(item.get("code", ""))
            if not soc or soc in seen:
                continue
            seen.add(soc)
            out.append(Occupation(
                code=soc,
                title=item.get("title", ""),
                description=item.get("description", "") or "",
            ))
            if len(out) >= limit:
                break
        return out

    async def skills(self, code: str, limit: int = 10) -> list[str]:
        """Named skills for an occupation. Not on the base contract; used to
        enrich the pathway when the live source is available."""
        onet = self._onet_code(code)
        async with self._client() as client:
            response = await client.get(
                f"/online/occupations/{onet}/summary/skills"
            )
            response.raise_for_status()
            payload = response.json()
        elements = payload.get("element") or []
        return [e.get("name", "") for e in elements[:limit] if e.get("name")]


# --------------------------------------------------------------------------
# Offline fallback -- the full O*NET-SOC taxonomy, vendored
# --------------------------------------------------------------------------


class OnetFallback(OccupationSource):
    """Offline resolution over all 867 O*NET-SOC occupations.

    Not the live Web Services API: adjacency is approximated from SOC
    structure rather than O*NET's real relatedness graph, and there are no
    skills. But it resolves any occupation in the taxonomy, which is what
    BLS needs to return wages. Reports `live=False` so the UI keeps labelling
    it as a fallback.
    """

    name = "onet"
    label = "O*NET taxonomy (offline)"
    signup_url = "https://services.onetcenter.org/developer"

    def configured(self) -> tuple[bool, str | None]:
        return False, (
            "Using the vendored O*NET-SOC taxonomy (867 occupations). "
            "Register for live O*NET to get the real relatedness graph and skills."
        )

    async def resolve(self, title: str) -> Occupation | None:
        hit = taxonomy.resolve(title)
        if hit is None:
            # Echo the entered title rather than inventing a SOC code.
            return Occupation(code="", title=title, description="")
        return Occupation(
            code=hit["soc"], title=hit["title"], description=hit["description"],
            job_zone=hit.get("job_zone"),
        )

    async def related(self, code: str, limit: int = 8) -> list[Occupation]:
        return [
            Occupation(code=o["soc"], title=o["title"], description=o["description"],
                       job_zone=o.get("job_zone"))
            for o in taxonomy.related(code, limit)
        ]


def get_occupation_source() -> OccupationSource:
    live = OnetSource()
    return live if live.live else OnetFallback()
