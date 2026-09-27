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


# --- the ways people really type a location (change record feat-place-fixes) ---

@pytest.mark.parametrize("typed, status, searched, note_has", [
    # 1. NYC boroughs are New York, NY -- but a named state still wins
    ("Brooklyn", "ok", ["New York, NY"], "New York City"),
    ("brooklyn ny", "ok", ["New York, NY"], "Brooklyn is part"),
    ("The Bronx", "ok", ["New York, NY"], "New York City"),
    ("Queens NY", "ok", ["New York, NY"], "New York City"),
    ("Staten Island", "ok", ["New York, NY"], "New York City"),
    ("Brooklyn, OH", "ok", ["Brooklyn, OH"], None),
    # 2. remote words aren't places
    ("Remote", "remote", [], "Remote only"),
    ("wfh", "remote", [], "Remote only"),
    ("Work from home", "remote", [], "Remote only"),
    # 3. ZIP codes are the place they're in
    ("78701", "ok", ["Austin, TX"], "ZIP 78701"),
    ("78701-1234", "ok", ["Austin, TX"], "ZIP 78701"),
    ("Austin, TX 78701", "ok", ["Austin, TX"], "ZIP 78701"),
    ("00901", "ok", ["San Juan, PR"], "ZIP 00901"),
    ("00000", "unknown", [], "no US ZIP code 00000"),
    ("123456", "invalid", [], None),
    # 4. regions search their main cities; "greater … area" is the city
    ("Bay Area", "region", ["San Francisco, CA", "Oakland, CA", "San Jose, CA"], "searched as"),
    ("DFW", "region", ["Dallas, TX", "Fort Worth, TX"], "searched as"),
    ("twin cities", "region", ["Minneapolis, MN", "St. Paul, MN"], "searched as"),
    ("Greater Boston area", "ambiguous", ["Boston, MA"], None),
    ("Denver metro", "ambiguous", ["Denver, CO"], None),
    # 5. outside the US: said, never a quiet near-miss
    ("London", "ambiguous", ["London, OH"], "US jobs only"),
    ("Tokyo", "unknown", [], "US jobs only"),
    ("M5V 2T6", "invalid", [], "US jobs only"),
    ("SW1A 1AA", "invalid", [], "US jobs only"),
    # 6. accents either way
    ("San José", "ambiguous", ["San Jose, CA"], None),
    ("Canon City", "ok", ["Cañon City, CO"], None),
    # 7. places the 2023 estimates skip are still ranked by size
    ("San Juan", "ambiguous", ["San Juan, PR"], None),
    # 8. a real name in the wrong state
    ("Austin, CA", "unknown", [], "find Austin in California"),
    # towns and townships where they are the local government
    ("Edison, NJ", "ok", ["Edison, NJ"], None),
    ("Cherry Hill NJ", "ok", ["Cherry Hill, NJ"], None),
    ("Lower Merion, PA", "ok", ["Lower Merion, PA"], None),
    ("Queensbury, NY", "ok", ["Queensbury, NY"], None),
    # unchanged: junk and markup stay unsearched
    ("<script>alert(1)</script>", "unknown", [], None),
    (".", "invalid", [], None),
])
def test_how_people_type_places(typed, status, searched, note_has):
    r = places.resolve(typed)
    assert (r.status, r.places) == (status, searched), vars(r)
    if note_has is None:
        assert r.note is None, r.note
    else:
        assert note_has in (r.note or ""), r.note


def test_a_foreign_city_gets_no_fuzzy_near_miss():
    assert places.resolve("Tokyo").suggestions == []


def test_a_wrong_state_suggests_where_the_name_is_real():
    assert places.resolve("Austin, CA").suggestions[0] == "Austin, TX"


def test_a_name_that_is_also_a_state_offers_the_state_first():
    # 9. "Washington" is usually the state or DC; the state comes first.
    r = places.resolve("Washington")
    assert r.place == "Washington, DC"
    assert r.alternatives[0] == "Washington State"


def test_region_and_borough_places_are_real_labels():
    # Every place a table sends to the board must itself resolve to itself,
    # or the board would be guessing again.
    for listed in [*{p for ps in places.REGIONS.values() for p in ps}, "New York, NY"]:
        assert places.resolve(listed).place == listed, listed


def test_every_zip_points_at_a_known_place():
    known = {p.label for ps in places._data()[0].values() for p in ps}
    zips = places._zips()
    assert len(zips) > 30000
    assert set(zips.values()) <= known


# --- found by the tester beyond the plan's criteria (bugs B1-B4, fixed) ----

@pytest.mark.parametrize("typed", ["Paris, France", "London, UK", "Toronto, Canada", "Toronto ON"])
def test_city_with_a_foreign_country_says_us_only(typed):
    r = places.resolve(typed)
    assert (r.status, r.suggestions) == ("unknown", [])
    assert "US jobs only" in (r.note or "")


@pytest.mark.parametrize("typed", ["Remote - Austin, TX", "Austin (remote)", "remote austin"])
def test_remote_with_a_place_searches_the_place_remote_only(typed):
    r = places.resolve(typed)
    assert r.places == ["Austin, TX"] and r.remote


def test_a_number_that_is_no_zip_falls_back_to_the_text():
    assert places.resolve("Austin, TX 00000").places == ["Austin, TX"]


def test_a_region_with_its_state():
    assert places.resolve("Bay Area, CA").status == "region"
