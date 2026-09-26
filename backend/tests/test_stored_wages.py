"""Stored BLS wages: no network, no daily limit, never a half-written file.

The live site lost its pay figures when BLS's 500-requests-a-day limit ran
out; OEWS changes once a year, so the figures are stored instead.
"""

import asyncio

import pytest

from app.scripts import vendor_bls
from app.services.labor import bls, taxonomy

OK = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [
    {"seriesID": "A", "data": [{"year": "2025", "value": "135,980"}]},
    {"seriesID": "B", "data": [{"year": "2025", "value": "1687890"}]},
    {"seriesID": "C", "data": []},
]}}


def test_parse_folds_values_in():
    into: dict = {}
    year = vendor_bls.parse(OK, {"A": ("15-1252", "median"), "B": ("15-1252", "employment"),
                                 "C": ("15-1252", "mean")}, into)
    assert year == "2025"
    assert into == {"15-1252": {"median": 135980.0, "employment": 1687890}}


def test_a_refused_request_stops_everything():
    refused = {"status": "REQUEST_NOT_PROCESSED",
               "message": ["daily threshold for total number of requests ... has been reached."]}
    with pytest.raises(vendor_bls.BlsRefused, match="daily threshold"):
        vendor_bls.parse(refused, {}, {})


@pytest.fixture
def stored(monkeypatch):
    def use(by_soc, year="2025"):
        monkeypatch.setattr(taxonomy, "oews", lambda: {"year": year, "by_soc": by_soc})
    return use


def test_stored_wages_need_no_network(stored):
    stored({"15-1252": {"median": 135980.0, "mean": 148100.0, "employment": 1687890}})
    source = bls.StoredBlsWages()
    got = asyncio.run(source.wages("15-1252", "Software Developers"))
    assert (got.annual_median, got.annual_mean, got.employment, got.year) == (135980.0, 148100.0, 1687890, "2025")
    assert asyncio.run(source.wages("99-9999", "Unknown")) is None
    assert source.label == "BLS OEWS 2025 (stored)"


def test_site_uses_stored_wages_once_there_are_any(stored):
    stored({"15-1252": {"median": 135980.0}})
    assert isinstance(bls.get_wage_source(), bls.StoredBlsWages)


def test_employment_alone_is_not_wages(stored, monkeypatch):
    # Today's file holds employment only; until wages are stored, keep the
    # live API (or no wages at all), never an empty "stored" source.
    stored({"15-1252": {"employment": 1687890}})
    monkeypatch.setenv("BLS_API_KEY", "key")
    assert isinstance(bls.get_wage_source(), bls.BlsSource)
    monkeypatch.delenv("BLS_API_KEY")
    assert isinstance(bls.get_wage_source(), bls.BlsFallback)
