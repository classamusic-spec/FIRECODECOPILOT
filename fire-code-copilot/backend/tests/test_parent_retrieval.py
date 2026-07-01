"""Parent-document retrieval: long sections split into linked windows at ingest, and the
retriever stitches a matched window back into the whole section for the model — losslessly,
and without losing citation granularity."""
from app import retriever
from app.chunking import OVERLAP_WORDS, TARGET_WORDS, _split_long, chunk_pages
from app.reranker import Scored


class FakeColl:
    """A stand-in Chroma collection whose .get returns preset windows for any parent_id."""
    def __init__(self, docs, metas):
        self._docs, self._metas = docs, metas

    def get(self, where=None, include=None):
        return {"documents": self._docs, "metadatas": self._metas}


def _long_section_pieces():
    original = " ".join(f"w{i}" for i in range(TARGET_WORDS * 2 + 40))  # forces multiple windows
    pieces = _split_long(original)
    assert len(pieces) > 1, "test text must be long enough to split"
    return original, pieces


def test_split_section_gets_parent_linkage():
    # Heading on its own line, then enough prose body lines to exceed TARGET_WORDS twice over.
    body_lines = [f"Requirement {i} shall be provided throughout the entire building fire area."
                  for i in range(160)]
    page_text = "903.2 Automatic sprinkler systems.\n" + "\n".join(body_lines)
    pages = [(1, page_text)]
    chunks = chunk_pages(pages, {"book": "IFC", "edition": "2021", "is_amendment_doc": False})
    split = [c for c in chunks if c["metadata"].get("section") == "903.2"]
    assert len(split) > 1
    pids = {c["metadata"]["parent_id"] for c in split}
    assert len(pids) == 1                                   # all windows share one parent id
    parts = sorted(c["metadata"]["part"] for c in split)
    assert parts == list(range(len(split)))                 # contiguous part indices 0..n-1
    assert all(c["metadata"]["n_parts"] == len(split) for c in split)


def test_stitch_parent_reconstructs_original_losslessly():
    original, pieces = _long_section_pieces()
    metas = [{"part": i} for i in range(len(pieces))]
    stitched = retriever._stitch_parent(FakeColl(pieces, metas), "pid", OVERLAP_WORDS)
    assert stitched == original                             # overlap removed, nothing lost/duplicated


def test_expand_replaces_window_with_full_section_and_prunes_meta():
    original, pieces = _long_section_pieces()
    metas = [{"part": i} for i in range(len(pieces))]
    coll = FakeColl(pieces, metas)
    child = Scored({"text": pieces[1],
                    "metadata": {"section": "903.2", "page": 5, "book": "IFC",
                                 "parent_id": "pid", "part": 1, "n_parts": len(pieces)}}, 0.91)
    passthrough = Scored({"text": "a short whole section", "metadata": {"section": "907.2", "page": 6}}, 0.4)

    out = retriever._expand_to_parents([child, passthrough], coll)
    assert len(out) == 2
    expanded = out[0]
    assert expanded.chunk["text"] == original               # window -> full section
    assert expanded.score == 0.91                           # keeps the matched window's score
    m = expanded.chunk["metadata"]
    assert m["section"] == "903.2" and "parent_id" not in m and "part" not in m
    assert out[1].chunk["text"] == "a short whole section"  # non-split chunk untouched


def test_expand_dedupes_multiple_windows_of_same_parent():
    original, pieces = _long_section_pieces()
    metas = [{"part": i} for i in range(len(pieces))]
    coll = FakeColl(pieces, metas)
    base = {"section": "903.2", "page": 5, "parent_id": "pid", "n_parts": len(pieces)}
    scored = [Scored({"text": pieces[0], "metadata": {**base, "part": 0}}, 0.9),
              Scored({"text": pieces[1], "metadata": {**base, "part": 1}}, 0.8)]
    out = retriever._expand_to_parents(scored, coll)
    assert len(out) == 1                                    # collapsed to a single full section
    assert out[0].chunk["text"] == original
