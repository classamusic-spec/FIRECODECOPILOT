# Using Fire Code CoPilot from Hermes (or any MCP agent)

The app exposes itself as an **MCP server** (`backend/app/mcp_server.py`), so an outer agent —
your Hermes agent, Codex, Claude Desktop, anything MCP-capable — can call it as a tool while its
own model (e.g. GPT-5.5 Codex) does the conversation. Retrieval, reranking, Connecticut-amendment
layering, and citation validation all still run **locally on your Mac**.

## What Hermes gets

| Tool | What it does |
|---|---|
| `fire_code_lookup` | The main tool. `mode="retrieve"` (default) returns grounded, amendment-layered source passages for *Hermes' model* to reason over — **needs no local LLM**, works even when LM Studio is closed. `mode="answer"` makes this app's own configured model compose a citation-validated answer. Supports `building_context`, `collection` (legacy editions), `deep`, and `history` (follow-up memory). |
| `fire_code_list_editions` | Lists the indexed code-cycle collections so the agent can target a legacy edition. |
| `fire_code_cycle_status` | The adopted CT editions + any pending-cycle warning. |

**Recommended pattern for Hermes:** call `fire_code_lookup` with `mode="retrieve"` and let
GPT-5.5 reason over the returned passages, keeping the `unverified`/`citations_ok` fields visible.
The sources come back with the controlling CT amendments marked — instruct Hermes to treat those
as governing and never to cite a section that isn't in the returned sources.

## One-time setup (2 steps)

**1. Make sure the app itself is configured and indexed** (see the main README). In
`~/FIRECODECOPILOT/fire-code-copilot/.env` — note the quotes, the folder name has spaces:

```bash
CODE_BOOKS_DIR="/Users/XAVI/Desktop/2022 Fire Codes"
```

…and index the books once (Library panel → *Index new / changed*, or `python -m app.ingest`).

**2. Register the MCP server in your agent.** The only command a client needs is the launcher
script (it finds the venv and working directory by itself):

```
/Users/XAVI/FIRECODECOPILOT/fire-code-copilot/scripts/mcp_server.sh
```

### Generic MCP client config (Hermes, Claude Desktop, most others)

Most MCP clients take a JSON block like this — in Hermes, add it wherever it configures MCP
servers/tools:

```json
{
  "mcpServers": {
    "fire-code-copilot": {
      "command": "/Users/XAVI/FIRECODECOPILOT/fire-code-copilot/scripts/mcp_server.sh",
      "args": []
    }
  }
}
```

### Codex CLI (`~/.codex/config.toml`)

```toml
[mcp_servers.fire_code_copilot]
command = "/Users/XAVI/FIRECODECOPILOT/fire-code-copilot/scripts/mcp_server.sh"
```

Restart the agent; it should list `fire_code_lookup`, `fire_code_list_editions`, and
`fire_code_cycle_status` among its tools. Test with a smoke question:
*"Use fire_code_lookup to find the sprinkler requirements for an existing Group R-2."*

## Verify it by hand (optional)

```bash
cd ~/FIRECODECOPILOT/fire-code-copilot
bash scripts/mcp_server.sh
# it waits silently for stdio input — that's correct; Ctrl-C to exit.
```

## Things to know

- **`mode="retrieve"` needs no LLM.** The whole Hermes flow works with LM Studio closed —
  only `mode="answer"` (and the web UI) need the generation backend running.
- **Cold start:** the first lookup loads the local embedding model (~seconds once cached;
  the first-ever run downloads it). Subsequent calls are fast.
- **Don't run ingest from two places at once.** Indexing from the web UI while Hermes is
  mid-query is fine for reads, but run only one ingest at a time.
- **Copyright envelope:** retrieved passages are excerpts from your licensed books. Whatever
  model Hermes uses will see them (same envelope as this app's own cloud-generation path).
  Keep them inside the conversation — no logging pipelines, no republishing.
- **The marshal is still the AHJ.** Tell Hermes' system prompt to present results as decision
  support with citations to verify — never as a binding determination.
