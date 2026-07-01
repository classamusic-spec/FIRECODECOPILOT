#!/usr/bin/env bash
# Freeze the Python backend into a standalone program folder and stage it where Tauri will
# bundle it into the .app. Run this ONCE before `npm run build` whenever the backend changes.
#
#   cd desktop && bash scripts/build-sidecar.sh
#
# Prereqs: the backend venv exists (bash scripts/launch.sh once) and PyInstaller is installed:
#   backend/.venv/bin/pip install -r backend/requirements-desktop.txt
set -euo pipefail

DESKTOP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "$DESKTOP/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
RESOURCES="$DESKTOP/src-tauri/resources"

if [ ! -x "$PY" ]; then
  echo "✗ No backend venv at $PY — run 'bash scripts/launch.sh' from the repo root once first." >&2
  exit 1
fi

if ! "$PY" -c "import PyInstaller" 2>/dev/null; then
  echo "→ Installing PyInstaller into the backend venv…"
  "$PY" -m pip install -q -r "$ROOT/backend/requirements-desktop.txt"
fi

echo "→ Freezing the backend with PyInstaller (this takes a few minutes)…"
cd "$DESKTOP"
"$PY" -m PyInstaller --noconfirm --clean --distpath "$DESKTOP/dist" --workpath "$DESKTOP/build" \
  fcc-backend.spec

echo "→ Staging the frozen backend as a Tauri resource…"
rm -rf "$RESOURCES/fcc-backend"
mkdir -p "$RESOURCES"
cp -R "$DESKTOP/dist/fcc-backend" "$RESOURCES/fcc-backend"
chmod +x "$RESOURCES/fcc-backend/fcc-backend" 2>/dev/null || true

echo
echo "✅ Standalone backend staged at src-tauri/resources/fcc-backend/"
echo "   Now build the app:  npm run build   (or: npm run dev)"
