"""What pay is worth where someone lives: BEA Regional Price Parities.

Mentor, on switching cities: "100k is basically 70k here." All lookups in
the vendored app/data/col.json and arithmetic, so these are deterministic.
"""

import json

import pytest

from app.services.labor import living_costs as L


# --- the vendored data --------------------------------------------------------

def test_the_data_is_whole_and_sane():
    d = json.loads(L._DATA.read_text())
    assert len(d["states"]) == 51                    # 50 states and DC
    assert len(d["metros"]) > 350
    for table in ("counties", "places"):
        assert set(d[table].values()) <= set(d["metros"])
    for area in [*d["states"].values(), *d["metros"].values()]:
        assert 70 < area["all"] < 140                # an index around 100


# --- where someone is ---------------------------------------------------------

@pytest.mark.parametrize("typed, name, level", [
    ("Plano, TX", "Dallas-Fort Worth-Arlington, TX", "metro"),     # a suburb, through its county
    ("78701", "Austin-Round Rock-San Marcos, TX", "metro"),        # a ZIP
    ("Brooklyn", "New York-Newark-Jersey City, NY-NJ", "metro"),   # a borough
    ("Collin County, TX", "Dallas-Fort Worth-Arlington, TX", "metro"),
    ("Marfa, TX", "Texas", "state"),                                # outside any metro
    ("Texas", "Texas", "state"),
])
def test_home_areas(typed, name, level):
    area = L.area_for_place(typed)
    assert (area.name, area.level) == (name, level)


@pytest.mark.parametrize("typed", [None, "", "zzzz", "London", "Remote"])
def test_no_home_area_when_the_place_is_not_known(typed):
    assert L.area_for_place(typed) is None


@pytest.mark.parametrize("board_area, short, level", [
    (["US", "Texas", "Collin County", "Plano"], "Dallas", "metro"),
    (["US", "Texas", "Dallas", "Richardson"], "Dallas", "metro"),     # 3rd level is a region
    (["US", "New York", "New York City", "Brooklyn"], "New York", "metro"),
    (["US", "California", "Santa Clara County", "Palo Alto"], "San Jose", "metro"),
    (["US", "Texas", "Presidio County", "Marfa"], "Texas", "state"),
    (["US", "Texas"], "Texas", "state"),
])
def test_advert_areas_from_the_boards_breakdown(board_area, short, level):
    area = L.area_for_posting(board_area)
    assert (area.short, area.level) == (short, level)


@pytest.mark.parametrize("board_area", [[], ["US"], ["UK", "London"], ["US", "Atlantis"]])
def test_no_advert_area_when_unknown(board_area):
    assert L.area_for_posting(board_area) is None


# --- the comparison -----------------------------------------------------------

def test_san_francisco_pay_in_dallas_terms():
    home = L.area_for_place("Plano, TX")
    sf = L.area_for_posting(["US", "California", "San Francisco County", "San Francisco"])
    c = L.compare(100000, 120000, sf, home)
    assert c["difference_pct"] == 12                        # 115.6 vs 103.1
    assert (c["equivalent_min"], c["equivalent_max"]) == (89000, 107000)
    assert c["housing_difference_pct"] > 50                 # most of it is housing
    assert c["source"].startswith("BEA Regional Price Parities, 20")


def test_nothing_to_say_when_it_would_not_help():
    home = L.area_for_place("Plano, TX")
    dallas = L.area_for_posting(["US", "Texas", "Dallas", "Richardson"])
    austin = L.area_for_posting(["US", "Texas", "Travis County", "Austin"])
    assert L.compare(100000, None, dallas, home) is None    # the same area
    assert L.compare(None, None, austin, home) is None      # no pay
    assert L.compare(100000, None, None, home) is None      # no known area
    assert L.compare(100000, None, austin, None) is None    # no home
    assert L.compare(100000, None, austin, home)["difference_pct"] == -5
