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
from . import llm, citations, audit, feedback
from .retriever import retrieve_scored, render_sources

PROMPT_PATH = Path(__file__).resolve().parents[2] / "docs" / "AGENT_SYSTEM_PROMPT.md"

# Appended to the user turn so a clarification request comes back in a machine-readable shape
# without disturbing the markdown ANSWER FORMAT for normal answers.
_OUTPUT_PROTOCOL = (
    "\n\nOUTPUT PROTOCOL: Search the supplied code excerpts first. Prefer a scoped or conditional "
    "answer when a missing fact only changes a threshold. Ask for clarification only when no safe "
    "answer can be given, and ask AT MOST ONE decisive question. If clarification is required, reply "
    "with ONLY this JSON object and nothing else:\n"
    '{"needs_clarification": true, '
    '"questions": ["<one decisive question>"], '
    '"chips": {"<question>": ["<quick pick>"]}}\n'
    "The \"chips\" map is optional quick-pick suggestions. Otherwise, answer normally in the "
    "ANSWER FORMAT (markdown)."
)

_AFTER_CLARIFICATION_PROTOCOL = (
    "\n\nThe marshal has already supplied the available follow-up facts. Do not ask another "
    "clarifying question. Search the supplied excerpts and give the best grounded, conditional "
    "answer. State any remaining unknown fact as a condition rather than stopping the answer."
)

_CLARIFICATION_SYSTEM_POLICY = (
    "\n\nCURRENT APPLICATION POLICY — this overrides the general clarification guidance above: "
    "retrieved source excerpts are already available for this turn. Give a conditional, grounded "
    "answer whenever possible. If an answer truly cannot be safely scoped, ask only ONE decisive "
    "question — never a batch or a follow-up chain."
)

