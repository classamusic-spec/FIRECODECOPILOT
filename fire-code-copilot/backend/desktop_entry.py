"""Frozen entry point for the standalone desktop app (PyInstaller sidecar).

This is what runs *inside* the bundled `.app` — a self-contained executable that starts the
same FastAPI server the browser/dev flow uses, with no repo or venv on disk.

Port comes from argv[1] (or FCC_API_PORT, default 8000). All *mutable* paths — the vector
store, feedback DB, ingested data, and the user's code-books folder — are injected by the
desktop shell via environment variables (DATA_DIR / CHROMA_DIR / FEEDBACK_DB / CODE_BOOKS_DIR),
so nothing is ever written inside the read-only, code-signed bundle.

Model *weights* (BGE-M3 embedder, reranker) are not frozen in — they download once to
~/.cache/huggingface on first use. This ships the code that runs them.
"""
from __future__ import annotations

import os
import sys


def _port() -> int:
    if len(sys.argv) > 1:
        try:
            return int(sys.argv[1])
        except ValueError:
            pass
    return int(os.environ.get("FCC_API_PORT", "8000"))


def main() -> None:
    # Import lazily so a --version/help style invocation stays cheap and import errors surface
    # with a clear traceback in the shell's captured stderr.
    import uvicorn

    from app.main import app

    # Bind to loopback only: this server is for the local desktop window, never the network.
    uvicorn.run(app, host="127.0.0.1", port=_port(), log_level="info")


if __name__ == "__main__":
    main()
