"""Ingestion: read PDFs from CODE_BOOKS_DIR -> section-aware chunks -> local embeddings ->
Chroma. Run once after adding/updating books:  python -m app.ingest

Books stay where they are (e.g. your Desktop folder). Only the derived index lives in
DATA_DIR/chroma (gitignored). An optional code_books/books.yaml lets you set each PDF's
book/edition, mark Connecticut amendment documents, and route it to a per-edition COLLECTION.

One Chroma collection per code cycle/edition (e.g. "csfsc_2022") keeps legacy editions
queryable for existing-building questions without polluting current-cycle answers. A book's
collection comes from its books.yaml `collection:` (default: settings.active_collection). Put a
model code and its Connecticut amendments in the SAME collection so amendment-merge can pair them.
"""
from __future__ import annotations
import hashlib, json, os, re, sys
from collections import defaultdict
from pathlib import Path

from .settings import settings
from . import embeddings
from .chunking import chunk_pages, TARGET_WORDS as TARGET_HINT

STATE_FILE = Path(settings.data_dir) / "ingest_state.json"
COLLECTIONS_FILE = Path(settings.data_dir) / "collections.json"


def _books_manifest() -> dict:
    """Optional code_books/books.yaml: {filename: {book, edition, is_amendment_doc, collection}}."""
    man = Path(settings.code_books_dir) / "books.yaml"
    if man.exists():
        import yaml
        return yaml.safe_load(man.read_text()) or {}
    return {}


def _meta_for(pdf: Path, manifest: dict) -> dict:
    entry = manifest.get(pdf.name, {})
    name = pdf.stem
    return {
        "book": entry.get("book", name),
        "edition": entry.get("edition", "?"),
        # Heuristic fallback: filename hints it's a CT amendment doc.
        "is_amendment_doc": entry.get("is_amendment_doc",
                                      any(k in name.lower() for k in ("amend", "ct-", "csfsc-amd"))),
        # Which Chroma collection (code cycle) this book belongs to.
        "collection": entry.get("collection", settings.active_collection),
    }


_MIN_PAGE_CHARS = 20   # below this a page is "empty" — try the fallback, then flag for OCR


def _pypdf_pages(pdf: Path) -> list[str] | None:
    """Per-page text via pypdf (the declared fallback extractor). None if pypdf can't read it."""
    try:
        from pypdf import PdfReader
        return [(p.extract_text() or "") for p in PdfReader(str(pdf)).pages]
    except Exception:
        return None


def _read_pdf(pdf: Path) -> tuple[list[tuple[int, str]], dict]:
    """Extract (page_no, text) for every page, with a real fallback chain:
    PyMuPDF → pypdf for any near-empty page. A page that stays empty AND has images is almost
    certainly scanned/image-only — we flag it so the marshal knows it needs OCR (we never OCR
    silently). Returns (pages, info) where info reports empty/image pages and whether pypdf helped.
    """
    import fitz  # PyMuPDF
    doc = fitz.open(pdf)
    pages: list[tuple[int, str]] = []
    pypdf_text: list[str] | None = None
    empty = image_only = 0
    used_fallback = False

    for i, page in enumerate(doc):
        text = page.get_text("text")
        if len(text.strip()) < _MIN_PAGE_CHARS:
            if pypdf_text is None:
                pypdf_text = _pypdf_pages(pdf) or []
            alt = pypdf_text[i] if i < len(pypdf_text) else ""
            if len(alt.strip()) >= _MIN_PAGE_CHARS:
                text, used_fallback = alt, True
            else:
                empty += 1
                if page.get_images():          # near-empty but has images → scanned page
                    image_only += 1
        pages.append((i + 1, text))

    info = {"pages": len(pages), "empty_pages": empty, "image_only_pages": image_only,
            "needs_ocr": image_only > 0, "used_pypdf_fallback": used_fallback}
    return pages, info


_TABLE_CAP = re.compile(r"TABLE\s+([0-9]+(?:\.[0-9]+)*[A-Z]?)", re.IGNORECASE)


