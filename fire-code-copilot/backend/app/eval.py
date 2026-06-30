"""Eval / regression harness — guards the "no wrong citations" promise.

Builds a throwaway index from a SYNTHETIC fire-code corpus (original text, never copyrighted),
then runs the golden questions in eval/golden.yaml through the real retrieval path and checks:
  - the governing section is retrieved (hit@k), and
  - where a CT amendment applies, it comes back marked controlling.
It also spot-checks the citation validator (a fabricated section must be flagged).

Run it:  python -m app.eval        (prints a report, exits non-zero on regression)
It's also wired into the test suite (tests/test_eval.py) so changes can't silently regress.
"""
from __future__ import annotations
import contextlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

from .settings import settings
from . import embeddings, citations
from .chunking import chunk_pages
from .sections import relates, canonical

GOLDEN = Path(__file__).resolve().parents[1] / "eval" / "golden.yaml"

# --- Synthetic corpus (original text; mimics ICC/NFPA structure only). ----------------------
_MODEL_META = {"book": "IFC (model)", "edition": "2021", "is_amendment_doc": False}
_AMD_META = {"book": "CSFSC", "edition": "2022", "is_amendment_doc": True}

_MODEL_PAGES = [
    (1,
     "SECTION 903  AUTOMATIC SPRINKLER SYSTEMS\n"
     "903.2 Where required\n"
     "Approved automatic sprinkler systems shall be installed in the locations described in this\n"
     "section for the occupancies and conditions listed.\n"
     "903.2.8 Group R\n"
     "An automatic sprinkler system shall be provided throughout all buildings with a Group R\n"
     "fire area, as determined in accordance with the building code.\n"
     "903.2.8.1 Group R-2\n"
     "An automatic sprinkler system shall be installed throughout buildings containing a Group\n"
     "R-2 occupancy where the building is more than three stories above grade plane, has more\n"
     "than 16 dwelling units, or any Group R-2 fire area exceeds 12,000 square feet.\n"
     "903.3.1.1 NFPA 13 sprinkler systems\n"
     "Where this code requires a building to be equipped with an automatic sprinkler system,\n"
     "sprinklers shall be installed throughout in accordance with NFPA 13.\n"),
    (2,
     "903.4 Sprinkler system supervision and alarms\n"
     "Valves controlling the water supply and waterflow switches on automatic sprinkler systems\n"
     "shall be electrically supervised by a listed fire alarm control unit.\n"
     "TABLE 903.2.11.6  ADDITIONAL REQUIRED SPRINKLER SYSTEM LOCATIONS\n"
     "Section Subject\n"
     "903.2.11.1 Stories without openings\n"
     "903.2.11.3 Buildings 55 feet or more in height\n"
     "SECTION 907  FIRE ALARM AND DETECTION SYSTEMS\n"
     "907.2.9 Group R-2\n"
     "A manual fire alarm system shall be installed in Group R-2 occupancies where any dwelling\n"
     "unit is three or more stories above the lowest level of exit discharge or the building has\n"
     "more than 16 dwelling units.\n"
     "907.2.9.3 Smoke alarms\n"
     "Single- and multiple-station smoke alarms shall be installed in Group R-2 occupancies in\n"
     "accordance with NFPA 72.\n"),
]

_AMD_PAGES = [
    (1,
     "CONNECTICUT AMENDMENTS TO THE 2021 INTERNATIONAL FIRE CODE\n"
     "903.2.8 Group R  (Amd)\n"
     "Delete the model code text of Section 903.2.8 and substitute the following: an automatic\n"
     "sprinkler system shall be provided throughout all buildings with a Group R fire area,\n"
     "including existing buildings undergoing a change of occupancy to Group R.\n"
     "903.2.8.4 Group R-2 existing buildings  (Add)\n"
     "Add a new Section 903.2.8.4: in existing Group R-2 buildings, an automatic sprinkler\n"
     "system shall be installed throughout where required by the State Fire Marshal upon a\n"
     "change of occupancy or a substantial alteration.\n"),
]


def _build_corpus(coll) -> int:
    rows = chunk_pages(_MODEL_PAGES, _MODEL_META) + chunk_pages(_AMD_PAGES, _AMD_META)
    texts = [c["text"] for c in rows]
    metas = [c["metadata"] for c in rows]
    vecs = embeddings.embed(texts, input_type="document")
    coll.add(ids=[str(i) for i in range(len(rows))], documents=texts, metadatas=metas, embeddings=vecs)
    return len(rows)


