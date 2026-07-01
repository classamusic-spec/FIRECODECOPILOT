"""On-disk cache for text embeddings, keyed by content hash, so identical text is never
re-embedded. This turns a re-ingest (or a repeated query) from a model run into a dict lookup.

Local + private, like everything else: the cache lives under `data/` (gitignored) exactly like
the vector store, and it holds vectors derived from copyrighted code text — it must NEVER be
committed. Vectors are stored as packed float32 (via the stdlib `array` module) so the file stays
compact and there's no numpy dependency at import time.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from array import array
from pathlib import Path

from .settings import settings

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = Path(settings.data_dir) / "embed_cache.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(path), check_same_thread=False)
        _conn.execute("CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, vec BLOB NOT NULL)")
        _conn.commit()
    return _conn


def _key(text: str, namespace: str) -> str:
    """Hash of (namespace, text). The namespace carries the model id + input_type, so changing the
    embedding model or the query/passage role invalidates cache entries automatically."""
    h = hashlib.sha256()
    h.update(namespace.encode("utf-8"))
    h.update(b"\x00")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


def get_many(texts: list[str], namespace: str) -> dict[int, list[float]]:
    """Return {index -> vector} for the texts already present in the cache."""
    if not texts:
        return {}
    hits: dict[int, list[float]] = {}
    with _lock:
        db = _db()
        for i, t in enumerate(texts):
            row = db.execute("SELECT vec FROM embeddings WHERE key=?", (_key(t, namespace),)).fetchone()
            if row is not None:
                a = array("f")
                a.frombytes(row[0])
                hits[i] = a.tolist()
    return hits


def put_many(pairs: list[tuple[str, list[float]]], namespace: str) -> None:
    """Store (text, vector) pairs. Idempotent — re-storing the same text is a no-op overwrite."""
    if not pairs:
        return
    with _lock:
        db = _db()
        db.executemany(
            "INSERT OR REPLACE INTO embeddings (key, vec) VALUES (?, ?)",
            [(_key(t, namespace), array("f", v).tobytes()) for t, v in pairs],
        )
        db.commit()


def clear() -> None:
    """Drop every cached vector (e.g. after switching embedding models on the same data dir)."""
    with _lock:
        db = _db()
        db.execute("DELETE FROM embeddings")
        db.commit()


def _reset_for_tests() -> None:
    """Close the connection so a test can point `data_dir` at a fresh tmp dir."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
