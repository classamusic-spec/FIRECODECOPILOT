"""Backup/restore of the learning data: verified answers round-trip (re-embedded on restore,
deduped by stable id), feedback DB restored only when missing, configs never clobbered."""
import pytest

from app import backup, feedback
from app.settings import settings


@pytest.fixture
def learning_env(tmp_path, monkeypatch):
    """Isolated data dir + verified store with one confirmed answer and one feedback row."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "chroma_dir", str(tmp_path / "data" / "chroma"))
    monkeypatch.setattr(settings, "feedback_db", str(tmp_path / "data" / "feedback.sqlite"))
    monkeypatch.setattr(settings, "verified_collection", "bk_verified")
    monkeypatch.setattr(settings, "active_collection", "bk_edition")
    monkeypatch.setattr(settings, "code_books_dir", str(tmp_path / "books"))
    monkeypatch.setattr(settings, "code_cycles_config", str(tmp_path / "config" / "code_cycles.yaml"))
    (tmp_path / "books").mkdir()
    # feedback._conn caches the sqlite connection module-globally — reset for isolation.
    if getattr(feedback, "_db", None) is not None:
        feedback._db = None
    feedback.record_feedback(question="q1", answer="a1", rating="down", note="fix this")
    feedback.promote_verified(question="Are sprinklers required for Group R?",
                              corrected_answer="Yes — per 903.2.8, throughout Group R fire areas.",
                              governing_sections=["903.2.8"], edition="bk_edition")
    return tmp_path


def test_backup_restore_roundtrip(learning_env, tmp_path, monkeypatch):
    zip_path = backup.backup()
    assert zip_path.is_file() and zip_path.suffix == ".zip"

    # Wipe the learning data (fresh-install simulation) and restore into it.
    fresh = tmp_path / "fresh"
    monkeypatch.setattr(settings, "data_dir", str(fresh / "data"))
    monkeypatch.setattr(settings, "chroma_dir", str(fresh / "data" / "chroma"))
    monkeypatch.setattr(settings, "feedback_db", str(fresh / "data" / "feedback.sqlite"))
    if getattr(feedback, "_db", None) is not None:
        feedback._db = None

    summary = backup.restore(str(zip_path))
    assert summary["verified_restored"] == 1
    assert summary["feedback_db"] == "restored"

    items = feedback.list_verified()
    assert len(items) == 1
    assert items[0]["sections"] == ["903.2.8"]
    assert "903.2.8" in items[0]["answer"]

    # Restoring AGAIN merges (stable ids) — no duplicates, feedback kept.
    summary2 = backup.restore(str(zip_path))
    assert summary2["feedback_db"] == "kept-existing"
    assert len(feedback.list_verified()) == 1