_AFTER_CLARIFICATION_SYSTEM_POLICY = (
    "\n\nCURRENT APPLICATION POLICY — a clarification was already collected for this turn. You MUST "
    "not ask any question or output clarification JSON. Give the best grounded conditional answer "
    "from the retrieved excerpts now, and explicitly label remaining facts as assumptions."
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
    trace: dict = field(default_factory=dict)


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


# The Chapter 541 collection is a current Connecticut legal authority, not a 2022 adopted-code
# edition. Route unmistakably statutory questions to it only when the caller did not make a manual
# library choice. A bare "29-250" is a Connecticut General Statutes citation in this jurisdiction.
_STATUTORY_QUERY = re.compile(
    r"(?:\bconnecticut\s+general\s+statutes\b|\bgeneral\s+statutes\s+of\s+connecticut\b|"
    r"\bc\.?\s*g\.?\s*s\.?\b|(?:\bsec(?:tion)?\.?|§)\s*29-\d{2,}\b|\b29-\d{2,}\b)",
    re.IGNORECASE,
)


def _effective_collection(question: str, collection: str | None) -> str | None:
    if collection is not None:
        return collection
    return settings.statutes_collection if _STATUTORY_QUERY.search(question or "") else None


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


def _determinative_facts(question: str, building_context: str, history: list[dict] | None = None) -> tuple[list[str], dict]:
    """Local clarify gate: ask only facts that change common code paths before retrieval."""
    combined = " ".join([question, building_context] + [str(x.get("question", "")) + " " + str(x.get("answer", "")) for x in (history or [])]).lower()
    if any(x in combined for x in ("i don't know", "i do not know", "unknown")):
        return [], {}
    qs, chips = [], {}
    def missing(patterns, label, options):
        if not any(p in combined for p in patterns):
            qs.append(label); chips[label] = options
    code_words = ("exit", "egress", "standpipe", "sprinkler", "fire alarm", "occupant load", "height", "story")
    if not any(w in question.lower() for w in code_words):
        return [], {}
    missing(("group ", "occupancy", "factory", "business", "assembly", "residential", "r-", "f-", "b occupancy"),
            "What is the occupancy/use group?", ["B", "F-1", "F-2", "R-2", "Mixed-use"])
    missing(("new", "existing", "alteration", "addition", "change of occupancy", "change of use"),
            "Is this new construction, an existing building, or an alteration/change of use?", ["New", "Existing", "Alteration", "Change of use"])
    if any(w in question.lower() for w in ("exit", "egress", "standpipe", "sprinkler", "height", "story")):
        missing(("sprinklered", "sprinklered", "not sprinklered", "without sprinklers"),
                "Is the building sprinklered?", ["Sprinklered", "Not sprinklered", "I don't know"])
    if any(w in question.lower() for w in ("exit", "egress", "standpipe", "height", "story")):
        missing(("story", "stories", "feet", " ft", "height", "floor level"),
                "What are the building height/stories (or highest floor elevation)?", ["1–3 stories", "4+ stories", "Over 30 ft", "I don't know"])
    if any(w in question.lower() for w in ("exit", "egress", "occupant")):
        missing(("occupant", "people", "persons", " load"),
                "What is the occupant load for the space?", ["Under 50", "50–499", "500+", "I don't know"])
    # Keep the non-streaming/MCP path as lightweight as the UI: one decisive fact at most.
    if not qs:
        return [], {}
    first = qs[0]
    return [first], {first: chips[first]}


def _trace_base(question: str, building_context: str, scored, model: str | None = None) -> dict:
    refs = [audit.chunk_ref(s.chunk, score=s.score, source="dense") for s in scored]
    return {"interpreted_query": {"normalized_question": " ".join(question.split()), "building_context": building_context,
                                   "facts_used": building_context},
            "retrieval": {"dense_terms": [question], "bm25_terms": [question] if settings.use_hybrid else [], "candidates": refs},
            "reranked": {"chunks": refs[:settings.keep_after_rerank]}, "controlling_source": [], "citation_check": [],
            "generation": {"model": model or settings.generator_model, "thinking": "off", "confidence": None}, "attempts": []}


def ask(question: str, *, mode: str = "answer", building_context: str = "",
        active_cycle_block: str = "", deep: bool = False,
        provider: str | None = None, generator_model: str | None = None,
        collection: str | None = None, history: list[dict] | None = None,
        allow_clarification: bool = True) -> AgentResult:
    # Clarify before retrieval when a missing fact changes the governing branch. Retrieve-only is
    # intentionally exempt because callers use it to inspect passages without asking for a ruling.
    missing, chips = _determinative_facts(question, building_context, history)
    if mode == "answer" and allow_clarification and missing:
        trace = {"interpreted_query": {"normalized_question": " ".join(question.split()), "building_context": building_context,
                                        "facts_used": building_context, "missing_facts": missing},
                 "retrieval": {"dense_terms": [], "bm25_terms": [], "candidates": []}, "reranked": {"chunks": []},
                 "controlling_source": [], "citation_check": [],
                 "generation": {"model": settings.generator_model, "thinking": "off", "confidence": None}, "attempts": []}
        return AgentResult(mode="answer", answer=None, sources=[], citations_ok=True, unverified=[],
                           needs_clarification=True, clarifying_questions=missing, chips=chips, trace=trace)

    # Follow-up memory: a context-carrying query variant built from the previous question, fused
    # with the literal question (RRF), so "what about existing buildings?" retrieves the topic
    # it refers to. Reranking still scores against the marshal's ORIGINAL wording.
    extra = _history_queries(question, history)
    effective_collection = _effective_collection(question, collection)
    active_edition = effective_collection or settings.active_collection
    try:
        precedent = feedback.find_precedent(question, active_edition)
    except Exception:
        precedent = None
    if precedent:
        extra.append(f"{precedent['question']} {precedent['answer']}")
    scored = retrieve_scored(question, collection=effective_collection, extra_queries=extra or None)
    chunks = [s.chunk for s in scored]

    if mode == "retrieve":
        # Pattern B: hand grounded sources back to the caller; no generation here.
        return AgentResult(mode="retrieve", answer=None, sources=chunks,
                           citations_ok=True, unverified=[])

    # Deep-mode hook: escalate a hard/low-confidence question to the stronger model. We only
    # trust the score signal when the reranker is on (otherwise scores are uniform placeholders).
    top_score = max((s.score for s in scored), default=0.0)
    deep_allowed = settings.deep_provider.lower() not in {"", "off", "false", "none", "disabled"}
    auto_deep = deep_allowed and settings.use_reranker and bool(scored) and top_score < settings.deep_escalate_below
    use_deep = deep_allowed and (deep or auto_deep)

    # Deep mode also does a SECOND retrieval pass with a rewritten query (folding in the building
    # context), then reranks the union — not just a model swap.
    if use_deep and (rewrite := _deep_rewrite(question, building_context)):
        scored = retrieve_scored(question, collection=effective_collection,
                                 extra_queries=extra + [rewrite])
        chunks = [s.chunk for s in scored]

    conf, band = _confidence(scored)

    system = _system_prompt(active_cycle_block) + _CLARIFICATION_SYSTEM_POLICY
    if not allow_clarification:
        system += _AFTER_CLARIFICATION_SYSTEM_POLICY
    user = _build_user_block(question, building_context, render_sources(chunks),
                             history=history) + (_OUTPUT_PROTOCOL if allow_clarification else _AFTER_CLARIFICATION_PROTOCOL)

    # The grounded answer path is oMLX local only. Deep is disabled unless DEEP_PROVIDER is an
    # explicitly configured cloud provider, and runtime generator switching is by model id.
    gen_provider = settings.deep_provider if use_deep else "local"
    model = settings.deep_model if use_deep else settings.assert_allowed_generator(generator_model)
    trace = _trace_base(question, building_context, scored, model)
    if precedent:
        trace["verified_precedent"] = precedent
    trace["generation"].update({"thinking": "off", "confidence": conf, "confidence_band": band})
    draft = llm.chat(system, user, provider=gen_provider, model=model)

    # Did the model ask for clarification instead of answering? Return the questions, not a guess.
    clar = _parse_clarification(draft)
    if clar is not None and allow_clarification:
        return AgentResult(mode="answer", answer=None, sources=chunks, citations_ok=True,
                           unverified=[], needs_clarification=True,
                           clarifying_questions=clar.get("questions", []),
                           chips=clar.get("chips", {}) or {}, escalated=use_deep,
                           confidence=conf, confidence_band=band, trace=trace)
    if clar is not None:
        # A model can occasionally ignore the post-clarification instruction. Re-prompt once,
        # rather than returning another chip form and trapping the marshal in a loop.
        draft = llm.chat(system, user + "\n\nYou already asked the one allowed follow-up. Give the grounded answer now.",
                         provider=gen_provider, model=model)

    # Safety net: verify every cited section actually appears in the retrieved sources. If grounding
    # fails (or retrieval is weak), retry locally with a broadened/section-targeted retrieval pass.
    check = citations.validate(draft, chunks) if settings.validate_citations else None
    ok = check.ok if check else True
    retry_reason = (not ok) or (conf is not None and conf < settings.rerank_min_score)
    attempt = 0
    while retry_reason and attempt < settings.max_retrieval_retries:
        attempt += 1
        terms = [f"{question} {building_context}".strip()]
        if check and check.unverified:
            terms.extend(check.unverified)
        scored = retrieve_scored(question, collection=effective_collection, extra_queries=extra + terms)
        chunks = [x.chunk for x in scored]
        conf, band = _confidence(scored)
        user = _build_user_block(question, building_context, render_sources(chunks), history=history) + _OUTPUT_PROTOCOL
        draft = llm.chat(system, user, provider=gen_provider, model=model)
        check = citations.validate(draft, chunks) if settings.validate_citations else None
        ok = check.ok if check else True
        retry_reason = (not ok) or (conf is not None and conf < settings.rerank_min_score)
        trace["attempts"].append({"attempt": attempt, "reason": "citation-fail-or-low-rerank", "queries": terms,
                                  "citations_ok": ok, "top_rerank_score": conf,
                                  "unverified": check.unverified if check else []})
    answer = citations.annotate(draft, check) if check else draft
    if not ok:
        answer = "⚠️ **Unverified — could not confirm in the indexed code.**\n\n" + answer
    unverified = check.unverified if check else []
    trace["reranked"] = {"chunks": [audit.chunk_ref(x.chunk, score=x.score, source="rerank") for x in scored[:settings.keep_after_rerank]]}
    trace["generation"].update({"thinking": "off", "confidence": conf, "confidence_band": band})
    trace["controlling_source"] = audit.controlling_sources(chunks, draft)
    trace["citation_check"] = audit.citation_rows(draft, chunks, check)
    trace["attempts"].append({"attempt": 0, "reason": "initial", "citations_ok": ok,
                              "top_rerank_score": conf, "unverified": unverified})
    _flag_low_confidence(question, answer, chunks, building_context, band)
    return AgentResult(mode="answer", answer=answer, sources=chunks, citations_ok=ok,
                       unverified=unverified, escalated=use_deep,
                       confidence=conf, confidence_band=band, trace=trace)


def ask_stream(question: str, *, building_context: str = "", active_cycle_block: str = "",
               deep: bool = False, provider: str | None = None, generator_model: str | None = None,
               collection: str | None = None, history: list[dict] | None = None):
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
    effective_collection = _effective_collection(question, collection)
    active_edition = effective_collection or settings.active_collection
    try:
        precedent = feedback.find_precedent(question, active_edition)
    except Exception:
        precedent = None
    if precedent:
        extra.append(f"{precedent['question']} {precedent['answer']}")
    scored = retrieve_scored(question, collection=effective_collection, extra_queries=extra or None)
    chunks = [s.chunk for s in scored]

    top_score = max((s.score for s in scored), default=0.0)
    deep_allowed = settings.deep_provider.lower() not in {"", "off", "false", "none", "disabled"}
    auto_deep = deep_allowed and settings.use_reranker and bool(scored) and top_score < settings.deep_escalate_below
    use_deep = deep_allowed and (deep or auto_deep)

    if use_deep and (rewrite := _deep_rewrite(question, building_context)):
        scored = retrieve_scored(question, collection=effective_collection,
                                 extra_queries=extra + [rewrite])
        chunks = [s.chunk for s in scored]

    conf, band = _confidence(scored)

    system = _system_prompt(active_cycle_block) + _CLARIFICATION_SYSTEM_POLICY
    user = _build_user_block(question, building_context, render_sources(chunks),
                             history=history) + _OUTPUT_PROTOCOL
    gen_provider = settings.deep_provider if use_deep else "local"
    model = settings.deep_model if use_deep else settings.assert_allowed_generator(generator_model)

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

    trace = _trace_base(question, building_context, scored, model)
    trace["generation"].update({"thinking": "off", "confidence": conf, "confidence_band": band})
    trace["controlling_source"] = audit.controlling_sources(chunks, full)
    trace["citation_check"] = audit.citation_rows(full, chunks, check)
    trace["attempts"].append({"attempt": 0, "reason": "stream-initial", "citations_ok": ok,
                              "top_rerank_score": conf, "unverified": unverified})
    _flag_low_confidence(question, full + suffix, chunks, building_context, band)
    yield {"type": "meta", "sources": chunks, "citations_ok": ok, "unverified": unverified,
           "answer_suffix": suffix, "escalated": use_deep,
           "confidence": conf, "confidence_band": band, "trace": trace}
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
    if obj.get("needs_clarification") is not True:
        return None
    # The UI has a single, deterministic continuation route. Trim a model-produced batch to
    # one question so it cannot create a question-at-a-time loop.
    questions = [str(q).strip() for q in (obj.get("questions") or []) if str(q).strip()]
    if not questions:
        return None
    question = questions[0]
    all_chips = obj.get("chips") if isinstance(obj.get("chips"), dict) else {}
    options = all_chips.get(question)
    chips = {question: options} if isinstance(options, list) else {}
    return {"questions": [question], "chips": chips}


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
