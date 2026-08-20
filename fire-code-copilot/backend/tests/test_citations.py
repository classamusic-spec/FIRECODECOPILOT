"""Citation validator — fabricated section numbers must be flagged, never silently trusted."""
from app import citations

SOURCES = [
    {"text": "903.2.8 Group R. An automatic sprinkler system shall be provided...",
     "metadata": {"section": "903.2.8", "book": "IFC", "edition": "2021", "page": 1}},
    {"text": "Table 903.2.11.6 lists additional locations...",
     "metadata": {"section": "903.2.11.6", "book": "IFC", "edition": "2021", "page": 2}},
]


def test_real_citation_verifies():
    check = citations.validate("Per Section 903.2.8 a sprinkler system is required.", SOURCES)
    assert check.ok
    assert "903.2.8" in " ".join(check.verified)


def test_fabricated_citation_is_flagged():
    check = citations.validate("This is governed by Section 1234.5.6.", SOURCES)
    assert not check.ok
    assert any("1234.5.6" in u for u in check.unverified)
    annotated = citations.annotate("...Section 1234.5.6...", check)
    assert "UNVERIFIED CITATION" in annotated


def test_section_in_metadata_only_still_verifies():
    # Citing a section present in metadata (even if phrased differently) verifies.
    check = citations.validate("See §903.2.11.6 for additional locations.", SOURCES)
    assert check.ok


def test_substring_section_is_not_a_false_positive():
    # "903.2" must NOT be considered present just because "903.2.8" was shown (whole-token check).
    check = citations.validate("This falls under Section 903.2.", SOURCES)
    assert not check.ok
    assert "903.2" in " ".join(check.unverified)


def test_grounded_quote_passes():
    check = citations.validate(
        'The code states: "An automatic sprinkler system shall be provided" in Group R.', SOURCES)
    assert check.ok
    assert check.quotes  # the quote was substantial enough to be checked


def test_fabricated_quote_is_flagged():
    check = citations.validate(
        'Per §903.2.8, "sprinklers are required in every closet over two feet wide".', SOURCES)
    assert not check.ok                     # section is real but the quote is invented
    assert check.unverified_quotes
    assert "UNVERIFIED QUOTE" in citations.annotate("…", check)


def test_nfpa_standard_name_verifies_from_source_book_metadata():
    sources = [{
        "text": "The requirements of this chapter apply to existing apartment occupancies.",
        "metadata": {
            "section": "31.1.1.1",
            "book": "NFPA 101 2021 — Life Safety Code, Chapter 31",
            "edition": "2021",
            "page": 1,
        },
    }]
    check = citations.validate("Use NFPA 101 §31.1.1.1 for this existing building.", sources)
    assert check.ok
    assert "NFPA 101" in check.verified


def test_different_nfpa_standard_is_not_verified_by_book_metadata():
    sources = [{
        "text": "The requirements of this chapter apply to existing apartment occupancies.",
        "metadata": {"section": "31.1.1.1", "book": "NFPA 101 Life Safety Code"},
    }]
    check = citations.validate("NFPA 999 applies.", sources)
    assert not check.ok
    assert check.unverified == ["NFPA 999"]


def test_annex_citation_is_checked_against_annex_section_metadata():
    sources = [{"text": "Explanatory material.", "metadata": {
        "section": "A.31.1.1", "book": "NFPA 101 Life Safety Code"}}]
    assert citations.validate("See NFPA 101 §A.31.1.1.", sources).ok
    bad = citations.validate("See NFPA 101 §A.999.9.", sources)
    assert not bad.ok
    assert any("A.999.9" in item for item in bad.unverified)


def test_nfpa_standard_and_section_must_come_from_the_same_source_book():
    sources = [
        {"text": "Life Safety Code material.", "metadata": {
            "section": "7.1", "book": "NFPA 101 Life Safety Code"}},
        {"text": "Fire Code material.", "metadata": {
            "section": "31.1.1.1", "book": "NFPA 1 Fire Code"}},
    ]
    check = citations.validate("NFPA 101 §31.1.1.1 applies.", sources)
    assert not check.ok
    assert any("31.1.1.1" in item for item in check.unverified)


def test_nfpa_standard_and_section_pair_verifies_from_same_book_chunk():
    sources = [{"text": "Existing apartment requirements.", "metadata": {
        "section": "31.1.1.1", "book": "NFPA 101 Life Safety Code"}}]
    assert citations.validate("NFPA 101, Section 31.1.1.1 applies.", sources).ok


def test_short_decimal_measurement_is_not_mistaken_for_a_bare_nfpa_citation():
    assert citations.extract_citations("Maintain a clearance of 1.5 inches.") == []
