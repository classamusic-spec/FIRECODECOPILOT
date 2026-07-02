"""Follow-up memory, the page-image endpoint, and the Library (books list / manifest /
streaming ingest) — the capability batch on top of the audited core."""
import fitz
import pytest
from fastapi.testclient import TestClient

import app.agent as agent
import app.main as main
from app.reranker import Scored

CHUNK = Scored({"text": "903.2.8 Group R. Sprinklers required throughout.",
                "metadata": {"section": "903.2.8", "page": 1}}, 0.9)


# --- Follow-up memory --------------------------------------------------------------------------

def test_followup_adds_context_carrying_retrieval_variant(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: calls.append((q, k)) or [CHUNK])
    monkeypatch.setattr(agent.llm, "chat", lambda *a, **k: "Per §903.2.8, yes.")
    history = [{"question": "When are sprinklers required for Group R-2?",
                "answer": "Per §903.2.8 they are required throughout Group R fire areas."}]
    agent.ask("what about existing buildings?", history=history)
    q, kw = calls[0]
    assert q == "what about existing buildings?"          # literal question still primary
    extra = kw.get("extra_queries") or []
    assert extra and "Group R-2" in extra[0]              # prior topic carried into retrieval


def test_followup_history_lands_in_prompt(monkeypatch):
    seen = {}
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: [CHUNK])
    monkeypatch.setattr(agent.llm, "chat",
                        lambda system, user, **k: seen.update(user=user) or "Per §903.2.8, yes.")
    history = [{"question": "When are sprinklers required for Group R-2?", "answer": "Per §903.2.8 …"}]
    agent.ask("what about existing buildings?", history=history)
    assert "PRIOR CONVERSATION" in seen["user"]
    assert "Group R-2" in seen["user"]


def test_no_history_no_variant(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: calls.append(k) or [CHUNK])
    monkeypatch.setattr(agent.llm, "chat", lambda *a, **k: "Per §903.2.8, yes.")
    agent.ask("when are sprinklers required?")
    assert not calls[0].get("extra_queries")


def test_history_flows_through_the_api(monkeypatch):
    captured = {}
    from app.agent import AgentResult

    def fake_ask(question, **kw):
        captured.update(kw)
        return AgentResult(mode="answer", answer="ok", sources=[], citations_ok=True, unverified=[])
    monkeypatch.setattr(main, "agent_ask", fake_ask)
    client = TestClient(main.app)
    r = client.post("/ask", json={"question": "and for existing?",
                                  "history": [{"question": "sprinklers for R-2?", "answer": "yes"}]})
    assert r.status_code == 200
    assert captured["history"] == [{"question": "sprinklers for R-2?", "answer": "yes"}]


# --- Page image (verify against the real typeset page) ------------------------------------------

@pytest.fixture
def books_dir(tmp_path, monkeypatch):
    from app.settings import settings
    d = tmp_path / "books"; d.mkdir()
    doc = fitz.open(); page = doc.new_page()
    page.insert_text((72, 100), "903.2.8 Group R. Sprinklers required.")
    doc.save(str(d / "ifc.pdf")); doc.close()
    monkeypatch.setattr(settings, "code_books_dir", str(d))
    return d


def test_page_image_returns_png(books_dir):
    client = TestClient(main.app)
    r = client.get("/page-image", params={"source": "ifc.pdf", "page": 1})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_page_image_rejects_traversal_and_missing(books_dir):
    client = TestClient(main.app)
    assert client.get("/page-image", params={"source": "../secrets.pdf", "page": 1}).status_code == 400
    assert client.get("/page-image", params={"source": "nope.pdf", "page": 1}).status_code == 404
    assert client.get("/page-image", params={"source": "ifc.pdf", "page": 99}).status_code == 404


# --- Library: books list, manifest save, streaming ingest ---------------------------------------

def test_books_list_and_manifest_roundtrip(books_dir, tmp_path, monkeypatch):
    from app.settings import settings
    from app import ingest as ing
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(ing, "STATE_FILE", tmp_path / "data" / "ingest_state.json")
    monkeypatch.setattr(ing, "COLLECTIONS_FILE", tmp_path / "data" / "collections.json")

    client = TestClient(main.app)
    r = client.get("/books")
    assert r.status_code == 200
    books = r.json()["books"]
    assert [b["file"] for b in books] == ["ifc.pdf"]
    assert books[0]["indexed"] is False and books[0]["in_manifest"] is False

    r = client.put("/books-manifest", json={
        "ifc.pdf": {"book": "IFC", "edition": "2021", "collection": "test_2021",
                    "is_amendment_doc": False, "junk_field": "dropped"},
        "not-present.pdf": {"book": "ghost"},
    })
    assert r.status_code == 200
    saved = r.json()
    assert saved["saved"] == 1 and "junk_field" not in saved["manifest"]["ifc.pdf"]

    books = client.get("/books").json()["books"]
    assert books[0]["in_manifest"] is True and books[0]["collection"] == "test_2021"


def test_ingest_stream_emits_progress_events(books_dir, tmp_path, monkeypatch):
    from app.settings import settings
    from app import ingest as ing
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "chroma_dir", str(tmp_path / "data" / "chroma"))
    monkeypatch.setattr(settings, "active_collection", "lib_test")
    monkeypatch.setattr(settings, "extract_tables", False)
    monkeypatch.setattr(ing, "STATE_FILE", tmp_path / "data" / "ingest_state.json")
    monkeypatch.setattr(ing, "COLLECTIONS_FILE", tmp_path / "data" / "collections.json")

    client = TestClient(main.app)
    r = client.post("/ingest/stream", json={"force": True})
    assert r.status_code == 200
    body = r.text
    for expected in ('"type": "start"', '"type": "file"', '"type": "done"'):
        assert expected in body, f"missing {expected} in stream:\n{body}"
