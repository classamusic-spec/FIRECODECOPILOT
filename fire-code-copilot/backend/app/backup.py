"""Backup / restore the LEARNING data — the compounding asset that makes *your* copy of the
tool smarter than a fresh install: the Verified Answer Library, the feedback DB (👍/👎 +
review queue), the books manifest, and the code-cycle config.

    python -m app.backup                      # write data/backups/fcc-backup-<stamp>.zip
    python -m app.backup --out ~/Backups      # write it somewhere else (e.g. a synced folder)
    python -m app.backup --restore FILE.zip   # merge a backup into this install
    python -m app.backup --restore FILE.zip --replace-feedback   # also overwrite feedback.sqlite

Design notes:
  - Verified answers are exported as JSON (question/answer/sections/edition) and RE-EMBEDDED on
    restore via promote_verified — so a backup survives switching embedding models, and restoring
    is a MERGE (stable ids dedupe; existing entries are refreshed, never duplicated).
  - feedback.sqlite is copied verbatim, but only onto a missing DB unless --replace-feedback:
    merging two histories is not meaningful, and silently clobbering a newer one would be worse.
  - The vector store for the code books is NOT backed up — it's derived data, rebuilt any time
    with `python -m app.ingest`, and would bloat the zip by gigabytes.
  - Backups may contain snippets of code text inside your verified answers: they live under the
    gitignored data/ dir by default and must never be committed or shared.
"""
from __future__ import annotations

import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from .settings import settings

_VERIFIED_JSON = "verified.json"
_FEEDBACK_DB = "feedback.sqlite"
_BOOKS_YAML = "books.yaml"
_CYCLES_YAML = "code_cycles.yaml"
_MANIFEST = "manifest.json"


def backup(out_dir: str | None = None) -> Path:
    """Write a dated backup zip. Returns its path."""
    from . import feedback

    dest_dir = Path(out_dir).expanduser() if out_dir else Path(settings.data_dir) / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"fcc-backup-{stamp}.zip"

    verified = feedback.list_verified(limit=100_000)
    fb_db = Path(settings.feedback_db)
    books_yaml = Path(settings.code_books_dir).expanduser() / _BOOKS_YAML
    cycles_yaml = Path(settings.code_cycles_config)

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(_VERIFIED_JSON, json.dumps(verified, indent=2, ensure_ascii=False))
        if fb_db.is_file():
            z.write(fb_db, _FEEDBACK_DB)
        if books_yaml.is_file():
            z.write(books_yaml, _BOOKS_YAML)
        if cycles_yaml.is_file():
            z.write(cycles_yaml, _CYCLES_YAML)
        z.writestr(_MANIFEST, json.dumps({
            "created": stamp,
            "verified_answers": len(verified),
            "has_feedback_db": fb_db.is_file(),
            "has_books_manifest": books_yaml.is_file(),
            "has_code_cycles": cycles_yaml.is_file(),
            "active_collection": settings.active_collection,
        }, indent=2))
    return dest


def restore(zip_path: str, replace_feedback: bool = False) -> dict:
    """Merge a backup into this install. Returns a summary of what was restored."""
    from . import feedback

    src = Path(zip_path).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"No backup at {src}")
    summary = {"verified_restored": 0, "feedback_db": "kept-existing",
               "books_manifest": "absent-in-backup", "code_cycles": "absent-in-backup"}

    with zipfile.ZipFile(src) as z:
        names = set(z.namelist())

        # Restore feedback before re-promoting verified answers; promotion itself creates the
        # SQLite store, which must not make a genuinely fresh install look "existing".
        fb_db = Path(settings.feedback_db)
        if _FEEDBACK_DB in names and (replace_feedback or not fb_db.is_file()):
            fb_db.parent.mkdir(parents=True, exist_ok=True)
            with z.open(_FEEDBACK_DB) as f, open(fb_db, "wb") as out:
                shutil.copyfileobj(f, out)
            summary["feedback_db"] = "restored"

        if _VERIFIED_JSON in names:
            entries = json.loads(z.read(_VERIFIED_JSON).decode("utf-8"))
            for e in entries:
                q = (e.get("question") or "").strip()
                a = (e.get("answer") or "").strip()
                if not q or not a:
                    continue
                feedback.promote_verified(question=q, corrected_answer=a,
                                          governing_sections=e.get("sections") or [],
                                          edition=e.get("edition") or "")
                summary["verified_restored"] += 1

        for name, target, key in (
            (_BOOKS_YAML, Path(settings.code_books_dir).expanduser() / _BOOKS_YAML, "books_manifest"),
            (_CYCLES_YAML, Path(settings.code_cycles_config), "code_cycles"),
        ):
            if name not in names:
                continue
            if target.is_file():
                summary[key] = "kept-existing"        # never clobber a possibly-newer config
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as f, open(target, "wb") as out:
                shutil.copyfileobj(f, out)
            summary[key] = "restored"
    return summary


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--restore" in args:
        zp = args[args.index("--restore") + 1]
        s = restore(zp, replace_feedback="--replace-feedback" in args)
        print("Restored:", json.dumps(s, indent=2))
    else:
        out = None
        if "--out" in args:
            out = args[args.index("--out") + 1]
        path = backup(out)
        print(f"✅ Backup written: {path}")
        print("   Keep it somewhere safe (it holds your verified answers + feedback history).")
