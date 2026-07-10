"""MCP server — exposes Fire Code CoPilot as tools any MCP-capable agent can call
(Hermes, Codex, Claude Desktop, …). Runs locally over stdio; retrieval, reranking,
amendment layering, and citation validation all happen on this machine.

Run:  python -m app.mcp_server          (or scripts/mcp_server.sh, which sets cwd/venv)

Tools:
  fire_code_lookup        answer or retrieve, with edition selection + deep mode + history
  fire_code_list_editions discover the indexed code-cycle collections
  fire_code_cycle_status  the adopted CT editions + any pending-cycle warning

Two modes, and which one your outer agent should use matters:
  - mode="retrieve" (RECOMMENDED for an outer agent like Hermes): returns the grounded,
    amendment-layered source passages and lets YOUR model reason over them. Needs no local
    LLM — works even when oMLX isn't running.
  - mode="answer": this app's own configured model composes a citation-validated answer.
    Requires the configured oMLX generation backend to be up.

Containment note: the passages returned here are excerpts from the marshal's licensed books.
Whatever model the CALLING agent uses (e.g. a cloud model) will see them — the same envelope
as this app's own cloud-generation path. Do not log, store, or republish them beyond the
conversation.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .agent import ask, result_dict
from .cycles import active_cycle_block  # builds the adopted-editions block from code_cycles.yaml

mcp = FastMCP("fire-code-copilot")


@mcp.tool()
def fire_code_lookup(question: str, mode: str = "retrieve", building_context: str = "",
                     collection: str = "", deep: bool = False,
                     history: list[dict] | None = None) -> dict:
    """Look up fire/building code for the City of Hartford, CT from the marshal's own code books.

    Args:
        question: The code question in plain language.
        mode: "retrieve" (default — returns grounded source passages for YOU to reason over;
              needs no local LLM) or "answer" (this app's own model composes a
              citation-validated answer; requires its generation backend to be running).
        building_context: Optional known facts (occupancy, new/existing, construction type,
              height, area, sprinklered). Pass what you know — it changes the answer.
        collection: Optional edition collection name (see fire_code_list_editions) to search a
              LEGACY code cycle for existing-building questions. Empty = the active edition.
        deep: In answer mode, escalate to the stronger configured model with a second
              retrieval pass.
        history: Optional prior exchanges in this conversation, oldest first, each
              {"question": ..., "answer": ...} — lets follow-ups resolve what they refer to.

    Returns a dict with: answer (null in retrieve mode), sources (book/section/page + text,
    with Connecticut amendments marked controlling), citations_ok (bool), unverified (any
    citations that could NOT be verified against the loaded books — treat as suspect),
    confidence / confidence_band, and clarifying questions when facts are missing.
    """
    res = ask(question, mode=mode, building_context=building_context,
              active_cycle_block=active_cycle_block(), deep=deep,
              collection=collection or None, history=history)
    return result_dict(res)


@mcp.tool()
def fire_code_list_editions() -> dict:
    """List the indexed code-edition collections (one per adopted cycle) and which is active.
    Pass a non-active collection name to fire_code_lookup's `collection` to search a legacy
    edition for existing-building questions. Never blend editions in one determination."""
    from .ingest import list_collections
    from .settings import settings
    return {"active": settings.active_collection, "collections": list_collections()}


@mcp.tool()
def fire_code_cycle_status() -> str:
    """Report the currently adopted Connecticut code editions and any pending-cycle warning."""
    return active_cycle_block()


if __name__ == "__main__":
    mcp.run()  # stdio transport
