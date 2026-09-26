"""Occupation resolution must work beyond tech roles.

The first version of this resolver understood four tech-adjacent families and
silently returned nothing for a nurse, an electrician, or a cook -- which made
the whole product tech-only. These tests pin the breadth.
"""

import pytest

from app.services.labor import taxonomy


@pytest.mark.parametrize("query,expected_soc", [
    # tech
    ("Senior Backend Software Engineer", "15-1252"),
    ("Data Scientist", "15-2051"),
    # healthcare
    ("Registered Nurse", "29-1141"),
    ("Dental Hygienist", "29-1292"),
    ("Medical Assistant", "31-9092"),
    ("Pharmacist", "29-1051"),
    ("Physical Therapist", "29-1123"),
    # trades
    ("Electrician", "47-2111"),
    ("HVAC Technician", "49-9021"),
    ("Welder", "51-4121"),
    ("Carpenter", "47-2031"),
    # transport / logistics
    ("Heavy Truck Driver", "53-3032"),
    ("Warehouse Associate", "53-7062"),
    # service
    ("Line Cook", "35-2014"),
    ("Security Guard", "33-9032"),
    # professional
    ("Accountant", "13-2011"),
    ("Paralegal", "23-2011"),
    ("Graphic Designer", "27-1024"),
    ("High School Teacher", "25-2031"),
    ("Retail Store Manager", "41-1011"),
])
def test_resolves_across_sectors(query, expected_soc):
    hit = taxonomy.resolve(query)
    assert hit is not None, f"{query} resolved to nothing"
    assert hit["soc"] == expected_soc, f"{query} -> {hit['soc']} {hit['title']}"


def test_seniority_words_are_ignored():
    for prefix in ("Senior ", "Junior ", "Lead ", "Principal "):
        assert taxonomy.resolve(f"{prefix}Electrician")["soc"] == "47-2111"


def test_singular_and_plural_both_match():
    assert taxonomy.resolve("Electrician")["soc"] == taxonomy.resolve("Electricians")["soc"]


def test_nonsense_returns_none_rather_than_a_wrong_guess():
    """A confidently wrong SOC code is worse than admitting no match."""
    # (Not "Underwater Basket Weaver": O*NET really lists "Basket Weaver", so
    # that now matches as a labelled similar title.)
    assert taxonomy.resolve("Xyzzy Frobnicator") is None
    assert taxonomy.resolve("") is None
    assert taxonomy.resolve("   ") is None


def test_taxonomy_covers_every_major_group():
    majors = {o["soc"][:2] for o in taxonomy.all_occupations()}
    assert len(majors) >= 22, f"only {len(majors)} SOC major groups"
    assert len(taxonomy.all_occupations()) > 800


def test_related_prefers_same_occupation_family():
    """A nurse must not be told to become an oral surgeon."""
    related = taxonomy.related("29-1141", limit=4)
    titles = " ".join(o["title"].lower() for o in related)
    assert "nurse" in titles
    assert "surgeon" not in titles
    assert "orthodontist" not in titles


def test_related_crosses_minor_groups_on_strong_affinity():
    """Licensed Practical Nurses (29-2061) is two groups from RN (29-1141)."""
    codes = {o["soc"] for o in taxonomy.related("29-1141", limit=6)}
    assert "29-2061" in codes


def test_related_is_empty_for_unknown_code():
    assert taxonomy.related("99-9999") == []


# --- skills transfer -------------------------------------------------------

def test_transferable_finds_cross_field_matches():
    """An electrician's skills should reach solar and HVAC work."""
    titles = " ".join(m["title"].lower() for m in taxonomy.transferable("47-2111", limit=8))
    assert "solar" in titles or "heating" in titles


def test_transferable_flags_training_honestly():
    """A cook can supervise now; becoming a chef needs more."""
    # Top 12: in O*NET 30.0 chefs rank 11th among a restaurant cook's matches.
    matches = {m["title"]: m for m in taxonomy.transferable("35-2014", limit=12)}
    chef = next((m for t, m in matches.items() if "Chefs" in t), None)
    assert chef is not None and chef["requires_more_training"] is True
    assert any(not m["requires_more_training"] for m in matches.values())


def test_transferable_does_not_suggest_lower_skilled_jobs():
    """The earlier version told a nurse to become an archivist."""
    titles = {m["title"] for m in taxonomy.transferable("29-1141", limit=10)}
    assert "Archivists" not in titles
    assert not any("Housekeeping" in t for t in titles)


def test_transferable_reports_skill_gaps():
    for match in taxonomy.transferable("35-2014", limit=6):
        for gap in match["skill_gaps"]:
            assert gap["gap"] > 0
            assert gap["skill"] in taxonomy.skill_names()


def test_transferable_similarity_is_ordered():
    matches = taxonomy.transferable("13-2011", limit=6)
    sims = [m["similarity"] for m in matches]
    assert sims == sorted(sims, reverse=True)


def test_transferable_empty_for_unknown_or_skill_less_code():
    assert taxonomy.transferable("99-9999") == []


def test_related_uses_the_real_onet_graph():
    """Not the old title-similarity heuristic."""
    codes = {o["soc"] for o in taxonomy.related("29-1141", limit=8)}
    assert "29-1171" in codes          # Nurse Practitioners
    assert "29-1022" not in codes      # Oral and Maxillofacial Surgeons


def test_job_zones_are_loaded():
    """The horizon filter was inert because nothing set job_zone."""
    zoned = [o for o in taxonomy.all_occupations() if o.get("job_zone")]
    assert len(zoned) > 700
    assert taxonomy.resolve("Registered Nurse")["job_zone"] == 4
    assert taxonomy.resolve("Line Cook")["job_zone"] == 2


def test_live_source_prefers_local_resolution(monkeypatch):
    """Live O*NET keyword search ranks Biofuels Product Development Managers
    top for "Senior Backend Software Engineer". The vendored resolver must
    answer first so qualifiers cannot derail the whole pathway."""
    import asyncio

    from app.services.labor.onet import OnetSource

    monkeypatch.setenv("ONET_API_KEY", "test-key")
    source = OnetSource()

    def no_network():
        raise AssertionError("live search called for a locally resolvable title")

    monkeypatch.setattr(source, "_client", no_network)
    occ = asyncio.run(source.resolve("Senior Backend Software Engineer"))
    assert occ.code == "15-1252"
