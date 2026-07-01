"""Model warm-up: status reports readiness; warm() loads the local embedder."""
from app import warm, embeddings


def test_status_shape():
    s = warm.status()
    assert {"embedding_provider", "embeddings_ready", "reranker_enabled", "reranker_ready"} <= s.keys()


def test_warm_loads_local_embedder(monkeypatch):
    monkeypatch.setattr(embeddings, "_local_model", None)   # force a cold state
    assert warm.warm()["embeddings_ready"] is True          # loaded after warming
