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
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .settings import settings
from . import llm, citations
from .retriever import retrieve_scored, render_sources

PROMPT_PATH = Path(__file__).resolve().parents[2] / "docs" / "AGENT_SYSTEM_PROMPT.md"

# Appended to the user turn so a clarification request comes back in a machine-readable shape
# without disturbing the markdown ANSWER FORMAT for normal answers.
_OUTPUT_PROTOCOL = (
    "\n\nOUTPUT PROTOCOL: If — and only if — you cannot answer safely until the marshal "
    "supplies decisive building facts, reply with ONLY a JSON object and nothing else:\n"
    '{"needs_clarification": true, '
    '"questions": ["<the few questions that actually change the answer>"], '
    '"chips": {"Occupancy": ["R-2", "B", "A-2"], "Sprinklered": ["Yes", "No"]}}\n'
    "The \"chips\" map is optional quick-pick suggestions per question. Otherwise, ignore this "
    "protocol and answer normally in the ANSWER FORMAT (markdown)."
)


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
    clarifying_questions: list[str] = field(default_factory=list)
    chips: dict = field(default_factory=dict)
    escalated: bool = False          # did we auto-escalate to the deep model?
    confidence: float | None = None       # top rerank score (None when the reranker is off)
    confidence_band: str | None = None    # "low" | "medium" | "high" | None


def _confidence(scored) -> tuple[float | None, str | None]:
    """Gauge retrieval confidence. Empty retrieval is unambiguously "low"; otherwise we band the
    top rerank score (only meaningful when the reranker is on — else the band is unknown/None)."""
    if not scored:
        return None, "low"
    if not settings.use_reranker:
        return None, None
    top = max(s.score for s in scored)
    band = ("high" if top >= settings.confidence_high_above
            else "low" if top < settings.deep_escalate_below else "medium")
    return round(float(top), 3), band


def _flag_low_confidence(question, answer, sources, building_context, band) -> None:
    """Auto-populate the review queue when an answer is low-confidence (best-effort; never
    breaks answering). This closes the gap-detection loop without the marshal doing anything."""
    if band != "low" or not settings.auto_flag_low_confidence:
        return
    try:
        from . import feedback
        feedback.record_feedback(question=question, answer=answer or "", rating="",
                                 building_context=building_context, sources=sources or [],
                                 low_confidence=True)
    except Exception:
        pass


def ask(question: str, *, mode: str = "answer", building_context: str = "",
        active_cycle_block: str = "", deep: bool = False,
        provider: str | None = None, collection: str | None = None,
        history: list[dict] | None = None) -> AgentResult:
    # Follow-up memory: a context-carrying query variant built from the previous question, fused
    # with the literal question (RRF), so "what about existing buildings?" retrieves the topic
    # it refers to. Reranking still scores against the marshal's ORIGINAL wording.
    extra = _history_queries(question, history)
    scored = retrieve_scored(question, collection=collection, extra_queries=extra or None)
    chunks = [s.chunk for s in scored]

    if mode == "retrieve":
        # Pattern B: hand grounded sources back to the caller; no generation here.
        return AgentResult(mode="retrieve", answer=None, sources=chunks,
                           citations_ok=True, unverified=[])

    # Deep-mode hook: escalate a hard/low-confidence question to the stronger model. We only
    # trust the score signal when the reranker is on (otherwise scores are uniform placeholders).
    top_score = max((s.score for s in scored), default=0.0)
    auto_deep = settings.use_reranker and bool(scored) and top_score < settings.deep_escalate_below
    use_deep = deep or auto_deep

    # Deep mode also does a SECOND retrieval pass with a rewritten query (folding in the building
    # context), then reranks the union — not just a model swap.
    if use_deep and (rewrite := _deep_rewrite(question, building_context)):
        scored = retrieve_scored(question, collection=collection,
                                 extra_queries=extra + [rewrite])
        chunks = [s.chunk for s in scored]

    conf, band = _confidence(scored)

    system = _system_prompt(active_cycle_block)
    user = _build_user_block(question, building_context, render_sources(chunks),
                             history=history) + _OUTPUT_PROTOCOL

    gen_provider = provider or (settings.deep_provider if use_deep else settings.generation_provider)
    model = settings.deep_model if use_deep else None
    draft = llm.chat(system, user, provider=gen_provider, model=model)

    # Did the model ask for clarification instead of answering? Return the questions, not a guess.
    clar = _parse_clarification(draft)
    if clar is not None:
        return AgentResult(mode="answer", answer=None, sources=chunks, citations_ok=True,
                           unverified=[], needs_clarification=True,
                           clarifying_questions=clar.get("questions", []),
                           chips=clar.get("chips", {}) or {}, escalated=use_deep,
                           confidence=conf, confidence_band=band)

    # Safety net: verify every cited section actually appears in the retrieved sources.
    check = citations.validate(draft, chunks) if settings.validate_citations else None
    answer = citations.annotate(draft, check) if check else draft
    ok = check.ok if check else True
    unverified = check.unverified if check else []
    _flag_low_confidence(question, answer, chunks, building_context, band)
    return AgentResult(mode="answer", answer=answer, sources=chunks, citations_ok=ok,
                       unverified=unverified, escalated=use_deep,
                       confidence=conf, confidence_band=band)


