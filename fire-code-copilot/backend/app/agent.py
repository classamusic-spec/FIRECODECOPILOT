"""The agent: retrieve -> (rerank) -> ground the local model -> validate citations.

Two modes:
  - "answer":   the LLM composes a final, citation-validated answer (Pattern A).
                Use for direct code questions; the citation validator guarantees grounding.
  - "retrieve": return the validated source chunks WITHOUT composing an answer (Pattern B).
                Use when an outer agent (e.g. Hermes' local model) wants to reason over the
                grounded passages itself across multiple tool calls.

Everything runs locally by default. The only thing that ever escalates to Claude is the
optional DEEP path, and only if you configure it.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path

from .settings import settings
from . import llm, citations
from .retriever import retrieve, render_sources

PROMPT_PATH = Path(__file__).resolve().parents[2] / "docs" / "AGENT_SYSTEM_PROMPT.md"


def _system_prompt(active_cycle_block: str) -> str:
    """Load the fire-marshal system prompt and fill in jurisdiction + active editions."""
    base = PROMPT_PATH.read_text(encoding="utf-8") if PROMPT_PATH.exists() else _FALLBACK_PROMPT
    # Pull only the fenced prompt body if the markdown wraps it in ```; else use whole file.
    if "```text" in base:
        base = base.split("```text", 1)[1].split("```", 1)[0]
    return (base
            .replace("{{JURISDICTION}}", settings.jurisdiction)
            .replace("{{ACTIVE_CODE_CYCLE_BLOCK}}", active_cycle_block)
            .replace("{{PENDING_CYCLE_LABEL}}", "the pending CT code cycle"))


@dataclass
class AgentResult:
    mode: str
    answer: str | None
    sources: list[dict]
    citations_ok: bool
    unverified: list[str]
    needs_clarification: bool = False


def ask(question: str, *, mode: str = "answer", building_context: str = "",
        active_cycle_block: str = "", deep: bool = False) -> AgentResult:
    chunks = retrieve(question)

    if mode == "retrieve":
        # Pattern B: hand grounded sources back to the caller; no generation here.
        return AgentResult(mode="retrieve", answer=None, sources=chunks,
                           citations_ok=True, unverified=[])

    system = _system_prompt(active_cycle_block)
    user = _build_user_block(question, building_context, render_sources(chunks))

    provider = settings.deep_provider if deep else settings.generation_provider
    model = settings.deep_model if deep else None
    draft = llm.chat(system, user, provider=provider, model=model)

    # Safety net: verify every cited section actually appears in the retrieved sources.
    if settings.validate_citations:
        check = citations.validate(draft, chunks)
        answer = citations.annotate(draft, check)
        return AgentResult(mode="answer", answer=answer, sources=chunks,
                           citations_ok=check.ok, unverified=check.unverified)

    return AgentResult(mode="answer", answer=draft, sources=chunks,
                       citations_ok=True, unverified=[])


def _build_user_block(question: str, building_context: str, sources: str) -> str:
    ctx = f"\nBUILDING CONTEXT PROVIDED BY MARSHAL:\n{building_context}\n" if building_context else ""
    return (
        f"QUESTION:\n{question}\n{ctx}\n"
        f"RETRIEVED SOURCE EXCERPTS (you may ONLY cite from these):\n{sources}\n\n"
        f"Answer per your instructions. If key building facts are missing and they change the "
        f"answer, ask the clarifying questions first instead of guessing. Cite only sections "
        f"present above."
    )


def result_dict(r: AgentResult) -> dict:
    return asdict(r)


_FALLBACK_PROMPT = (
    "You are Fire Code CoPilot, a research assistant to a fire marshal in {{JURISDICTION}}. "
    "Use ONLY the retrieved excerpts. Never invent a section number. If the answer isn't in "
    "the excerpts, say so. Ask for occupancy/new-vs-existing/construction type/height/area/"
    "sprinklered status when they change the answer. Cite book, edition, section, page."
)
