"""Robust PDF extraction: text pages read fine; scanned/image-only pages are flagged for OCR."""
import fitz

from app import ingest


def _text_pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((54, 72), "903.2.8 Group R. An automatic sprinkler system shall be provided "
                               "throughout all buildings with a Group R fire area.")
    doc.save(str(path)); doc.close()


def _image_only_pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    # A 2x2 red PNG embedded as the whole page content, with NO text -> looks scanned.
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2, 2), False)
    pix.set_rect(pix.irect, (255, 0, 0))
    page.insert_image(fitz.Rect(0, 0, 200, 200), pixmap=pix)
    doc.save(str(path)); doc.close()


def test_text_pdf_reads_cleanly(tmp_path):
    p = tmp_path / "text.pdf"
    _text_pdf(p)
    pages, info = ingest._read_pdf(p)
    assert "903.2.8" in pages[0][1]
    assert info["needs_ocr"] is False and info["empty_pages"] == 0


def test_image_only_pdf_flagged_for_ocr(tmp_path):
    p = tmp_path / "scan.pdf"
    _image_only_pdf(p)
    pages, info = ingest._read_pdf(p)
    assert info["needs_ocr"] is True
    assert info["image_only_pages"] >= 1


def _ruled_table_pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    x0, y0, cw, ch, rows, cols = 50, 80, 140, 30, 3, 3
    page.insert_text((x0, y0 - 15), "TABLE 903.2.11.6  REQUIRED SUPPRESSION SYSTEM LOCATIONS")
    for r in range(rows + 1):                       # horizontal rules
        page.draw_line((x0, y0 + r * ch), (x0 + cols * cw, y0 + r * ch))
    for c in range(cols + 1):                       # vertical rules
        page.draw_line((x0 + c * cw, y0), (x0 + c * cw, y0 + rows * ch))
    cells = [["Section", "Subject", "Page"],
             ["903.2.11.1", "Stories without openings", "41"],
             ["903.2.11.3", "Buildings 55 feet or more", "42"]]
    for r in range(rows):
        for c in range(cols):
            page.insert_text((x0 + c * cw + 4, y0 + r * ch + 20), cells[r][c], fontsize=9)
    doc.save(str(path)); doc.close()


def test_ruled_table_becomes_a_markdown_chunk(tmp_path):
    p = tmp_path / "table.pdf"
    _ruled_table_pdf(p)
    chunks = ingest._table_chunks(p, {"book": "IFC", "edition": "2021", "is_amendment_doc": False})
    assert chunks, "PyMuPDF find_tables should detect the ruled table"
    t = chunks[0]
    assert t["metadata"]["is_table"] is True
    assert t["metadata"]["section"] == "903.2.11.6"        # from the caption
    assert "903.2.11.1" in t["text"]                       # cell content preserved