def ask_stream(question: str, *, building_context: str = "", active_cycle_block: str = "",
               deep: bool = False, provider: str | None = None, collection: str | None = None,
               history: list[dict] | None = None):
    """Streaming twin of ask(): yields event dicts for Server-Sent Events.

    Event types (exactly one of clarify/meta terminates the answer, then done):
      {"type":"token","text": ...}     incremental answer text
      {"type":"clarify", ...}          the model asked for facts instead (chips/questions)
      {"type":"meta", ...}             sources + citation verdict + any unverified-warning suffix
      {"type":"error","message": ...}
      {"type":"done"}

    We peek the first non-empty delta: if it starts with "{" the model is returning the
    clarification JSON, so we buffer silently (never stream raw JSON to the UI) and resolve it
    at the end; otherwise we stream tokens as they arrive.
    """
    extra = _history_queries(question, history)
    scored = retrieve_scored(question, collection=collection, extra_queries=extra or None)
    chunks = [s.chunk for s in scored]

    top_score = max((s.score for s in scored), default=0.0)
    auto_deep = settings.use_reranker and bool(scored) and top_score < settings.deep_escalate_below
    use_deep = deep or auto_deep

    if use_deep and (rewrite := _deep_rewrite(question, building_context)):
        scored = retrieve_scored(question, collection=collection,
                                 extra_queries=extra + [rewrite])
        chunks = [s.chunk for s in scored]

    conf, band = _confidence(scored)

    system = _system_prompt(active_cycle_block)
    user = _build_user_block(question, building_context, render_sources(chunks),
                             history=history) + _OUTPUT_PROTOCOL
    gen_provider = provider or (settings.deep_provider if use_deep else settings.generation_provider)
    model = settings.deep_model if use_deep else None

    buffer: list[str] = []
    mode: str | None = None          # undecided -> "answer" | "json"
    try:
        for delta in llm.chat_stream(system, user, provider=gen_provider, model=model):
            buffer.append(delta)
            if mode is None:
                head = "".join(buffer).lstrip()
                if not head:
                    continue
                mode = "json" if head[0] == "{" else "answer"
                if mode == "answer":
                    yield {"type": "token", "text": "".join(buffer)}  # flush what we buffered
            elif mode == "answer":
                yield {"type": "token", "text": delta}
    except Exception as e:                                              # transport/model failure
        # Tokens already streamed are on the marshal's screen — the safety net must still run on
        # them. Validate the partial text and finalize with a meta carrying the verdict plus a
        # truncation warning, so a fabricated citation in a half-delivered answer doesn't slip
        # past unflagged. Only when NOTHING useful was delivered do we emit a bare error.
        partial = "".join(buffer)
        if mode == "answer" and partial.strip():
            ok, unverified, suffix = True, [], ""
            if settings.validate_citations:
                check = citations.validate(partial, chunks)
                suffix = citations.annotate(partial, check)[len(partial):]
                ok, unverified = check.ok, check.unverified
            suffix = (suffix + "\n\n" if suffix else "\n\n") + \
                "⚠️ The answer was cut off by a connection failure — treat it as incomplete."
            yield {"type": "meta", "sources": chunks, "citations_ok": ok,
                   "unverified": unverified, "answer_suffix": suffix, "escalated": use_deep,
                   "confidence": conf, "confidence_band": band}
        else:
            yield {"type": "error", "message": str(e)}
        yield {"type": "done"}
        return

    full = "".join(buffer)
    clar = _parse_clarification(full)
    if clar is not None:
        yield {"type": "clarify", "clarifying_questions": clar.get("questions", []),
               "chips": clar.get("chips", {}) or {}, "escalated": use_deep,
               "confidence": conf, "confidence_band": band}
        yield {"type": "done"}
        return

    if mode != "answer" and full.strip():     # was buffered as JSON but isn't a valid clarification
        yield {"type": "token", "text": full}

    suffix, ok, unverified = "", True, []
    if settings.validate_citations:
        check = citations.validate(full, chunks)
        suffix = citations.annotate(full, check)[len(full):]   # just the appended warning text
        ok, unverified = check.ok, check.unverified

    _flag_low_confidence(question, full + suffix, chunks, building_context, band)
    yield {"type": "meta", "sources": chunks, "citations_ok": ok, "unverified": unverified,
           "answer_suffix": suffix, "escalated": use_deep,
           "confidence": conf, "confidence_band": band}
    yield {"type": "done"}


