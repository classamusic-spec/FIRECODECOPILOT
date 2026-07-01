"""Provider-agnostic embeddings. Local-first (nothing leaves the machine) by default."""
from __future__ import annotations
from .settings import settings

_local_model = None


def embed(texts: list[str], *, input_type: str = "document") -> list[list[float]]:
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
