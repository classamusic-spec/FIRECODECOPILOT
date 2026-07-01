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


def retrieve_scored(query: str, *, collection: str | None = None,
                    extra_queries: list[str] | None = None):
    """Return reranked chunks WITH scores. `extra_queries` runs additional query variants and
    fuses everything (used by deep-mode's second retrieval pass — see agent._deep_rewrite);
    reranking is always against the marshal's ORIGINAL wording for precision."""
    coll_name = collection or settings.active_collection
    coll = _client().get_collection(coll_name)

    queries = [query] + [q for q in (extra_queries or []) if q and q.strip()]
    rankings: list[list[dict]] = []      # each entry is one ranked candidate list to fuse
    primary_qvec = None

    for i, q in enumerate(queries):
        # Embed the EXPANDED query (occupancy codes/acronyms spelled out) for recall.
        expanded = expand_query(q)
        qvec = embeddings.embed([expanded], input_type="query")[0]
        if i == 0:
            primary_qvec = qvec
        res = coll.query(query_embeddings=[qvec], n_results=settings.retrieve_before_rerank,
                         include=["documents", "metadatas"])
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        rankings.append([{"id": _id, "text": d, "metadata": m or {}}
                         for _id, d, m in zip(ids, docs, metas)])
        if settings.use_hybrid:
            # BM25 channel so exact tokens (section numbers, "NFPA 13") can't be missed.
            rankings.append(lexical.search(coll, expanded, settings.bm25_candidates))

    candidates = _fuse(rankings, settings.retrieve_before_rerank)
    candidates = _merge_amendments(candidates, coll)

    # Pull in the marshal's Verified Answer Library (confirmed answers) so they surface, labeled.
    verified = _verified_matches(query, primary_qvec)

    scored = rerank(query, verified + candidates)
    if settings.parent_retrieval:
        scored = _expand_to_parents(scored, coll)
    return scored


def _expand_to_parents(scored, coll):
    """Parent-document retrieval: when a matched chunk is one window of a section that was split
    at ingest, stitch its sibling windows back into the full section and hand the model that.

    The reranker still scored the precise child window (good precision); the model just sees the
    whole section around it (good context). Sections that weren't split, verified answers, and
    amendments pass through unchanged. Each parent section appears once, keeping its best score.
    """
    from .reranker import Scored
    from .chunking import OVERLAP_WORDS

    out, seen_parents = [], set()
    for s in scored:
        meta = s.chunk.get("metadata", {})
        pid = meta.get("parent_id")
        if not pid or meta.get("n_parts", 1) <= 1:
            out.append(s)                       # whole-section chunk, verified, or amendment
            continue
        if pid in seen_parents:
            continue                            # another window of a section we already expanded
        seen_parents.add(pid)
        full = _stitch_parent(coll, pid, OVERLAP_WORDS)
        if full is None:
            out.append(s)                       # couldn't fetch siblings — keep the window
            continue
        # Keep the matched window's metadata (section/page/score); drop the now-irrelevant part refs.
        pruned = {k: v for k, v in meta.items() if k not in ("parent_id", "part", "n_parts")}
        out.append(Scored({"text": full, "metadata": pruned}, s.score))
    return out


def _stitch_parent(coll, parent_id: str, overlap_words: int) -> str | None:
    """Fetch all windows of a split section and rejoin them in order, removing the fixed overlap."""
    try:
        got = coll.get(where={"parent_id": parent_id}, include=["documents", "metadatas"])
    except Exception:
        return None
    docs = got.get("documents") or []
    metas = got.get("metadatas") or []
    if not docs:
        return None
    parts = sorted(zip(metas, docs), key=lambda md: (md[0] or {}).get("part", 0))
    words = parts[0][1].split()
    for _m, doc in parts[1:]:
        words += doc.split()[overlap_words:]    # drop the words duplicated from the previous window
    return " ".join(words)


def _fuse(rankings: list[list[dict]], limit: int, k: int = 60):
    """Reciprocal-rank fusion over any number of ranked lists (dense + BM25, across query
    variants). Each list contributes 1/(k+rank) per item; sort by the summed score."""
    info: dict[str, tuple] = {}          # id -> (text, metadata)
    score: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, item in enumerate(ranking):
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
