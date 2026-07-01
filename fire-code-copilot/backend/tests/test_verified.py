"""Verified Answer Library: stable-id dedupe/edit, listing, and deletion (real local embeddings)."""
import pytest

from app.settings import settings
from app import feedback


@pytest.fixture
def temp_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "chroma_dir", str(tmp_path / "chroma"))
    monkeypatch.setattr(settings, "verified_collection", "tverified")


def test_reverify_edits_instead_of_duplicating(temp_verified):
    r1 = feedback.promote_verified(question="Sprinklers for an existing R-2?",
                                   corrected_answer="Yes — per CT §903.2.8.4.",
                                   governing_sections=["903.2.8.4"])
    r2 = feedback.promote_verified(question="  sprinklers for an existing r-2? ",  # same, reworded case/space
                                   corrected_answer="Yes — throughout, per CT §903.2.8.4.",
                                   governing_sections=["903.2.8.4", "903.2.8"])
    assert r1["id"] == r2["id"]                        # normalized question -> one stable entry
    items = feedback.list_verified()
    assert len(items) == 1
    assert items[0]["answer"].startswith("Yes — throughout")   # edited, not duplicated
    assert items[0]["sections"] == ["903.2.8.4", "903.2.8"]    # governing_sections preserved


def test_delete_removes_entry(temp_verified):
    feedback.promote_verified(question="Q?", corrected_answer="A.", governing_sections=[])
    [item] = feedback.list_verified()
    assert feedback.delete_verified(item["id"])["deleted"] is True
    assert feedback.list_verified() == []
