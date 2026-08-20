from app.reranker import Scored
from app.retriever import _balance_code_families


def _scored(book, score, *, source="x.pdf", amendment=False):
    return Scored({
        "text": book,
        "metadata": {
            "book": book,
            "source": source,
            "is_amendment_doc": amendment,
        },
    }, score)


def test_ifc_route_keeps_base_code_and_connecticut_amendment_in_final_sources():
    ranked = [
        _scored("CT Fire Safety Code — integrated Errata #1", 0.99, amendment=True),
        _scored("CT Fire Safety Code amendments", 0.98, amendment=True),
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
        _scored("CT Fire Safety Code — integrated Errata #1", 0.90, amendment=True),
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
