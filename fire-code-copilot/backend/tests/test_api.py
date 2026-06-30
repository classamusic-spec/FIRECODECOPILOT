"""API smoke tests: routes wire up and request/response models are correct (agent mocked)."""
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.agent import AgentResult


@pytest.fixture
def client():
    return TestClient(main.app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_cycle_status(client):
    r = client.get("/cycle-status")
    assert r.status_code == 200
    assert "active" in r.json() and "ACTIVE CYCLE" in r.json()["active"]


def test_ask_routes_to_agent(client, monkeypatch):
    captured = {}

    def fake_ask(question, **kw):
        captured.update(question=question, **kw)
        return AgentResult(mode="answer", answer="Per §903.2.8, yes.",
                           sources=[], citations_ok=True, unverified=[])

    monkeypatch.setattr(main, "agent_ask", fake_ask)
    r = client.post("/ask", json={"question": "sprinkler for R-2?", "provider": "anthropic"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "Per §903.2.8, yes." and body["citations_ok"] is True
    assert captured["provider"] == "anthropic"     # provider override threads through


def test_clarify_folds_answers_into_context(client, monkeypatch):
    captured = {}

    def fake_ask(question, **kw):
        captured.update(kw)
        return AgentResult(mode="answer", answer="ok", sources=[], citations_ok=True, unverified=[])

    monkeypatch.setattr(main, "agent_ask", fake_ask)
    r = client.post("/clarify", json={"question": "is it required?",
                                      "building_context": "Group R-2", "answers": "Sprinklered: No"})
    assert r.status_code == 200
    assert "Group R-2" in captured["building_context"] and "Sprinklered: No" in captured["building_context"]
