# Fire Code CoPilot — Desktop App (Tauri)

A native desktop wrapper around the same UI you get in the browser. The one thing it adds:
it **starts and stops the Python backend for you**. Open the app → it launches the backend on
`:8000`, waits for it, and shows the UI. Quit the app → the backend shuts down with it. No
second terminal, no `launch.sh` running in the background.

A shipped build is **fully standalone**: it embeds its own frozen Python backend, so the
installed `.app` needs no repo and no venv on disk. In development it falls back to the repo's
venv for fast iteration — same code path, no freeze step. (Both modes are covered below.)

Everything is still 100% local. This shell only spawns a process on your own machine and
loads `http://localhost`. Your code books never leave the Mac. (See the repo's
`CLAUDE.md` copyright rules — this wrapper doesn't change any of them.)

> **Tauri, not Electron.** The native shell uses the OS webview, so the wrapper itself is a
> few MB (the frozen Python backend it carries is the bulk of a standalone build). The right
> fit for a single-user local tool on a Mac Studio.

---

## One-time setup

You need three things installed. On a Mac Studio:

1. **Rust** (compiles the native shell):
   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   ```
2. **Xcode command-line tools** (for the macOS webview + linker):
   ```bash
   xcode-select --install
   ```
3. **Node.js** (you already have it if you've run the web UI).

Then, from the repo root, make sure the backend venv exists at least once (dev builds launch
it directly; the standalone build freezes it):
```bash
bash scripts/launch.sh        # first run builds backend/.venv; Ctrl-C once it's up
```

Install the Tauri CLI and generate the app icons:
```bash
cd desktop
npm install
npm run icons                 # generates .icns/.ico/pngs from src-tauri/icons/icon.png
```

For a **standalone** build (not just dev), also install PyInstaller into the backend venv:
```bash
../backend/.venv/bin/pip install -r ../backend/requirements-desktop.txt
```

---

## Run it in dev

```bash
cd desktop
npm run dev
```

This launches the Vite dev server **and** the native window, with hot-reload on the UI.
Tauri's `beforeDevCommand` starts the frontend; the Rust `setup` hook starts the backend.

## Build a real, **fully standalone** `.app` / `.dmg`

A shipped `.app` embeds its own Python — no repo, no venv, nothing else on disk. There are
two steps: freeze the backend, then build the app.

```bash
# 1) Freeze the Python backend into a self-contained program folder (a few minutes).
#    Needs the backend venv (bash scripts/launch.sh once) + PyInstaller.
cd desktop
bash scripts/build-sidecar.sh

# 2) Build the native app around it.
npm run build
```

The bundle lands in `desktop/src-tauri/target/release/bundle/`:
- `macos/Fire Code CoPilot.app` — drag to `/Applications`
- `dmg/Fire Code CoPilot_1.0.0_aarch64.dmg` — a distributable installer

**What "standalone" means here:** the frozen backend (`fcc-backend`) is bundled as an app
*resource*. On launch the Rust shell runs it directly and points all its writable paths at
the OS app-data folder — so the read-only, code-signed `.app` never writes inside itself.

> **One honest caveat — model weights.** The embedder (BGE-M3) and reranker weights are
> multi-GB, so they are **not** frozen into the app; they download once to
> `~/.cache/huggingface` the first time you ask a question with the local embedder. The
> *code* to run them is fully bundled. If you use `GENERATION_PROVIDER=anthropic` (or
> `openai`) and want zero local downloads, you can also set `EMBEDDING_PROVIDER=voyage`.

### Where the standalone app keeps its data

Everything mutable lives under
`~/Library/Application Support/com.firecodecopilot.desktop/`:

| Path | What |
|---|---|
| `.env` | **You create this.** Model provider + API key + any overrides (same keys as the repo `.env.example`). |
| `code_books/` | Drop your code-book PDFs here (or point elsewhere with `FCC_CODE_BOOKS_DIR`). |
| `code_cycles.yaml` | Optional — a config here overrides the copy frozen into the app. |
| `data/` | The vector store (`chroma/`), feedback DB, and ingested index — created for you. |

**First-run setup for the standalone app:**
1. Create the `.env` above with your model choice, e.g. `GENERATION_PROVIDER=anthropic` and
   `ANTHROPIC_API_KEY=...`.
2. Put your PDFs in `code_books/`.
3. Open the app and trigger ingestion — the UI's ingest action calls `POST /ingest`, so you
   never need the command line.

### Dev builds skip all of this

`npm run dev` (or `npm run build` **without** running `build-sidecar.sh` first) has no frozen
backend to bundle, so the shell falls back to the repo's `backend/.venv` — fast iteration
with no freeze step. The two modes share the same Rust code path.

---

## Configuration (env vars)

The wrapper reads these at launch:

| Variable | Default | What it does |
|---|---|---|
| `FCC_API_PORT` | `8001` | Backend port. Must match the UI's `VITE_API_BASE`; leaves oMLX on `8000`. |
| `FCC_STOP_OMLX_ON_EXIT` | `1` | Stop managed oMLX and release model memory when the desktop app quits. Set `0` only if another workload owns oMLX. |
| `FCC_CODE_BOOKS_DIR` | `<app-data>/code_books` | Where the **standalone** app reads your PDFs. |
| `FCC_NO_BACKEND` | unset | Don't spawn a backend — use this when you already run one yourself. |
| `FCC_ROOT` | auto-detected | **Dev fallback only:** pin the repo root (folder containing `backend/`). |

---

## How it fits together

```
┌──────────────────────── Fire Code CoPilot.app (standalone) ─────────────────────────┐
│  Native window (OS webview)                                                          │
│   └─ loads the built React UI  ── talks to ──▶  http://127.0.0.1:8001 (API)          │
│                                                        ▲                              │
│  Rust setup hook ─ spawns ─▶  <Resources>/fcc-backend/fcc-backend  (frozen Python)   │
│                     with DATA_DIR / CHROMA_DIR / CODE_BOOKS_DIR ─▶  ~/Library/…       │
│  Rust exit hook  ─ kills backend + runs `omlx stop` ─▶ releases local model memory    │
└──────────────────────────────────────────────────────────────────────────────────────┘
        (dev fallback: spawns backend/.venv/bin/uvicorn from the repo instead)
```

- `src-tauri/src/lib.rs` — picks the frozen backend or the dev venv; sets writable paths; spawns/kills the child.
- `fcc-backend.spec` + `scripts/build-sidecar.sh` — freeze the backend with PyInstaller and stage it as a resource.
- `backend/desktop_entry.py` — the frozen entry point (runs uvicorn on loopback).
- `src-tauri/tauri.conf.json` — window, `frontendDist`, and the `fcc-backend` resource.
- `src-tauri/capabilities/default.json` — core window permissions only (no plugin surface).

## Troubleshooting

- **Blank window** → the backend may still be warming (first model download can take a
  while). Give it a moment; check Console for `[fcc] Starting standalone backend …`.
- **"Frozen backend failed to start"** in the log → rebuild it with `bash scripts/build-sidecar.sh`,
  then `npm run build` again.
- **Answers say "No PDFs found"** → put PDFs in `~/Library/Application Support/com.firecodecopilot.desktop/code_books/`
  (or set `FCC_CODE_BOOKS_DIR`), then run ingestion from the UI.
- **Dev build can't find the backend** → run `bash scripts/launch.sh` once to create
  `backend/.venv`, or set `FCC_ROOT` to your repo path.
- **Want to use your own already-running backend** → launch with `FCC_NO_BACKEND=1`.
