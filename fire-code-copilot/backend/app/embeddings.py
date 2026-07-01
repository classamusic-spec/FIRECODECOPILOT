"""Provider-agnostic embeddings. Local-first (nothing leaves the machine) by default.

Two quality/perf refinements over a bare `model.encode`:
  * **Role prefixes.** Asymmetric-search embedders (e.g. BGE v1.5) want a short instruction on the
    *query* side only. `EMBEDDING_QUERY_PREFIX` / `EMBEDDING_PASSAGE_PREFIX` apply by `input_type`;
    both default to "" so the behavior is unchanged unless you opt in.
  * **On-disk cache.** Identical text is embedded once and reused (see `embed_cache`), so a
    re-ingest or a repeated query is a lookup, not a model run. Toggle with `CACHE_EMBEDDINGS`.
"""
from __future__ import annotations

from .settings import settings

_local_model = None


def _namespace(input_type: str) -> str:
    """Cache namespace: the active model id + the query/passage role. Changing either invalidates
    old entries automatically (they hash to different keys)."""
    model = settings.voyage_model if settings.embedding_provider == "voyage" else settings.local_embedding_model
    return f"{model}|{input_type}"


def _prefix_for(input_type: str) -> str:
    return settings.embedding_query_prefix if input_type == "query" else settings.embedding_passage_prefix


def embed(texts: list[str], *, input_type: str = "document") -> list[list[float]]:
    if not texts:
        return []
    prefix = _prefix_for(input_type)
    prepared = [prefix + t for t in texts] if prefix else list(texts)

    if not settings.cache_embeddings:
        return _embed_raw(prepared, input_type)

    # Serve what we can from the cache; compute + store only the misses.
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
    if settings.embedding_provider == "voyage":
        return _embed_voyage(texts, input_type)
    return _embed_local(texts)


def _embed_local(texts: list[str]) -> list[list[float]]:
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        import torch
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        _local_model = SentenceTransformer(settings.local_embedding_model, device=device)
    return _local_model.encode(texts, normalize_embeddings=True).tolist()


def _embed_voyage(texts: list[str], input_type: str) -> list[list[float]]:
    import voyageai
    vo = voyageai.Client(api_key=settings.voyage_api_key)
    return vo.embed(texts, model=settings.voyage_model, input_type=input_type).embeddings


def is_ready() -> bool:
    """Whether the embedder is ready to use without a cold load. Voyage (a hosted API) is always
    'ready'; the local model must have been loaded (the first embed downloads it)."""
    return settings.embedding_provider != "local" or _local_model is not None


def warm() -> None:
    """Force the local embedding model to load now (so the first real query isn't a silent hang)."""
    if settings.embedding_provider == "local":
        _embed_local(["warm up"])
