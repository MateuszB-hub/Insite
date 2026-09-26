"""Instant pathway: facts first with Job Zone readiness, the narrative after.

Tester feedback: the ~22 s wait for the whole report was "too slow, pretty
sure most people would just leave". The facts take a few seconds, so they
render at once; the model's summary follows from a second call.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.services import career_service as cs
from app.services import pathway_narrative as narrative
from app.services.labor import Occupation
from main import app

CURRENT = Occupation(code="29-1141", title="Registered Nurses", job_zone=4)
SAME = Occupation(code="29-2061", title="Licensed Practical Nurses", job_zone=3)
UP_ONE = Occupation(code="29-1171", title="Nurse Practitioners", job_zone=5)


def occ(code: str, zone: int | None = None) -> Occupation:
    return Occupation(code=code, title=code, job_zone=zone)


@pytest.mark.parametrize("current, target, horizon, expected", [
    # sideways: same zone or lower, no real skill gap
    (occ("29-1141", 4), occ("29-2061", 3), 12, "ready"),       # RN -> LPN
    (occ("13-2011", 4), occ("43-3031", 3), 12, "ready"),       # accountant -> bookkeeper
    # one zone up: a stretch with time, not within six months
    (occ("29-1141", 4), occ("29-1171", 5), 24, "stretch"),     # RN -> nurse practitioner
    (occ("29-1141", 4), occ("29-1171", 5), 6, "long-term"),
    # same zone, but the skills gap of a promotion
    (occ("13-2011", 4), occ("11-3031", 4), 12, "stretch"),     # -> financial manager
    (occ("41-2031", 2), occ("41-1011", 2), 12, "long-term"),   # salesperson -> supervisor
    # nothing known: no badge rather than a guess
    (occ("", None), occ("", None), 12, None),
])
def test_readiness(current, target, horizon, expected):
    assert cs.readiness(current, target, horizon) == expected


def test_zone_alone_still_decides_without_skill_data():
    # "00-0000" has no skill data; two zones up is longer term regardless.
    assert cs.readiness(occ("00-0000", 2), occ("00-0001", 4), 24) == "long-term"


def test_missing_job_zone_is_filled_from_taxonomy():
    bare = Occupation(code="29-1171", title="Nurse Practitioners")
    filled = cs._with_job_zone(bare)
    assert filled.job_zone is not None
    assert bare.job_zone is None  # the source's object is not modified


class FakeWages:
    async def wages(self, code, title):
        return None


@pytest.fixture
def pathway(monkeypatch):
    """Patch every outside source; the neighbours arrive without zones."""
    cs.clear_pathway_cache()

    async def resolve(source, role):
        return (
            CURRENT,
            [Occupation(code=SAME.code, title=SAME.title),
             Occupation(code=UP_ONE.code, title=UP_ONE.title)],
            source,
        )

    async def no_market(*args, **kwargs):
        return None

    monkeypatch.setattr(cs, "_resolve_occupations", resolve)
    monkeypatch.setattr(cs, "_market_snapshot", no_market)
    monkeypatch.setattr(cs, "get_occupation_source", lambda: None)
    monkeypatch.setattr(cs, "get_market_source", lambda: None)
    monkeypatch.setattr(cs, "get_wage_source", lambda: FakeWages())
    monkeypatch.setattr(cs, "_status_with", lambda source: [])
    monkeypatch.setattr(cs.taxonomy, "transferable", lambda code, limit=6: [])
    yield
    cs.clear_pathway_cache()


def _fake_model(monkeypatch, readiness="ready"):
    calls = []

    class FakeProvider:
        name, label = "fake", "Fake"

        async def generate_json(self, prompt, schema):
            calls.append(prompt)
            return {
                "summary": "Worth a look.",
                "pathways": [{"code": UP_ONE.code, "rationale": "adjacent",
                              "readiness": readiness, "steps": ["get a degree"]}],
                "skill_gaps": [],
                "risks": [],
            }

    async def get_provider(name=None):
        return FakeProvider()

    monkeypatch.setattr(narrative, "get_provider", get_provider)
    return calls


def test_facts_carry_readiness_without_the_model(pathway):
    # 24 months: under two years the horizon filter drops zone-5 roles.
    report = asyncio.run(cs.build_career_pathway("Nurse", horizon_months=24, include_narrative=False))
    badges = {p["code"]: p["readiness"] for p in report["pathways"]}
    assert badges == {SAME.code: "ready", UP_ONE.code: "stretch"}
    assert report["narrative"] is None


def test_narrative_follows_without_touching_the_cached_facts(pathway, monkeypatch):
    _fake_model(monkeypatch)
    facts = asyncio.run(cs.build_career_pathway("Nurse", horizon_months=24, include_narrative=False))
    narrated = asyncio.run(cs.narrate_career_pathway("Nurse", horizon_months=24))

    assert narrated["narrative"]["summary"] == "Worth a look."
    up = next(p for p in narrated["pathways"] if p["code"] == UP_ONE.code)
    assert up["rationale"] == "adjacent"
    # The report the first call cached is exactly as it was.
    assert facts["narrative"] is None
    assert all("rationale" not in p for p in facts["pathways"])


def test_skills_panel_uses_the_same_readiness(pathway, monkeypatch):
    # The page once said "Longer term" in one list and "Likely qualify now"
    # in the other for the same occupation.
    match = {"soc": UP_ONE.code, "title": UP_ONE.title, "description": "",
             "similarity": 0.98, "requires_more_training": True, "job_zone": 5,
             "skill_gaps": []}
    monkeypatch.setattr(cs.taxonomy, "transferable", lambda code, limit=6: [match])
    report = asyncio.run(cs.build_career_pathway("Nurse", horizon_months=24, include_narrative=False))
    listed = next(p for p in report["pathways"] if p["code"] == UP_ONE.code)
    assert report["transferable"][0]["readiness"] == listed["readiness"] == "stretch"


def test_repeat_narrative_does_not_rerun_the_model(pathway, monkeypatch):
    calls = _fake_model(monkeypatch)
    asyncio.run(cs.narrate_career_pathway("Nurse", horizon_months=24))
    asyncio.run(cs.narrate_career_pathway("Nurse", horizon_months=24))
    assert len(calls) == 1


def test_model_cannot_override_data_readiness(pathway, monkeypatch):
    _fake_model(monkeypatch, readiness="ready")  # a graduate degree is not "ready"
    narrated = asyncio.run(cs.narrate_career_pathway("Nurse", horizon_months=24))
    up = next(p for p in narrated["pathways"] if p["code"] == UP_ONE.code)
    assert up["readiness"] == "stretch"


@pytest.mark.parametrize("path, body", [
    ("/api/career-pathway", {"current_role": "Nurse", "include_narrative": False}),
    ("/api/career-pathway/narrative", {"current_role": "Nurse"}),
    ("/api/future-of-work", {"industry": "Healthcare"}),
])
def test_expensive_routes_need_sign_in(path, body):
    # Each call spends data-source quota or model time.
    response = TestClient(app).post(path, json=body)
    assert response.status_code == 401
