"""The golden eval set is the regression guard — it must stay at 100% on the synthetic corpus."""
from app import eval as fcc_eval


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
