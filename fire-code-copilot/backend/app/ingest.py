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
import hashlib, json, os, sys
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


def _read_pdf(pdf: Path) -> list[tuple[int, str]]:
    import fitz  # PyMuPDF
    doc = fitz.open(pdf)
    return [(i + 1, page.get_text("text")) for i, page in enumerate(doc)]


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

        chunks = chunk_pages(_read_pdf(pdf), meta)
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
        pages = _read_pdf(pdf)
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
