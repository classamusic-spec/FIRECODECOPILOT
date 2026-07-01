"""The embedding cache serves identical text without re-running the model, keys by model+role,
and applies query/passage prefixes. Uses a fake embedder so no model is loaded."""
import pytest

from app import embeddings, embed_cache
from app.settings import settings


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "embedding_provider", "local")
    monkeypatch.setattr(settings, "cache_embeddings", True)
    monkeypatch.setattr(settings, "embedding_query_prefix", "")
    monkeypatch.setattr(settings, "embedding_passage_prefix", "")
    embed_cache._reset_for_tests()
    yield
    embed_cache._reset_for_tests()


def _counting_embedder(monkeypatch):
    """A deterministic fake local embedder that records how many texts it was asked to embed."""
    calls = {"n": 0}

    def fake_local(texts):
        calls["n"] += len(texts)
        return [[float(len(t)), 1.0, 2.0] for t in texts]

    monkeypatch.setattr(embeddings, "_embed_local", fake_local)
    return calls


def test_cache_avoids_recompute(isolated_cache, monkeypatch):
    calls = _counting_embedder(monkeypatch)
    v1 = embeddings.embed(["sprinkler", "alarm"], input_type="document")
    v2 = embeddings.embed(["sprinkler", "alarm"], input_type="document")
    assert v1 == v2
    assert calls["n"] == 2                       # only the first batch computed; second was cached


def test_cache_partial_hit_only_embeds_misses(isolated_cache, monkeypatch):
    calls = _counting_embedder(monkeypatch)
    embeddings.embed(["sprinkler"], input_type="document")     # warm one entry
    embeddings.embed(["sprinkler", "standpipe"], input_type="document")
    assert calls["n"] == 2                       # "sprinkler" reused, only "standpipe" computed


def test_query_and_passage_roles_are_distinct_cache_entries(isolated_cache, monkeypatch):
    calls = _counting_embedder(monkeypatch)
    embeddings.embed(["sprinkler"], input_type="document")
    embeddings.embed(["sprinkler"], input_type="query")        # different role -> different key
    assert calls["n"] == 2


def test_query_prefix_changes_the_embedded_text(isolated_cache, monkeypatch):
    seen = []
    monkeypatch.setattr(embeddings, "_embed_local", lambda texts: seen.extend(texts) or [[0.0] for _ in texts])
    monkeypatch.setattr(settings, "embedding_query_prefix", "Query: ")
    embeddings.embed(["sprinkler"], input_type="query")
    assert seen == ["Query: sprinkler"]


def test_disabled_cache_always_recomputes(isolated_cache, monkeypatch):
    monkeypatch.setattr(settings, "cache_embeddings", False)
    calls = _counting_embedder(monkeypatch)
    embeddings.embed(["sprinkler"], input_type="document")
    embeddings.embed(["sprinkler"], input_type="document")
    assert calls["n"] == 2                       # no cache -> both computed
