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


def _pdfs(books_dir: Path) -> list[Path]:
    """All PDFs under the configured books folder, including organized subfolders."""
    return sorted(p for p in books_dir.rglob("*.pdf") if p.is_file())


def _book_key(pdf: Path, books_dir: Path) -> str:
    """Stable source key stored in Chroma/state: POSIX relative path from CODE_BOOKS_DIR."""
    try:
        return pdf.relative_to(books_dir).as_posix()
    except ValueError:
        return pdf.name


def _collection_name(base: str, version_suffix: str | None = None) -> str:
    """Keep the adopted index untouched when running an OCR/BGE candidate ingest for A/B eval."""
    suffix = (version_suffix if version_suffix is not None else settings.index_version_suffix).strip()
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", suffix).strip("-")
    return f"{base}__{clean}" if clean else base


def _meta_for(pdf: Path, manifest: dict, books_dir: Path | None = None) -> dict:
    # Prefer a relative path manifest key for nested folders, but keep the old bare-filename
    # lookup for backwards compatibility with existing top-level books.yaml files.
    key = _book_key(pdf, books_dir) if books_dir else pdf.name
    entry = manifest.get(key, manifest.get(pdf.name, {}))
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


def _page_png(page) -> bytes:
    """Render a page once for oMLX vision/OCR. Kept as bytes for cache hashing too."""
    return page.get_pixmap(dpi=settings.ocr_dpi, alpha=False).tobytes("png")


def _omlx_ocr(png: bytes, *, model: str, table_mode: bool = False) -> str:
    """Ask a local oMLX vision model for clean Markdown. No in-process OCR dependency."""
    import base64
    from openai import OpenAI
    instruction = (
        "Transcribe this fire/building code page faithfully as structured Markdown. Preserve section "
        "numbers, headings, paragraphs, footnotes, and line breaks. Do not summarize or invent text."
    )
    if table_mode:
        instruction += " Reconstruct every visible table as a GitHub-flavored Markdown table; preserve exact headers, rows, and numeric values."
    client = OpenAI(base_url=settings.local_base_url, api_key=settings.local_api_key or "not-needed")
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": instruction},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
    )
    return (response.choices[0].message.content or "").strip()


def _looks_table_heavy(page, extracted: str) -> bool:
    """Cheap local gate: table OCR is never called unless explicitly enabled and page looks tabular."""
    if "table" in (extracted or "").lower() or "|" in (extracted or ""):
        return True
    try:
        return bool(getattr(page.find_tables(), "tables", []) or [])
    except Exception:
        return False


def _ocr_page(page, extracted: str, cache: dict, page_no: int) -> tuple[str, bool]:
    """Return cached/default OCR Markdown and whether table OCR supplied it."""
    png = _page_png(page)
    page_hash = hashlib.sha256(png).hexdigest()
    table = bool(settings.ocr_table_enabled and _looks_table_heavy(page, extracted))
    model = settings.ocr_table_model if table else settings.ocr_model
    key = f"{settings.ocr_cache_version}|{model}|{page_hash}"
    if key not in cache:
        cache[key] = {"markdown": _omlx_ocr(png, model=model, table_mode=table), "table_mode": table,
                      "page": page_no}
    entry = cache[key]
    return str(entry.get("markdown", "")), bool(entry.get("table_mode"))


def _ocr_cache_path(pdf: Path) -> Path:
    # Keyed by content hash so an edited PDF re-OCRs; lives under gitignored data/ (copyright-safe).
    return Path(settings.data_dir) / "ocr_cache" / f"{_file_hash(pdf)}.json"


