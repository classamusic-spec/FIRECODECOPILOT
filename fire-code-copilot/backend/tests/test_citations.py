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


def test_plural_nfpa_sections_preserve_same_book_provenance():
    sources = [
        {"text": "First section.", "metadata": {
            "section": "31.1.1", "book": "NFPA 101 Life Safety Code"}},
        {"text": "Wrong-book second section.", "metadata": {
            "section": "31.1.2", "book": "NFPA 1 Fire Code"}},
    ]
    check = citations.validate("NFPA 101 Sections 31.1.1 and 31.1.2 apply.", sources)
    assert not check.ok
    assert any("31.1.2" in item for item in check.unverified)


def test_plural_nfpa_sections_verify_when_both_come_from_same_book():
    sources = [
        {"text": "First section.", "metadata": {
            "section": "31.1.1", "book": "NFPA 101 Life Safety Code"}},
        {"text": "Second section.", "metadata": {
            "section": "31.1.2", "book": "NFPA 101 Life Safety Code"}},
    ]
    check = citations.validate("NFPA 101 Sections 31.1.1 and 31.1.2 apply.", sources)
    assert check.ok


def test_chained_nfpa_section_symbols_preserve_same_book_provenance():
    sources = [
        {"text": "First section.", "metadata": {
            "section": "31.1.1", "book": "NFPA 101 Life Safety Code"}},
        {"text": "Wrong-book second section.", "metadata": {
            "section": "31.1.2", "book": "NFPA 1 Fire Code"}},
    ]
    check = citations.validate("NFPA 101 §31.1.1 and §31.1.2 apply.", sources)
    assert not check.ok
    assert any("31.1.2" in item for item in check.unverified)


def test_chained_sec_abbreviations_preserve_same_book_provenance():
    sources = [
        {"text": "First section.", "metadata": {
            "section": "31.1.1", "book": "NFPA 101 Life Safety Code"}},
        {"text": "Wrong-book second section.", "metadata": {
            "section": "31.1.2", "book": "NFPA 1 Fire Code"}},
    ]
    check = citations.validate("NFPA 101 Sec. 31.1.1 and Sec. 31.1.2 apply.", sources)
    assert not check.ok
    assert any("31.1.2" in item for item in check.unverified)


def test_nfpa_title_and_edition_do_not_break_same_book_citation_scope():
    sources = [
        {"text": "First section.", "metadata": {
            "section": "31.1.1", "book": "NFPA 101 Life Safety Code"}},
        {"text": "Wrong-book second section.", "metadata": {
            "section": "31.1.2", "book": "NFPA 1 Fire Code"}},
    ]
    answer = "NFPA 101 Life Safety Code (2021), Sections 31.1.1 and 31.1.2 apply."
    check = citations.validate(answer, sources)
    assert not check.ok
    assert any("31.1.2" in item for item in check.unverified)


def test_postfix_nfpa_attribution_preserves_same_book_provenance():
    sources = [
        {"text": "First.", "metadata": {"section": "31.1.1", "book": "NFPA 101"}},
        {"text": "Wrong book.", "metadata": {"section": "31.1.2", "book": "NFPA 1"}},
    ]
    check = citations.validate("Sections 31.1.1 and 31.1.2 of NFPA 101 apply.", sources)
    assert not check.ok and any("31.1.2" in x for x in check.unverified)


def test_postfix_nfpa_attribution_stops_after_prior_ifc_citation():
    sources = [
        {"text": "IFC rule.", "metadata": {
            "section": "903.2.8", "book": "IFC"}},
        {"text": "NFPA rule.", "metadata": {
            "section": "31.1.1", "book": "NFPA 101"}},
    ]
    check = citations.validate(
        "IFC Section 903.2.8 and Section 31.1.1 of NFPA 101 apply.", sources
    )
    assert check.ok


def test_mixed_ifc_nfpa_citations_reject_swapped_book_provenance_in_both_orders():
    swapped_sources = [
        {"text": "Only in IFC.", "metadata": {
            "section": "903.2.8", "book": "IFC"}},
        {"text": "Only in NFPA.", "metadata": {
            "section": "31.1.1", "book": "NFPA 101"}},
    ]
    answers = [
        "IFC Section 31.1.1 and Section 903.2.8 of NFPA 101 apply.",
        "Section 903.2.8 of NFPA 101 and IFC Section 31.1.1 apply.",
    ]
    for answer in answers:
        check = citations.validate(answer, swapped_sources)
        assert not check.ok
        assert check.unverified


def test_ibc_and_iebc_sections_require_their_own_book_provenance():
    swapped_sources = [
        {"text": "IEBC-only section.", "metadata": {
            "section": "1604.1", "book": "IEBC"}},
        {"text": "IBC-only section.", "metadata": {
            "section": "301.1", "book": "IBC"}},
    ]
    check = citations.validate(
        "IBC Section 1604.1 and IEBC Section 301.1 apply.", swapped_sources
    )
    assert not check.ok
    assert len(check.unverified) == 2


def test_nfpa_table_citation_preserves_same_book_provenance():
    sources = [{"text": "Wrong book.", "metadata": {
        "section": "31.1.2", "book": "NFPA 1"}}]
    check = citations.validate("NFPA 101 Table 31.1.2 applies.", sources)
    assert not check.ok and any("31.1.2" in x for x in check.unverified)


def test_nfpa_chapter_citation_preserves_same_book_provenance():
    sources = [
        {"text": "Right book, other chapter.", "metadata": {
            "section": "30", "book": "NFPA 101"}},
        {"text": "Wrong book chapter.", "metadata": {
            "section": "31", "book": "NFPA 1"}},
    ]
    check = citations.validate("NFPA 101 Chapter 31 applies.", sources)
    assert not check.ok and any("31" in x for x in check.unverified)


def test_bare_short_nfpa_section_is_cited_without_treating_measurement_as_citation():
    sources = [{"text": "Rule.", "metadata": {
        "section": "7.1", "book": "NFPA 101"}}]
    check = citations.validate("NFPA 101 7.1 applies; the door is 7.1 feet high.", sources)
    assert check.ok
    assert "7.1" in check.cited


def test_bare_short_nfpa_section_preserves_same_book_provenance():
    sources = [
        {"text": "Right standard.", "metadata": {
            "section": "8.1", "book": "NFPA 101"}},
        {"text": "Wrong standard.", "metadata": {
            "section": "7.1", "book": "NFPA 1"}},
    ]
    check = citations.validate("NFPA 101 7.1 applies.", sources)
    assert not check.ok and "7.1" in check.unverified


def test_semicolon_chained_nfpa_sections_preserve_same_book_provenance():
    sources = [
        {"text": "First.", "metadata": {"section": "31.1.1", "book": "NFPA 101"}},
        {"text": "Wrong book.", "metadata": {"section": "31.1.2", "book": "NFPA 1"}},
    ]
    check = citations.validate("NFPA 101 §31.1.1; §31.1.2 applies.", sources)
    assert not check.ok and any("31.1.2" in x for x in check.unverified)


def test_sentence_after_dotted_nfpa_citation_is_not_owned_by_nfpa():
    sources = [
        {"text": "Life safety.", "metadata": {"section": "31.1.1", "book": "NFPA 101"}},
        {"text": "IFC rule.", "metadata": {"section": "903.2.8", "book": "IFC (model)"}},
    ]
    check = citations.validate("NFPA 101 §31.1.1. IFC Section 903.2.8 applies.", sources)
    assert check.ok