def run(top_k: int | None = None) -> dict:
    """Run the golden set against a fresh synthetic index. Returns a structured report."""
    import chromadb
    from . import retriever

    cases = (yaml.safe_load(GOLDEN.read_text()) or {}).get("cases", [])
    tmp = tempfile.mkdtemp(prefix="fcc-eval-")
    saved = (settings.chroma_dir, settings.active_collection, settings.verified_collection,
             settings.use_reranker, settings.retrieve_before_rerank, settings.keep_after_rerank)
    settings.chroma_dir = tmp
    settings.active_collection = "eval"
    settings.verified_collection = "eval_verified"   # isolated; empty during eval
    settings.use_reranker = False
    settings.keep_after_rerank = top_k or 6
    settings.retrieve_before_rerank = max(settings.retrieve_before_rerank, 20)

    results, passed = [], 0
    try:
        client = chromadb.PersistentClient(path=tmp)
        n = _build_corpus(client.get_or_create_collection("eval"))

        for case in cases:
            chunks = retriever.retrieve(case["q"])
            want = case["expect_section"]
            hit = next((c for c in chunks if canonical(c["metadata"].get("section")) == canonical(want)
                        or relates(c["metadata"].get("section"), want)), None)
            ok = hit is not None
            detail = {"q": case["q"], "expect": want, "retrieved": ok}

            if ok and case.get("expect_controlling_amendment"):
                ctl = any(c["metadata"].get("controlling") and relates(c["metadata"].get("section"), want)
                          for c in chunks)
                detail["controlling_amendment"] = ctl
                ok = ok and ctl
            if ok and case.get("expect_table"):
                tbl = any(c["metadata"].get("is_table") and relates(c["metadata"].get("section"), want)
                          for c in chunks)
                detail["is_table"] = tbl
                ok = ok and tbl

            detail["pass"] = ok
            passed += int(ok)
            results.append(detail)

        # Safety spot-check: the validator must flag a fabricated section.
        sample = retriever.retrieve("Group R-2 sprinkler requirements")
        fab = citations.validate("This is governed by Section 911.9.9.", sample)
        safety_ok = not fab.ok and any("911.9.9" in u for u in fab.unverified)
    finally:
        (settings.chroma_dir, settings.active_collection, settings.verified_collection,
         settings.use_reranker, settings.retrieve_before_rerank, settings.keep_after_rerank) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(results)
    return {
        "corpus_chunks": n,
        "total": total,
        "passed": passed,
        "score": (passed / total) if total else 0.0,
        "safety_validator_flags_fabrication": safety_ok,
        "results": results,
    }


@contextlib.contextmanager
def _eval_corpus(top_k: int = 6):
    """Stand up the synthetic index in a temp dir, point settings at it, and restore after."""
    import chromadb
    tmp = tempfile.mkdtemp(prefix="fcc-eval-")
    saved = (settings.chroma_dir, settings.active_collection, settings.verified_collection,
             settings.use_reranker, settings.retrieve_before_rerank, settings.keep_after_rerank)
    settings.chroma_dir = tmp
    settings.active_collection = "eval"
    settings.verified_collection = "eval_verified"
    settings.use_reranker = False
    settings.keep_after_rerank = top_k
    settings.retrieve_before_rerank = max(settings.retrieve_before_rerank, 20)
    try:
        client = chromadb.PersistentClient(path=tmp)
        n = _build_corpus(client.get_or_create_collection("eval"))
        yield n
    finally:
        (settings.chroma_dir, settings.active_collection, settings.verified_collection,
         settings.use_reranker, settings.retrieve_before_rerank, settings.keep_after_rerank) = saved
        shutil.rmtree(tmp, ignore_errors=True)


# --- LLM-judge answer grading (opt-in; needs a generation model configured) ----------------
_JUDGE_SYSTEM = (
    "You are a strict evaluator of a fire-code assistant's answers. You are given the QUESTION, "
    "the exact SOURCES the assistant was shown, its ANSWER, and the EXPECTED governing section. "
    "Judge ONLY against the sources — do not use outside knowledge. Reply with ONLY a JSON object:\n"
    '{"grounded": true/false, "cites_governing": true/false, "no_fabrication": true/false, '
    '"score": 0.0-1.0, "notes": "one sentence"}\n'
    "grounded = every substantive claim is supported by the sources; cites_governing = the answer "
    "cites the expected governing section; no_fabrication = no invented section numbers or quotes; "
    "score = overall faithfulness/usefulness."
)