def _page_text(page) -> str:
    """Extract a page's text in READING ORDER, handling multi-column code pages.

    PyMuPDF's default `get_text("text")` linearizes strictly top-to-bottom, which on a typical
    two-column code page interleaves the columns (a left-column line, then the right-column line at
    the same height, and so on) — splicing unrelated provisions together and corrupting citations.
    Instead we read block-by-block: full-width blocks (headings/rules that span the page) in place,
    and within each horizontal band the LEFT column fully, then the RIGHT column. Falls back to
    plain extraction when the page isn't clearly two-column (so single-column books are unchanged).
    """
    try:
        raw = page.get_text("blocks")
    except Exception:
        return page.get_text("text")
    # blocks: (x0, y0, x1, y1, text, block_no, block_type). Keep non-empty TEXT blocks (type 0).
    blocks = [b for b in raw if len(b) >= 5 and str(b[4]).strip() and (len(b) < 7 or b[6] == 0)]
    if not blocks:
        return page.get_text("text")

    width = float(page.rect.width) or 1.0
    mid = width / 2.0

    def is_full(b):        # spans past the centerline → a full-width heading/rule, not a column
        return (b[2] - b[0]) > 0.55 * width

    def center(b):
        return (b[0] + b[2]) / 2.0

    lefts = [b for b in blocks if not is_full(b) and center(b) < mid]
    rights = [b for b in blocks if not is_full(b) and center(b) >= mid]
    # Not clearly two-column → read in natural (top, then left) order.
    if not lefts or not rights:
        ordered = sorted(blocks, key=lambda b: (round(b[1], 1), b[0]))
        return "\n".join(str(b[4]).strip() for b in ordered)

    # Two-column: scan top-to-bottom buffering each column; a full-width block flushes the current
    # band (left column then right column) and is emitted in place.
    out: list[str] = []
    lbuf: list = []
    rbuf: list = []

    def flush():
        for b in sorted(lbuf, key=lambda b: b[1]):
            out.append(str(b[4]).strip())
        for b in sorted(rbuf, key=lambda b: b[1]):
            out.append(str(b[4]).strip())
        lbuf.clear()
        rbuf.clear()

    for b in sorted(blocks, key=lambda b: (round(b[1], 1), b[0])):
        if is_full(b):
            flush()
            out.append(str(b[4]).strip())
        elif center(b) < mid:
            lbuf.append(b)
        else:
            rbuf.append(b)
    flush()
    return "\n".join(t for t in out if t)


def _read_pdf(pdf: Path) -> tuple[list[tuple[int, str]], dict]:
    """Extract (page_no, text) for every page, with a real fallback chain:
    PyMuPDF → pypdf → (optional) OCR for any near-empty page that is actually a scanned image.
    OCR is opt-in (USE_OCR) and cached under data/ocr_cache so re-ingest doesn't re-OCR. A page
    that stays empty AND has images is flagged so the marshal knows it needs OCR. Returns
    (pages, info) with per-book extraction stats.
    """
    import fitz  # PyMuPDF
    doc = fitz.open(pdf)
    pages: list[tuple[int, str]] = []
    pypdf_text: list[str] | None = None
    empty = image_only = ocr_pages = table_ocr_pages = 0
    used_fallback = False

    # OCR cache is keyed per rendered-page hash + model/version, so a PDF edit only re-OCRs changed pages.
    ocr_cache: dict = {}
    ocr_cache_dirty = False
    if settings.use_ocr:
        cp = _ocr_cache_path(pdf)
        ocr_cache = _load_json(cp) if cp.exists() else {}

    for i, page in enumerate(doc):
        text = _page_text(page)                    # reading-order aware (de-interleaves columns)
        if settings.use_ocr:
            try:
                ocr_text, table_mode = _ocr_page(page, text, ocr_cache, i + 1)
                ocr_cache_dirty = True
                if len(ocr_text.strip()) >= _MIN_PAGE_CHARS:
                    text, ocr_pages = ocr_text, ocr_pages + 1
                    table_ocr_pages += int(table_mode)
            except Exception as exc:
                # Retain selectable-text extraction if a model/page fails; ingest must be resumable.
                print(f"  OCR warning page {i + 1}: {type(exc).__name__}: {exc}")
        if len(text.strip()) < _MIN_PAGE_CHARS:
            if pypdf_text is None:
                pypdf_text = _pypdf_pages(pdf) or []
            alt = pypdf_text[i] if i < len(pypdf_text) else ""
            if len(alt.strip()) >= _MIN_PAGE_CHARS:
                text, used_fallback = alt, True
            elif page.get_images():
                empty += 1; image_only += 1
            else:
                empty += 1
        pages.append((i + 1, text))

    if ocr_cache_dirty:
        _save_json(_ocr_cache_path(pdf), ocr_cache)

    info = {"pages": len(pages), "empty_pages": empty, "image_only_pages": image_only,
            "ocr_pages": ocr_pages, "table_ocr_pages": table_ocr_pages,
            "needs_ocr": image_only > 0, "used_pypdf_fallback": used_fallback}
    doc.close()
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


