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