def _table_chunks(pdf: Path, meta: dict) -> list[dict]:
    """Extract RULED tables as their own markdown chunks (tagged is_table), so "what's the value
    in row X" questions keep structure instead of degrading to one flattened blob. Best-effort and
    defensive — any failure just yields no table chunks (the flattened text path still covers it).
    The section is taken from a "TABLE 903.2.11.6" caption on the same page when present.
    """
    import fitz
    out: list[dict] = []
    try:
        doc = fitz.open(pdf)
    except Exception:
        return out
    for i, page in enumerate(doc):
        try:
            found = getattr(page.find_tables(), "tables", []) or []
        except Exception:
            continue
        if not found:
            continue
        caps = _TABLE_CAP.findall(page.get_text("text"))
        for ti, t in enumerate(found):
            try:
                md = t.to_markdown()
            except Exception:
                continue
            if not md or not md.strip():
                continue
            section = caps[ti] if ti < len(caps) else (caps[0] if caps else "(table)")
            out.append({"text": md, "metadata": {
                "book": meta["book"], "edition": meta["edition"], "section": section,
                "page": i + 1, "is_amendment": bool(meta.get("is_amendment_doc")), "is_table": True}})
    doc.close()
    return out


def _file_hash(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def ingest(force: bool = False) -> dict:
    import chromadb
    books_dir = Path(os.path.expanduser(settings.code_books_dir))
    pdfs = sorted(books_dir.glob("*.pdf"))
    if not pdfs:
        return {"error": f"No PDFs found in {books_dir}. Put your code books there."}

    manifest = _books_manifest()
    state = _load_json(STATE_FILE)
    collections_idx = _load_json(COLLECTIONS_FILE)   # cumulative: {collection: {file: {...}}}
    client = chromadb.PersistentClient(path=settings.chroma_dir)

    open_colls: dict[str, object] = {}
    def _coll(name: str):
        if name not in open_colls:
            open_colls[name] = client.get_or_create_collection(name)
        return open_colls[name]

    per_collection: dict[str, dict] = defaultdict(lambda: {"books": [], "chunks": 0})
    summary = {"chunks_added": 0, "skipped": []}

    for pdf in pdfs:
        meta = _meta_for(pdf, manifest)
        cname = meta["collection"]
        h = _file_hash(pdf)
        stamp = f"{h}|{cname}"                        # re-ingest if the file OR its collection changed
        if not force and state.get(pdf.name) == stamp:
            summary["skipped"].append(pdf.name)
            continue

        pages, pdf_info = _read_pdf(pdf)
        if pdf_info["needs_ocr"]:
            summary.setdefault("needs_ocr", []).append(
                {"file": pdf.name, "image_only_pages": pdf_info["image_only_pages"]})
            print(f"  ⚠️  {pdf.name}: {pdf_info['image_only_pages']} image-only page(s) yielded no "
                  f"text — this book is scanned and needs OCR. Run e.g. "
                  f"`ocrmypdf in.pdf out.pdf` (brew install ocrmypdf), then re-ingest the OCR'd copy.")
        chunks = chunk_pages(pages, meta)
        if settings.extract_tables:
            chunks += _table_chunks(pdf, meta)      # structured (markdown) tables alongside text
        if not chunks:
            continue

        ids = [f"{meta['book']}|{c['metadata']['page']}|{i}" for i, c in enumerate(chunks)]
        texts = [c["text"] for c in chunks]
        metas = [c["metadata"] for c in chunks]

        coll = _coll(cname)
        B = 64                                        # batch embed+upsert to keep memory flat
        for s in range(0, len(texts), B):
            vecs = embeddings.embed(texts[s:s + B], input_type="document")
            coll.upsert(ids=ids[s:s + B], documents=texts[s:s + B],
                        metadatas=metas[s:s + B], embeddings=vecs)

        state[pdf.name] = stamp
        collections_idx.setdefault(cname, {})[pdf.name] = {
            "book": meta["book"], "edition": meta["edition"],
            "amendment_doc": meta["is_amendment_doc"], "chunks": len(chunks)}
        per_collection[cname]["books"].append({"file": pdf.name, "chunks": len(chunks),
                                               "edition": meta["edition"],
                                               "amendment_doc": meta["is_amendment_doc"]})
        per_collection[cname]["chunks"] += len(chunks)
        summary["chunks_added"] += len(chunks)
        print(f"  indexed {pdf.name}: {len(chunks)} chunks -> collection '{cname}'")

    _save_json(STATE_FILE, state)
    _save_json(COLLECTIONS_FILE, collections_idx)
    summary["collections"] = {k: dict(v) for k, v in per_collection.items()}
    summary["active_collection"] = settings.active_collection
    return summary


def list_collections() -> list[dict]:
    """All indexed collections (code cycles) with their books, editions, and chunk counts.

    Reads the ingest-maintained index; falls back to whatever Chroma actually has on disk.
    """
    idx = _load_json(COLLECTIONS_FILE)
    out = []
    if idx:
        for name, books in idx.items():
            editions = sorted({b.get("edition", "?") for b in books.values()})
            out.append({
                "name": name,
                "books": len(books),
                "chunks": sum(b.get("chunks", 0) for b in books.values()),
                "editions": editions,
                "active": name == settings.active_collection,
            })
        return sorted(out, key=lambda c: c["name"])
    # Fallback: ask Chroma directly (no per-book detail).
    try:
        import chromadb
        client = chromadb.PersistentClient(path=settings.chroma_dir)
        for c in client.list_collections():
            out.append({"name": c.name, "books": None, "chunks": c.count(),
                        "editions": [], "active": c.name == settings.active_collection})
    except Exception:
        pass
    return out


def inspect(samples: int = 2) -> dict:
    """Dry run: extract + chunk every PDF and report how section detection landed — WITHOUT
    embedding or writing to Chroma. Run this on a real book FIRST to confirm section numbers,
    pages, tables, amendment tags, and collection routing look right before a full ingest:

        python -m app.ingest --inspect
    """
    books_dir = Path(os.path.expanduser(settings.code_books_dir))
    pdfs = sorted(books_dir.glob("*.pdf"))
    if not pdfs:
        return {"error": f"No PDFs found in {books_dir}. Put your code books there."}
    manifest = _books_manifest()

    for pdf in pdfs:
        meta = _meta_for(pdf, manifest)
        pages, pdf_info = _read_pdf(pdf)
        chunks = chunk_pages(pages, meta)
        sections = [c["metadata"]["section"] for c in chunks]
        preamble = sum(s == "(preamble)" for s in sections)
        tables = sum(c["metadata"]["is_table"] for c in chunks)
        amend = sum(c["metadata"]["is_amendment"] for c in chunks)
        sizes = sorted(len(c["text"].split()) for c in chunks) or [0]

        print(f"\n===== {pdf.name} =====")
        print(f"  book={meta['book']!r} edition={meta['edition']!r} "
              f"collection={meta['collection']!r} amendment_doc={meta['is_amendment_doc']}")
        print(f"  pages={len(pages)}  chunks={len(chunks)}  tables={tables}  amendment_chunks={amend}")
        print(f"  distinct sections={len(set(sections))}  (preamble)-only chunks={preamble}")
        print(f"  chunk size words: min={sizes[0]} median={sizes[len(sizes)//2]} max={sizes[-1]}")
        flags = []
        if pdf_info["needs_ocr"]:
            flags.append(f"{pdf_info['image_only_pages']} image-only page(s) -> SCANNED book, needs OCR "
                         "(text extraction returned nothing for them)")
        if pdf_info["used_pypdf_fallback"]:
            flags.append("used the pypdf fallback on some pages (PyMuPDF returned little/no text)")
        if pdf_info["empty_pages"]:
            flags.append(f"{pdf_info['empty_pages']} page(s) had no extractable text")
        if preamble > max(1, len(chunks) // 5):
            flags.append("many (preamble) chunks -> section regex may not match this book's numbering")
        if sizes[-1] >= TARGET_HINT:
            flags.append(f"largest chunk is {sizes[-1]} words -> long sections are being sub-split (expected)")
        if len(chunks) and tables == 0:
            flags.append("no tables detected (fine if the book has none / they're images)")
        if flags:
            print("  flags: " + "; ".join(flags))
        print(f"  --- first {samples} chunk(s) ---")
        for c in chunks[:samples]:
            m = c["metadata"]
            head = c["text"].splitlines()[0][:80] if c["text"] else ""
            print(f"    §{m['section']} p.{m['page']} amd={m['is_amendment']} tbl={m['is_table']}  | {head}")
    return {"inspected": len(pdfs)}


if __name__ == "__main__":
    if "--inspect" in sys.argv:
        print(f"Inspecting (dry run) {settings.code_books_dir} — no embedding, nothing written")
        inspect()
    elif "--collections" in sys.argv:
        for c in list_collections():
            star = " (active)" if c["active"] else ""
            print(f"  {c['name']}{star}: {c['chunks']} chunks, {c['books']} books, "
                  f"editions={c['editions']}")
    else:
        force = "--force" in sys.argv
        print(f"Ingesting from {settings.code_books_dir} (one collection per edition)")
        out = ingest(force=force)
        print(json.dumps(out, indent=2))
