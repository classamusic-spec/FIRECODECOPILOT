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
