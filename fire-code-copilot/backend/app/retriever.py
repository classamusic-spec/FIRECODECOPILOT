"""Retrieval: query -> top candidates (recall) -> reranker (precision) -> labeled chunks.

Returns chunks with rich metadata so downstream citation validation and the agent prompt can
show the marshal exactly which book/section/page each fact came from. Also merges Connecticut
amendments so the adopted/amended text is marked as controlling.
"""
from __future__ import annotations
from collections import defaultdict
import re
from .settings import settings
from .reranker import rerank
from . import embeddings  # provider-agnostic embed(); see embeddings.py
from . import embed_cache  # clears stale vectors when an embedding model/cache changed
from . import lexical     # BM25 channel for exact-token matches
from .sections import relates
from .query import (
    expand_query,
    has_any_nonactive_primary_edition,
    has_explicit_nonactive_primary_edition,
    primary_edition_intents,
    primary_family_allows_active,
)


def _client():
    import chromadb
    return chromadb.PersistentClient(path=settings.chroma_dir)


def _format(meta: dict, text: str) -> dict:
    return {"text": text, "metadata": meta}


# We require at least two digits on both sides: Chapter 541 statutory citations use identifiers such
# as 29-250, while construction prose commonly contains incidental one-digit hyphenated ratios.
CITED_HYPHEN_SECTION = re.compile(r"\b\d{2,}[A-Za-z]*-\d{2,}[A-Za-z]*\b")


def _explicit_section_matches(coll, query: str) -> list[dict]:
    sections = list(dict.fromkeys(CITED_HYPHEN_SECTION.findall(query or "")))
    if not sections:
        return []
    out: list[dict] = []
    for section in sections:
        try:
            got = coll.get(where={"section": section}, include=["documents", "metadatas"])
        except Exception:
            continue
        out.extend({"id": _id, "text": doc, "metadata": meta or {}}
                   for _id, doc, meta in zip(got.get("ids", []) or [],
                                             got.get("documents", []) or [],
                                             got.get("metadatas", []) or []))
    return out


def _embedding_dimension_mismatch(error: Exception) -> bool:
    """Chroma's wording is stable across its Python and Rust clients."""
    message = str(error).lower()
    return "embedding" in message and "dimension" in message and "got" in message


def retrieve(query: str, *, collection: str | None = None) -> list[dict]:
    """Return the top reranked chunks for `query` from the active edition collection."""
    return [s.chunk for s in retrieve_scored(query, collection=collection)]


