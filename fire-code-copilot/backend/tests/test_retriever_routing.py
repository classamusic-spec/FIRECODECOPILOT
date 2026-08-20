from app.reranker import Scored
from app import retriever
from app.retriever import (
    _balance_code_families,
    _filter_mismatched_primary_editions,
    _merge_amendments,
)
from app.chunking import chunk_pages
from app.settings import settings


def _scored(book, score, *, source="x.pdf", amendment=False, code_family=None):
    metadata = {
        "book": book,
        "source": source,
        "is_amendment": amendment,
    }
    if code_family:
        metadata["code_family"] = code_family
    return Scored({"text": book, "metadata": metadata}, score)


def test_ifc_route_keeps_base_code_and_connecticut_amendment_in_final_sources():
    ranked = [
        _scored("CT Fire Safety Code — integrated Errata #1", 0.99,
                amendment=True, code_family="ifc"),
        _scored("CT Fire Safety Code amendments", 0.98,
                amendment=True, code_family="ifc"),
        _scored("NFPA 1 2021", 0.97),
        _scored("IFC (model)", 0.70, source="2021- INTERNATIONAL FIRE CODE.pdf"),
        _scored("IBC (model)", 0.60),
    ]
    result = _balance_code_families(
        ranked,
        "new construction [2021 International Fire Code Connecticut State Fire Safety Code Part III]",
        limit=4,
    )
    assert result[0].chunk["metadata"]["book"] == "IFC (model)"
    assert "CT Fire Safety Code" in result[1].chunk["metadata"]["book"]


def test_explicit_amendment_query_puts_connecticut_amendment_before_base_book():
    ranked = [
        _scored("NFPA 101 2021", 0.95),
        _scored("CT Fire Safety Code — integrated Errata #1", 0.90,
                amendment=True, code_family="nfpa:101"),
    ]
    result = _balance_code_families(
        ranked,
        "Connecticut Part IV amendments to NFPA 101 Life Safety Code 2021",
        limit=2,
    )
    assert "CT Fire Safety Code" in result[0].chunk["metadata"]["book"]
    assert result[1].chunk["metadata"]["book"].startswith("NFPA 101")


def test_nfpa_1_family_does_not_mistake_nfpa_101_for_requested_base():
    ranked = [_scored("NFPA 101 2021", 0.99), _scored("NFPA 1 2021", 0.80)]
    result = _balance_code_families(ranked, "NFPA 1 Fire Code 2021 hot work", limit=2)
    assert result[0].chunk["metadata"]["book"] == "NFPA 1 2021"


def test_balancing_recognizes_amendment_metadata_emitted_by_chunker():
    amendment_chunk = chunk_pages(
        [(1, "101.1 Connecticut amendment\nThis amendment text applies to the section and controls the requirement.")],
        {"book": "CT Fire Safety Code amendments", "edition": "2022",
         "is_amendment_doc": True},
    )[0]
    amendment_chunk["metadata"]["source"] = "ct-amendments.pdf"
    ranked = [
        Scored(amendment_chunk, 0.9),
        _scored("IFC (model)", 0.8, source="2021- INTERNATIONAL FIRE CODE.pdf"),
    ]
    result = _balance_code_families(ranked, "2021 International Fire Code Part III", limit=2)
    assert result[1].chunk["metadata"]["book"] == "CT Fire Safety Code amendments"


def test_historical_edition_does_not_force_active_base_or_amendment_order():
    ranked = [
        _scored("Other historical source", 0.99),
        _scored("IFC (model)", 0.70, source="2021- INTERNATIONAL FIRE CODE.pdf"),
    ]
    result = _balance_code_families(ranked, "Compare 2018 IFC Section 903.2.8", limit=2)
    assert result == ranked


def test_mixed_ifc_editions_still_preserve_active_connecticut_amendment():
    ranked = [
        _scored("Other historical source", 0.99),
        _scored("IFC (model)", 0.70, source="2021- INTERNATIONAL FIRE CODE.pdf"),
        _scored("CT Fire Safety Code amendments", 0.60,
                amendment=True, code_family="ifc"),
    ]
    result = _balance_code_families(ranked, "Compare 2018 IFC with 2021 IFC", limit=3)
    assert result[0].chunk["metadata"]["book"] == "IFC (model)"
    assert "CT Fire Safety Code" in result[1].chunk["metadata"]["book"]