def _deep_rewrite(question: str, building_context: str) -> str | None:
    """The rewritten query for deep mode's second retrieval pass. Folding the building context
    into the query pulls in chunks the bare question missed. Returns None when there's nothing to
    add (deep then falls back to a model swap only)."""
    ctx = (building_context or "").strip()
    return f"{question} — building details: {ctx}" if ctx else None


def _parse_clarification(draft: str) -> dict | None:
    """If the model returned the clarification JSON (optionally fenced), parse it; else None."""
    s = draft.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL)
    if m:
        s = m.group(1)
    if not (s.startswith("{") and '"needs_clarification"' in s):
        return None
    try:
        obj = json.loads(s)
    except (ValueError, json.JSONDecodeError):
        return None
    return obj if obj.get("needs_clarification") is True else None


# Follow-up memory bounds: how many prior exchanges inform the prompt, and how much of each
# prior ANSWER is included (answers are long; the topic usually lives in the first lines).
_HISTORY_MAX_EXCHANGES = 3
_HISTORY_ANSWER_CHARS = 600


def _history_queries(question: str, history: list[dict] | None) -> list[str]:
    """A context-carrying retrieval variant for follow-up questions, built deterministically
    from the PREVIOUS question. "what about existing buildings?" alone retrieves nothing useful;
    "<prev question> — follow-up: <question>" carries the topic terms. Fused via RRF alongside
    the literal question, so a self-contained question is never hurt by the extra variant."""
    if not history:
        return []
    prev_q = str((history[-1] or {}).get("question", "")).strip()
    if not prev_q or prev_q == question.strip():
        return []
    return [f"{prev_q} — follow-up: {question}"]


def _history_block(history: list[dict] | None) -> str:
    """Compact prior-conversation block so the model can resolve references like "that section"
    or "what about existing buildings?". Answers are truncated to keep the context lean."""
    if not history:
        return ""
    lines = ["PRIOR CONVERSATION (context only — the current question may refer to it):"]
    for ex in history[-_HISTORY_MAX_EXCHANGES:]:
        q = str((ex or {}).get("question", "")).strip()
        a = str((ex or {}).get("answer", "")).strip()
        if not q:
            continue
        if len(a) > _HISTORY_ANSWER_CHARS:
            a = a[:_HISTORY_ANSWER_CHARS].rstrip() + " …"
        lines.append(f"Q: {q}")
        if a:
            lines.append(f"A: {a}")
    return "\n" + "\n".join(lines) + "\n" if len(lines) > 1 else ""


def _build_user_block(question: str, building_context: str, sources: str,
                      history: list[dict] | None = None) -> str:
    ctx = f"\nBUILDING CONTEXT PROVIDED BY MARSHAL:\n{building_context}\n" if building_context else ""
    past = _history_block(history)
    return (
        f"{past}"
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
