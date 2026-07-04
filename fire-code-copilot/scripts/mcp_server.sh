#!/usr/bin/env bash
# Launch the Fire Code CoPilot MCP server (stdio) — the one command an MCP client (Hermes,
# Codex, Claude Desktop, …) needs. Handles the working directory and finds the venv, so the
# client config never has to know about Python paths.
#
#   command: /path/to/fire-code-copilot/scripts/mcp_server.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The venv lives at backend/.venv when created by scripts/launch.sh, or at .venv for a
# manual setup. Prefer whichever exists.
for PY in "$ROOT/backend/.venv/bin/python" "$ROOT/.venv/bin/python"; do
  if [ -x "$PY" ]; then
    cd "$ROOT/backend"
    exec "$PY" -m app.mcp_server
  fi
done

echo "✗ No Python venv found. Run 'bash scripts/launch.sh' once from $ROOT first." >&2
exit 1