def ingest(force: bool = False, on_event=None, version_suffix: str | None = None) -> dict:
    """Index every PDF in the books folder. `on_event`, when given, receives progress dicts
    ({"type": "start"|"file"|"file_done"|"removed"|"done", ...}) so a UI can show live progress
    instead of staring at a blocked request."""
    import chromadb

    def emit(ev: dict) -> None:
        if on_event:
            try:
                on_event(ev)
            except Exception:
                pass  # progress reporting must never break indexing

    books_dir = Path(os.path.expanduser(settings.code_books_dir))
    pdfs = _pdfs(books_dir)
    if not pdfs:
        return {"error": f"No PDFs found in {books_dir}. Put your code books there."}
    emit({"type": "start", "files": len(pdfs)})

    manifest = _books_manifest()
    state = _load_json(STATE_FILE)
    collections_idx = _load_json(COLLECTIONS_FILE)   # cumulative: {collection: {file: {...}}}
    client = chromadb.PersistentClient(path=settings.chroma_dir)

    if force:
        # A forced ingest must recreate collections, not just overwrite rows. Chroma fixes a
        # collection's embedding dimension at first insert; switching from the old 384-dim local
        # embedder to oMLX/BGE-M3's 1024-dim vectors otherwise fails with a dimension mismatch.
        target_collections = {_collection_name(settings.active_collection, version_suffix), *collections_idx.keys()}
        for pdf in pdfs:
            try:
                target_collections.add(_collection_name(_meta_for(pdf, manifest, books_dir)["collection"], version_suffix))
            except Exception:
                pass
        for cname in sorted(c for c in target_collections if c):
            try:
                client.delete_collection(cname)
                print(f"  reset collection '{cname}' for forced re-ingest")
            except Exception:
                pass
        state = {}
        collections_idx = {}

    open_colls: dict[str, object] = {}
    def _coll(name: str):
        if name not in open_colls:
            open_colls[name] = client.get_or_create_collection(name)
        return open_colls[name]

    per_collection: dict[str, dict] = defaultdict(lambda: {"books": [], "chunks": 0})
    summary = {"chunks_added": 0, "skipped": []}

    for pdf in pdfs:
        key = _book_key(pdf, books_dir)
        meta = _meta_for(pdf, manifest, books_dir)
        cname = _collection_name(meta["collection"], version_suffix)
        h = _file_hash(pdf)
        stamp = f"{h}|{cname}|{settings.embedding_model}|{settings.ingest_version}"
        if not force and state.get(key) == stamp:
            summary["skipped"].append(key)
            emit({"type": "file", "file": key, "status": "skipped"})
            continue

        emit({"type": "file", "file": key, "status": "indexing"})
        pages, pdf_info = _read_pdf(pdf)
        if pdf_info["needs_ocr"]:
            summary.setdefault("needs_ocr", []).append(
                {"file": key, "image_only_pages": pdf_info["image_only_pages"]})
            print(f"  ⚠️  {key}: {pdf_info['image_only_pages']} image-only page(s) yielded no "
                  f"text — this book is scanned and needs OCR. Run e.g. "
                  f"`ocrmypdf in.pdf out.pdf` (brew install ocrmypdf), then re-ingest the OCR'd copy.")
        chunks = chunk_pages(pages, meta)
        if settings.extract_tables:
            chunks += _table_chunks(pdf, meta)      # structured (markdown) tables alongside text
        if not chunks:
            continue

        # Ids are keyed by the FILE (not the book label): two volumes sharing a `book` value must
        # not overwrite each other's chunks.
        ids = [f"{key}|{c['metadata']['page']}|{i}" for i, c in enumerate(chunks)]
        texts = [c["text"] for c in chunks]
        metas = [c["metadata"] for c in chunks]
        for m in metas:
            m["source"] = key                         # provenance + lets re-ingest purge cleanly
            m["ingest_version"] = settings.ingest_version
            m["embedding_model"] = settings.embedding_model

        coll = _coll(cname)
        # Re-ingest hygiene: drop this file's PRIOR vectors before re-indexing it. Chunk ids are
        # positional (…|page|i), so a corrected/updated book re-chunks to shifted ids and the old
        # vectors would otherwise linger — leaving outdated code text retrievable and citable. We
        # key the purge on the source filename so exactly this file's chunks are replaced. If the
        # manifest moved this file to a DIFFERENT collection, purge its copy from the old one too,
        # so a stale duplicate can't keep answering queries in the previous cycle.
        try:
            coll.delete(where={"source": key})
        except Exception:
            pass
        for old_cname, files in list(collections_idx.items()):
            if old_cname != cname and key in files:
                try:
                    _coll(old_cname).delete(where={"source": key})
                except Exception:
                    pass
                files.pop(key, None)
        B = 64                                        # batch embed+upsert to keep memory flat
        for s in range(0, len(texts), B):
            vecs = embeddings.embed(texts[s:s + B], input_type="document")
            coll.upsert(ids=ids[s:s + B], documents=texts[s:s + B],
                        metadatas=metas[s:s + B], embeddings=vecs)

        state[key] = stamp
        collections_idx.setdefault(cname, {})[key] = {
            "book": meta["book"], "edition": meta["edition"],
            "amendment_doc": meta["is_amendment_doc"], "chunks": len(chunks)}
        per_collection[cname]["books"].append({"file": key, "chunks": len(chunks),
                                               "edition": meta["edition"],
                                               "amendment_doc": meta["is_amendment_doc"]})
        per_collection[cname]["chunks"] += len(chunks)
        summary["chunks_added"] += len(chunks)
        emit({"type": "file_done", "file": key, "chunks": len(chunks), "collection": cname})
        print(f"  indexed {key}: {len(chunks)} chunks -> collection '{cname}'")

    # Files DELETED from the books folder: purge their chunks from every collection that holds
    # them. Without this, removing a book leaves its text permanently retrievable and citable.
    current = {_book_key(p, books_dir) for p in pdfs}
    for gone in [name for name in state if name not in current]:
        for old_cname, files in list(collections_idx.items()):
            if gone in files:
                try:
                    _coll(old_cname).delete(where={"source": gone})
                except Exception:
                    pass
                files.pop(gone, None)
        state.pop(gone, None)
        summary.setdefault("removed", []).append(gone)
        emit({"type": "removed", "file": gone})
        print(f"  removed {gone}: purged its chunks (file no longer in the books folder)")

    _save_json(STATE_FILE, state)
    _save_json(COLLECTIONS_FILE, collections_idx)

    # The BM25 index is cached per (store, collection, count); a same-size re-ingest would keep
    # serving the replaced text. Anything indexed/purged above invalidates the lexical channel.
    from . import lexical
    lexical.reset_cache()

    summary["collections"] = {k: dict(v) for k, v in per_collection.items()}
    summary["active_collection"] = settings.active_collection
    emit({"type": "done", "summary": summary})
    return summary