def _parse_judge(text: str) -> dict:
    s = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL) or re.search(r"(\{.*\})", s, re.DOTALL)
    if m:
        s = m.group(1)
    try:
        return json.loads(s)
    except (ValueError, json.JSONDecodeError):
        return {"grounded": False, "cites_governing": False, "no_fabrication": False,
                "score": 0.0, "notes": "judge output was not valid JSON"}


def grade_answer(question: str, sources_block: str, answer: str, expect_section: str,
                 *, provider: str | None = None) -> dict:
    """Have the judge model grade one answer against its sources. Returns the parsed verdict."""
    from . import llm
    user = (f"QUESTION:\n{question}\n\nEXPECTED GOVERNING SECTION: {expect_section}\n\n"
            f"SOURCES:\n{sources_block}\n\nANSWER:\n{answer}\n\nGrade it per your instructions.")
    return _parse_judge(llm.chat(_JUDGE_SYSTEM, user, provider=provider))


def run_judged(provider: str | None = None, pass_score: float = 0.7) -> dict:
    """Generate an answer for each golden case and have a judge model grade faithfulness +
    citation correctness. Needs a generation model configured (GENERATION_PROVIDER); if generation
    isn't available, returns {"skipped": <reason>} rather than failing."""
    from . import agent
    from .retriever import render_sources

    cases = (yaml.safe_load(GOLDEN.read_text()) or {}).get("cases", [])
    graded, scores = [], []
    with _eval_corpus() as n:
        for case in cases:
            try:
                res = agent.ask(case["q"], provider=provider)
            except Exception as e:
                return {"skipped": f"generation unavailable ({e}). Configure GENERATION_PROVIDER "
                                   f"(see docs/LOCAL_MODELS.md) or pass provider=...", "corpus_chunks": n}
            answer = res.answer or "(the assistant asked for clarification instead of answering)"
            verdict = grade_answer(case["q"], render_sources(res.sources), answer,
                                   case["expect_section"], provider=provider)
            score = float(verdict.get("score", 0.0) or 0.0)
            scores.append(score)
            graded.append({"q": case["q"], "expect": case["expect_section"],
                           "score": score, "pass": score >= pass_score,
                           "cites_governing": bool(verdict.get("cites_governing")),
                           "grounded": bool(verdict.get("grounded")),
                           "no_fabrication": bool(verdict.get("no_fabrication")),
                           "notes": verdict.get("notes", "")})
    total = len(graded)
    return {
        "corpus_chunks": n,
        "total": total,
        "passed": sum(g["pass"] for g in graded),
        "mean_score": (sum(scores) / total) if total else 0.0,
        "results": graded,
    }


def _print(report: dict) -> None:
    print(f"Eval corpus: {report['corpus_chunks']} chunks  |  golden cases: {report['total']}")
    for r in report["results"]:
        mark = "✅" if r["pass"] else "❌"
        extra = []
        if "controlling_amendment" in r:
            extra.append(f"controlling={r['controlling_amendment']}")
        if "is_table" in r:
            extra.append(f"table={r['is_table']}")
        suffix = f"  ({', '.join(extra)})" if extra else ""
        print(f"  {mark} §{r['expect']:<12} retrieved={r['retrieved']}{suffix}  | {r['q']}")
    print(f"\nSafety: validator flags fabricated section: "
          f"{'✅' if report['safety_validator_flags_fabrication'] else '❌'}")
    print(f"Score: {report['passed']}/{report['total']} = {report['score']:.0%}")


def _print_judged(report: dict) -> None:
    if report.get("skipped"):
        print(f"LLM-judge grading skipped: {report['skipped']}")
        return
    print(f"LLM-judge grading ({report['total']} cases, corpus {report['corpus_chunks']} chunks):")
    for r in report["results"]:
        mark = "✅" if r["pass"] else "❌"
        flags = f"cites={r['cites_governing']} grounded={r['grounded']} no_fab={r['no_fabrication']}"
        print(f"  {mark} {r['score']:.2f}  §{r['expect']:<12} {flags}  | {r['q']}")
        if r["notes"]:
            print(f"       ↳ {r['notes']}")
    print(f"\nMean score: {report['mean_score']:.2f}  |  passed: {report['passed']}/{report['total']}")


if __name__ == "__main__":
    if "--judge" in sys.argv:
        # Generate + LLM-judge each golden answer (needs a model). Deterministic retrieval eval still runs.
        _print_judged(run_judged())
        sys.exit(0)
    rep = run()
    _print(rep)
    ok = rep["score"] >= 0.9 and rep["safety_validator_flags_fabrication"]
    sys.exit(0 if ok else 1)
