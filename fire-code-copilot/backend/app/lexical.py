"""Lexical (BM25) retrieval channel for hybrid search.

Dense embeddings are great at meaning but weak at EXACT tokens — and code questions are full of
them: section numbers ("903.2.11.6"), standard names ("NFPA 13"), "Table 509". BM25 nails those.
We run BM25 alongside the dense query and fuse the two rankings (see retriever._fuse), so a
verbatim section/standard lookup can't fall through the cracks.

The BM25 index is built from the collection's documents and cached per (store, collection, size)
so it rebuilds only when the collection changes.
"""
from __future__ import annotations
import re
from pathlib import Path

from .settings import settings

# Tokenizer that keeps dotted section numbers ("903.2.8") and standard refs as single tokens.
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)+|[a-z0-9]+")

# (store_path, collection_name, count) -> (BM25Okapi, ids, docs, metas)
_cache: dict[tuple, tuple] = {}


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def _store_revision() -> tuple[int, int]:
    """Filesystem revision for external Chroma writes that do not change collection count."""
    root = Path(settings.chroma_dir)
    stamps = []
    for path in (root / "chroma.sqlite3", root / "chroma.sqlite3-wal"):
        try:
            stamps.append(path.stat().st_mtime_ns)
        except OSError:
            stamps.append(0)
    return tuple(stamps)


def _index_for(coll):
    n = coll.count()
    key = (settings.chroma_dir, coll.name, n, _store_revision())
    hit = _cache.get(key)
    if hit is not None:
        return hit
    # Chroma/SQLite can exceed its SQL-variable limit on one unbounded get after a corpus grows.
    # Page large collections and cache the assembled immutable BM25 view.
    page_size = 5000
    if n <= page_size:
        got = coll.get(include=["documents", "metadatas"])
        ids = got.get("ids", []) or []
        docs = got.get("documents", []) or []
        metas = got.get("metadatas", []) or []
    else:
        ids, docs, metas = [], [], []
        for offset in range(0, n, page_size):
            got = coll.get(
                include=["documents", "metadatas"],
                limit=min(page_size, n - offset),
                offset=offset,
            )
            ids.extend(got.get("ids", []) or [])
            docs.extend(got.get("documents", []) or [])
            metas.extend(got.get("metadatas", []) or [])
    bm25 = None
    if docs:
        from rank_bm25 import BM25Okapi
        # Searchable text includes provenance labels as well as body text. Chapter-split NFPA PDFs
        # often omit "NFPA 101" from the extracted body after page boilerplate is removed, even
        # though `book` and `source` identify them exactly. Indexing those labels lets an explicit
        # book request retrieve the requested book without altering text handed to the model.
        searchable = [
            f"{(m or {}).get('book', '')} {(m or {}).get('source', '')} {d}"
            for d, m in zip(docs, metas)
        ]
        bm25 = BM25Okapi([_tokenize(d) for d in searchable])
    _cache[key] = (bm25, ids, docs, metas)
    return _cache[key]


def search(coll, query: str, k: int) -> list[dict]:
    """Top-k lexical matches for `query`: [{id, text, metadata, score}], best first (score > 0)."""
    bm25, ids, docs, metas = _index_for(coll)
    if bm25 is None:
        return []
    toks = _tokenize(query)
    if not toks:
        return []
    scores = bm25.get_scores(toks)
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    return [{"id": ids[i], "text": docs[i], "metadata": metas[i] or {}, "score": float(scores[i])}
            for i in order if scores[i] > 0]


def reset_cache() -> None:
    """Drop the cached BM25 indexes (used by tests; also safe after a re-ingest)."""
    _cache.clear()
