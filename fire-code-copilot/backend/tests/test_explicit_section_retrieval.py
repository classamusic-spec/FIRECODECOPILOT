from app.retriever import _explicit_section_matches


class FakeCollection:
    def __init__(self):
        self.lookups = []

    def get(self, *, where, include):
        self.lookups.append((where, include))
        if where == {"section": "29-250"}:
            return {
                "ids": ["chapter-541|9|0"],
                "documents": ["Sec. 29-250. Office of the State Fire Marshal."],
                "metadatas": [{"section": "29-250", "book": "CGS Chapter 541"}],
            }
        return {"ids": [], "documents": [], "metadatas": []}


def test_explicit_hyphenated_statute_section_is_a_retrieval_candidate():
    coll = FakeCollection()
    matches = _explicit_section_matches(coll, "What authority exists under Sec. 29-250?")

    assert coll.lookups == [({"section": "29-250"}, ["documents", "metadatas"])]
    assert matches == [{
        "id": "chapter-541|9|0",
        "text": "Sec. 29-250. Office of the State Fire Marshal.",
        "metadata": {"section": "29-250", "book": "CGS Chapter 541"},
    }]


def test_inline_hyphenated_number_is_not_mistaken_for_a_section():
    coll = FakeCollection()
    assert _explicit_section_matches(coll, "Use a 3-1 mixture ratio") == []
    assert coll.lookups == []
