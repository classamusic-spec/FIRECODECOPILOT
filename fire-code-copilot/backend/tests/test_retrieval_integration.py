"""Integration: Connecticut amendment precedence + Verified Answer Library feed-back.

Uses real local embeddings against a throwaway Chroma index (no PDFs, no LLM, no network).
"""
import chromadb
import pytest

from app.settings import settings
from app import embeddings


@pytest.fixture
def temp_index(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "chroma_dir", str(tmp_path / "chroma"))
    monkeypatch.setattr(settings, "active_collection", "test_edition")
    monkeypatch.setattr(settings, "verified_collection", "test_verified")
    monkeypatch.setattr(settings, "use_reranker", False)

    client = chromadb.PersistentClient(path=settings.chroma_dir)
    coll = client.get_or_create_collection("test_edition")
    rows = [
        ("903.2.8 Group R. Base model code: an automatic sprinkler system shall be provided "
         "throughout buildings with a Group R fire area.",
         {"section": "903.2.8", "book": "IFC", "edition": "2021", "is_amendment": False,
          "is_table": False, "page": 1}),
        ("903.2.8 Group R (Amd). Connecticut substitutes: sprinklers required throughout all "
         "Group R buildings including existing buildings on change of occupancy.",
         {"section": "903.2.8", "book": "CSFSC", "edition": "2022", "is_amendment": True,
          "is_table": False, "page": 1}),
        ("907.2.9 Group R-2. A manual fire alarm system shall be installed in Group R-2 "
         "occupancies meeting the listed conditions.",
         {"section": "907.2.9", "book": "IFC", "edition": "2021", "is_amendment": False,
          "is_table": False, "page": 2}),
    ]
    embs = embeddings.embed([t for t, _ in rows], input_type="document")
    coll.add(ids=[str(i) for i in range(len(rows))], documents=[t for t, _ in rows],
             metadatas=[m for _, m in rows], embeddings=embs)
    return coll


def test_amendment_marked_controlling_and_ranked_first(temp_index):
    from app.retriever import retrieve
    chunks = retrieve("when is a sprinkler system required for a Group R building?")
    amd = [c for c in chunks if c["metadata"]["section"] == "903.2.8" and c["metadata"].get("is_amendment")]
    base = [c for c in chunks if c["metadata"]["section"] == "903.2.8" and not c["metadata"].get("is_amendment")]
    assert amd, "CT amendment for 903.2.8 should be retrieved"
    assert amd[0]["metadata"].get("controlling") is True
    if base:  # amendment (controlling) must come before the base model text
        assert chunks.index(amd[0]) < chunks.index(base[0])


def test_verified_answer_surfaces_on_similar_question(temp_index):
    from app.retriever import retrieve
    from app import feedback

    q = "sprinkler requirements for an existing Group R building"
    assert not any(c["metadata"].get("verified") for c in retrieve(q))  # none yet

    feedback.promote_verified(
        question=q,
        corrected_answer="Yes — under the CT amendment, sprinklers are required throughout, "
                         "including existing Group R buildings on a change of occupancy.",
        governing_sections=["903.2.8"])

    chunks = retrieve("do I need sprinklers in an existing Group R building?")
    assert any(c["metadata"].get("verified") for c in chunks), "verified answer should surface"
