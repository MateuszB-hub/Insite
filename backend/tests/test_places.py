"""Locations are checked against real US places before they are searched.

Live, the job board guessed silently: "new yotrk" returned nothing without a
word, "3" was read as Puerto Rico, "." as Alabama, "Springfield" as MA.
These run on the vendored Census place list, so they are deterministic.
"""

import pytest

from app.services import places


@pytest.mark.parametrize("typed, status, place", [
    # junk: never searched
    ("3", "invalid", None),
    (".", "invalid", None),
    ("  ", "invalid", None),
    # real places, however they're written
    ("Austin tx", "ok", "Austin, TX"),
    ("austin, Texas", "ok", "Austin, TX"),
    ("Springfield IL", "ok", "Springfield, IL"),
    ("St. Louis, MO", "ok", "St. Louis, MO"),
    ("Arlington VA", "ok", "Arlington, VA"),          # a census-designated place
    ("Winston Salem", "ok", "Winston-Salem, NC"),
    ("NYC", "ok", "New York, NY"),
    # a name several places share: the largest, others offered
    ("springfield", "ambiguous", "Springfield, MO"),
    ("orange county", "ambiguous", "Orange County, CA"),
    ("saint louis", "ambiguous", "St. Louis, MO"),
    ("new york", "ambiguous", "New York, NY"),
    # states
    ("texas", "state", "Texas"),
    ("TX", "state", "Texas"),
    ("New York State", "state", "New York"),
    # typos and nonsense: not searched, suggestions where there are any
    ("new yotrk", "unknown", None),
    ("zzzz", "unknown", None),
])
def test_resolve(typed, status, place):
    got = places.resolve(typed)
    assert (got.status, got.place) == (status, place)
    assert got.searchable == (status in {"ok", "ambiguous", "state"})


@pytest.mark.parametrize("typo, first", [
    ("new yotrk", "New York, NY"), ("Seatle", "Seattle, WA"), ("Chicgo", "Chicago, IL"),
])
def test_typos_get_the_right_suggestion_first(typo, first):
    assert places.resolve(typo).suggestions[0] == first


def test_ambiguous_names_offer_the_others_largest_first():
    got = places.resolve("springfield")
    assert got.alternatives[:2] == ["Springfield, MA", "Springfield, IL"]


def test_new_york_offers_the_state_in_a_form_that_stays_the_state():
    assert "New York State" in places.resolve("new york").alternatives
    assert places.resolve("New York State").status == "state"


def test_suggestions_as_you_type():
    assert places.complete("sea")[0] == "Seattle, WA"
    assert places.complete("aus tx")[0] == "Austin, TX"
    assert places.complete("s") == []   # too little to go on
