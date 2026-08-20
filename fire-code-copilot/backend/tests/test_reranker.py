from app import reranker


def test_reranker_scores_provenance_labels_without_mutating_returned_chunk(monkeypatch):
    chunk = {
        "text": "The requirements of this chapter apply to existing apartment occupancies.",
        "metadata": {
            "book": "NFPA 101 2021 — Chapter 31 Existing Apartment Buildings",
            "source": "NFPA 101/chapter31.pdf",
            "section": "31.1.1.1",
        },
    }
    seen = {}

    def fake_post(query, docs, top_n):
        seen["docs"] = docs
        return {"results": [{"index": 0, "relevance_score": 0.9}]}

    monkeypatch.setattr(reranker, "_post_rerank", fake_post)
    result = reranker.rerank("What does NFPA 101 require?", [chunk], top_k=1)
    assert "NFPA 101 2021" in seen["docs"][0]
    assert "chapter31.pdf" in seen["docs"][0]
    assert result[0].chunk == chunk
