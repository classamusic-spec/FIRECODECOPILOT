"""Pre-load the local models so the FIRST real question isn't a silent multi-GB hang.

The local embedder (and the reranker, if enabled) download + load lazily on first use — which
can look like the app froze. Warm them ahead of time:

    python -m app.warm        # from the backend/ dir
    # or POST /warm once the server is up

`status()` (also surfaced by GET /health) reports whether each is loaded yet.
"""
from __future__ import annotations

from .settings import settings
from . import embeddings, reranker


def status() -> dict:
    return {
        "embedding_provider": settings.embedding_provider,
        "embeddings_ready": embeddings.is_ready(),
        "reranker_enabled": settings.use_reranker,
        "reranker_ready": reranker.is_ready(),
    }


def warm() -> dict:
    """Load the local models now; returns the readiness status when done."""
    embeddings.warm()
    reranker.warm()
    return status()


if __name__ == "__main__":
    import json
    print("Warming local models (the first run downloads them — this can take a minute)…")
    print(json.dumps(warm(), indent=2))
