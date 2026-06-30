"""MCP server — exposes Fire Code CoPilot as a tool any MCP-capable agent can call,
including Nous Hermes Agent. Runs locally; the local model does all the work.

Run:  python -m app.mcp_server         (stdio transport, what Hermes/most clients use)

Exposes one tool, `fire_code_lookup`, with two modes:
  - mode="answer"   -> returns a citation-validated answer (recommended for direct questions)
  - mode="retrieve" -> returns grounded source passages for the calling agent to reason over

Either way, retrieval + reranking + (optional) generation + citation validation are local.
"""
from __future__ import annotations
from mcp.server.fastmcp import FastMCP
from .agent import ask, result_dict
from .cycles import active_cycle_block  # builds the adopted-editions block from code_cycles.yaml

mcp = FastMCP("fire-code-copilot")


@mcp.tool()
def fire_code_lookup(question: str, mode: str = "answer", building_context: str = "") -> dict:
    """Look up fire/building code for the City of Hartford, CT from the marshal's own code books.

    Args:
        question: The code question in plain language.
        mode: "answer" for a citation-validated answer, or "retrieve" for grounded source
              passages the calling agent can reason over itself.
        building_context: Optional known facts (occupancy, new/existing, construction type,
              height, area, sprinklered) that change the answer. Pass what you know.

    Returns a dict with: answer (or null in retrieve mode), sources (book/section/page +
    text), citations_ok (bool), and unverified (any citations that could NOT be verified
    against the loaded books — treat these as suspect).
    """
    res = ask(question, mode=mode, building_context=building_context,
              active_cycle_block=active_cycle_block())
    return result_dict(res)


@mcp.tool()
def fire_code_cycle_status() -> str:
    """Report the currently adopted Connecticut code editions and any pending-cycle warning."""
    return active_cycle_block()


if __name__ == "__main__":
    mcp.run()  # stdio transport
