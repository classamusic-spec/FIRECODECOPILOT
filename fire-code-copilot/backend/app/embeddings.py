"""Embeddings via the single local oMLX OpenAI-compatible endpoint.

The app no longer loads sentence-transformers in-process. All vectorization goes through
LOCAL_BASE_URL (/v1/embeddings) using EMBEDDING_MODEL, so generator switching, embeddings,
and reranking are managed by one resident oMLX process.
"""
from __future__ import annotations
import math
from .settings import settings

_ready = False
_local_model = None  # legacy test hook; runtime does not load an in-process model


def _namespace(input_type: str) -> str:
    return f"{settings.embedding_model}|{input_type}"


def _prefix_for(input_type: str) -> str:
    return settings.embedding_query_prefix if input_type == "query" else settings.embedding_passage_prefix


def embed(texts: list[str], *, input_type: str = "document") -> list[list[float]]:
    if not texts:
        return []
    prefix = _prefix_for(input_type)
    prepared = [prefix + t for t in texts] if prefix else list(texts)

    if not settings.cache_embeddings:
        return _embed_raw(prepared, input_type)

    from . import embed_cache
    ns = _namespace(input_type)
    vectors = embed_cache.get_many(prepared, ns)
    missing = [i for i in range(len(prepared)) if i not in vectors]
    if missing:
        fresh = _embed_raw([prepared[i] for i in missing], input_type)
        embed_cache.put_many([(prepared[i], v) for i, v in zip(missing, fresh)], ns)
        for i, v in zip(missing, fresh):
            vectors[i] = v
    return [vectors[i] for i in range(len(prepared))]


def _embed_raw(texts: list[str], input_type: str) -> list[list[float]]:
    if settings.embedding_provider != "local":
        raise ValueError("Only EMBEDDING_PROVIDER=local is supported in the oMLX single-endpoint stack")
    return _embed_local(texts)


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(float(x) * float(x) for x in vec)) or 1.0
    return [float(x) / norm for x in vec]


def _embed_omlx(texts: list[str]) -> list[list[float]]:
    global _ready
    from openai import OpenAI
    client = OpenAI(base_url=settings.local_base_url, api_key=settings.local_api_key or "not-needed")
    resp = client.embeddings.create(model=settings.embedding_model, input=texts, encoding_format="float")
    # Preserve request order; OpenAI-compatible servers return an index per item.
    data = sorted(resp.data, key=lambda item: item.index)
    _ready = True
    return [_normalize(list(item.embedding)) for item in data]


def _embed_local(texts: list[str]) -> list[list[float]]:
    """Legacy hook name used by tests; production implementation calls oMLX."""
    return _embed_omlx(texts)


def is_ready() -> bool:
    return _ready


def warm() -> None:
    if settings.embedding_provider == "local":
        _embed_local(["warm up fire code retrieval"])
