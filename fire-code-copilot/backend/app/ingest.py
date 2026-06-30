"""Ingestion: read PDFs from CODE_BOOKS_DIR -> section-aware chunks -> local embeddings ->
Chroma. Run once after adding/updating books:  python -m app.ingest

Books stay where they are (e.g. your Desktop folder). Only the derived index lives in
DATA_DIR/chroma (gitignored). An optional code_books/books.yaml lets you set each PDF's
book/edition and mark which files are Connecticut amendment documents.
"""
from __future__ import annotations
import hashlib, json, os, sys
from pathlib import Path

from .settings import settings
from . import embeddings
from .chunking import chunk_pages

STATE_FILE = Path(settings.data_dir) / "ingest_state.json"


def _books_manifest() -> dict:
    """Optional code_books/books.yaml: {filename: {book, edition, is_amendment_doc}}."""
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
    }


def _read_pdf(pdf: Path) -> list[tuple[int, str]]:
    import fitz  # PyMuPDF
    doc = fitz.open(pdf)
    return [(i + 1, page.get_text("text")) for i, page in enumerate(doc)]


def _file_hash(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _load_state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def ingest(force: bool = False) -> dict:
    import chromadb
    books_dir = Path(os.path.expanduser(settings.code_books_dir))
    pdfs = sorted(books_dir.glob("*.pdf"))
    if not pdfs:
        return {"error": f"No PDFs found in {books_dir}. Put your code books there."}

    manifest = _books_manifest()
    state = _load_state()
    client = chromadb.PersistentClient(path=settings.chroma_dir)
    coll = client.get_or_create_collection(settings.active_collection)

    summary = {"collection": settings.active_collection, "books": [], "chunks_added": 0, "skipped": []}

    for pdf in pdfs:
        h = _file_hash(pdf)
        if not force and state.get(pdf.name) == h:
            summary["skipped"].append(pdf.name)
            continue

        meta = _meta_for(pdf, manifest)
        chunks = chunk_pages(_read_pdf(pdf), meta)
        if not chunks:
            continue

        ids = [f"{meta['book']}|{c['metadata']['page']}|{i}" for i, c in enumerate(chunks)]
        texts = [c["text"] for c in chunks]
        metas = [c["metadata"] for c in chunks]

        # Embed + upsert in batches (keeps memory flat on large books).
        B = 64
        for s in range(0, len(texts), B):
            vecs = embeddings.embed(texts[s:s + B], input_type="document")
            coll.upsert(ids=ids[s:s + B], documents=texts[s:s + B],
                        metadatas=metas[s:s + B], embeddings=vecs)

        state[pdf.name] = h
        summary["books"].append({"file": pdf.name, "chunks": len(chunks),
                                 "edition": meta["edition"], "amendment_doc": meta["is_amendment_doc"]})
        summary["chunks_added"] += len(chunks)
        print(f"  indexed {pdf.name}: {len(chunks)} chunks")

    _save_state(state)
    return summary


if __name__ == "__main__":
    force = "--force" in sys.argv
    print(f"Ingesting from {settings.code_books_dir} -> collection '{settings.active_collection}'")
    out = ingest(force=force)
    print(json.dumps(out, indent=2))
