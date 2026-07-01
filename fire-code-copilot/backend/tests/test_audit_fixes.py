"""Regression tests for the full-app audit fixes: amendment mislabeling, NFPA citation
false-alarms, occupancy-expansion false positives, verified-answer relevance/edition guards,
reranker-off ordering, streaming error safety, and API error shapes."""
import pytest
from fastapi.testclient import TestClient

import app.agent as agent
import app.main as main
from app.agent import AgentResult
from app.chunking import chunk_pages
from app.citations import validate
from app.query import expand_query
from app.reranker import Scored


# --- 1. Base model-code text must never masquerade as the controlling CT amendment ------------

def test_prose_amended_does_not_tag_base_text_as_amendment():
    pages = [(1, "903.2 Automatic sprinkler systems.\n"
                 "An automatic sprinkler system shall be installed as amended by local ordinance "
                 "where required by this chapter for the fire areas described below.")]
    chunks = chunk_pages(pages, {"book": "IFC", "edition": "2021", "is_amendment_doc": False})
    assert chunks and all(not c["metadata"]["is_amendment"] for c in chunks)


def test_explicit_parenthetical_marker_still_tags():
    pages = [(1, "903.2.8.4 Group R-2 existing buildings (Amd)\n"
                 "In existing Group R-2 buildings an automatic sprinkler system shall be installed "
                 "throughout where required by the State Fire Marshal upon change of occupancy.")]
    chunks = chunk_pages(pages, {"book": "IFC", "edition": "2021", "is_amendment_doc": False})
    assert chunks and any(c["metadata"]["is_amendment"] for c in chunks)


# --- 2. NFPA standards named in the sources must verify (no chronic false alarms) -------------

def test_nfpa_citation_verifies_against_source_text():
    chunks = [{"text": "903.3.1.1 NFPA 13 sprinkler systems. Sprinkler systems shall be installed "
                       "in accordance with NFPA 13.",
               "metadata": {"section": "903.3.1.1"}}]
    check = validate("Sprinklers must comply with NFPA 13 per Section 903.3.1.1.", chunks)
    assert check.ok, f"NFPA 13 should verify; unverified={check.unverified}"


def test_nfpa_citation_not_in_sources_still_flags():
    chunks = [{"text": "907.2.9 A manual fire alarm system shall be installed.",
               "metadata": {"section": "907.2.9"}}]
    check = validate("Install per NFPA 72.", chunks)
    assert not check.ok and any("72" in u for u in check.unverified)


# --- 3. Occupancy expansion must not fire on the English words "a" / "I" ----------------------

def test_articles_do_not_expand_to_occupancy_groups():
    out = expand_query("do i need a permit for the work?")
    assert "Group A" not in out and "Group I" not in out


def test_real_occupancy_forms_still_expand():
    assert "Group R-2" in expand_query("sprinklers for an existing R-2?")
    assert "Group A assembly" in expand_query("occupant load for a Group A space")


# --- 4/5. Verified answers: relevance threshold + edition filter + no crowd-out ---------------

@pytest.fixture
def seeded_index(tmp_path, monkeypatch):
    """Real-embedding throwaway index: 903.x + 907.x chunks and two verified answers
    (one for this edition, one for another), reranker OFF."""
    import chromadb
    from app.settings import settings
    from app import embeddings, lexical

    monkeypatch.setattr(settings, "chroma_dir", str(tmp_path / "chroma"))
    monkeypatch.setattr(settings, "active_collection", "aud_edition")
    monkeypatch.setattr(settings, "verified_collection", "aud_verified")
    monkeypatch.setattr(settings, "use_reranker", False)
    lexical.reset_cache()

    client = chromadb.PersistentClient(path=settings.chroma_dir)
    coll = client.get_or_create_collection("aud_edition")
    rows = [
        ("903.2.8 Group R. An automatic sprinkler system shall be provided throughout buildings "
         "with a Group R fire area.", {"section": "903.2.8", "book": "IFC", "edition": "2021",
                                       "is_amendment": False, "is_table": False, "page": 1}),
        ("907.2.9.3 Smoke alarms. Single- and multiple-station smoke alarms shall be installed "
         "in Group R-2 occupancies in each sleeping room.", {"section": "907.2.9.3", "book": "IFC",
                                                             "edition": "2021", "is_amendment": False,
                                                             "is_table": False, "page": 2}),
    ]
    embs = embeddings.embed([t for t, _ in rows], input_type="document")
    coll.add(ids=[f"f{i}" for i in range(len(rows))], documents=[t for t, _ in rows],
             metadatas=[m for _, m in rows], embeddings=embs)

    vcoll = client.get_or_create_collection("aud_verified")
    ventries = [
        ("Are sprinklers required for Group R buildings?\nYes — per 903.2.8 sprinklers are "
         "required throughout Group R fire areas.", {"edition": "aud_edition", "section": "903.2.8"}),
        ("Are sprinklers required for Group R buildings?\nOld-cycle answer that must not appear.",
         {"edition": "some_other_edition", "section": "903.2.8"}),
    ]
    vembs = embeddings.embed([t for t, _ in ventries], input_type="document")
    vcoll.add(ids=["v-this", "v-other"], documents=[t for t, _ in ventries],
              metadatas=[m for _, m in ventries], embeddings=vembs)
    return coll


