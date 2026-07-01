"""Retrieval: query -> top candidates (recall) -> reranker (precision) -> labeled chunks.

Returns chunks with rich metadata so downstream citation validation and the agent prompt can
show the marshal exactly which book/section/page each fact came from. Also merges Connecticut
amendments so the adopted/amended text is marked as controlling.
"""
from __future__ import annotations
from collections import defaultdict
from .settings import settings
from .reranker import rerank
from . import embeddings  # provider-agnostic embed(); see embeddings.py
from . import lexical     # BM25 channel for exact-token matches
from .sections import relates
from .query import expand_query


def _client():
    import chromadb
    return chromadb.PersistentClient(path=settings.chroma_dir)


def _format(meta: dict, text: str) -> dict:
    return {"text": text, "metadata": meta}


def retrieve(query: str, *, collection: str | None = None) -> list[dict]:
    """Return the top reranked chunks for `query` from the active edition collection."""
    return [s.chunk for s in retrieve_scored(query, collection=collection)]


def retrieve_scored(query: str, *, collection: str | None = None):
    """Like retrieve(), but returns the reranked chunks WITH their relevance scores so callers
    (e.g. the agent's deep-mode hook) can gauge retrieval confidence."""
    coll_name = collection or settings.active_collection
    coll = _client().get_collection(coll_name)

    # Embed the EXPANDED query (occupancy codes/acronyms spelled out) for recall; rerank below
    # uses the marshal's original wording for precision.
    expanded = expand_query(query)
    qvec = embeddings.embed([expanded], input_type="query")[0]
    res = coll.query(
        query_embeddings=[qvec],
        n_results=settings.retrieve_before_rerank,
        include=["documents", "metadatas"],
    )
    dense_ids = res.get("ids", [[]])[0]
    dense_docs = res.get("documents", [[]])[0]
    dense_metas = res.get("metadatas", [[]])[0]

    if settings.use_hybrid:
        # Fuse dense + BM25 so exact tokens (section numbers, "NFPA 13") can't be missed.
        lex = lexical.search(coll, expanded, settings.bm25_candidates)
        candidates = _fuse(dense_ids, dense_docs, dense_metas, lex, settings.retrieve_before_rerank)
    else:
        candidates = [_format(m or {}, d) for d, m in zip(dense_docs, dense_metas)]

    candidates = _merge_amendments(candidates, coll)

    # Pull in the marshal's Verified Answer Library (confirmed answers) so they surface, labeled,
    # on similar questions. This is the compounding "memory" of the learning loop.
    verified = _verified_matches(query, qvec)

    scored = rerank(query, verified + candidates)
    return scored


def _fuse(dense_ids, dense_docs, dense_metas, lex, limit, k: int = 60):
    """Reciprocal-rank fusion of the dense and lexical rankings. Each list contributes
    1/(k+rank) per item; we sort by the summed score and return the top `limit` candidates."""
    info: dict[str, tuple] = {}          # id -> (text, metadata)
    score: dict[str, float] = defaultdict(float)
    for rank, did in enumerate(dense_ids):
        score[did] += 1.0 / (k + rank + 1)
        info.setdefault(did, (dense_docs[rank], dense_metas[rank] or {}))
    for rank, item in enumerate(lex):
        score[item["id"]] += 1.0 / (k + rank + 1)
        info.setdefault(item["id"], (item["text"], item["metadata"]))
    ordered = sorted(score, key=lambda i: score[i], reverse=True)[:limit]
    return [_format(info[i][1], info[i][0]) for i in ordered]


def _verified_matches(query: str, qvec: list[float], k: int = 3) -> list[dict]:
    """Top verified answers similar to the query, labeled so the agent weights them as confirmed."""
    try:
        vcoll = _client().get_collection(settings.verified_collection)
    except Exception:
        return []  # no verified answers yet
    try:
        res = vcoll.query(query_embeddings=[qvec], n_results=k, include=["documents", "metadatas"])
    except Exception:
        return []
    out = []
    for d, m in zip(res.get("documents", [[]])[0], res.get("metadatas", [[]])[0]):
        meta = {**(m or {}), "verified": True}
        out.append(_format(meta, d))
    return out


def _merge_amendments(chunks: list[dict], coll) -> list[dict]:
    """For any base-model section that CT amended, pull in the amendment and mark it controlling.

    Relies on ingestion having tagged amendment chunks with {is_amendment: True, section: "<n>"}.
    We match on section *relation*, not exact string equality, so an amendment to a parent
    section (e.g. "903.2") still governs a retrieved child ("903.2.8"), and a newly-added CT
    subsection ("903.2.8.4") surfaces for a query that retrieved its parent ("903.2.8"). This is
    what makes the "CT version governs" rule robust to sub-section / range / formatting drift.
    """
    sections = {c["metadata"].get("section") for c in chunks if c["metadata"].get("section")}
    sections.discard("(preamble)")          # not a real section — don't merge a doc title as an amendment
    if not sections:
        return chunks

    # Fetch ALL amendment chunks once (they're a small subset — one amendment document), then
    # match by hierarchy in Python. Chroma's `$in` can only do exact equality, which is the bug.
    try:
        amd = coll.get(where={"is_amendment": True}, include=["documents", "metadatas"])
    except Exception:
        return chunks  # ingestion may not have amendment tags yet

    amendments = []
    for d, m in zip(amd.get("documents", []) or [], amd.get("metadatas", []) or []):
        amd_section = (m or {}).get("section")
        if amd_section and any(relates(amd_section, s) for s in sections):
            amendments.append(_format({**(m or {}), "controlling": True}, d))

    # Amendments first (controlling), then base chunks, de-duped by (section, page, is_amendment).
    seen, merged = set(), []
    for c in amendments + chunks:
        key = (c["metadata"].get("section"), c["metadata"].get("page"), c["metadata"].get("is_amendment"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(c)
    return merged


def render_sources(chunks: list[dict]) -> str:
    """Format chunks into the source-labeled block the agent prompt expects."""
    lines = []
    for c in chunks:
        m = c["metadata"]
        tag = "VERIFIED" if m.get("verified") else ("CT-AMENDMENT (controlling)" if m.get("is_amendment") else "")
        label = f"[{m.get('book','?')} {m.get('edition','')} • §{m.get('section','?')} • p.{m.get('page','?')}]"
        if tag:
            label = f"{label} [{tag}]"
        lines.append(f"{label}\n{c['text']}")
    return "\n\n".join(lines)
