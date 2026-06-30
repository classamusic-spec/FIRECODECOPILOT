"""Cross-encoder reranker — the single biggest anti-hallucination lever.

Bi-encoder embedding search is fast but optimizes for recall, not precision: it returns
chunks that are *similar*, not necessarily *relevant*. A cross-encoder reads the (query, chunk)
pair together and scores true relevance, so we can keep only the few chunks that actually
answer the question. Pipeline: retrieve ~20 -> rerank -> keep top 5-7.

Runs fully local on Apple Silicon (MPS) or CPU. Default model: bge-reranker-v2-m3.
Swap RERANKER_MODEL=Qwen/Qwen3-Reranker-4B for a stronger (heavier) option.
"""
from __future__ import annotations
from dataclasses import dataclass
from .settings import settings

_reranker = None


def _get_reranker():
    """Lazy-load so importing this module is cheap and model load happens once."""
    global _reranker
    if _reranker is None:
        # sentence-transformers CrossEncoder is the most portable wrapper on Apple Silicon.
        # (FlagEmbedding's FlagReranker also works; CrossEncoder avoids some MPS fp16 pitfalls.)
        from sentence_transformers import CrossEncoder
        import torch
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        _reranker = CrossEncoder(settings.reranker_model, device=device, max_length=1024)
    return _reranker


@dataclass
class Scored:
    chunk: dict          # {"text": str, "metadata": {...}}
    score: float


def rerank(query: str, chunks: list[dict], top_k: int | None = None) -> list[Scored]:
    """Reorder `chunks` by true relevance to `query`; return the top_k as Scored items.

    chunks: list of {"text": ..., "metadata": {book, edition, section, page, is_amendment}}
    """
    top_k = top_k or settings.keep_after_rerank
    if not chunks:
        return []
    if not settings.use_reranker:
        return [Scored(c, 0.0) for c in chunks[:top_k]]

    model = _get_reranker()
    pairs = [(query, c["text"]) for c in chunks]
    scores = model.predict(pairs)  # higher = more relevant
    ranked = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
    return [Scored(chunk=c, score=float(s)) for c, s in ranked[:top_k]]
