"""Per-edition collection routing: each book goes to its books.yaml `collection` (default active)."""
from pathlib import Path

from app import ingest
from app.settings import settings


def test_collection_defaults_to_active():
    meta = ingest._meta_for(Path("2021 IFC.pdf"), manifest={})
    assert meta["collection"] == settings.active_collection


def test_collection_from_manifest():
    manifest = {
        "2021 IFC.pdf": {"book": "IFC", "edition": "2021", "collection": "csfsc_2022"},
        "2024 IFC.pdf": {"book": "IFC", "edition": "2024", "collection": "csfsc_2026"},
    }
    assert ingest._meta_for(Path("2024 IFC.pdf"), manifest)["collection"] == "csfsc_2026"
    assert ingest._meta_for(Path("2021 IFC.pdf"), manifest)["edition"] == "2021"


def test_amendment_doc_heuristic_still_applies():
    meta = ingest._meta_for(Path("CT-amendments-2022.pdf"), manifest={})
    assert meta["is_amendment_doc"] is True
