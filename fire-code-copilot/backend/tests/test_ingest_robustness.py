"""Two real-book robustness fixes:
  1. Two-column pages are read column-by-column, not interleaved top-to-bottom.
  2. Re-ingesting a changed book purges its prior vectors (no stale/outdated text left behind).
"""
import fitz

from app import ingest


def _two_column_pdf(path):
    """A page with a left and a right text column at the same vertical band (US-Letter width)."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # Left column at x≈60, right column at x≈340; same y positions so naive top-to-bottom
    # extraction would interleave them (L1, R1, L2, R2).
    page.insert_text((60, 120), "LEFTONE alpha provision text for the left column here")
    page.insert_text((60, 140), "LEFTTWO more of the left column body continues here")
    page.insert_text((340, 120), "RIGHTONE bravo provision text for the right column")
    page.insert_text((340, 140), "RIGHTTWO more of the right column body continues too")
    doc.save(str(path)); doc.close()


def test_two_column_page_is_not_interleaved(tmp_path):
    p = tmp_path / "twocol.pdf"
    _two_column_pdf(p)
    pages, info = ingest._read_pdf(p)
    text = pages[0][1]
    assert info["needs_ocr"] is False
    # The whole LEFT column must come before the whole RIGHT column (not interleaved).
    iL1, iL2 = text.index("LEFTONE"), text.index("LEFTTWO")
    iR1, iR2 = text.index("RIGHTONE"), text.index("RIGHTTWO")
    assert iL1 < iL2 < iR1 < iR2, f"columns interleaved / out of order:\n{text}"


def _section_pdf(path, body):
    """A page with a section heading on its own line and a prose body line below it (so the
    section-aware chunker emits a real chunk)."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((54, 72), "903.2.8 Group R.")
    page.insert_text((54, 92), body)
    doc.save(str(path)); doc.close()


def test_reingest_purges_stale_vectors(tmp_path, monkeypatch):
    import chromadb
    from app.settings import settings

    books = tmp_path / "books"; books.mkdir()
    data = tmp_path / "data"
    monkeypatch.setattr(settings, "code_books_dir", str(books))
    monkeypatch.setattr(settings, "data_dir", str(data))
    monkeypatch.setattr(settings, "chroma_dir", str(data / "chroma"))
    monkeypatch.setattr(settings, "active_collection", "reix")
    monkeypatch.setattr(settings, "extract_tables", False)
    # These module-level paths were bound at import from the original data_dir — repoint them.
    monkeypatch.setattr(ingest, "STATE_FILE", data / "ingest_state.json")
    monkeypatch.setattr(ingest, "COLLECTIONS_FILE", data / "collections.json")

    pdf = books / "book.pdf"
    _section_pdf(pdf, "ALPHATOKEN an automatic sprinkler system shall be provided throughout the fire area.")
    ingest.ingest()

    client = chromadb.PersistentClient(path=settings.chroma_dir)
    coll = client.get_collection("reix")
    docs_v1 = coll.get(include=["documents"])["documents"]
    assert any("ALPHATOKEN" in d for d in docs_v1)

    # Edit the same file (new content + hash) and re-ingest.
    _section_pdf(pdf, "BETATOKEN automatic sprinklers are required throughout the entire fire area now.")
    ingest.ingest()

    docs_v2 = coll.get(include=["documents"])["documents"]
    assert any("BETATOKEN" in d for d in docs_v2), "new content should be indexed"
    assert not any("ALPHATOKEN" in d for d in docs_v2), "stale prior text must be purged on re-ingest"


def test_targeted_forced_reingest_preserves_unrelated_vectors(tmp_path, monkeypatch):
    import chromadb
    from app.settings import settings

    books = tmp_path / "books"; books.mkdir()
    data = tmp_path / "data"
    monkeypatch.setattr(settings, "code_books_dir", str(books))
    monkeypatch.setattr(settings, "data_dir", str(data))
    monkeypatch.setattr(settings, "chroma_dir", str(data / "chroma"))
    monkeypatch.setattr(settings, "active_collection", "targeted")
    monkeypatch.setattr(settings, "extract_tables", False)
    monkeypatch.setattr(ingest, "STATE_FILE", data / "ingest_state.json")
    monkeypatch.setattr(ingest, "COLLECTIONS_FILE", data / "collections.json")

    target = books / "target.pdf"
    unrelated = books / "unrelated.pdf"
    _section_pdf(target, "OLDTARGET provision text that will be replaced during the targeted ingest.")
    _section_pdf(unrelated, "KEEPTHIS unrelated provision text that must survive the targeted ingest.")
    ingest.ingest()

    _section_pdf(target, "NEWTARGET replacement provision text for the targeted source only.")
    result = ingest.ingest(force=True, only_files=["target.pdf"])

    coll = chromadb.PersistentClient(path=settings.chroma_dir).get_collection("targeted")
    docs = coll.get(include=["documents"])["documents"] or []
    assert result["chunks_added"] == 1
    assert any("NEWTARGET" in d for d in docs)
    assert any("KEEPTHIS" in d for d in docs)
    assert not any("OLDTARGET" in d for d in docs)
    assert coll.count() == 2
