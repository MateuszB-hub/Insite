"""Contracts for the labour-market data layer.

Three different questions, three different sources. Keeping them as separate
capabilities (rather than one god-interface) means each can be live, mocked, or
missing independently -- which is exactly the state we're in while API
registrations are pending.

  OccupationSource -- "what is this role, and what is adjacent to it?"  (O*NET)
  WageSource       -- "what does it pay?"                              (BLS)
  MarketSource     -- "who is hiring, and at what rate?"               (Adzuna)

Every provider reports `live` so the API can tell the caller which parts of a
report are real data and which are placeholders. Never silently pass a mock off
as measured data -- an applicant may act on this.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class LaborDataError(RuntimeError):
    """A labour-market source failed or is not configured."""


@dataclass
class Occupation:
    """A normalized occupation, keyed by SOC code where available."""

    code: str
    title: str
    description: str = ""
    #: 0-1 similarity to the role the applicant asked about.
    relatedness: float | None = None
    skills: list[str] = field(default_factory=list)
    #: O*NET Job Zone 1-5: how much prep the role needs. Useful as a proxy
    #: for "could I move here in about a year?"
    job_zone: int | None = None


@dataclass
class WageEstimate:
    """Wage figures for one occupation, in one area."""

    occupation_code: str
    occupation_title: str
    area: str = "United States"
    annual_median: float | None = None
    annual_mean: float | None = None
    employment: int | None = None
    year: str | None = None
    source: str = "unknown"


@dataclass
class Employer:
    """A company hiring for a given search, with posting volume."""

    name: str
    postings: int
    average_salary: float | None = None


@dataclass
class SalaryBand:
    """One bucket of a salary distribution."""

    lower: float
    upper: float | None
    count: int


@dataclass
class MarketSnapshot:
    """Live hiring-market view for a role/industry query."""

    query: str
    total_postings: int | None = None
    top_employers: list[Employer] = field(default_factory=list)
    salary_distribution: list[SalaryBand] = field(default_factory=list)
    #: month (YYYY-MM) -> average advertised salary, for the look-back.
    salary_history: dict[str, float] = field(default_factory=dict)


class LaborSource(ABC):
    """Shared plumbing: identity and configuration status."""

    name: str = "unnamed"
    label: str = "Unnamed source"
    #: Where to register, surfaced in status output so setup is self-service.
    signup_url: str = ""

    @abstractmethod
    def configured(self) -> tuple[bool, str | None]:
        """Return (has_credentials, reason_if_not). No network calls."""

    @property
    def live(self) -> bool:
        return self.configured()[0]

    def describe(self) -> dict[str, Any]:
        ok, reason = self.configured()
        return {
            "name": self.name,
            "label": self.label,
            "live": ok,
            "reason": reason,
            "signup_url": self.signup_url,
        }


class OccupationSource(LaborSource):
    @abstractmethod
    async def resolve(self, title: str) -> Occupation | None:
        """Best-matching occupation for a free-text job title."""

    @abstractmethod
    async def related(self, code: str, limit: int = 8) -> list[Occupation]:
        """Occupations adjacent to `code` -- the candidate's next moves."""


class WageSource(LaborSource):
    @abstractmethod
    async def wages(self, code: str, title: str) -> WageEstimate | None:
        """Wage estimate for an SOC occupation code."""


class MarketSource(LaborSource):
    @abstractmethod
    async def snapshot(self, query: str, location: str | None = None) -> MarketSnapshot:
        """Hiring-market view: who posts, how many, at what pay."""
