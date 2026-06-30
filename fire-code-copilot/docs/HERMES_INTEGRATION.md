# Hermes Integration — Fire Code CoPilot as a local skill

Goal: your **Hermes Agent** (Nous Research) orchestrates with a **local** LLM, and when a
fire-code question comes up it calls **Fire Code CoPilot**, which does local retrieval +
reranking + local generation + citation validation, and hands back a grounded, cited answer.
No prompts and no code books leave your Mac.

## The all-local data flow

```
You ──▶ Hermes Agent (local model: GLM-5.2 or fast Qwen3.6)
            │  recognizes a fire-code question
            ▼
     fire_code_lookup tool  ─────────────┐
            │                            │  (all local)
            ▼                            │
   Fire Code CoPilot backend            │
     embed (local) → Chroma → rerank    │
     → GLM-5.2 (local) drafts answer    │
     → citation validator               │
            │                            │
            ▼                            │
   grounded, cited answer ──────────────┘
            │
            ▼
        Hermes relays it to you (Telegram/CLI/etc.)
```

Two local models are in play and that's fine:
- **Hermes orchestrator model** — decides when to call the tool. A fast model (e.g. Qwen3.6)
  is plenty here, since the hard reasoning happens inside the tool.
- **Fire Code answering model** — GLM-5.2 inside the tool, where citation accuracy matters.
- Or use GLM-5.2 for both. Your 512GB can hold it.

## Step 0 — get Hermes talking to a local model first

Nous' own advice: don't add tools/skills until one clean local chat + one successful tool
call work. Point Hermes at your local OpenAI-compatible server (LM Studio `:1234`, Ollama
`:11434`, or `mlx_lm.server`). In `~/.hermes/config.yaml`:

```yaml
provider: custom
model:
  default: glm-5.2          # or a fast model like qwen3.6 for orchestration
  base_url: http://localhost:1234/v1
  context_length: 131072
```

Run `hermes model` for the interactive flow if you prefer — it writes the correct fields for
your version. Verify with a simple "what model are you running?" chat. (Field names can change
between Hermes versions — confirm against hermes-agent.nousresearch.com/docs.)

## Wiring option 1 — MCP server (recommended, most portable)

Fire Code CoPilot ships an MCP server (`backend/app/mcp_server.py`) exposing `fire_code_lookup`
and `fire_code_cycle_status`. MCP is reusable across agents (Hermes, Claude, LM Studio…), so
you build the tool once.

1. Start the backend services (local model server + Chroma already running):
   ```bash
   cd backend && source .venv/bin/activate
   python -m app.mcp_server          # stdio MCP server
   ```
2. Register it with Hermes as an MCP tool server (via `hermes tools` / the MCP config section
   in `config.yaml`). Point Hermes at the command that launches the server, e.g.:
   ```yaml
   mcp_servers:
     fire-code-copilot:
       command: "python"
       args: ["-m", "app.mcp_server"]
       cwd: "/Users/you/Fire-Code-CoPilot/backend"
   ```
3. Enable the tool (`hermes tools`) and confirm Hermes can call `fire_code_lookup`.

## Wiring option 2 — agentskills.io skill (native Hermes skill)

Hermes skills follow the **agentskills.io** open standard. The skill in
`hermes-skill/fire-code-copilot/` contains:
- `SKILL.md` — the manifest + instructions that tell the Hermes model *when* to use the tool
  and the hard rules (never invent citations, ask clarifying questions, CT amendments govern).
- `scripts/fire_code.py` — a fallback that calls the local REST API if you'd rather expose it
  as a script-tool than MCP.

Install by placing the skill folder in your Hermes skills directory (the location Hermes uses
for user skills — check `hermes` docs / `hermes tools` for the exact path on your version),
then enable it. The `tools:` list in the manifest references the MCP tools from option 1, so
**use option 1 + option 2 together**: MCP provides the callable tool; the skill provides the
judgment about when and how to call it.

> Tip: the SKILL.md `description` is what Hermes matches against to decide relevance, so keep
> it trigger-rich (fire code, sprinkler, egress, occupancy, plan review…). This is the same
> reason the description in the manifest is written the way it is.

## Keeping it honest and local

- **Answer mode** (default) runs the citation validator — fabricated section numbers get
  flagged, not relayed silently. Tell Hermes (it's in SKILL.md) to pass through the ⚠️ warning.
- **Retrieve mode** returns grounded passages so the Hermes model can reason across multiple
  lookups; instruct it to answer only from those passages.
- Nothing leaves the machine: local orchestrator model, local embeddings, local reranker,
  local answering model, local vector store. The optional Claude escalation is OFF by default
  (`DEEP_PROVIDER=local`).

## Smoke test

1. `hermes` → ask "what model are you running?" (confirms local model).
2. Ask a fire-code question → confirm Hermes calls `fire_code_lookup` and returns a cited answer.
3. Ask something NOT in your books → confirm it says so instead of inventing a citation.
4. Ask "which fire code edition is in force?" → confirms `fire_code_cycle_status` works.
