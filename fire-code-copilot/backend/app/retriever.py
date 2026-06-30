"""Retrieval: query -> top candidates (recall) -> reranker (precision) -> labeled chunks.

Returns chunks with rich metadata so downstream citation validation and the agent prompt can
show the marshal exactly which book/section/page each fact came from. Also merges Connecticut
amendments so the adopted/amended text is marked as controlling.
"""
from __future__ import annotations
from .settings import settings
from .reranker import rerank
from . import embeddings  # provider-agnostic embed(); see embeddings.py


def _client():
    import chromadb
    return chromadb.PersistentClient(path=settings.chroma_dir)


def _format(meta: dict, text: str) -> dict:
    return {"text": text, "metadata": meta}


def retrieve(query: str, *, collection: str | None = None) -> list[dict]:
    """Return the top reranked chunks for `query` from the active edition collection."""
    coll_name = collection or settings.active_collection
    coll = _client().get_collection(coll_name)

    qvec = embeddings.embed([query], input_type="query")[0]
    res = coll.query(
        query_embeddings=[qvec],
        n_results=settings.retrieve_before_rerank,
        include=["documents", "metadatas"],
    )
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    candidates = [_format(m or {}, d) for d, m in zip(docs, metas)]

    candidates = _merge_amendments(candidates, coll)

    scored = rerank(query, candidates)
    return [s.chunk for s in scored]


def _merge_amendments(chunks: list[dict], coll) -> list[dict]:
    """For any base-model section that CT amended, pull in the amendment and mark it controlling.

    Relies on ingestion having tagged amendment chunks with metadata
    {is_amendment: True, section: "<n>"}. We look up amendments for each retrieved section and
    prepend them so the agent sees the controlling text first.
    """
    sections = {c["metadata"].get("section") for c in chunks if c["metadata"].get("section")}
    if not sections:
        return chunks
    try:
        amd = coll.get(
            where={"$and": [{"is_amendment": True}, {"section": {"$in": list(sections)}}]},
            include=["documents", "metadatas"],
        )
    except Exception:
        return chunks  # ingestion may not have amendment tags yet

    amendments = [
        _format({**(m or {}), "controlling": True}, d)
        for d, m in zip(amd.get("documents", []), amd.get("metadatas", []))
    ]
    # Amendments first (controlling), then base chunks, de-duped by (section, page).
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
