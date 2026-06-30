"""Streaming: agent.ask_stream event sequence + the /ask/stream SSE endpoint (LLM mocked)."""
import json

import pytest
from fastapi.testclient import TestClient

import app.agent as agent
import app.main as main
from app.reranker import Scored

SOURCES = [
    Scored({"text": "903.2.8 Group R. An automatic sprinkler system shall be provided "
                    "throughout buildings with a Group R fire area.",
            "metadata": {"section": "903.2.8", "book": "IFC", "edition": "2021", "page": 1}}, 0.9),
]


def _patch_stream(monkeypatch, deltas):
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: SOURCES)
    monkeypatch.setattr(agent.llm, "chat_stream", lambda *a, **k: iter(deltas))


def test_streams_tokens_then_meta(monkeypatch):
    _patch_stream(monkeypatch, ["Per ", "§903.2.8", ", a sprinkler system is required."])
    events = list(agent.ask_stream("sprinkler for R?"))
    types = [e["type"] for e in events]
    assert types[0] == "token" and "meta" in types and types[-1] == "done"
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "903.2.8" in text
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["citations_ok"] and len(meta["sources"]) == 1


def test_clarification_is_not_streamed_as_tokens(monkeypatch):
    # JSON clarification must be buffered (never streamed as raw text) and surface as a clarify event.
    _patch_stream(monkeypatch, ['{"needs_clarification": true,', ' "questions": ["Occupancy?"]}'])
    events = list(agent.ask_stream("is it required?"))
    assert not any(e["type"] == "token" for e in events)
    clar = next(e for e in events if e["type"] == "clarify")
    assert clar["clarifying_questions"] == ["Occupancy?"]


def test_fabricated_citation_flagged_in_meta(monkeypatch):
    _patch_stream(monkeypatch, ["This is governed by Section 815.4."])
    events = list(agent.ask_stream("obscure q"))
    meta = next(e for e in events if e["type"] == "meta")
    assert not meta["citations_ok"]
    assert any("815.4" in u for u in meta["unverified"])
    assert "UNVERIFIED" in meta["answer_suffix"]


def test_sse_endpoint_formats_events(monkeypatch):
    def fake_stream(*a, **k):
        yield {"type": "token", "text": "hi"}
        yield {"type": "done"}
    monkeypatch.setattr(main, "agent_ask_stream", fake_stream)

    client = TestClient(main.app)
    with client.stream("POST", "/ask/stream", json={"question": "x"}) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        body = "".join(r.iter_text())
    payloads = [json.loads(line[len("data: "):]) for line in body.splitlines() if line.startswith("data: ")]
    assert {"type": "token", "text": "hi"} in payloads
    assert payloads[-1] == {"type": "done"}
