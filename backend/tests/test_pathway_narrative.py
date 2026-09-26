"""Guard tests for the narrative overlay.

These cover the rule that makes the design safe: model prose may never
introduce an occupation we did not fetch, and may never supply a number.
"""

import asyncio

import pytest

from app.services.pathway_narrative import _validate, build_fact_sheet, attach_narrative


BASE_REPORT = {
    "current_role": "Senior Backend Software Engineer",
    "industry": "Fintech",
    "horizon_months": 12,
    "current_occupation": {
        "code": "15-1252",
        "title": "Software Developers",
        "description": "",
        "skills": [],
        "job_zone": None,
        "wage": {"annual_median": 133080.0, "annual_mean": None,
                 "employment": None, "year": "2025", "area": "US", "source": "BLS"},
    },
    "pathways": [
        {"code": "15-2051", "title": "Data Scientists", "description": "",
         "skills": [], "job_zone": None, "wage": None},
        {"code": "11-3021", "title": "Computer and Information Systems Managers",
         "description": "", "skills": [], "job_zone": None, "wage": None},
    ],
    "hiring": None,
    "data_sources": [],
}


def test_validate_drops_unknown_codes():
    """A code we never sent must not reach the response."""
    parsed = {
        "summary": "s",
        "pathways": [
            {"code": "15-2051", "rationale": "real", "readiness": "ready"},
            {"code": "99-9999", "rationale": "invented", "readiness": "ready"},
        ],
        "skill_gaps": ["SQL"],
    }
    clean, warnings = _validate(parsed, {"15-2051", "11-3021"})
    assert set(clean["by_code"]) == {"15-2051"}
    assert any("99-9999" in w for w in warnings)


def test_validate_normalises_bad_readiness():
    parsed = {
        "summary": "s",
        "pathways": [{"code": "15-2051", "rationale": "r", "readiness": "immediately"}],
        "skill_gaps": [],
    }
    clean, _ = _validate(parsed, {"15-2051"})
    assert clean["by_code"]["15-2051"]["readiness"] == "stretch"


def test_validate_survives_garbage():
    """Malformed model output must not raise."""
    clean, _ = _validate({"pathways": ["nonsense", 42, None]}, {"15-2051"})
    assert clean["by_code"] == {}
    assert clean["summary"] == ""


def test_fact_sheet_states_missing_data_explicitly():
    """Silence invites invention; absence must be named."""
    sheet = build_fact_sheet(BASE_REPORT)
    assert "not available" in sheet
    assert "15-2051" in sheet and "11-3021" in sheet
    assert "$133,080" in sheet


def test_narrative_cannot_introduce_numbers():
    """The schema has no numeric field; merged output keeps our wage objects."""
    class FakeProvider:
        name, label = "fake", "Fake"
        async def generate_json(self, prompt, schema):
            return {
                "summary": "Go for it.",
                "pathways": [{"code": "15-2051", "rationale": "adjacent",
                              "readiness": "ready", "steps": ["learn stats"]}],
                "skill_gaps": ["statistics"],
                "risks": [],
            }

    import app.services.pathway_narrative as mod
    original = mod.get_provider

    async def fake_get_provider(name=None):
        return FakeProvider()

    mod.get_provider = fake_get_provider
    try:
        report = asyncio.run(attach_narrative({**BASE_REPORT,
                                               "pathways": [dict(p) for p in BASE_REPORT["pathways"]]}))
    finally:
        mod.get_provider = original

    assert report["narrative_status"] == "ok"
    ds = next(p for p in report["pathways"] if p["code"] == "15-2051")
    assert ds["rationale"] == "adjacent"
    # Wage stays exactly what the labour layer produced -- None, not invented.
    assert ds["wage"] is None


def test_model_failure_degrades_to_facts():
    """A dead model must not lose the facts."""
    import app.services.pathway_narrative as mod
    original = mod.get_provider

    async def boom(name=None):
        raise RuntimeError("no model")

    mod.get_provider = boom
    try:
        report = asyncio.run(attach_narrative({**BASE_REPORT}))
    except RuntimeError:
        pytest.fail("attach_narrative must not propagate provider errors")
    finally:
        mod.get_provider = original

    assert report["narrative"] is None
    assert report["pathways"][0]["code"] == "15-2051"


def test_readiness_restatement_is_stripped_from_prose():
    """The badge is authoritative; prose must not contradict it."""
    parsed = {
        "summary": "s",
        "pathways": [{
            "code": "15-2051",
            "rationale": "Strong overlap with your current work. Readiness: Long-term.",
            "readiness": "stretch",
        }],
        "skill_gaps": [],
    }
    clean, _ = _validate(parsed, {"15-2051"})
    rationale = clean["by_code"]["15-2051"]["rationale"]
    assert "Readiness" not in rationale
    assert rationale == "Strong overlap with your current work."
    assert clean["by_code"]["15-2051"]["readiness"] == "stretch"


@pytest.mark.parametrize("prose,expected", [
    ("Strong overlap with your work. Readiness: Long-term.",
     "Strong overlap with your work."),
    ("A natural fit for backend skills. This transition is considered 'ready'.",
     "A natural fit for backend skills."),
    ("Requires new skills. This role is considered a stretch.",
     "Requires new skills."),
    ("Plain rationale with no restatement.",
     "Plain rationale with no restatement."),
])
def test_readiness_restatement_variants_stripped(prose, expected):
    """Several phrasings; the badge must stay the only readiness signal."""
    parsed = {
        "summary": "s",
        "pathways": [{"code": "15-2051", "rationale": prose, "readiness": "stretch"}],
        "skill_gaps": [],
    }
    clean, _ = _validate(parsed, {"15-2051"})
    got = clean["by_code"]["15-2051"]["rationale"]
    assert got == expected, f"got {got!r}"
    assert "readiness" not in got.lower()
