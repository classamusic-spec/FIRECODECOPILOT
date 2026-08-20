"""Query expansion: spell out occupancy codes + code acronyms to lift recall (append, never replace)."""
from app.query import expand_query
from app.settings import settings


def test_expands_occupancy_code():
    out = expand_query("sprinkler requirements for R-2")
    assert "sprinkler requirements for R-2" in out      # original preserved
    assert "Group R-2" in out and "residential" in out   # expansion appended


def test_expands_acronyms():
    out = expand_query("what does the IFC say about AHJ authority?")
    assert "International Fire Code" in out
    # "authority having jurisdiction" — but "authority" already present, so AHJ still expands the rest
    assert "having jurisdiction" in out


def test_no_expansion_leaves_query_unchanged():
    assert expand_query("minimum corridor width") == "minimum corridor width"


def test_respects_disable_toggle(monkeypatch):
    monkeypatch.setattr(settings, "expand_queries", False)
    assert expand_query("sprinkler for R-2") == "sprinkler for R-2"


def test_does_not_double_expand_spelled_out_terms():
    # If the user already wrote "Group R-2", we don't tack the same phrase on again ad nauseam.
    out = expand_query("Group R-2 apartment")
    assert out.count("Group R-2 apartment multifamily residential") <= 1


def test_expands_nfpa_101_to_life_safety_code_without_confusing_nfpa_1():
    out = expand_query("What does NFPA 101 require for existing apartment corridors?")
    assert "Life Safety Code" in out
    assert "NFPA 1 Fire Code" not in out


def test_expands_nfpa_1_to_fire_code():
    out = expand_query("What does NFPA 1 require for hot work?")
    assert "NFPA 1 Fire Code" in out


def test_old_building_alteration_expands_to_both_layers():
    out = expand_query("Alteration to a 1920 apartment building originally permitted in 1920")
    assert "NFPA 101 Life Safety Code" in out
    assert "International Fire Code" in out


def test_pre_2006_existing_building_expands_to_nfpa_101_part_iv():
    out = expand_query("Egress in an existing apartment building originally permitted in 1995")
    assert "NFPA 101 Life Safety Code 2021" in out
    assert "Part IV" in out


def test_unrelated_before_2006_date_does_not_override_explicit_post_cutoff_permit():
    out = expand_query(
        "Existing R-2; original permit issued in 2015; sprinkler installed before 2006"
    )
    assert "International Fire Code" in out
    assert "NFPA 101 Life Safety Code" not in out


def test_renovation_date_alone_does_not_claim_original_permit_period():
    out = expand_query("Existing apartment renovated after 2006")
    assert "NFPA 101 Life Safety Code" not in out


def test_equipment_construction_year_does_not_select_building_code_layer():
    out = expand_query("Existing apartment; sprinkler system constructed in 1995")
    assert "NFPA 101 Life Safety Code" not in out


def test_equipment_cutoff_phrase_does_not_select_building_code_layer():
    out = expand_query("Existing apartment; sprinkler system constructed before 2006")
    assert "NFPA 101 Life Safety Code" not in out


def test_post_2005_existing_building_expands_to_ifc_part_iii_not_nfpa_101():
    out = expand_query("Egress in an existing apartment building originally permitted in 2015")
    assert "International Fire Code" in out and "Part III" in out
    assert "NFPA 101 Life Safety Code" not in out


def test_explicit_nonactive_ifc_edition_is_not_rewritten_as_2021():
    out = expand_query("Compare 2018 IFC Section 903.2.8")
    assert "2021 International Fire Code" not in out
    assert "Part III" not in out


def test_explicit_future_ifc_edition_is_not_rewritten_as_active_cycle():
    out = expand_query("What changed in the 2024 International Fire Code?")
    assert "2021 International Fire Code" not in out
    assert "Part III" not in out


def test_operational_hot_work_question_expands_to_nfpa_1_and_csfpc():
    out = expand_query("What permit and fire-watch rules apply to this hot work operation?")
    assert "NFPA 1 Fire Code 2021" in out
    assert "Connecticut State Fire Prevention Code" in out


def test_new_construction_question_expands_to_ifc_part_iii():
    out = expand_query("Sprinkler requirements for a brand-new six-story apartment building")
    assert "2021 International Fire Code" in out and "Part III" in out


def test_pre_2006_building_alteration_searches_both_existing_and_new_work_layers():
    out = expand_query("Alteration of an apartment building originally permitted in 1920")
    assert "NFPA 101 Life Safety Code 2021" in out and "Part IV" in out
    assert "2021 International Fire Code" in out and "Part III" in out
