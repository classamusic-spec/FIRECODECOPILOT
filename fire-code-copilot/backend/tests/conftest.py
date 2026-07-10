"""Test fixtures that keep the suite offline.

Production embeddings/reranking are served by oMLX. Unit/integration tests still need small,
deterministic vectors without requiring a running model server, so we patch the legacy
`embeddings._embed_local` hook and the oMLX rerank HTTP bridge here.
"""
from __future__ import annotations

import hashlib
import math
import re
import pytest

_TOKEN_RE = re.compile(r"[a-z0-9.]+")


def _stem(tok: str) -> str:
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    if tok.endswith("es") and len(tok) > 4:
        return tok[:-2]
    if tok.endswith("s") and len(tok) > 3:
        return tok[:-1]
    return tok


def _tokens(text: str) -> list[str]:
    raw = _TOKEN_RE.findall(text.lower())
    toks = [_stem(t) for t in raw]
    compact = " ".join(toks)
    trigrams = [compact[i:i + 3] for i in range(max(0, len(compact) - 2))]
    # Add simple section-normalized variants so 903.2.8 and §903.2.8 line up.
    return toks + [t.replace(".", "_") for t in toks if "." in t] + trigrams


@pytest.fixture(autouse=True)
def offline_omlx_models(monkeypatch):
    from app import embeddings, reranker, embed_cache
    embed_cache._reset_for_tests()

    def fake_embed(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * 128
            for tok in _tokens(text):
                idx = hashlib.sha256(tok.encode("utf-8")).digest()[0] % len(vec)
                vec[idx] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        embeddings._ready = True
        return out

    def fake_post_rerank(query: str, docs: list[str], top_n: int) -> dict:
        q = set(_tokens(query))
        results = []
        for i, doc in enumerate(docs):
            d = set(_tokens(doc))
            score = len(q & d) / max(1, len(q))
            results.append({"index": i, "relevance_score": score})
        reranker._ready = True
        return {"results": sorted(results, key=lambda r: r["relevance_score"], reverse=True)[:top_n]}

    monkeypatch.setattr(embeddings, "_embed_local", fake_embed)
    monkeypatch.setattr(reranker, "_post_rerank", fake_post_rerank)
    from app.settings import settings
    monkeypatch.setattr(settings, "embedding_query_prefix", "")
    monkeypatch.setattr(settings, "embedding_passage_prefix", "")
    monkeypatch.setattr(settings, "use_hybrid", True)
    yield
    embed_cache._reset_for_tests()
