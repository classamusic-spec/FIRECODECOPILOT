"""Section-number utilities: normalization + ancestor/descendant relation."""
from app.sections import canonical, numeric_tuple, relates, section_tokens


def test_canonical_strips_keywords_and_symbols():
    assert canonical("§903.2.8") == "903.2.8"
    assert canonical("Section 903.2.8.") == "903.2.8"
    assert canonical("Table 903.2.11.6") == "903.2.11.6"
    assert canonical("NFPA 13") == "NFPA 13"


def test_numeric_tuple_only_for_pure_sections():
    assert numeric_tuple("903.2.8") == ("903", "2", "8")
    assert numeric_tuple("NFPA 13") is None  # a standard label, not a dotted section


def test_relates_equal_and_hierarchy():
    assert relates("903.2.8", "903.2.8")            # equal
    assert relates("903.2", "903.2.8")              # parent governs child
    assert relates("903.2.8", "903.2")              # symmetric
    assert relates("903.2.8", "903.2.8.4")          # newly-added child surfaces for parent


def test_relates_rejects_siblings_and_bare_chapter():
    assert not relates("903.2.8", "903.2.9")        # siblings are not related
    assert not relates("903", "903.2.8")            # a bare chapter must not sweep everything
    assert not relates("903.2.8", "907.2.9")        # different sections


def test_section_tokens_finds_dotted_numbers():
    toks = section_tokens("903.2.8 Group R. See also 907.2.9 for alarms.")
    assert "903.2.8" in toks and "907.2.9" in toks
