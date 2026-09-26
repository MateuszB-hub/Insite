"""Which occupation a typed title means -- and when to ask instead of guess.

Mentor: "Jobs that have the same name trip up the ai. Qa lead can be for
multiple types of jobs. Software qa lead / Materials qa like checking parts as
they arrive. So you may want to make it ask for a category."

Before this, a single match was picked silently, and often badly: "project
manager" meant Computer and Information Systems Managers, "operator" meant
Crematory Operators, "technician" Agricultural Technicians. These cases run
on the vendored O*NET and BLS data, so they are deterministic.
"""

import pytest

from app.services.labor import taxonomy

# title, best match, other occupations that must be offered, ambiguous?
CASES = [
    # the mentor's case: both readings offered, and it asks
    ("QA lead", "15-1253", {"51-9061"}, True),
    # one clear occupation: no question asked
    ("registered nurse", "29-1141", set(), False),
    ("software engineer", "15-1252", set(), False),
    ("Senior Backend Software Engineer", "15-1252", set(), False),
    ("electrician", "47-2111", set(), False),
    ("welder", "51-4121", set(), False),
    ("accountant", "13-2011", set(), False),
    ("HR manager", "11-3121", set(), False),
    # genuinely several jobs: most common first, and it asks
    ("project manager", "13-1082", {"11-9041", "11-3021"}, True),
    ("data analyst", "15-2051", set(), True),
    ("cook", "35-2014", {"35-2011"}, True),
    ("inspector", "51-9061", {"47-4011"}, True),
    ("account manager", None, {"41-3091", "11-2022"}, True),
    ("technician", None, set(), True),
]


@pytest.mark.parametrize("title, best, offered, ambiguous", CASES, ids=[c[0] for c in CASES])
def test_title_matching(title, best, offered, ambiguous):
    found = taxonomy.candidates(title)
    codes = [c["soc"] for c in found]
    if best is not None:
        assert codes[0] == best, codes
    assert offered <= set(codes), codes
    assert taxonomy.is_ambiguous(found) is ambiguous


def test_old_silent_mistakes_are_gone():
    assert taxonomy.resolve("project manager")["soc"] != "11-3021"
    assert "Crematory" not in taxonomy.resolve("operator")["title"]
    assert "Agricultural" not in taxonomy.resolve("technician")["title"]


def test_military_only_when_asked_for():
    assert not any(c["soc"].startswith("55-") for c in taxonomy.candidates("analyst", limit=10))
    assert any(c["soc"].startswith("55-") for c in taxonomy.candidates("army intelligence analyst", limit=10))


def test_each_candidate_says_how_it_matched():
    top = taxonomy.candidates("registered nurse")[0]
    assert top["match"] == "official title"
    qa = taxonomy.candidates("QA lead")[0]
    assert qa["match"] == "similar title" and qa["via"]


# --- Career Pathway: the choice is offered, and a pick is honoured ----------

import asyncio  # noqa: E402

from app.services import career_service as cs  # noqa: E402
from app.services.labor import Occupation  # noqa: E402
from app.services.labor.onet import OnetFallback  # noqa: E402


def test_a_picked_occupation_wins_over_the_title():
    current, _, _ = asyncio.run(cs._resolve_occupations(OnetFallback(), "QA lead", "51-9061"))
    assert current.code == "51-9061"


def test_ambiguous_title_offers_the_other_readings():
    shown = Occupation(code="15-1253", title="Software Quality Assurance Analysts and Testers")
    got = cs._title_choices("QA lead", shown, chosen=False)
    codes = [a["code"] for a in got["alternatives"]]
    assert got["ambiguous"] is True
    assert "51-9061" in codes and "15-1253" not in codes
    assert got["matched_via"].startswith("similar title")


def test_once_picked_it_stops_asking():
    shown = Occupation(code="51-9061", title="Inspectors, Testers, Sorters, Samplers, and Weighers")
    got = cs._title_choices("QA lead", shown, chosen=True)
    assert got["ambiguous"] is False
    assert "15-1253" in [a["code"] for a in got["alternatives"]]  # can still switch back
