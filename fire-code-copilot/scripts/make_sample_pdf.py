"""Generate a SYNTHETIC fire-code-style PDF for smoke-testing ingestion & chunking.

Why this exists: the real code books are copyrighted and never live in the repo, so we
need a structurally-realistic stand-in to prove the pipeline and tune section detection.
ALL text below is original, generic paraphrase written for this fixture — it is NOT copied
from any ICC/NFPA publication. It only mimics the *structure* real code PDFs have:
running headers/footers, ICC-style numbered sections (903.2.8.1), tables, exceptions,
NFPA references, and a Connecticut amendment block with (Amd)/(Add)/(Del) markers.

Usage:
    python scripts/make_sample_pdf.py            # writes code_books/SAMPLE_fire_code.pdf
    python scripts/make_sample_pdf.py out.pdf
"""
from __future__ import annotations
import sys
from pathlib import Path

import fitz  # PyMuPDF


# (heading_line, body_paragraph) — body may be "" for a pure heading.
# Headings use the real ICC numbering shape so the regex gets a realistic workout.
BLOCKS: list[tuple[str, str]] = [
    ("CHAPTER 9  FIRE PROTECTION AND LIFE SAFETY SYSTEMS", ""),
    ("SECTION 901  GENERAL", ""),
    ("901.1 Scope",
     "The provisions of this chapter govern the design, installation, and maintenance of "
     "fire protection and life safety systems within structures regulated by this code. "
     "Where a specific system is required elsewhere in this code, it shall be provided and "
     "maintained in an operable condition for the life of the building."),
    ("901.4.3 Additional fire protection systems",
     "In occupancies of a hazardous nature, where special hazards exist in addition to the "
     "normal hazards of the occupancy, or where the authority having jurisdiction determines "
     "that an unusual hazard is present, additional safeguards shall be required."),
    ("SECTION 903  AUTOMATIC SPRINKLER SYSTEMS", ""),
    ("903.1 General",
     "Automatic sprinkler systems shall comply with this section. Approved automatic sprinkler "
     "systems in new buildings and structures shall be provided in the locations described in "
     "Section 903.2."),
    ("903.2 Where required",
     "Approved automatic sprinkler systems shall be installed in the locations described in "
     "Sections 903.2.1 through 903.2.12. Exception: Spaces or areas in telecommunications "
     "buildings used exclusively for telecommunications equipment, where those spaces are "
     "separated from the remainder of the building as required by this code."),
    ("903.2.8 Group R",
     "An automatic sprinkler system installed in accordance with Section 903.3 shall be "
     "provided throughout all buildings with a Group R fire area. For the purposes of this "
     "section, fire areas are determined in accordance with the building code."),
    ("903.2.8.1 Group R-2",
     "An automatic sprinkler system shall be installed throughout buildings containing a "
     "Group R-2 occupancy where any of the following conditions apply: the building is more "
     "than three stories above grade plane; the building has more than 16 dwelling units; or "
     "the floor area of any Group R-2 fire area exceeds 12,000 square feet (1115 m2)."),
    ("903.3.1.1 NFPA 13 sprinkler systems",
     "Where the provisions of this code require that a building or portion thereof be equipped "
     "throughout with an automatic sprinkler system, sprinklers shall be installed throughout "
     "in accordance with NFPA 13 except as provided in Sections 903.3.1.1.1 and 903.3.1.1.2."),
    ("903.4 Sprinkler system supervision and alarms",
     "Valves controlling the water supply for automatic sprinkler systems, pumps, tanks, water "
     "levels and temperatures, critical air pressures, and waterflow switches on all sprinkler "
     "systems shall be electrically supervised by a listed fire alarm control unit. "
     "Exceptions: 1. Automatic sprinkler systems protecting one- and two-family dwellings. "
     "2. Limited area systems serving fewer than 20 sprinklers."),
    ("TABLE 903.2.11.6  ADDITIONAL REQUIRED SPRINKLER SYSTEM LOCATIONS", ""),
    ("",  # table-ish content extracted as lines
     "Section   Subject\n"
     "903.2.11.1   Stories without openings\n"
     "903.2.11.2   Rubbish and linen chutes\n"
     "903.2.11.3   Buildings 55 feet or more in height\n"
     "903.2.11.6   Other required suppression systems"),
    ("SECTION 907  FIRE ALARM AND DETECTION SYSTEMS", ""),
    ("907.2.9 Group R-2",
     "A manual fire alarm system that activates the occupant notification system shall be "
     "installed in Group R-2 occupancies where any dwelling unit is located three or more "
     "stories above the lowest level of exit discharge, where any dwelling unit is located "
     "more than one story below the highest level of exit discharge of exits serving the "
     "dwelling unit, or where the building contains more than 16 dwelling units."),
    ("907.2.9.3 Smoke alarms",
     "Single- and multiple-station smoke alarms shall be installed in Group R-2 occupancies "
     "in accordance with NFPA 72 and Section 907.2.11."),
]

