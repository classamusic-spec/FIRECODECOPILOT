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
    res = agent.ask("sprinkler for group R?", building_context="new Group R; sprinklered; 4 stories")
    assert res.mode == "answer"
    assert not res.needs_clarification
    assert res.citations_ok                     # 903.2.8 is in the sources
    assert res.answer and "903.2.8" in res.answer


def test_nfpa_101_book_name_is_not_falsely_reported_as_missing(monkeypatch):
    nfpa_sources = [Scored({
        "text": "31.1.1.1 The requirements of this chapter shall apply to existing apartment occupancies.",
        "metadata": {
            "section": "31.1.1.1",
            "book": "NFPA 101 2021 — Chapter 31 Existing Apartment Buildings",
            "edition": "2021",
            "page": 1,
        },
    }, 0.9)]
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: nfpa_sources)
    monkeypatch.setattr(
        agent.llm, "chat",
        lambda *a, **k: "NFPA 101 §31.1.1.1 applies to existing apartment occupancies.",
    )
    res = agent.ask("Look up NFPA 101 §31.1.1.1")
    assert res.citations_ok
    assert res.answer and "not found in your loaded code books" not in res.answer


def test_clarifying_questions(monkeypatch):
    _patch(monkeypatch,
           '{"needs_clarification": true, '
           '"questions": ["Is the building sprinklered?", "How many stories?"], '
           '"chips": {"Sprinklered": ["Yes", "No"]}}')
    res = agent.ask("is a sprinkler required?")
    assert res.needs_clarification
    assert res.answer is None
    assert res.clarifying_questions == ["What is the occupancy/use group?"]
    assert res.chips == {"What is the occupancy/use group?": ["B", "F-1", "F-2", "R-2", "Mixed-use"]}


def test_existing_building_gate_asks_original_permit_date_when_it_controls_part_iv():
    questions, chips = agent._determinative_facts(
        "What are the egress requirements for an existing R-2 apartment building?",
        "Existing R-2; sprinklered; 3 stories; occupant load 40",
    )
    assert questions == ["Was the original building permit issued before January 1, 2006?"]
    assert chips[questions[0]] == ["Before Jan. 1, 2006", "Jan. 1, 2006 or later", "I don't know"]


def test_existing_building_gate_accepts_an_explicit_pre_2006_year():
    questions, _chips = agent._determinative_facts(
        "What are the egress requirements for this existing R-2 apartment building?",
        "Originally permitted in 1995; sprinklered; 3 stories; occupant load 40",
    )
    assert "Was the original building permit issued before January 1, 2006?" not in questions


def test_existing_building_gate_does_not_treat_nfpa_101_mention_as_applicability_fact():
    questions, _chips = agent._determinative_facts(
        "Does NFPA 101 apply to this existing R-2 apartment building?",
        "Existing R-2; sprinklered; 3 stories; occupant load 40",
    )
    assert questions == ["Was the original building permit issued before January 1, 2006?"]


def test_clarifying_json_in_code_fence(monkeypatch):
    _patch(monkeypatch, '```json\n{"needs_clarification": true, "questions": ["Occupancy?"]}\n```')
    res = agent.ask("requirements?")
    assert res.needs_clarification and res.clarifying_questions == ["Occupancy?"]


def test_clarification_parser_keeps_only_one_decisive_question():
    parsed = agent._parse_clarification(
        '{"needs_clarification": true, "questions": ["Occupancy?", "Sprinklered?"], '
        '"chips": {"Occupancy?": ["F-1"], "Sprinklered?": ["Yes", "No"]}}'
    )
    assert parsed == {"questions": ["Occupancy?"], "chips": {"Occupancy?": ["F-1"]}}


def test_answer_after_clarification_bypasses_another_clarification_round(monkeypatch):
    """Continue must retrieve and answer, even when some facts remain unknown."""
    _patch(monkeypatch, "For the described existing factory building, see Section 903.2.8.")
    retrievals = []
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: retrievals.append((q, k)) or SOURCES)
    res = agent.ask(
        "what is required for standpipe systems at a factory building?",
        building_context="Existing; permitted in 1995; 1–3 stories",
        allow_clarification=False,
    )
    assert retrievals[0][0] == "what is required for standpipe systems at a factory building?"
    assert any("permitted in 1995" in q for q in retrievals[0][1].get("extra_queries", []))
    assert not res.needs_clarification
    assert res.answer and "903.2.8" in res.answer


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


def test_deep_mode_runs_second_retrieval_pass(monkeypatch):
    monkeypatch.setattr(agent.settings, "use_reranker", True)
    monkeypatch.setattr(agent.settings, "deep_provider", "anthropic")
    calls = []
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: calls.append(k) or SOURCES)
    monkeypatch.setattr(agent.llm, "chat", lambda *a, **k: "Per §903.2.8, yes.")
    agent.ask("sprinkler?", deep=True,
              building_context="Existing R-2, permitted in 1995, 4 stories, not sprinklered")
    assert len(calls) == 2                                   # first pass, then the deep rewrite pass
    assert calls[1].get("extra_queries") and "building details" in calls[1]["extra_queries"][0]


def test_deep_mode_without_context_no_second_pass(monkeypatch):
    monkeypatch.setattr(agent.settings, "use_reranker", True)
    monkeypatch.setattr(agent.settings, "deep_provider", "anthropic")
    calls = []
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: calls.append(k) or SOURCES)
    monkeypatch.setattr(agent.llm, "chat", lambda *a, **k: "Per §903.2.8, yes.")
    agent.ask("new sprinklered Group R building: sprinkler required?", deep=True)  # specified; no rewrite extra needed
    assert len(calls) == 1


def test_retrieve_mode_returns_sources_without_generation(monkeypatch):
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: SOURCES)
    # llm.chat must NOT be called in retrieve mode.
    monkeypatch.setattr(agent.llm, "chat",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not generate")))
    res = agent.ask("anything", mode="retrieve")
    assert res.answer is None and len(res.sources) == 1


def test_cgs_question_routes_to_current_statutes_without_manual_collection_selection(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: calls.append(k) or SOURCES)

    agent.ask("What authority does the State Fire Marshal have under Connecticut General Statutes §29-250?",
              mode="retrieve")

    assert calls[0]["collection"] == "ct_general_statutes_chapter_541_2025_2026"


def test_common_statutes_spelling_routes_to_current_statutes(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: calls.append(k) or SOURCES)

    agent.ask("What do Connecticut general statues say about the State Fire Marshal?", mode="retrieve")

    assert calls[0]["collection"] == "ct_general_statutes_chapter_541_2025_2026"


def test_explicit_collection_choice_is_not_overridden_for_cgs_question(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: calls.append(k) or SOURCES)

    agent.ask("What authority does the State Fire Marshal have under CGS §29-250?", mode="retrieve",
              collection="csfsc_2022")

    assert calls[0]["collection"] == "csfsc_2022"
