# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: freeze the Fire Code CoPilot backend into a self-contained program folder
# so the Tauri desktop app can ship a fully standalone .app (no repo, no venv on disk).
#
#   Build:  cd desktop && bash scripts/build-sidecar.sh      (wraps `pyinstaller fcc-backend.spec`)
#
# Output: dist/fcc-backend/  (a folder: the `fcc-backend` executable + an `_internal/` payload).
# The build script copies that folder into src-tauri/resources/ so Tauri bundles it into the .app;
# at runtime the Rust shell spawns the inner executable. We use one-DIR (not one-file) so launch is
# instant — no multi-hundred-MB self-extraction on every start.
#
# NOTE: model *weights* (BGE-M3 embedder, reranker) are NOT frozen in here. They're multi-GB and
# download once to ~/.cache/huggingface on first use. This bundles the *code* that runs them.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPEC_DIR = Path(SPECPATH)                              # desktop/
ROOT = SPEC_DIR.parent
BACKEND = (ROOT / "backend").resolve()
CONFIG = (ROOT / "config").resolve()

datas, binaries, hiddenimports = [], [], []

# Bundle the code-cycle config so settings._ROOT/config/code_cycles(.example).yaml resolves inside
# the frozen bundle. (cycles.py falls back to the committed .example when no real file is present.)
datas += [(str(CONFIG), "config")]

# Pull in everything these libraries need at runtime: submodules PyInstaller can't see statically,
# their data files, and any bundled shared objects.
for pkg in ("chromadb", "sentence_transformers", "transformers", "tokenizers",
            "fitz", "pymupdf", "rank_bm25", "tiktoken", "tiktoken_ext",
            "onnxruntime", "tqdm", "huggingface_hub", "safetensors", "yaml",
            "regex", "sympy"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as e:                             # a missing optional pkg shouldn't abort the build
        print(f"[spec] skipping {pkg}: {e}", file=sys.stderr)

# uvicorn[standard] imports its workers/protocols dynamically; grab the whole tree + our app pkg.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += ["httptools", "websockets", "watchfiles", "anyio", "app", "app.main"]

a = Analysis(
    [str(BACKEND / "desktop_entry.py")],
    pathex=[str(BACKEND)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "httpx", "IPython", "notebook"],   # dev-only weight we don't need at runtime
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,                 # one-DIR: binaries live beside the exe in _internal/
    name="fcc-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,                          # stdout/stderr captured by the desktop shell for logs
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,                      # matches the build host (arm64 on Apple Silicon)
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="fcc-backend",
)
