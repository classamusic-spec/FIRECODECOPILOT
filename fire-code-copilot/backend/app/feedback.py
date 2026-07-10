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
CREATE TABLE IF NOT EXISTS verified_answers (
    id TEXT PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL, edition TEXT NOT NULL,
    citations_json TEXT NOT NULL, verified_by TEXT NOT NULL, verified_at TEXT NOT NULL,
    question_embedding TEXT NOT NULL
);

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
    conn.executescript(_SCHEMA)
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
    # Stable ID from the NORMALIZED question, so re-verifying the same question EDITS (replaces)
    # the entry instead of piling up near-duplicates on every reword.
    vid = _verified_id(question)
    meta = {
        "verified": True,
        "book": "VERIFIED",
        "edition": edition or settings.active_collection,
        "section": ", ".join(sections) if sections else "(verified answer)",
        "question": question,
        "answer": corrected_answer,
        "sections_json": json.dumps(sections),
        "verified_at": _now(),
    }
    vcoll.upsert(ids=[vid], documents=[doc], metadatas=meta and [meta], embeddings=[qvec])
    with _conn() as conn:
        conn.execute("INSERT OR REPLACE INTO verified_answers (id,question,answer,edition,citations_json,verified_by,verified_at,question_embedding) VALUES (?,?,?,?,?,?,?,?)",
                     (vid, question, corrected_answer, meta["edition"], json.dumps(sections), "marshal", meta["verified_at"], json.dumps(qvec)))
    return {"id": vid, "collection": settings.verified_collection, "sections": sections}


def _verified_id(question: str) -> str:
    """Deterministic id keyed on the normalized question (dedupe/edit anchor)."""
    import hashlib as _h
    norm = " ".join((question or "").lower().split())
    return "verified-" + _h.md5(norm.encode("utf-8")).hexdigest()[:16]


def _verified_collection():
    import chromadb
    return chromadb.PersistentClient(path=settings.chroma_dir).get_or_create_collection(
        settings.verified_collection)


def list_verified(limit: int = 200) -> list[dict]:
    """All confirmed answers in the Verified Answer Library, for review/management."""
    try:
        got = _verified_collection().get(include=["metadatas"])
    except Exception:
        return []
    out = []
    for vid, m in zip(got.get("ids", []) or [], got.get("metadatas", []) or []):
        m = m or {}
        try:
            secs = json.loads(m.get("sections_json", "[]"))
        except (ValueError, TypeError):
            secs = []
        out.append({"id": vid, "question": m.get("question", ""), "answer": m.get("answer", ""),
                    "sections": secs, "edition": m.get("edition", ""),
                    "verified_at": m.get("verified_at", "")})
    out.sort(key=lambda v: v.get("verified_at", ""), reverse=True)
    return out[:limit]


def delete_verified(vid: str) -> dict:
    """Remove a verified answer (a wrong/stale one shouldn't keep surfacing as [VERIFIED])."""
    try:
        _verified_collection().delete(ids=[vid])
        return {"deleted": True, "id": vid}
    except Exception as e:
        return {"deleted": False, "id": vid, "error": str(e)}


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


def find_precedent(question: str, edition: str) -> dict | None:
    """SQLite semantic match used as a labeled precedent only; normal retrieval/validation still run."""
    import math
    q = embeddings.embed([question], input_type="query")[0]
    best = None
    with _conn() as conn:
        for row in conn.execute("SELECT * FROM verified_answers WHERE edition=?", (edition,)).fetchall():
            try: v = json.loads(row["question_embedding"])
            except Exception: continue
            dot = sum(float(a)*float(b) for a,b in zip(q,v)); nq=math.sqrt(sum(float(a)*float(a) for a in q)); nv=math.sqrt(sum(float(b)*float(b) for b in v))
            score = dot / max(nq*nv, 1e-9)
            if score >= settings.verified_match_threshold and (best is None or score > best["score"]):
                best = {"id": row["id"], "question": row["question"], "answer": row["answer"], "edition": row["edition"], "verified_by": row["verified_by"], "verified_at": row["verified_at"], "score": score}
    return best
