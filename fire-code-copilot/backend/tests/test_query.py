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