def retrieve_scored(query: str, *, collection: str | None = None,
                    extra_queries: list[str] | None = None):
    """Return reranked chunks WITH scores. `extra_queries` runs additional query variants and
    fuses everything (used by deep-mode's second retrieval pass — see agent._deep_rewrite);
    reranking uses the expanded variants so Connecticut applicability facts and explicit book
    names remain visible to the cross-encoder."""
    coll_name = collection or settings.active_collection
    coll = _client().get_collection(coll_name)

    # Preserve order but dedupe: building context may already be present before deep mode adds its
    # rewrite, and embedding/ranking the same variant twice would distort reciprocal-rank fusion.
    queries = list(dict.fromkeys([query] + [q for q in (extra_queries or []) if q and q.strip()]))
    rankings: list[list[dict]] = []      # each entry is one ranked candidate list to fuse
    expanded_queries: list[str] = []
    explicit_sections = _explicit_section_matches(coll, query)
    if explicit_sections:
        rankings.append(explicit_sections)
    primary_qvec = None
    cleared_stale_cache = False

    for i, q in enumerate(queries):
        # Embed the EXPANDED query (occupancy codes/acronyms spelled out) for recall.
        expanded = expand_query(q)
        expanded_queries.append(expanded)
        qvec = embeddings.embed([expanded], input_type="query")[0]
        try:
            res = coll.query(query_embeddings=[qvec], n_results=settings.retrieve_before_rerank,
                             include=["documents", "metadatas"])
        except Exception as exc:
            # The cached vector may predate the current embedding model/collection. Clear it and
            # regenerate once; otherwise the stale query vector permanently blocks every search.
            if cleared_stale_cache or not _embedding_dimension_mismatch(exc):
                raise
            embed_cache.clear()
            cleared_stale_cache = True
            qvec = embeddings.embed([expanded], input_type="query")[0]
            res = coll.query(query_embeddings=[qvec], n_results=settings.retrieve_before_rerank,
                             include=["documents", "metadatas"])
        if i == 0:
            primary_qvec = qvec
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        rankings.append([{"id": _id, "text": d, "metadata": m or {}}
                         for _id, d, m in zip(ids, docs, metas)])
        if settings.use_hybrid:
            # BM25 channel so exact tokens (section numbers, "NFPA 13") can't be missed.
            rankings.append(lexical.search(coll, expanded, settings.bm25_candidates))

    candidates = _fuse(rankings, settings.retrieve_before_rerank)
    rerank_query = "\n".join(dict.fromkeys(expanded_queries))
    candidates = _filter_mismatched_primary_editions(candidates, rerank_query)
    historical_primary = has_explicit_nonactive_primary_edition(rerank_query)
    any_historical_primary = has_any_nonactive_primary_edition(rerank_query)

    # Pull in the marshal's Verified Answer Library (confirmed answers) so they surface, labeled.
    # Filtered to THIS edition and distance-thresholded — a confirmed answer for a different
    # question (or a different code cycle) must not masquerade as relevant. An explicitly requested
    # historical/future primary-code edition is not the active collection and cannot use current
    # verified precedents.
    verified = ([] if any_historical_primary or primary_qvec is None
                else _verified_matches(query, primary_qvec, coll_name))

    if settings.use_reranker:
        # The cross-encoder scores everything (verified + amendments + candidates) by true
        # relevance. Include every expanded/contextual variant: an original-permit year supplied
        # in building context can determine whether Part III/IFC or Part IV/NFPA 101 controls.
        if not historical_primary:
            candidates = _merge_amendments(candidates, coll, rerank_query)
        # Add a small metadata-aware lexical slate for every routed base book. Dense similarity can
        # otherwise omit the named standard entirely when another code contains nearly identical
        # language. These are still reranked by topic; this is not an unconditional source filter.
        required = []
        routed_families = [
            family for family in _requested_code_families(rerank_query)
            if primary_family_allows_active(rerank_query, family)
        ]
        for family in routed_families:
            phrase = _family_search_phrase(family)
            required.extend(lexical.search(coll, f"{phrase} {rerank_query}", 5))
            required.extend(_exact_model_book_candidates(coll, primary_qvec, family, 5))
        rerank_input = _dedupe_chunk_dicts(verified + candidates + required)
        # Score the complete candidate slate, then preserve the controlling base/amendment layers
        # in the final six. Pure score truncation can otherwise return six CT amendment snippets
        # and omit the IFC base text—or rank analogous NFPA 1 text over explicit NFPA 101.
        scored = rerank(rerank_query, rerank_input, top_k=len(rerank_input))
        scored = _balance_code_families(scored, rerank_query, settings.keep_after_rerank)
    else:
        # No reranker → fusion order IS the ranking, and rerank() would just head-truncate.
        # Keep the top fused candidates FIRST (the actual target must never be displaced), then
        # add their related amendments and any verified extras WITHOUT truncating them away.
        from .reranker import Scored
        kept = candidates[:settings.keep_after_rerank]
        merged = kept if historical_primary else _merge_amendments(kept, coll, rerank_query)
        scored = [Scored(c, 0.0) for c in merged] + [Scored(v, 0.0) for v in verified]

    if settings.parent_retrieval:
        scored = _expand_to_parents(scored, coll)
    return scored


def _requested_code_families(query: str) -> list[str]:
    """Return base-code families in the order explicitly named or added by query expansion."""
    value = query or ""
    matches: list[tuple[int, str]] = []
    patterns = (
        ("nfpa:101", r"\bNFPA\s*101\b"),
        ("nfpa:1", r"\bNFPA\s*1(?!\d)\b"),
        ("ifc", r"\b(?:IFC|International Fire Code)\b"),
        ("iebc", r"\b(?:IEBC|International Existing Building Code)\b"),
        ("ibc", r"\b(?:IBC|International Building Code)\b"),
    )
    for family, pattern in patterns:
        matches.extend((m.start(), family) for m in re.finditer(pattern, value, re.IGNORECASE))
    for match in re.finditer(r"\bNFPA\s*(\d+[A-Z]?)\b", value, re.IGNORECASE):
        matches.append((match.start(), f"nfpa:{match.group(1).upper()}"))
    families: list[str] = []
    for _position, family in sorted(matches, key=lambda item: item[0]):
        if family not in families:
            families.append(family)
    return families


def _family_search_phrase(family: str) -> str:
    if family.startswith("nfpa:"):
        return f"NFPA {family.split(':', 1)[1]}"
    return {
        "ifc": "2021 International Fire Code IFC",
        "ibc": "2021 International Building Code IBC",
        "iebc": "2021 International Existing Building Code IEBC",
    }.get(family, family)


def _exact_model_book_candidates(coll, query_vector, family: str, k: int) -> list[dict]:
    """Dense-search model-code books whose canonical metadata value is exact and stable."""
    book = {"ifc": "IFC (model)", "ibc": "IBC (model)", "iebc": "IEBC (model)"}.get(family)
    if not book or query_vector is None:
        return []
    try:
        got = coll.query(
            query_embeddings=[query_vector],
            n_results=k,
            where={"book": book},
            include=["documents", "metadatas"],
        )
    except Exception:
        return []
    return [{"id": ident, "text": text, "metadata": meta or {}}
            for ident, text, meta in zip(got.get("ids", [[]])[0],
                                         got.get("documents", [[]])[0],
                                         got.get("metadatas", [[]])[0])]