def test_exact_section_query_not_displaced_by_verified_or_amendments(seeded_index):
    from app.retriever import retrieve_scored
    scored = retrieve_scored("what does section 907.2.9.3 require?")
    sections = [s.chunk["metadata"].get("section") for s in scored]
    assert "907.2.9.3" in sections, f"target section displaced; got {sections}"
    # And the target must precede any verified extra (verified are appended, not prepended).
    v_idx = [i for i, s in enumerate(scored) if s.chunk["metadata"].get("verified")]
    t_idx = sections.index("907.2.9.3")
    assert not v_idx or t_idx < min(v_idx)


def test_verified_filtered_to_matching_edition(seeded_index):
    from app.retriever import retrieve_scored
    scored = retrieve_scored("Are sprinklers required for Group R buildings?")
    vtexts = [s.chunk["text"] for s in scored if s.chunk["metadata"].get("verified")]
    assert any("required throughout Group R" in t for t in vtexts), "this-edition verified missing"
    assert not any("Old-cycle answer" in t for t in vtexts), "other-edition verified leaked"


def test_unrelated_verified_answer_does_not_surface(seeded_index):
    from app.retriever import retrieve_scored
    scored = retrieve_scored("portable fire extinguisher hydrostatic test intervals")
    assert not any(s.chunk["metadata"].get("verified") for s in scored), \
        "irrelevant verified answer surfaced despite the distance threshold"


# --- 6. Mid-stream failure: already-streamed text still gets the citation safety net ----------

def test_stream_error_after_tokens_validates_partial_and_ends_clean(monkeypatch):
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: [Scored(
        {"text": "903.2.8 Group R. Sprinklers required.", "metadata": {"section": "903.2.8"}}, 0.9)])

    def broken_stream(*a, **k):
        yield "Per Section 999.9.9, sprinklers are never required. "
        raise ConnectionError("model server dropped")

    monkeypatch.setattr(agent.llm, "chat_stream", broken_stream)
    events = list(agent.ask_stream("q"))
    types = [e["type"] for e in events]
    assert types[-1] == "done", f"stream must terminate with done; got {types}"
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["citations_ok"] is False                      # fabricated 999.9.9 caught
    assert "cut off" in meta["answer_suffix"]                 # truncation surfaced


def test_stream_error_before_tokens_emits_error_and_done(monkeypatch):
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: [])

    def dead_stream(*a, **k):
        raise ConnectionError("no model")
        yield  # pragma: no cover

    monkeypatch.setattr(agent.llm, "chat_stream", dead_stream)
    types = [e["type"] for e in agent.ask_stream("q")]
    assert types == ["error", "done"]


# --- 7. API: retrieve-mode streaming + structured HTTP errors ---------------------------------

def test_stream_retrieve_mode_returns_sources_without_llm(monkeypatch):
    def fake_ask(question, **kw):
        assert kw.get("mode") == "retrieve"
        return AgentResult(mode="retrieve", answer=None, citations_ok=True, unverified=[],
                           sources=[{"text": "903.2.8 …", "metadata": {"section": "903.2.8"}}])
    monkeypatch.setattr(main, "agent_ask", fake_ask)
    monkeypatch.setattr(main, "agent_ask_stream",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM path used")))
    client = TestClient(main.app)
    r = client.post("/ask/stream", json={"question": "q", "mode": "retrieve"})
    assert r.status_code == 200
    body = r.text
    assert '"type": "meta"' in body and '"type": "done"' in body and "903.2.8" in body


def test_unknown_collection_is_404(monkeypatch):
    class FakeNotFoundError(Exception):
        pass
    FakeNotFoundError.__name__ = "NotFoundError"

    def boom(*a, **k):
        raise FakeNotFoundError("Collection [nope_2099] does not exist")
    monkeypatch.setattr(main, "agent_ask", boom)
    client = TestClient(main.app)
    r = client.post("/ask", json={"question": "q", "collection": "nope_2099"})
    assert r.status_code == 404
