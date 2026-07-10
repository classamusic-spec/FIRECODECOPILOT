"""Structured, local-only provenance helpers for the answer trace."""
from __future__ import annotations
from . import citations


def chunk_ref(chunk: dict, *, score: float | None = None, source: str = "dense") -> dict:
    meta = chunk.get("metadata", {}) or {}
    out = {
        "chunk_id": str(meta.get("chunk_id") or meta.get("source", "")) + f":{meta.get('page', '?')}:{meta.get('section', '?')}",
        "section": meta.get("section", ""), "page": meta.get("page"),
        "book": meta.get("book", ""), "edition": meta.get("edition", ""),
        "source": source, "score": round(float(score), 6) if score is not None else None,
        "pdf_source": meta.get("source", ""),
    }
    return out


def controlling_sources(chunks: list[dict], answer: str) -> list[dict]:
    """Cited sources plus model/amendment pairs already retrieved by amendment merge."""
    cited = {citations._normalize(c) for c in citations.extract_citations(answer or "")}
    rows: dict[str, dict] = {}
    for c in chunks:
        m = c.get("metadata", {}) or {}
        sec = citations._normalize(str(m.get("section", "")))
        if cited and sec not in cited:
            continue
        key = sec or f"{m.get('book')}:{m.get('page')}"
        row = rows.setdefault(key, {"section": m.get("section", ""), "edition": m.get("edition", ""),
                                    "page": m.get("page"), "book": m.get("book", ""),
                                    "ct_amendment_controls": False, "base_text": None, "amended_text": None,
                                    "source": m.get("source", "")})
        if m.get("is_amendment") or m.get("controlling"):
            row["ct_amendment_controls"] = True
            row["amended_text"] = c.get("text", "")
        elif row["base_text"] is None:
            row["base_text"] = c.get("text", "")
    return list(rows.values())


def citation_rows(answer: str, chunks: list[dict], check) -> list[dict]:
    if check is None:
        return []
    return [{"section": sec, "verified": sec in check.verified,
             "reason": "present in retrieved chunks" if sec in check.verified else "not found in retrieved chunks"}
            for sec in check.cited]
