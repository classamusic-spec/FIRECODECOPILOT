"""BM25 lexical channel: exact-token lookups (section numbers, standard names) rank first."""
from app import lexical


class FakeColl:
    """Minimal stand-in for a Chroma collection (BM25 only needs name/count/get)."""
    name = "t"

    def __init__(self, docs):
        self._docs = docs
        self._ids = [str(i) for i in range(len(docs))]

    def count(self):
        return len(self._docs)

    def get(self, include=None):
        return {"ids": self._ids, "documents": self._docs, "metadatas": [{} for _ in self._docs]}


DOCS = [
    "903.2.8.1 Group R-2. Sprinklers where over three stories or 16 dwelling units.",
    "907.2.9 Group R-2. A manual fire alarm system shall be installed.",
    "Table 903.2.11.6 lists additional required suppression system locations.",
    "Means of egress width and occupant load factors for assembly occupancies.",
]


def setup_function(_):
    lexical.reset_cache()


def test_exact_section_number_ranks_first():
    res = lexical.search(FakeColl(DOCS), "903.2.11.6", k=3)
    assert res and "903.2.11.6" in res[0]["text"]


def test_standard_name_match():
    res = lexical.search(FakeColl(DOCS), "manual fire alarm Group R-2", k=3)
    assert res and "907.2.9" in res[0]["text"]


def test_tokenizer_keeps_dotted_sections():
    assert "903.2.8" in lexical._tokenize("see 903.2.8 group r")


def test_no_match_returns_empty():
    assert lexical.search(FakeColl(DOCS), "zzzzqqq nonexistent", k=3) == []
