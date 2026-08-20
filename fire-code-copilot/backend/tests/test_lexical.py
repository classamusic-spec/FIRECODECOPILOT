"""BM25 lexical channel: exact-token lookups (section numbers, standard names) rank first."""
from concurrent.futures import ThreadPoolExecutor

from app import lexical


class FakeColl:
    """Minimal stand-in for a Chroma collection (BM25 only needs name/count/get)."""
    name = "t"

    def __init__(self, docs, metas=None):
        self._docs = docs
        self._ids = [str(i) for i in range(len(docs))]
        self._metas = metas or [{} for _ in docs]

    def count(self):
        return len(self._docs)

    def get(self, include=None):
        return {"ids": self._ids, "documents": self._docs, "metadatas": self._metas}


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


def test_book_metadata_makes_explicit_nfpa_book_searchable():
    docs = [
        "Existing apartment occupancy requirements.",
        "Generic fire safety requirements.",
        "Unrelated building permit checklist.",
    ]
    metas = [
        {"book": "NFPA 101 2021 — Life Safety Code, Chapter 31", "source": "nfpa101/ch31.pdf"},
        {"book": "Unrelated local checklist", "source": "checklist.pdf"},
        {"book": "Another unrelated source", "source": "permits.pdf"},
    ]
    res = lexical.search(FakeColl(docs, metas), "NFPA 101", k=2)
    assert res and res[0]["metadata"]["book"].startswith("NFPA 101")


def test_large_chroma_collection_is_loaded_in_pages():
    class FakePagedColl(FakeColl):
        name = "large-paged"

        def get(self, include=None, limit=None, offset=None):
            assert limit is not None, "large collections must not use an unbounded Chroma get()"
            start = offset or 0
            stop = start + limit
            return {
                "ids": self._ids[start:stop],
                "documents": self._docs[start:stop],
                "metadatas": self._metas[start:stop],
            }

    docs = ["generic requirements"] * 5000 + ["unique kitchen exhaust requirement"]
    metas = [{} for _ in docs]
    result = lexical.search(FakePagedColl(docs, metas), "unique kitchen exhaust", k=1)
    assert result and result[0]["text"] == "unique kitchen exhaust requirement"


def test_same_count_external_store_revision_rebuilds_metadata_index(monkeypatch):
    revisions = iter([(1, 0), (2, 0)])
    monkeypatch.setattr(lexical, "_store_revision", lambda: next(revisions))

    class CountingColl(FakeColl):
        name = "same-count-revision"

        def __init__(self):
            super().__init__(["requirements"], [{"book": "NFPA 1"}])
            self.get_calls = 0

        def get(self, include=None):
            self.get_calls += 1
            return super().get(include=include)

    coll = CountingColl()
    lexical._index_for(coll)
    lexical._index_for(coll)
    assert coll.get_calls == 2
    assert len(lexical._cache) == 1


def test_concurrent_first_reads_build_one_cache_generation(monkeypatch):
    monkeypatch.setattr(lexical, "_store_revision", lambda: (1, 0))

    class CountingColl(FakeColl):
        name = "concurrent"

        def __init__(self):
            super().__init__(["NFPA 101 requirement"], [{"book": "NFPA 101"}])
            self.get_calls = 0

        def get(self, include=None):
            self.get_calls += 1
            return super().get(include=include)

    coll = CountingColl()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _index: lexical._index_for(coll), range(4)))
    assert coll.get_calls == 1
    assert all(result is results[0] for result in results)
