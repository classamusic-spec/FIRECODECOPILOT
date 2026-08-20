"""Section-aware chunking: the failures that produce wrong citations must stay fixed."""
from app.chunking import chunk_pages, _normalized_code_families

META = {"book": "IFC", "edition": "2021", "is_amendment_doc": False}


def _pages():
    p1 = (
        "2021 INTERNATIONAL FIRE CODE\n"            # running header (must be stripped)
        "SECTION 903  AUTOMATIC SPRINKLER SYSTEMS\n"
        "903.2 Where required\n"
        "Approved automatic sprinkler systems shall be installed as described in\n"
        "Section 903.2.1 through 903.2.12 of this code for the occupancies listed.\n"
        "903.2.8 Group R\n"
        "An automatic sprinkler system shall be provided throughout buildings with a\n"
        "Group R fire area as required by this section and the building code.\n"
        "FIRE PROTECTION\n"                          # running footer (must be stripped)
        "1\n"                                        # page number (must be stripped)
    )
    p2 = (
        "2021 INTERNATIONAL FIRE CODE\n"
        "TABLE 903.2.11.6  REQUIRED SUPPRESSION SYSTEM LOCATIONS\n"
        "Section Subject\n"
        "903.2.11.1 Stories without openings\n"
        "903.2.11.2 Rubbish and linen chutes\n"
        "FIRE PROTECTION\n"
        "2\n"
    )
    return [(1, p1), (2, p2)]


def test_running_headers_and_page_numbers_are_stripped():
    chunks = chunk_pages(_pages(), META)
    blob = "\n".join(c["text"] for c in chunks)
    assert "2021 INTERNATIONAL FIRE CODE" not in blob
    assert not any(c["metadata"]["section"] == "2021" for c in chunks)


def test_inline_cross_reference_does_not_fake_a_section():
    # "Section 903.2.1 through ..." is body text, not a heading -> no §903.2.1 chunk.
    chunks = chunk_pages(_pages(), META)
    sections = [c["metadata"]["section"] for c in chunks]
    assert "903.2.1" not in sections


def test_real_sections_detected_with_pages():
    chunks = chunk_pages(_pages(), META)
    by_section = {c["metadata"]["section"]: c for c in chunks}
    assert "903.2" in by_section
    assert "903.2.8" in by_section
    assert by_section["903.2.8"]["metadata"]["page"] == 1


def test_table_stays_together_and_is_tagged():
    chunks = chunk_pages(_pages(), META)
    tables = [c for c in chunks if c["metadata"]["is_table"]]
    assert len(tables) == 1
    t = tables[0]
    # Both rows live inside the single table chunk, not as separate sections.
    assert "903.2.11.1" in t["text"] and "903.2.11.2" in t["text"]
    assert t["metadata"]["section"] == "903.2.11.6"


def test_amendment_markers_are_tagged():
    amd_pages = [(1,
        "903.2.8 Group R  (Amd)\n"
        "Delete the model code text and substitute the following: an automatic sprinkler\n"
        "system shall be provided throughout all Group R buildings in Connecticut.\n")]
    chunks = chunk_pages(amd_pages, {"book": "CSFSC", "edition": "2022", "is_amendment_doc": True})
    assert chunks and all(c["metadata"]["is_amendment"] for c in chunks)
    assert chunks[0]["metadata"]["section"] == "903.2.8"   # base section preserved for merge


def test_connecticut_statute_headings_are_citable_sections():
    pages = [(1,
        "CHAPTER 541\n"
        "Sec. 29-250. Office of the State Fire Marshal. Office of the State Building Inspector.\n"
        "There is established an Office of the State Fire Marshal.\n"
        "185 C. 445. Annotation citation, not a statute section.\n"
        "Sec. 29-252. State Building Code: Adoption, revision and amendments.\n"
        "The State Building Code shall be adopted and revised as provided by law.\n")]
    chunks = chunk_pages(pages, {"book": "CGS Chapter 541", "edition": "2025", "is_amendment_doc": False})
    sections = {c["metadata"]["section"]: c for c in chunks}
    assert set(sections) >= {"29-250", "29-252"}
    assert "185" not in sections
    assert "Office of the State Fire Marshal" in sections["29-250"]["text"]
    assert sections["29-252"]["metadata"]["page"] == 1


