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

from .settings import settings

# Tokenizer that keeps dotted section numbers ("903.2.8") and standard refs as single tokens.
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)+|[a-z0-9]+")

# (store_path, collection_name, count) -> (BM25Okapi, ids, docs, metas)
_cache: dict[tuple, tuple] = {}


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def _index_for(coll):
    key = (settings.chroma_dir, coll.name, coll.count())
    hit = _cache.get(key)
    if hit is not None:
        return hit
    got = coll.get(include=["documents", "metadatas"])
    ids = got.get("ids", []) or []
    docs = got.get("documents", []) or []
    metas = got.get("metadatas", []) or []
    bm25 = None
    if docs:
        from rank_bm25 import BM25Okapi
        bm25 = BM25Okapi([_tokenize(d) for d in docs])
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
