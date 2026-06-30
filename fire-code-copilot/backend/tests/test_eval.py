"""The golden eval set is the regression guard — it must stay at 100% on the synthetic corpus."""
import app.agent as agent
import app.llm as llm
from app import eval as fcc_eval
from app.agent import AgentResult


def test_golden_eval_passes():
    report = fcc_eval.run()
    failing = [r["q"] for r in report["results"] if not r["pass"]]
    assert report["score"] == 1.0, f"retrieval regressions: {failing}"
    assert report["safety_validator_flags_fabrication"]


def test_amendment_precedence_in_eval():
    # The existing-R-2 change-of-occupancy case must surface the CT amendment as controlling.
    report = fcc_eval.run()
    case = next(r for r in report["results"] if r["expect"] == "903.2.8.4")
    assert case["pass"] and case.get("controlling_amendment")


def test_judged_run_aggregates_grades(monkeypatch):
    # Mock generation (agent.ask) and the judge (llm.chat) so the tier is testable with no model.
    monkeypatch.setattr(agent, "ask", lambda q, **k: AgentResult(
        mode="answer", answer="Per §903.2.8, sprinklers are required.", sources=[],
        citations_ok=True, unverified=[]))
    monkeypatch.setattr(llm, "chat", lambda *a, **k:
                        '{"grounded": true, "cites_governing": true, "no_fabrication": true, '
                        '"score": 0.9, "notes": "faithful"}')
    report = fcc_eval.run_judged()
    assert "skipped" not in report
    assert report["total"] == report["passed"]        # all 0.9 >= 0.7
    assert report["mean_score"] >= 0.8


def test_judged_run_skips_gracefully_without_a_model(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no model server")
    monkeypatch.setattr(agent, "ask", boom)
    report = fcc_eval.run_judged()
    assert "skipped" in report and "no model server" in report["skipped"]


def test_judge_parser_handles_fenced_json():
    v = fcc_eval._parse_judge('```json\n{"score": 0.5, "grounded": false}\n```')
    assert v["score"] == 0.5 and v["grounded"] is False