def test_nfpa_decimal_headings_and_number_only_lines_are_citable_sections():
    pages = [(1,
        "2020 National Fire Protection Association. All Rights Reserved.\n"
        "31.1 *  General Requirements.\n"
        "31.1.1 Application.\n"
        "31.1.1.1 \n"
        "The requirements of this chapter shall apply to existing apartment occupancies.\n"
        "31.2 Means of Egress Requirements.\n"
        "31.2.1 General.\n"
        "Means of egress shall comply with Chapter 7 and this chapter.\n")]
    chunks = chunk_pages(
        pages,
        {"book": "NFPA 101 — Life Safety Code", "edition": "2021", "is_amendment_doc": False},
    )
    sections = {c["metadata"]["section"]: c for c in chunks}
    assert "31.1.1.1" in sections
    assert "31.2.1" in sections
    assert "2020" not in sections
    assert "existing apartment occupancies" in sections["31.1.1.1"]["text"]


def test_nfpa_annex_headings_keep_the_corresponding_section_number():
    chunks = chunk_pages(
        [(1, "A.31.1.1 Application guidance.\nThis annex text explains the application rule.\n")],
        {"book": "NFPA 101 Annex A", "edition": "2021", "is_amendment_doc": False},
    )
    assert chunks[0]["metadata"]["section"] == "A.31.1.1"


def test_nfpa_heading_accepts_attached_significance_asterisk():
    chunks = chunk_pages(
        [(1, "31.1* General Requirements.\n31.1.1.1*\nAttached-star subsection text.\n")],
        {"book": "NFPA 101", "edition": "2021", "is_amendment_doc": False},
    )
    assert "31.1.1.1" in {c["metadata"]["section"] for c in chunks}


def test_ct_fire_safety_amendments_emit_normalized_part_code_family():
    chunks = chunk_pages(
        [
            (9, "SECTION 101 SCOPE\n101.1 Title. Part III of the Connecticut State Fire Safety Code applies.\n"),
            (103, "PART IV—Existing Buildings/Occupancies Amendments to the 2021 NFPA 101, Life Safety Code\n"
                  "CHAPTER 1 ADMINISTRATION\n1.1.1 This Part IV rule.\n"
                  "This requirement applies to all applicable existing occupancies in this part.\n"),
        ],
        {"book": "CT Fire Safety Code amendments", "edition": "2022",
         "is_amendment_doc": True},
    )
    by_section = {c["metadata"]["section"]: c["metadata"] for c in chunks}
    assert by_section["101.1"]["code_family"] == "ifc"
    assert by_section["1.1.1"]["code_family"] == "nfpa:101"


def test_ct_building_amendment_family_stops_at_other_model_code_portions():
    families = _normalized_code_families(
        [
            (2, "TABLE OF CONTENTS Amendments to the 2021 International Existing Building Code"),
            (6, "3 AMENDMENTS TO THE 2021 INTERNATIONAL BUILDING CODE CHAPTER 1"),
            (76, "73 AMENDMENTS TO THE 2021 INTERNATIONAL EXISTING BUILDING CODE CHAPTER 1"),
            (84, "81 AMENDMENTS TO THE 2021 INTERNATIONAL PLUMBING CODE CHAPTER 1"),
            (85, "Plumbing amendment continuation."),
        ],
        {"book": "CT Building Code amendments", "edition": "2022",
         "is_amendment_doc": True},
    )
    assert families[2] == "ibc"
    assert families[6] == "ibc"
    assert families[76] == "iebc"
    assert 84 not in families and 85 not in families
