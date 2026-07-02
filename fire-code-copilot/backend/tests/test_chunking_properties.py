"""Property tests (Hypothesis) for chunking invariants — the guarantees every other layer
leans on, checked across generated inputs instead of a handful of examples:
  1. Window splitting is LOSSLESS under parent stitching (drop OVERLAP_WORDS per window).
  2. Every emitted chunk carries a section and an in-range page.
  3. Split sections have a shared parent_id and contiguous part indices.
  4. Chunking is deterministic.
"""
from hypothesis import given, settings as hsettings, strategies as st

from app.chunking import OVERLAP_WORDS, _split_long, chunk_pages

hsettings.register_profile("ci", max_examples=40, deadline=None)
hsettings.load_profile("ci")


def _stitch(pieces: list[str]) -> str:
    """Reference implementation of retriever._stitch_parent's overlap removal."""
    words = pieces[0].split()
    for p in pieces[1:]:
        words += p.split()[OVERLAP_WORDS:]
    return " ".join(words)


@given(n_words=st.integers(min_value=1, max_value=4000))
def test_split_stitch_roundtrip_is_lossless(n_words):
    text = " ".join(f"w{i}" for i in range(n_words))
    pieces = _split_long(text)
    assert pieces, "splitting must never produce zero pieces"
    assert _stitch(pieces) == text


@given(n_words=st.integers(min_value=1, max_value=4000))
def test_every_piece_overlaps_enough_to_stitch(n_words):
    text = " ".join(f"w{i}" for i in range(n_words))
    pieces = _split_long(text)
    for p in pieces:
        assert len(p.split()) > OVERLAP_WORDS or len(pieces) == 1, \
            "a window smaller than the overlap would vanish when stitched"


# A generated "code page": a few numbered sections, each with a prose body of varying length.
_section_nums = st.lists(st.integers(min_value=901, max_value=999), min_size=1, max_size=4,
                         unique=True)
_body_len = st.integers(min_value=8, max_value=1200)


@given(nums=_section_nums, body_lens=st.data())
def test_every_chunk_has_section_and_valid_page(nums, body_lens):
    lines = []
    for n in sorted(nums):
        body_words = body_lens.draw(_body_len)
        lines.append(f"{n}.2 Requirements for item {n}.")
        lines.append(" ".join(
            f"provision{i} shall be maintained accessible and operable at all times."
            for i in range(max(1, body_words // 10))))
    pages = [(1, "\n".join(lines))]
    chunks = chunk_pages(pages, {"book": "IFC", "edition": "2021", "is_amendment_doc": False})
    assert chunks
    for c in chunks:
        m = c["metadata"]
        assert m["section"], "chunk lost its section"
        assert m["page"] == 1
        assert c["text"].strip(), "empty chunk emitted"


@given(nums=_section_nums)
def test_chunking_is_deterministic(nums):
    lines = []
    for n in sorted(nums):
        lines.append(f"{n}.2 Requirements.")
        lines.append("An automatic system shall be provided throughout the building fire area.")
    pages = [(1, "\n".join(lines))]
    meta = {"book": "IFC", "edition": "2021", "is_amendment_doc": False}
    assert chunk_pages(pages, meta) == chunk_pages(pages, meta)


def test_split_sections_share_parent_and_have_contiguous_parts():
    body = " ".join(
        f"requirement {i} shall be provided and maintained in an operable condition always."
        for i in range(200))
    pages = [(1, "903.2 Automatic sprinkler systems.\n" + body)]
    chunks = chunk_pages(pages, {"book": "IFC", "edition": "2021", "is_amendment_doc": False})
    split = [c for c in chunks if c["metadata"].get("parent_id")]
    assert len(split) > 1
    assert len({c["metadata"]["parent_id"] for c in split}) == 1
    assert sorted(c["metadata"]["part"] for c in split) == list(range(len(split)))
