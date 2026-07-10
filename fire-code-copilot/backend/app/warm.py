"""Warm the retrieval side of the oMLX stack.

Embeddings and reranking load lazily on first use, which can look like the app froze. Warm them
ahead of time:

    python -m app.warm        # from the backend/ dir
    # or POST /warm once the server is up

Generator pinning is handled by `python -m app.llm --model-check`, which calls both configured
generators with MLX_THINKING=off.
"""
from __future__ import annotations

from .settings import settings
from . import embeddings, reranker


def status() -> dict:
    return {
        "endpoint": settings.local_base_url,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "embeddings_ready": embeddings.is_ready(),
        "reranker_enabled": settings.use_reranker,
        "reranker_model": settings.reranker_model,
        "reranker_ready": reranker.is_ready(),
    }


def warm() -> dict:
    """Load the local models now; returns the readiness status when done."""
    embeddings.warm()
    reranker.warm()
    return status()


if __name__ == "__main__":
    import json
    print("Warming oMLX retrieval models (embeddings + reranker; first run may download/load)…")
    print(json.dumps(warm(), indent=2))
