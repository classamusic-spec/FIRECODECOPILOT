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


if __name__ == "__main__":
    rep = run()
    _print(rep)
    ok = rep["score"] >= 0.9 and rep["safety_validator_flags_fabrication"]
    sys.exit(0 if ok else 1)
