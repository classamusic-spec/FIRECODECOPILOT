from app import agent
from app.reranker import Scored

SRC = {"text": "SECTION 905\n905.3.1 Height\nClass III standpipe systems are required above 30 feet.",
       "metadata": {"section":"905.3.1", "page": 22, "book":"IFC", "edition":"2021", "source":"ifc.pdf"}}

def test_trace_contains_all_audit_sections(monkeypatch):
    monkeypatch.setattr(agent, "retrieve_scored", lambda *a, **k: [Scored(SRC, 0.9)])
    monkeypatch.setattr(agent.llm, "chat", lambda *a, **k: "Standpipes are required above 30 feet per §905.3.1.")
    r = agent.ask("new sprinklered factory, 5 stories: standpipe requirement?", building_context="new F-1; sprinklered; 5 stories")
    assert r.trace
    assert {"interpreted_query", "retrieval", "reranked", "controlling_source", "citation_check", "generation"} <= set(r.trace)
    assert r.trace["citation_check"][0]["verified"] is True
    assert r.trace["generation"]["thinking"] == "off"

def test_invalid_citation_retries_then_resolves(monkeypatch):
    calls = []
    def retrieve(*a, **k):
        calls.append(k)
        return [Scored(SRC, 0.9)]
    replies = iter(["Wrong §999.9.", "Correct §905.3.1."])
    monkeypatch.setattr(agent, "retrieve_scored", retrieve)
    monkeypatch.setattr(agent.llm, "chat", lambda *a, **k: next(replies))
    r = agent.ask("new sprinklered factory, 5 stories: standpipe requirement?", building_context="new F-1; sprinklered; 5 stories")
    assert r.citations_ok
    assert len(calls) == 2
    assert r.trace["attempts"]
