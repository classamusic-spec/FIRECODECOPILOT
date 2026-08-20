"""Cross-encoder reranking through the single local oMLX endpoint.

The reranker is kept resident by oMLX. This module only calls /v1/rerank and adapts common
OpenAI-compatible rerank response shapes into Scored chunks.
"""
from __future__ import annotations
from dataclasses import dataclass
from .settings import settings

_ready = False


def is_ready() -> bool:
    return (not settings.use_reranker) or _ready


def warm() -> None:
    if settings.use_reranker:
        rerank("warm up", [{"text": "automatic sprinkler system", "metadata": {}}], top_k=1)


@dataclass
class Scored:
    chunk: dict
    score: float


def _post_rerank(query: str, docs: list[str], top_n: int) -> dict:
    import json
    import urllib.error
    import urllib.request

    base = settings.local_base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if settings.local_api_key:
        headers["Authorization"] = f"Bearer {settings.local_api_key}"
    payload = {"model": settings.reranker_model, "query": query, "documents": docs, "top_n": top_n}
    data = json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None
    # oMLX should expose /v1/rerank. Try /rerank relative to LOCAL_BASE_URL, then a base-stripped
    # variant for runtimes that mount rerank outside /v1.
    for url in [base + "/rerank", base.removesuffix("/v1") + "/rerank"]:
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body) if body else {}
        except Exception as e:
            last_error = e
    raise RuntimeError(f"oMLX rerank endpoint failed: {last_error}")


def _parse_ranked(resp: dict, chunks: list[dict]) -> list[Scored]:
    raw = resp.get("results", resp.get("data", resp.get("rankings", [])))
    out: list[Scored] = []
    if isinstance(raw, list) and raw:
        for i, item in enumerate(raw):
            if isinstance(item, (int, float)):
                out.append(Scored(chunks[i], float(item)))
                continue
            if not isinstance(item, dict):
                continue
            idx = int(item.get("index", item.get("document_index", i)))
            score = float(item.get("relevance_score", item.get("score", item.get("logit", 0.0))))
            if 0 <= idx < len(chunks):
                out.append(Scored(chunks[idx], score))
    if not out and "scores" in resp and isinstance(resp["scores"], list):
        out = [Scored(c, float(s)) for c, s in zip(chunks, resp["scores"])]
    return sorted(out, key=lambda x: x.score, reverse=True)


def rerank(query: str, chunks: list[dict], top_k: int | None = None) -> list[Scored]:
    global _ready
    top_k = top_k or settings.keep_after_rerank
    if not chunks:
        return []
    if not settings.use_reranker:
        return [Scored(c, 0.0) for c in chunks[:top_k]]
    # Provenance labels are retrieval evidence too. Chapter-split standards often omit their book
    # title from every body chunk; without metadata the cross-encoder can rank semantically similar
    # text from the wrong code above the book the marshal explicitly named. The original chunks stay
    # untouched and are still what the generator receives.
    docs = []
    for chunk in chunks:
        meta = chunk.get("metadata", {}) or {}
        label = (f"[Book: {meta.get('book', '')}; Section: {meta.get('section', '')}; "
                 f"Source: {meta.get('source', '')}]")
        docs.append(f"{label}\n{chunk['text']}")
    resp = _post_rerank(query, docs, min(len(docs), max(top_k, settings.keep_after_rerank)))
    ranked = _parse_ranked(resp, chunks)
    _ready = True
    return ranked[:top_k] if ranked else [Scored(c, 0.0) for c in chunks[:top_k]]