def test_secondary_nfpa_edition_does_not_disable_active_ifc_amendment():
    ranked = [
        _scored("Other source", 0.99),
        _scored("IFC (model)", 0.70, source="2021- INTERNATIONAL FIRE CODE.pdf"),
        _scored("CT Fire Safety Code amendments", 0.60,
                amendment=True, code_family="ifc"),
    ]
    query = "Under the 2021 IFC, use the 2018 edition of NFPA 13"
    result = _balance_code_families(ranked, query, limit=3)
    assert result[0].chunk["metadata"]["book"] == "IFC (model)"
    assert "CT Fire Safety Code" in result[1].chunk["metadata"]["book"]


def test_amendment_merge_excludes_historical_family_in_mixed_query():
    chunks = [
        {"text": "IFC base", "metadata": {
            "book": "IFC (model)", "edition": "2021", "section": "903.2.8",
            "is_amendment": False}},
        {"text": "NFPA 101 base", "metadata": {
            "book": "NFPA 101", "edition": "2021", "section": "31.1.1",
            "is_amendment": False}},
    ]

    filtered = _filter_mismatched_primary_editions(
        chunks, "Compare 2018 IFC with NFPA 101"
    )
    assert [c["metadata"]["book"] for c in filtered] == ["NFPA 101"]

    class Coll:
        def get(self, **_kwargs):
            return {
                "documents": ["IFC amendment", "NFPA amendment"],
                "metadatas": [
                    {"book": "CT Fire Safety Code", "section": "903.2.8",
                     "is_amendment": True, "code_family": "ifc"},
                    {"book": "CT Fire Safety Code", "section": "31.1.1",
                     "is_amendment": True, "code_family": "nfpa:101"},
                ],
            }

    merged = _merge_amendments(chunks, Coll(), "Compare 2018 IFC with NFPA 101")
    controlling = [c for c in merged if c["metadata"].get("controlling")]
    assert [c["metadata"]["section"] for c in controlling] == ["31.1.1"]


def test_amendment_merge_rejects_same_section_from_wrong_csfsc_part():
    chunks = [{"text": "NFPA 101 rule", "metadata": {
        "book": "NFPA 101", "edition": "2021", "section": "7.1",
        "is_amendment": False}}]

    class Coll:
        def get(self, **_kwargs):
            return {
                "documents": ["Part III IFC rule", "Part IV NFPA 101 rule"],
                "metadatas": [
                    {"book": "CSFSC Part III IFC amendments", "section": "7.1",
                     "is_amendment": True, "code_family": "ifc"},
                    {"book": "CSFSC Part IV NFPA 101 amendments", "section": "7.1",
                     "is_amendment": True, "code_family": "nfpa:101"},
                ],
            }

    merged = _merge_amendments(chunks, Coll(), "NFPA 101 Section 7.1")
    controlling = [c for c in merged if c["metadata"].get("controlling")]
    assert [c["text"] for c in controlling] == ["Part IV NFPA 101 rule"]


def test_amendment_merge_does_not_cross_from_nfpa_13_by_section_number():
    chunks = [{"text": "NFPA 13 base", "metadata": {
        "book": "NFPA 13", "section": "903.2.8", "is_amendment": False}}]

    class Coll:
        def get(self, **_kwargs):
            raise AssertionError("no controlling CT family exists for this source")

    assert _merge_amendments(chunks, Coll(), "NFPA 13 Section 903.2.8") == chunks


def test_historical_edition_skips_current_amendments_and_verified_answers(monkeypatch):
    class Coll:
        name = "active"

        def query(self, **_kwargs):
            return {
                "ids": [["ifc"]],
                "documents": [["IFC section text"]],
                "metadatas": [[{"book": "IFC (model)", "section": "903.2.8"}]],
            }

    coll = Coll()
    monkeypatch.setattr(retriever, "_client", lambda: type(
        "Client", (), {"get_collection": lambda *_args: coll})())
    monkeypatch.setattr(retriever.embeddings, "embed", lambda *_args, **_kwargs: [[0.0]])
    monkeypatch.setattr(retriever, "_verified_matches", lambda *_args, **_kwargs: (
        (_ for _ in ()).throw(AssertionError("current verified answer must not be loaded"))))
    monkeypatch.setattr(retriever, "_merge_amendments", lambda *_args, **_kwargs: (
        (_ for _ in ()).throw(AssertionError("current amendments must not be merged"))))
    monkeypatch.setattr(settings, "use_reranker", False)
    monkeypatch.setattr(settings, "use_hybrid", False)
    monkeypatch.setattr(settings, "parent_retrieval", False)

    result = retriever.retrieve_scored("Compare 2018 IFC Section 903.2.8")
    assert result and result[0].chunk["metadata"]["book"] == "IFC (model)"
