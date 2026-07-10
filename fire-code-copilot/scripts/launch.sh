#!/usr/bin/env bash
# One-command launcher for Fire Code CoPilot.
#
#   bash scripts/launch.sh
#
# First run: creates the Python venv, installs backend + frontend deps, and copies .env.
# Every run: warms the retrieval stack, starts the app API (:8001) and web UI (:5173), and opens
# your browser. Press Control-C once to stop both. Nothing leaves your machine.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY=backend/.venv/bin/python
API_PORT="${API_PORT:-8001}"
WEB_PORT="${WEB_PORT:-5173}"

# --- First-run setup (idempotent) -------------------------------------------------------------
if [ ! -x "$PY" ]; then
  echo "→ Setting up the Python environment (first run — this takes a few minutes)…"
  python3 -m venv backend/.venv
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q -r backend/requirements.txt
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠️  Created .env from the template. Open it and set CODE_BOOKS_DIR (your PDF folder) and a"
  echo "    model (e.g. GENERATION_PROVIDER=anthropic + ANTHROPIC_API_KEY), then run this again."
  exit 1
fi

if [ ! -d frontend/node_modules ]; then
  echo "→ Installing the web UI dependencies (first run)…"
  ( cd frontend && npm install )
fi

# --- Start everything --------------------------------------------------------------------------
PIDS=()
cleanup() { echo; echo "→ Stopping…"; kill "${PIDS[@]}" 2>/dev/null || true; exit 0; }
trap cleanup INT TERM

echo "→ Starting the API on :$API_PORT …"
backend/.venv/bin/uvicorn app.main:app --app-dir backend --port "$API_PORT" &
PIDS+=($!)

# Warm the local models in the background so the first question isn't a cold-start hang.
( for i in $(seq 1 30); do
    curl -sf "http://localhost:$API_PORT/health" >/dev/null 2>&1 && break; sleep 1; done
  echo "→ Warming models…"; curl -s -X POST "http://localhost:$API_PORT/warm" >/dev/null 2>&1 || true
) &

echo "→ Starting the web UI on :$WEB_PORT …"
( cd frontend && VITE_API_BASE="http://localhost:$API_PORT" npm run dev -- --port "$WEB_PORT" ) &
PIDS+=($!)

# Open the browser once the UI is reachable.
( URL="http://localhost:$WEB_PORT"
  for i in $(seq 1 30); do curl -sf "$URL" >/dev/null 2>&1 && break; sleep 1; done
  ( command -v open >/dev/null 2>&1 && open "$URL" ) \
    || ( command -v xdg-open >/dev/null 2>&1 && xdg-open "$URL" ) \
    || echo "→ Open $URL in your browser."
) &

echo
echo "✅ Fire Code CoPilot is starting. Web UI: http://localhost:$WEB_PORT   API: http://localhost:$API_PORT"
echo "   Press Control-C to stop."
wait
