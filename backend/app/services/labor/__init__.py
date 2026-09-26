"""Labour-market data layer: occupations, wages and hiring market."""

from .adzuna import AdzunaFallback, AdzunaSource, get_market_source
from .base import (
    Employer,
    LaborDataError,
    MarketSnapshot,
    MarketSource,
    Occupation,
    OccupationSource,
    SalaryBand,
    WageEstimate,
    WageSource,
)
from .bls import BlsFallback, BlsSource, get_wage_source
from .onet import OnetFallback, OnetSource, get_occupation_source

__all__ = [
    "Employer", "LaborDataError", "MarketSnapshot", "MarketSource",
    "Occupation", "OccupationSource", "SalaryBand", "WageEstimate", "WageSource",
    "AdzunaSource", "AdzunaFallback", "get_market_source",
    "BlsSource", "BlsFallback", "get_wage_source",
    "OnetSource", "OnetFallback", "get_occupation_source",
    "labor_status",
]


def labor_status() -> list[dict]:
    """Per-source configuration status, for GET /api/labor/status."""
    return [
        {"capability": "occupations", **get_occupation_source().describe()},
        {"capability": "wages", **get_wage_source().describe()},
        {"capability": "market", **get_market_source().describe()},
    ]