def list_books() -> list[dict]:
    """Every PDF in the books folder with its manifest entry (or heuristics) and indexed state —
    what the Library UI shows. Filenames + metadata only; never any code text."""
    books_dir = Path(os.path.expanduser(settings.code_books_dir))
    manifest = _books_manifest()
    state = _load_json(STATE_FILE)
    collections_idx = _load_json(COLLECTIONS_FILE)
    indexed_in: dict[str, tuple[str, int]] = {}
    for cname, files in collections_idx.items():
        for fname, info in files.items():
            indexed_in[fname] = (cname, int(info.get("chunks", 0)))
    out = []
    for pdf in _pdfs(books_dir):
        key = _book_key(pdf, books_dir)
        meta = _meta_for(pdf, manifest, books_dir)
        coll, chunks = indexed_in.get(key, ("", 0))
        out.append({
            "file": key,
            "book": meta["book"],
            "edition": meta["edition"],
            "collection": meta["collection"],
            "is_amendment_doc": meta["is_amendment_doc"],
            "in_manifest": key in manifest or pdf.name in manifest,
            "indexed": key in state,
            "indexed_collection": coll,
            "chunks": chunks,
        })
    return out


# Manifest fields the UI may set; anything else in the payload is dropped.
_MANIFEST_FIELDS = ("book", "edition", "collection", "is_amendment_doc")


