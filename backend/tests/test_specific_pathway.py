"""Specific pathway: each role carries facts and links, not generic prose.

Tester feedback: the pathway text was "kind of useless tbh. Super generic
information", and on "Skills to build": "might be more helpful to link to one
of those roadmaps that people do".
"""

from types import SimpleNamespace

from app.services import career_service as cs
from app.services.labor import Occupation, learning, taxonomy


def test_every_occupation_links_to_official_sources():
    got = learning.links("29-1171", "29-1171.00", "Nurse Practitioners")
    assert [link["source"] for link in got] == ["O*NET OnLine", "CareerOneStop"]
    assert got[0]["url"] == "https://www.onetonline.org/link/summary/29-1171.00"
    assert got[1]["url"].endswith("keyword=Nurse+Practitioners")


def test_tech_occupations_lead_with_a_roadmap():
    got = learning.links("15-1253", "15-1253.00", "Software Quality Assurance Analysts")
    assert got[0] == {"label": "QA roadmap", "url": "https://roadmap.sh/qa", "source": "roadmap.sh"}
    assert got[-1]["source"] == "CareerOneStop"


def test_no_code_no_links():
    assert learning.links("", None, "Something typed") == []


def test_training_in_plain_words():
    assert learning.training(5).startswith("Usually a graduate degree")
    assert learning.training(None) is None


def test_skill_gaps_skip_what_the_job_barely_uses():
    # Unfiltered, a developer -> systems analyst move led with "Repairing".
    gaps = [g["skill"] for g in taxonomy.skill_gaps("15-1252", "15-1211")]
    assert "Repairing" not in gaps
    assert all(g["gap"] >= taxonomy.SHORTFALL_MIN_GAP
               for g in taxonomy.skill_gaps("15-1252", "15-1211"))


def test_skill_gaps_empty_without_skill_data():
    assert taxonomy.skill_gaps("00-0000", "15-1211") == []


def wage(median):
    return SimpleNamespace(annual_median=median)


def test_specifics_pay_change_and_training():
    rn = Occupation(code="29-1141", title="Registered Nurses", job_zone=4)
    np_ = Occupation(code="29-1171", title="Nurse Practitioners", job_zone=5)
    got = cs._specifics(rn, wage(97550.0), np_, wage(132300.0))
    assert got["pay_change"] == 132300.0 - 97550.0
    assert got["training"].startswith("Usually a graduate degree")
    assert got["links"][0]["source"] == "O*NET OnLine"


def test_specifics_no_pay_change_without_both_wages():
    rn = Occupation(code="29-1141", title="Registered Nurses", job_zone=4)
    np_ = Occupation(code="29-1171", title="Nurse Practitioners", job_zone=5)
    assert cs._specifics(rn, None, np_, wage(132300.0))["pay_change"] is None
    assert cs._specifics(rn, wage(97550.0), np_, None)["pay_change"] is None
