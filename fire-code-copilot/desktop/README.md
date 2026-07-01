# Fire Code CoPilot — Desktop App (Tauri)

A native desktop wrapper around the same UI you get in the browser. The one thing it adds:
it **starts and stops the Python backend for you**. Open the app → it launches uvicorn on
`:8000`, waits for it, and shows the UI. Quit the app → the backend shuts down with it. No
second terminal, no `launch.sh` running in the background.

Everything is still 100% local. This shell only spawns a process on your own machine and
loads `http://localhost`. Your code books never leave the Mac. (See the repo's
`CLAUDE.md` copyright rules — this wrapper doesn't change any of them.)

> **Tauri, not Electron.** The bundle is a few MB (it uses the OS webview) instead of a
> few hundred, and it's the right fit for a single-user local tool on a Mac Studio.

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

Then, from the repo root, make sure the backend venv exists at least once (this is what the
desktop app launches):
```bash
bash scripts/launch.sh        # first run builds backend/.venv; Ctrl-C once it's up
```

Finally, install the Tauri CLI and generate the app icons:
```bash
cd desktop
npm install
npm run icons                 # generates .icns/.ico/pngs from src-tauri/icons/icon.png
```

---

## Run it in dev

```bash
cd desktop
npm run dev
```

This launches the Vite dev server **and** the native window, with hot-reload on the UI.
Tauri's `beforeDevCommand` starts the frontend; the Rust `setup` hook starts the backend.

## Build a real `.app` / `.dmg`

```bash
cd desktop
npm run build
```

The signed-or-unsigned bundle lands in
`desktop/src-tauri/target/release/bundle/`:
- `macos/Fire Code CoPilot.app` — drag to `/Applications`
- `dmg/Fire Code CoPilot_1.0.0_aarch64.dmg` — a distributable installer

> **Where does the bundled `.app` find the backend?** It walks up from its own location
> looking for `backend/app/main.py`. For a Mac Studio where the repo lives in your home
> folder, the simplest robust setup is to keep the repo in place and pin it explicitly —
> see the env vars below. (Bundling Python itself into the `.app` is a future step; for a
> single-machine local tool, pointing at the repo is simpler and keeps the venv you already
> trust.)

---

## Configuration (env vars)

The wrapper reads these at launch:

| Variable | Default | What it does |
|---|---|---|
| `FCC_ROOT` | auto-detected | Pin the project root (the folder containing `backend/`). Set this for the bundled `.app`. |
| `FCC_API_PORT` | `8000` | Backend port. Must match the UI's `VITE_API_BASE`. |
| `FCC_NO_BACKEND` | unset | If set, the app does **not** spawn the backend — use this when you already run `scripts/launch.sh` yourself. |

To bake `FCC_ROOT` into the installed app, set it in your shell profile, or launch from a
tiny wrapper:
```bash
FCC_ROOT="$HOME/FIRECODECOPILOT/fire-code-copilot" open -a "Fire Code CoPilot"
```

---

## How it fits together

```
┌─────────────────────────── Fire Code CoPilot.app ───────────────────────────┐
│  Native window (OS webview)                                                  │
│   └─ loads the built React UI  ── talks to ──▶  http://localhost:8000 (API)  │
│                                                        ▲                      │
│  Rust setup hook  ── spawns ──▶  backend/.venv/bin/uvicorn app.main:app ──────┘
│  Rust exit hook   ── kills  ──▶  (same child process)
└──────────────────────────────────────────────────────────────────────────────┘
```

- `src-tauri/src/lib.rs` — finds the repo root, spawns/kills the backend child.
- `src-tauri/tauri.conf.json` — window, bundle, and `frontendDist: ../../frontend/dist`.
- `src-tauri/capabilities/default.json` — core window permissions only (no plugin surface).

## Troubleshooting

- **"Could not locate the project root"** in the console → set `FCC_ROOT` to your repo path.
- **Backend didn't start** → run `bash scripts/launch.sh` once from the repo root to create
  `backend/.venv`, then reopen the app.
- **Blank window** → the backend may still be warming (first model load). Give it a few
  seconds; check the console for `[fcc] Starting backend …`.
- **Want to use your own already-running backend** → launch with `FCC_NO_BACKEND=1`.