# A separate amendment-style block as Connecticut publishes them: the affected base
# section number, an action marker, and the amended text. This exercises is_amendment.
CT_AMENDMENT_BLOCKS: list[tuple[str, str]] = [
    ("CONNECTICUT AMENDMENTS TO THE 2021 INTERNATIONAL FIRE CODE", ""),
    ("903.2.8 Group R  (Amd)",
     "Delete the model code text of Section 903.2.8 and substitute the following: An automatic "
     "sprinkler system shall be provided throughout all buildings with a Group R fire area, "
     "including existing buildings undergoing a change of occupancy to Group R as regulated by "
     "the Connecticut State Building Code."),
    ("903.2.8.4 Group R-2 existing buildings  (Add)",
     "Add a new Section 903.2.8.4 as follows: In existing Group R-2 buildings, an automatic "
     "sprinkler system shall be installed throughout where required by the State Fire Marshal "
     "upon a change of occupancy or a substantial alteration as defined by the Connecticut "
     "State Building Code."),
    ("903.3.1.3 Residential combination systems  (Del)",
     "Delete Section 903.3.1.3 of the model code in its entirety."),
]


def _add_page(doc: fitz.Document, header: str, footer: str, blocks: list[tuple[str, str]]):
    """Lay out heading/body blocks on one page with a running header and footer, the way a
    typeset code page extracts under PyMuPDF (header/footer noise on every page)."""
    page = doc.new_page(width=612, height=792)  # US Letter
    margin = 54
    y = margin

    # Running header (page-top noise that real code PDFs repeat on every page).
    page.insert_text((margin, y), header, fontsize=8, fontname="helv", color=(0.4, 0.4, 0.4))
    y += 24

    for heading, body in blocks:
        if heading:
            page.insert_text((margin, y), heading, fontsize=11, fontname="hebo")
            y += 16
        if body:
            for para_line in body.split("\n"):
                # naive word wrap to ~92 chars so we get multi-line paragraphs
                line, words = "", para_line.split()
                for w in words:
                    if len(line) + len(w) + 1 > 92:
                        page.insert_text((margin, y), line, fontsize=10, fontname="helv")
                        y += 13
                        line = w
                    else:
                        line = f"{line} {w}".strip()
                if line:
                    page.insert_text((margin, y), line, fontsize=10, fontname="helv")
                    y += 13
            y += 8

    # Running footer (edition string + page number, like real code books).
    page.insert_text((margin, 760), footer, fontsize=8, fontname="helv", color=(0.4, 0.4, 0.4))
    page.insert_text((540, 760), str(page.number + 1), fontsize=8, fontname="helv",
                     color=(0.4, 0.4, 0.4))


def _build_doc(pages: list[list[tuple[str, str]]], header: str, footer: str) -> fitz.Document:
    doc = fitz.open()
    for blocks in pages:
        _add_page(doc, header, footer, blocks)
    return doc


def build(books_dir: Path) -> list[Path]:
    """Write two files, mirroring the real setup: a model-code PDF and a SEPARATE Connecticut
    amendment PDF (amendments ship as their own document, marked is_amendment_doc in books.yaml)."""
    books_dir.mkdir(parents=True, exist_ok=True)
    out = []

    # Model code: split across two pages to exercise cross-page sections.
    model = _build_doc([BLOCKS[:9], BLOCKS[9:]],
                       header="2021 INTERNATIONAL FIRE CODE",
                       footer="FIRE PROTECTION AND LIFE SAFETY SYSTEMS")
    p1 = books_dir / "SAMPLE_fire_code.pdf"
    model.save(p1); model.close(); out.append(p1)

    # Connecticut amendments as their own file (distinct header/footer).
    amd = _build_doc([CT_AMENDMENT_BLOCKS],
                     header="CONNECTICUT STATE FIRE SAFETY CODE — 2022 AMENDMENTS",
                     footer="STATE OF CONNECTICUT")
    p2 = books_dir / "SAMPLE_ct_amendments.pdf"
    amd.save(p2); amd.close(); out.append(p2)
    return out


if __name__ == "__main__":
    default_dir = Path(__file__).resolve().parents[1] / "code_books"
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else default_dir
    for p in build(target):
        print(f"Wrote synthetic sample PDF -> {p}  ({p.stat().st_size} bytes)")