def _dedupe_chunk_dicts(chunks: list[dict]) -> list[dict]:
    out, seen = [], set()
    for chunk in chunks:
        meta = chunk.get("metadata", {}) or {}
        key = (meta.get("source"), meta.get("section"), chunk.get("text", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(chunk)
    return out


def _filter_mismatched_primary_editions(chunks: list[dict], query: str) -> list[dict]:
    """Remove provably wrong active-edition base chunks from explicit historical family requests."""
    intents = primary_edition_intents(query)
    historical_families = {
        family: years for family, years in intents.items()
        if years and "2021" not in years
    }
    if not historical_families:
        return chunks
    historical_only = has_explicit_nonactive_primary_edition(query)
    kept = []
    for chunk in chunks:
        meta = chunk.get("metadata", {}) or {}
        if historical_only and _is_amendment(meta):
            continue
        edition_match = re.search(r"\b(?:19|20)\d{2}\b", str(meta.get("edition", "")))
        edition = edition_match.group(0) if edition_match else None
        if edition and any(
            _chunk_matches_base_family(chunk, family) and edition not in requested
            for family, requested in historical_families.items()
        ):
            continue
        kept.append(chunk)
    return kept


def _is_amendment(meta: dict) -> bool:
    """Accept manifest input metadata and normalized metadata emitted by the chunker."""
    return bool(meta.get("is_amendment") or meta.get("is_amendment_doc"))


def _chunk_matches_base_family(chunk: dict, family: str) -> bool:
    meta = chunk.get("metadata", {}) or {}
    if _is_amendment(meta):
        return False
    label = f"{meta.get('book', '')} {meta.get('source', '')}".upper().replace("_", " ")
    if family.startswith("nfpa:"):
        number = re.escape(family.split(":", 1)[1])
        return bool(re.search(rf"\bNFPA\s*{number}(?![A-Z0-9])", label))
    if family == "ifc":
        return "INTERNATIONAL FIRE CODE" in label or str(meta.get("book", "")).upper().startswith("IFC")
    if family == "iebc":
        return "INTERNATIONAL EXISTING BUILDING CODE" in label or str(meta.get("book", "")).upper().startswith("IEBC")
    if family == "ibc":
        return ("INTERNATIONAL BUILDING CODE" in label
                and "INTERNATIONAL EXISTING BUILDING CODE" not in label) or str(meta.get("book", "")).upper().startswith("IBC")
    return False


def _matches_base_family(scored, family: str) -> bool:
    return _chunk_matches_base_family(scored.chunk, family)


def _chunk_matches_controlling_amendment(chunk: dict, family: str) -> bool:
    meta = chunk.get("metadata", {}) or {}
    if not _is_amendment(meta):
        return False
    normalized_family = str(meta.get("code_family", "")).lower()
    label = f"{meta.get('book', '')} {meta.get('source', '')}".upper()
    ct_provenance = bool(
        "CONNECTICUT" in label
        or re.search(r"\bCT\b", label)
        or re.search(r"\bCS(?:FSC|FPC|BC)\b", label)
    )
    if normalized_family:
        return ct_provenance and normalized_family == family

    # Compatibility for older chunks only when the family is explicit in provenance. A generic
    # CSFSC label is ambiguous because one PDF contains Part III/IFC and Part IV/NFPA 101.
    if not ct_provenance:
        return False
    if family == "ifc":
        return "PART III" in label or bool(re.search(r"\bIFC\b", label))
    if family == "nfpa:101":
        return "PART IV" in label or bool(re.search(r"\bNFPA\s*101\b", label))
    if family == "nfpa:1":
        return "CT FIRE PREVENTION CODE" in label or "CSFPC" in label
    if family == "ibc":
        return (bool(re.search(r"\bIBC\b", label))
                or ("INTERNATIONAL BUILDING CODE" in label
                    and "INTERNATIONAL EXISTING BUILDING CODE" not in label))
    if family == "iebc":
        return bool(re.search(r"\bIEBC\b", label)) or "INTERNATIONAL EXISTING BUILDING CODE" in label
    return False


def _matches_controlling_amendment(scored, family: str) -> bool:
    return _chunk_matches_controlling_amendment(scored.chunk, family)


def _balance_code_families(scored: list, query: str, limit: int) -> list:
    """Keep required base books and Connecticut amendments in the final retrieval slate."""
    families = [
        family for family in _requested_code_families(query)
        if primary_family_allows_active(query, family)
    ]
    if not families or not scored:
        return scored[:limit]
    bases = [next((s for s in scored if _matches_base_family(s, family)), None)
             for family in families]
    amendments = [next((s for s in scored if _matches_controlling_amendment(s, family)), None)
                  for family in families]
    asks_amendment = bool(re.search(r"\bamend(?:ment|ments|ed)?\b", query, re.IGNORECASE))
    preferred = (amendments + bases) if asks_amendment else (bases + amendments)
    out, seen = [], set()
    for item in [s for s in preferred if s is not None] + scored:
        marker = id(item)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
        if len(out) >= limit:
            break
    return out


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


def _verified_matches(query: str, qvec: list[float], collection: str, k: int = 3) -> list[dict]:
    """Verified answers SIMILAR to the query, for THIS edition, labeled as confirmed.

    Two guards, both load-bearing:
      - `where={"edition": collection}` — an answer verified under the 2022 cycle must not
        surface as [VERIFIED] for a legacy-edition query (or vice versa after a transition).
      - a distance cutoff — Chroma returns the k *nearest* entries no matter how far; without a
        threshold the library's single answer about R-2 sprinklers would front every unrelated
        question as "confirmed". Empty/corrupt entries are skipped for the same reason.
    """
    try:
        vcoll = _client().get_collection(settings.verified_collection)
    except Exception:
        return []  # no verified answers yet
    try:
        res = vcoll.query(query_embeddings=[qvec], n_results=k,
                          where={"edition": collection},
                          include=["documents", "metadatas", "distances"])
    except Exception:
        return []
    out = []
    dists = (res.get("distances") or [[]])[0]
    for i, (d, m) in enumerate(zip(res.get("documents", [[]])[0], res.get("metadatas", [[]])[0])):
        if not (d or "").strip():
            continue
        if i < len(dists) and dists[i] is not None and dists[i] > settings.verified_max_distance:
            continue
        meta = {**(m or {}), "verified": True}
        out.append(_format(meta, d))
    if out:
        return out
    return _verified_lexical_fallback(query, vcoll, collection, k)


def _verified_lexical_fallback(query: str, vcoll, collection: str, k: int) -> list[dict]:
    """Offline/test safety net and production backstop when vector distance is conservative."""
    import re
    def toks(s: str) -> set[str]:
        raw = re.findall(r"[a-z0-9.]+", (s or "").lower())
        return {t[:-1] if t.endswith("s") and len(t) > 3 else t for t in raw}
    q = toks(query)
    if not q:
        return []
    try:
        got = vcoll.get(where={"edition": collection}, include=["documents", "metadatas"])
    except Exception:
        return []
    scored = []
    for d, m in zip(got.get("documents", []) or [], got.get("metadatas", []) or []):
        if not (d or "").strip():
            continue
        score = len(q & toks(d)) / max(1, len(q))
        if score >= 0.35:
            scored.append((score, _format({**(m or {}), "verified": True}, d)))
    return [item for _score, item in sorted(scored, key=lambda x: x[0], reverse=True)[:k]]


def _merge_amendments(chunks: list[dict], coll, query: str = "") -> list[dict]:
    """For active base-code sections, pull in only that family's controlling CT amendments.

    Family pairing matters as much as section pairing: many standards reuse the same section
    numbers, so a section-only merge can attach an IFC amendment to an NFPA source. Explicitly
    historical families are excluded while active sides of a mixed-edition query remain eligible.
    """
    governed_families = ("nfpa:101", "nfpa:1", "ifc", "iebc", "ibc")
    base_sections = {
        (c["metadata"].get("section"), family)
        for c in chunks
        for family in governed_families
        if c["metadata"].get("section") != "(preamble)"
        and primary_family_allows_active(query, family)
        and _chunk_matches_base_family(c, family)
    }
    if not base_sections:
        return chunks

    # Fetch all normalized amendment chunks once, then pair by family and section hierarchy.
    try:
        amd = coll.get(where={"is_amendment": True}, include=["documents", "metadatas"])
    except Exception:
        return chunks

    amendments = []
    for document, metadata in zip(
        amd.get("documents", []) or [], amd.get("metadatas", []) or []
    ):
        amendment = _format(metadata or {}, document)
        amd_section = amendment["metadata"].get("section")
        if amd_section and any(
            relates(amd_section, section)
            and _chunk_matches_controlling_amendment(amendment, family)
            for section, family in base_sections
        ):
            amendments.append(_format({**amendment["metadata"], "controlling": True}, document))

    # Amendments first (controlling), then base chunks, de-duped by section/page/type.
    seen, merged = set(), []
    for chunk in amendments + chunks:
        meta = chunk["metadata"]
        key = (meta.get("section"), meta.get("page"), meta.get("is_amendment"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(chunk)
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
