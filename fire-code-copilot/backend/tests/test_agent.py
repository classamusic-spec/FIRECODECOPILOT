"""Agent's three Phase-3 behaviors, exercised with a mocked LLM (no live model needed):
   (a) a good cited answer, (b) asks clarifying Qs when underspecified, (c) refuses to fabricate.
"""
import app.agent as agent
from app.reranker import Scored

SOURCES = [
    Scored({"text": "903.2.8 Group R. An automatic sprinkler system shall be provided "
                    "throughout buildings with a Group R fire area.",
            "metadata": {"section": "903.2.8", "book": "IFC", "edition": "2021", "page": 1}}, 0.9),
]


def _patch(monkeypatch, llm_reply: str):
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: SOURCES)
    monkeypatch.setattr(agent.llm, "chat", lambda *a, **k: llm_reply)


def test_good_cited_answer(monkeypatch):
    _patch(monkeypatch, "Yes. Per Section 903.2.8, a sprinkler system is required for Group R.")
    res = agent.ask("sprinkler for group R?")
    assert res.mode == "answer"
    assert not res.needs_clarification
    assert res.citations_ok                     # 903.2.8 is in the sources
    assert res.answer and "903.2.8" in res.answer


def test_clarifying_questions(monkeypatch):
    _patch(monkeypatch,
           '{"needs_clarification": true, '
           '"questions": ["Is the building sprinklered?", "How many stories?"], '
           '"chips": {"Sprinklered": ["Yes", "No"]}}')
    res = agent.ask("is a sprinkler required?")
    assert res.needs_clarification
    assert res.answer is None
    assert len(res.clarifying_questions) == 2
    assert res.chips.get("Sprinklered") == ["Yes", "No"]


def test_clarifying_json_in_code_fence(monkeypatch):
    _patch(monkeypatch, '```json\n{"needs_clarification": true, "questions": ["Occupancy?"]}\n```')
    res = agent.ask("requirements?")
    assert res.needs_clarification and res.clarifying_questions == ["Occupancy?"]


def test_refuses_to_fabricate(monkeypatch):
    # Model invents §815.4, which is NOT in the retrieved sources -> flagged unverified.
    _patch(monkeypatch, "This is covered by Section 815.4 of the fire code.")
    res = agent.ask("some obscure question")
    assert not res.citations_ok
    assert any("815.4" in u for u in res.unverified)
    assert "UNVERIFIED CITATION" in res.answer


def test_confidence_band_high(monkeypatch):
    monkeypatch.setattr(agent.settings, "use_reranker", True)  # scores are meaningful
    _patch(monkeypatch, "Per §903.2.8, yes.")                  # SOURCES score = 0.9
    res = agent.ask("q")
    assert res.confidence == 0.9 and res.confidence_band == "high"


def test_low_confidence_auto_flags_review_queue(monkeypatch):
    monkeypatch.setattr(agent.settings, "use_reranker", True)
    weak = [Scored(SOURCES[0].chunk, 0.05)]                    # below the deep/low floor
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: weak)
    monkeypatch.setattr(agent.llm, "chat", lambda *a, **k: "Per §903.2.8, yes.")
    captured = {}
    monkeypatch.setattr("app.feedback.record_feedback",
                        lambda **kw: captured.update(kw) or {"id": 1})
    res = agent.ask("q")
    assert res.confidence_band == "low"
    assert captured.get("low_confidence") is True


def test_retrieve_mode_returns_sources_without_generation(monkeypatch):
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: SOURCES)
    # llm.chat must NOT be called in retrieve mode.
    monkeypatch.setattr(agent.llm, "chat",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not generate")))
    res = agent.ask("anything", mode="retrieve")
    assert res.answer is None and len(res.sources) == 1
