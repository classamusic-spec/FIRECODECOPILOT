"""Retrieval must recover if an old cached vector has the wrong Chroma dimension."""
from app import retriever
from app.settings import settings


class _Collection:
    name = "test"

    def __init__(self):
        self.dimensions = []

    def query(self, *, query_embeddings, **_kwargs):
        dim = len(query_embeddings[0])
        self.dimensions.append(dim)
        if dim != 1024:
            raise RuntimeError(f"Collection expecting embedding with dimension of 1024, got {dim}")
        return {
            "ids": [["standpipe-1"]],
            "documents": [["905.3 Standpipe systems are required in specified buildings."]],
            "metadatas": [[{"section": "905.3", "book": "IFC", "page": 1}]],
        }


def test_retrieval_clears_stale_embedding_cache_and_retries_once(monkeypatch):
    coll = _Collection()
    vectors = iter([[0.0] * 128, [0.0] * 1024])
    cleared = []

    monkeypatch.setattr(retriever, "_client", lambda: type("Client", (), {"get_collection": lambda *_: coll})())
    monkeypatch.setattr(retriever.embeddings, "embed", lambda *_args, **_kwargs: [next(vectors)])
    monkeypatch.setattr(retriever.embed_cache, "clear", lambda: cleared.append(True))
    monkeypatch.setattr(retriever, "_verified_matches", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(retriever, "_merge_amendments", lambda chunks, _coll: chunks)
    monkeypatch.setattr(settings, "use_reranker", False)
    monkeypatch.setattr(settings, "use_hybrid", False)
    monkeypatch.setattr(settings, "parent_retrieval", False)

    result = retriever.retrieve_scored("standpipe requirements")

    assert coll.dimensions == [128, 1024]
    assert cleared == [True]
    assert result[0].chunk["metadata"]["section"] == "905.3"