def save_books_manifest(entries: dict) -> dict:
    """Write code_books/books.yaml from {filename: {book, edition, collection, is_amendment_doc}}.
    Only files actually present in the books folder are written (no dangling entries), and only
    the known fields are kept. The manifest lives in the gitignored books folder."""
    import yaml
    books_dir = Path(os.path.expanduser(settings.code_books_dir))
    present = {_book_key(p, books_dir) for p in _pdfs(books_dir)}
    clean: dict[str, dict] = {}
    for fname, fields in (entries or {}).items():
        if fname not in present or not isinstance(fields, dict):
            continue
        entry = {k: fields[k] for k in _MANIFEST_FIELDS if k in fields}
        if "is_amendment_doc" in entry:
            entry["is_amendment_doc"] = bool(entry["is_amendment_doc"])
        if entry:
            clean[fname] = entry
    (books_dir / "books.yaml").write_text(
        yaml.safe_dump(clean, sort_keys=True, allow_unicode=True), encoding="utf-8")
    return {"saved": len(clean), "manifest": clean}


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
    pdfs = _pdfs(books_dir)
    if not pdfs:
        return {"error": f"No PDFs found in {books_dir}. Put your code books there."}
    manifest = _books_manifest()

    for pdf in pdfs:
        key = _book_key(pdf, books_dir)
        meta = _meta_for(pdf, manifest, books_dir)
        pages, pdf_info = _read_pdf(pdf)
        chunks = chunk_pages(pages, meta)
        sections = [c["metadata"]["section"] for c in chunks]
        preamble = sum(s == "(preamble)" for s in sections)
        tables = sum(c["metadata"]["is_table"] for c in chunks)
        amend = sum(c["metadata"]["is_amendment"] for c in chunks)
        sizes = sorted(len(c["text"].split()) for c in chunks) or [0]

        print(f"\n===== {key} =====")
        print(f"  book={meta['book']!r} edition={meta['edition']!r} "
              f"collection={meta['collection']!r} amendment_doc={meta['is_amendment_doc']}")
        print(f"  pages={len(pages)}  chunks={len(chunks)}  tables={tables}  amendment_chunks={amend}")
        print(f"  distinct sections={len(set(sections))}  (preamble)-only chunks={preamble}")
        print(f"  chunk size words: min={sizes[0]} median={sizes[len(sizes)//2]} max={sizes[-1]}")
        flags = []
        if pdf_info.get("ocr_pages"):
            flags.append(f"OCR'd {pdf_info['ocr_pages']} scanned page(s) (USE_OCR is on)")
        if pdf_info["needs_ocr"]:
            hint = "enable USE_OCR (needs tesseract) or " if not settings.use_ocr else ""
            flags.append(f"{pdf_info['image_only_pages']} image-only page(s) -> SCANNED book: {hint}"
                         "OCR the file (ocrmypdf) and re-ingest")
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
