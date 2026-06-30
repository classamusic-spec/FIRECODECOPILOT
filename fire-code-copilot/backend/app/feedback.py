"""The learning loop — curated memory, not model retraining (see ARCHITECTURE §5).

Level 1: every answer can be rated 👍/👎 with an optional correction, stored in SQLite.
Level 2: a confirmed/corrected answer is promoted into the Verified Answer Library (its own
         Chroma collection). Future similar questions retrieve it, labeled [VERIFIED], via
         retriever._verified_matches — so confirmed rulings compound.
Level 3: a review queue surfaces 👎 and low-confidence questions for the marshal to revisit.

Everything here is local: SQLite on disk + a local Chroma collection. Nothing leaves the machine.
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

from .settings import settings
from . import embeddings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    question        TEXT NOT NULL,
    building_context TEXT,
    answer          TEXT,
    rating          TEXT,             -- 'up' | 'down'
    note            TEXT,             -- optional "correct this"
    sources_json    TEXT,             -- the source chunks shown
    low_confidence  INTEGER DEFAULT 0 -- 1 if flagged for the review queue
);
"""


def _conn() -> sqlite3.Connection:
    Path(settings.feedback_db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.feedback_db)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def _now() -> str:
    # Imported here (not module top) so importing this module never trips the no-clock rules
    # used elsewhere; this is a real runtime timestamp for the feedback row.
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_feedback(*, question: str, answer: str, rating: str, note: str = "",
                    building_context: str = "", sources: list[dict] | None = None,
                    low_confidence: bool = False) -> dict:
    """Store a 👍/👎 (+ optional correction). A 👎 or low-confidence answer enters the review queue."""
    rating = rating.lower().strip()
    flagged = 1 if (low_confidence or rating == "down") else 0
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO feedback (created_at, question, building_context, answer, rating, note, "
            "sources_json, low_confidence) VALUES (?,?,?,?,?,?,?,?)",
            (_now(), question, building_context, answer, rating, note,
             json.dumps(sources or []), flagged),
        )
        return {"id": cur.lastrowid, "queued_for_review": bool(flagged)}


def promote_verified(*, question: str, corrected_answer: str,
                     governing_sections: list[str] | None = None, edition: str = "") -> dict:
    """Embed the QUESTION (so similar future questions match) and store the confirmed answer in
    the Verified Answer Library collection. The stored document is what the agent will be shown."""
    import chromadb
    sections = governing_sections or []
    client = chromadb.PersistentClient(path=settings.chroma_dir)
    vcoll = client.get_or_create_collection(settings.verified_collection)

    # Match on question similarity; show the corrected answer (with the question for context).
    qvec = embeddings.embed([question], input_type="query")[0]
    doc = f"Q: {question}\nVERIFIED ANSWER: {corrected_answer}"
    vid = f"verified-{abs(hash((question, corrected_answer)))}"
    meta = {
        "verified": True,
        "book": "VERIFIED",
        "edition": edition or settings.active_collection,
        "section": ", ".join(sections) if sections else "(verified answer)",
        "verified_at": _now(),
    }
    vcoll.upsert(ids=[vid], documents=[doc], metadatas=[meta], embeddings=[qvec])
    return {"id": vid, "collection": settings.verified_collection, "sections": sections}


def review_queue(limit: int = 50) -> list[dict]:
    """👎 and low-confidence questions the marshal should revisit (gap detection, Level 3)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, created_at, question, building_context, answer, rating, note "
            "FROM feedback WHERE low_confidence = 1 OR rating = 'down' "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
