/**
 * App — the chat shell for Fire Code CoPilot ("navy cockpit" theme).
 *
 * Layout (top to bottom):
 *   - Header: brand mark + jurisdiction/provider (from GET /health) + CycleBanner.
 *   - Message log: alternating user questions and assistant answers, scrollable.
 *   - Composer dock: textarea (Enter sends, Shift+Enter newline), coral send button,
 *     a provider toggle (Local | Anthropic), a "Deep" toggle, and a collapsible
 *     building-context field.
 *
 * Flow: send -> push a user turn + a loading assistant turn -> POST /ask -> fill it in.
 * If response.needs_clarification, ChatMessage renders ClarifyingChips; answering posts
 * /clarify (original question + assembled answers) and replaces that turn.
 */
import { useEffect, useRef, useState } from "react";
import { askStream, clarify, getHealth, getCollections, ApiError, type AskResponse, type Collection, type Health, type Provider } from "./lib/api";
import type { Turn, AssistantTurn } from "./lib/types";
import { DEMO, DEMO_VARIANT, demoAnswer, demoClarify } from "./demo";
import {
  type Thread,
  loadThreads,
  loadActiveId,
  saveActiveId,
  upsertThread,
  removeThread,
  newThreadId,
  setThreadMatter,
  knownMatters,
} from "./lib/threads";
import ChatMessage from "./components/ChatMessage";
import CycleBanner from "./components/CycleBanner";
import ReviewQueue from "./components/ReviewQueue";
import HistoryDrawer from "./components/HistoryDrawer";
import { SendIcon, StopIcon, ChevronIcon, BrandMark, SparkIcon, ListIcon, PlusIcon, ClockIcon } from "./components/icons";

let _seq = 0;
const uid = () => `${Date.now().toString(36)}-${(_seq++).toString(36)}`;

/** Distance (px) from the bottom within which we treat the log as "at bottom". */
const NEAR_BOTTOM_PX = 140;

/** In showcase mode, pre-seed the log so the UI renders fully populated. */
function demoSeed(): Turn[] {
  if (!DEMO || DEMO_VARIANT === "empty") return [];
  const q =
    DEMO_VARIANT === "clarify"
      ? "Do I need a sprinkler system for a Group R-2?"
      : "Is a sprinkler system required for an existing Group R-2 in Hartford on a change of occupancy?";
  return [
    { id: uid(), role: "user", text: q, buildingContext: "" },
    {
      id: uid(),
      role: "assistant",
      status: "done",
      question: q,
      buildingContext: "",
      response: DEMO_VARIANT === "clarify" ? demoClarify : demoAnswer,
    },
  ];
}

export default function App() {
  const [turns, setTurns] = useState<Turn[]>(demoSeed);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  const [provider, setProvider] = useState<Provider>(null); // null = backend default
  const [deep, setDeep] = useState(DEMO && DEMO_VARIANT !== "clarify");
  const [showContext, setShowContext] = useState(false);
  const [buildingContext, setBuildingContext] = useState("");

  const [health, setHealth] = useState<Health | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);

  // Stored code-edition collections + the marshal's current pick. `selectedCollection`
  // holds a collection NAME when a legacy edition is chosen, or null for the active one.
  // Best-effort: if the fetch fails or there's ≤1 collection, the selector stays hidden.
  const [collections, setCollections] = useState<Collection[]>([]);
  const [selectedCollection, setSelectedCollection] = useState<string | null>(null);

  // Local conversation persistence (non-demo only). `threads` is the saved list;
  // `activeId` is the conversation currently loaded into `turns`.
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeId, setActiveId] = useState<string>(() => newThreadId());
  const [historyOpen, setHistoryOpen] = useState(false);

  // True while new content should auto-follow the user. Flips off when the user
  // scrolls up to read; the "Latest" pill appears so they can jump back down.
  const [atBottom, setAtBottom] = useState(true);

  const logRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Holds the AbortController for the in-flight send so Stop can cancel it.
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let alive = true;
    getHealth()
      .then((h) => alive && setHealth(h))
      .catch(() => {/* header shows defaults if /health is unreachable */});
    return () => { alive = false; };
  }, []);

  // On mount (all modes — demo returns canned): load the stored code-edition
  // collections so the marshal can search a legacy cycle. Best-effort: on any
  // failure we simply leave `collections` empty and the selector never renders.
  useEffect(() => {
    let alive = true;
    getCollections()
      .then((r) => alive && setCollections(r.collections))
      .catch(() => {/* selector stays hidden if /collections is unreachable */});
    return () => { alive = false; };
  }, []);

  // On mount (NON-demo only): restore saved conversations and open the most recent.
  // Demo mode never touches localStorage — it keeps the seeded showcase turns.
  useEffect(() => {
    if (DEMO) return;
    const loaded = loadThreads();
    setThreads(loaded);
    if (loaded.length > 0) {
      const savedId = loadActiveId();
      const active = loaded.find((t) => t.id === savedId) ?? loaded[0]; // newest-first
      setActiveId(active.id);
      setTurns(active.turns);
    }
    // else: keep the fresh empty thread created in state initializers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist the active thread whenever its turns settle. We skip while a turn is
  // still loading/streaming so we only ever save completed exchanges.
  useEffect(() => {
    if (DEMO) return;
    const settling = turns.some(
      (t) => t.role === "assistant" && (t.status === "loading" || t.status === "streaming"),
    );
    if (settling || turns.length === 0) return;
    setThreads((prev) => upsertThread(prev, activeId, turns));
    saveActiveId(activeId);
  }, [turns, activeId]);

  // Smart auto-scroll: only follow new content when the user is already near the
  // bottom, so scrolling up to read isn't yanked back down on every token.
  useEffect(() => {
    if (atBottom) scrollToBottom();
  }, [turns, atBottom]);

  // ⌘K / Ctrl-K focuses the composer from anywhere in the app.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        const el = textareaRef.current;
        el?.focus();
        // Put the caret at the end if there's an existing draft.
        el?.setSelectionRange(el.value.length, el.value.length);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /** Grow the composer to fit its content (1 line up to the max-h-40 cap, then scroll). */
  function autosize(el: HTMLTextAreaElement) {
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }

  /** Smoothly pin the log to the latest message. */
  function scrollToBottom() {
    const el = logRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }

  /** Track whether the user is near the bottom; drives auto-follow + the pill. */
  function onLogScroll() {
    const el = logRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    setAtBottom(distance <= NEAR_BOTTOM_PX);
  }

  function patchTurn(id: string, patch: Partial<AssistantTurn>) {
    setTurns((prev) =>
      prev.map((t) => (t.id === id && t.role === "assistant" ? { ...t, ...patch } : t)),
    );
  }

  async function handleSend() {
    const question = draft.trim();
    if (!question || sending) return;
    const ctx = buildingContext.trim();
    const assistantId = uid();

    setTurns((prev) => [
      ...prev,
      { id: uid(), role: "user", text: question, buildingContext: ctx },
      { id: assistantId, role: "assistant", status: "streaming", streamText: "", question, buildingContext: ctx },
    ]);
    setDraft("");
    // Reset the auto-grown composer back to a single line after a send.
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    // A fresh send always follows the new content.
    setAtBottom(true);
    setSending(true);

    // Track this send so the Stop button can abort it.
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await askStream(
        // `collection: undefined` = the backend's active edition; a name = a legacy cycle.
        { question, building_context: ctx || undefined, deep, provider, collection: selectedCollection ?? undefined },
        {
          // Append each token to the in-progress text. Use the functional updater
          // so rapid back-to-back tokens compose instead of clobbering each other.
          onToken: (t) =>
            setTurns((prev) =>
              prev.map((turn) =>
                turn.id === assistantId && turn.role === "assistant"
                  ? { ...turn, streamText: (turn.streamText ?? "") + t }
                  : turn,
              ),
            ),
          // A clarification arrived: discard any streamed text and render chips.
          onClarify: (q, chips, escalated) =>
            patchTurn(assistantId, {
              status: "done",
              streamText: "",
              response: {
                mode: "answer",
                answer: null,
                sources: [],
                citations_ok: true,
                unverified: [],
                needs_clarification: true,
                clarifying_questions: q,
                chips,
                escalated,
                confidence: null,
                confidence_band: null,
              },
            }),
          // Finalize: the answer is the accumulated tokens + the meta suffix.
          onMeta: (m) =>
            setTurns((prev) =>
              prev.map((turn) => {
                if (turn.id !== assistantId || turn.role !== "assistant") return turn;
                const response: AskResponse = {
                  mode: "answer",
                  answer: (turn.streamText ?? "") + m.answer_suffix,
                  sources: m.sources,
                  citations_ok: m.citations_ok,
                  unverified: m.unverified,
                  needs_clarification: false,
                  clarifying_questions: [],
                  chips: {},
                  escalated: m.escalated,
                  confidence: m.confidence ?? null,
                  confidence_band: m.confidence_band ?? null,
                };
                return { ...turn, status: "done", response };
              }),
            ),
          onError: (msg) => patchTurn(assistantId, { status: "error", error: msg }),
          // Stopped by the user: finalize the turn using whatever streamed so far
          // as the answer (with a faint "(stopped)" note iff there was any text).
          onAbort: () =>
            setTurns((prev) =>
              prev.map((turn) => {
                if (turn.id !== assistantId || turn.role !== "assistant") return turn;
                const partial = turn.streamText ?? "";
                const response: AskResponse = {
                  mode: "answer",
                  answer: partial ? partial + " _(stopped)_" : "",
                  sources: [],
                  citations_ok: true,
                  unverified: [],
                  needs_clarification: false,
                  clarifying_questions: [],
                  chips: {},
                  escalated: false,
                  confidence: null,
                  confidence_band: null,
                };
                return { ...turn, status: "done", response };
              }),
            ),
        },
        { signal: controller.signal },
      );
    } catch (e) {
      patchTurn(assistantId, {
        status: "error",
        error: e instanceof ApiError ? e.message : "Unexpected error.",
      });
    } finally {
      abortRef.current = null;
      setSending(false);
      textareaRef.current?.focus();
    }
  }

  /** Stop button: abort the active stream; onAbort finalizes the turn. */
  function handleStop() {
    abortRef.current?.abort();
  }

  /** New chat: persist the current turns (if any), then open a fresh empty thread. */
  function handleNewChat() {
    if (sending) return; // don't switch away mid-stream
    // The persistence effect already saved the current thread once it settled.
    const id = newThreadId();
    setActiveId(id);
    setTurns([]);
    saveActiveId(id);
    setAtBottom(true);
    textareaRef.current?.focus();
  }

  /** Load a saved conversation into the log. */
  function handleSelectThread(id: string) {
    if (sending) return;
    const t = threads.find((x) => x.id === id);
    if (!t) return;
    setActiveId(id);
    setTurns(t.turns);
    saveActiveId(id);
    setAtBottom(true);
  }

  /** Delete a saved conversation; if it was active, drop to a fresh empty thread. */
  function handleDeleteThread(id: string) {
    setThreads((prev) => removeThread(prev, id));
    if (id === activeId) {
      const fresh = newThreadId();
      setActiveId(fresh);
      setTurns([]);
      saveActiveId(fresh);
    }
  }

  /** File (or unfile) a conversation under a matter — a street address or permit number. */
  function handleSetMatter(id: string, matter: string) {
    setThreads((prev) => setThreadMatter(prev, id, matter));
  }

  async function handleClarify(turnId: string, answers: string) {
    const turn = turns.find((t) => t.id === turnId);
    if (!turn || turn.role !== "assistant") return;
    patchTurn(turnId, { clarifying: true });
    try {
      const res = await clarify({
        question: turn.question,
        answers,
        building_context: turn.buildingContext || undefined,
        deep,
        provider,
      });
      patchTurn(turnId, { response: res, clarifying: false, status: "done" });
    } catch (e) {
      patchTurn(turnId, {
        status: "error",
        clarifying: false,
        error: e instanceof ApiError ? e.message : "Unexpected error.",
      });
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const providerLabel =
    health?.generation_provider === "anthropic" ? "Anthropic"
      : health?.generation_provider === "openai" ? "OpenAI"
        : "Local";

  // Only offer the edition picker when there's a real choice (≥2 collections).
  const showEditionSelector = collections.length >= 2;
  // A readable label for a collection: its edition years, e.g. "2021/2022".
  const editionLabel = (c: Collection) => c.editions.join("/") || c.name;
  // The currently-selected non-active collection, if any (drives the inline note).
  const legacyCollection =
    selectedCollection === null
      ? null
      : collections.find((c) => c.name === selectedCollection && !c.active) ?? null;

  return (
    <div className="flex h-screen flex-col">
      {/* ----------------------------------------------------------- Header */}
      <header className="sticky top-0 z-20 border-b border-white/10 bg-navy-950/70 backdrop-blur-xl">
        <div className="mx-auto w-full max-w-3xl px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-navy-800 text-coral-500 shadow-glow-sm ring-1 ring-white/10">
                <BrandMark className="h-6 w-6" />
              </span>
              <div className="leading-tight">
                <h1 className="text-[15px] font-semibold tracking-tight text-white">
                  Fire Code <span className="text-coral-400">CoPilot</span>
                </h1>
                <p className="text-xs text-steel-400">
                  {health?.jurisdiction ?? "Hartford, Connecticut"} · decision support
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {/* New chat — save the current conversation and start a fresh one.
                  Hidden in demo mode (persistence is off there). */}
              {!DEMO && (
                <button
                  type="button"
                  onClick={handleNewChat}
                  disabled={sending}
                  aria-label="New conversation"
                  title="New conversation"
                  className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-steel-300 transition-colors hover:border-coral-500/40 hover:bg-white/[0.07] hover:text-steel-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <PlusIcon className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">New</span>
                </button>
              )}

              {/* History — open the saved-conversations drawer. */}
              {!DEMO && (
                <button
                  type="button"
                  onClick={() => setHistoryOpen(true)}
                  aria-label="Open conversation history"
                  title="History"
                  className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-steel-300 transition-colors hover:border-coral-500/40 hover:bg-white/[0.07] hover:text-steel-100"
                >
                  <ClockIcon className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">History</span>
                </button>
              )}

              {/* Open the flagged-questions review drawer. */}
              <button
                type="button"
                onClick={() => setReviewOpen(true)}
                aria-label="Open review queue"
                className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-steel-300 transition-colors hover:border-coral-500/40 hover:bg-white/[0.07] hover:text-steel-100"
              >
                <ListIcon className="h-3.5 w-3.5" />
                Review
              </button>

              {/* Code-edition selector — search a legacy cycle for existing-building
                  questions. Only shown when the backend exposes ≥2 collections. */}
              {showEditionSelector && (
                <EditionSelector
                  collections={collections}
                  selected={selectedCollection}
                  onChange={setSelectedCollection}
                  label={editionLabel}
                />
              )}

              <div className="hidden items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 sm:flex">
                <span
                  className={"h-1.5 w-1.5 rounded-full " + (health?.ok ? "bg-verified-500 shadow-[0_0_8px] shadow-verified-500/70" : "bg-steel-500")}
                />
                <span className="text-xs font-medium text-steel-200">{providerLabel}</span>
                {health?.model && (
                  <span className="font-mono text-[11px] text-steel-400">· {health.model}</span>
                )}
              </div>
            </div>
          </div>

          <div className="mt-2.5">
            <CycleBanner />
          </div>
        </div>
      </header>

      {/* ------------------------------------------------------- Message log */}
      <main ref={logRef} onScroll={onLogScroll} className="scroll-thin flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-5 px-4 py-6">
          {turns.length === 0 ? (
            <EmptyState onPick={(ex) => { setDraft(ex); textareaRef.current?.focus(); }} />
          ) : (
            turns.map((t) => <ChatMessage key={t.id} turn={t} onClarify={handleClarify} />)
          )}
        </div>
      </main>

      {/* ---------------------------------------------------------- Composer */}
      <footer className="relative border-t border-white/10 bg-navy-950/70 backdrop-blur-xl">
        {/* "Jump to latest" pill — floats above the composer when the user has
            scrolled up while new content is arriving. */}
        {!atBottom && turns.length > 0 && (
          <button
            type="button"
            onClick={() => { setAtBottom(true); scrollToBottom(); }}
            className="glass absolute -top-12 left-1/2 z-10 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium text-steel-200 shadow-card transition hover:text-white active:scale-95 animate-rise"
          >
            <ChevronIcon className="h-3.5 w-3.5 rotate-90" />
            Latest
          </button>
        )}

        <div className="mx-auto w-full max-w-3xl px-4 py-3">
          {/* Off-active-edition notice — makes it obvious the answers won't come from
              the currently adopted cycle (the system prompt already warns not to blend). */}
          {legacyCollection && (
            <div className="mb-2 inline-flex items-center gap-1.5 rounded-md border border-coral-500/30 bg-coral-500/10 px-2.5 py-1 text-xs font-medium text-coral-200 animate-rise">
              <span className="h-1.5 w-1.5 rounded-full bg-coral-500 shadow-glow-sm" />
              Searching the {editionLabel(legacyCollection)} edition — not the active cycle
            </div>
          )}

          {/* Collapsible building-context field. */}
          <div className="mb-2">
            <button
              type="button"
              onClick={() => setShowContext((v) => !v)}
              aria-expanded={showContext}
              className="inline-flex items-center gap-1 text-xs font-medium text-steel-400 transition-colors hover:text-steel-200"
            >
              <ChevronIcon className={"h-3.5 w-3.5 transition-transform " + (showContext ? "rotate-90" : "")} />
              Building context
              {buildingContext.trim() && !showContext && (
                <span className="ml-1 rounded bg-coral-500/15 px-1.5 py-0.5 font-mono text-[10px] text-coral-300">set</span>
              )}
            </button>
            {showContext && (
              <textarea
                value={buildingContext}
                onChange={(e) => setBuildingContext(e.target.value)}
                rows={2}
                placeholder="Occupancy, new vs. existing, construction type, height/area, sprinklered… (applies to your questions)"
                className="scroll-thin mt-1.5 w-full resize-y rounded-lg border border-white/10 bg-navy-950/60 px-3 py-2 text-sm text-steel-100 placeholder:text-steel-500 focus:border-coral-500/50"
              />
            )}
          </div>

          {/* Input row. */}
          <div className="glass flex items-end gap-2 p-2">
            <label htmlFor="composer" className="sr-only">Ask a code question</label>
            <textarea
              id="composer"
              ref={textareaRef}
              value={draft}
              // Grow with content (1 → ~8 lines, then scroll): reset to auto so the
              // height shrinks on delete, then size to the content's scrollHeight.
              onChange={(e) => { setDraft(e.target.value); autosize(e.currentTarget); }}
              onKeyDown={onKeyDown}
              rows={1}
              placeholder="Ask a code question…  (Enter to send · Shift+Enter for a new line)"
              className="scroll-thin max-h-40 min-h-[2.75rem] w-full resize-none bg-transparent px-2.5 py-2.5 text-[15px] leading-relaxed text-steel-100 placeholder:text-steel-500 focus:outline-none"
            />
            {/* ⌘K hint — muted, hidden on small screens. */}
            <kbd className="mb-2.5 hidden select-none items-center rounded-md border border-white/10 bg-white/[0.03] px-1.5 py-0.5 font-mono text-[10px] text-steel-500 sm:inline-flex">
              ⌘K
            </kbd>
            {sending ? (
              // While streaming, the coral button becomes a Stop (abort) control.
              <button
                type="button"
                onClick={handleStop}
                aria-label="Stop generating"
                className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-coral-500 text-white shadow-glow transition hover:bg-coral-400 active:scale-95"
              >
                <StopIcon className="h-[18px] w-[18px]" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSend}
                disabled={!draft.trim()}
                aria-label="Send question"
                className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-coral-500 text-white shadow-glow transition hover:bg-coral-400 active:scale-95 disabled:cursor-not-allowed disabled:bg-steel-700 disabled:text-steel-500 disabled:shadow-none disabled:active:scale-100"
              >
                <SendIcon className="h-[18px] w-[18px]" />
              </button>
            )}
          </div>

          {/* Option toggles. */}
          <div className="mt-2.5 flex flex-wrap items-center gap-3 text-xs">
            <ProviderToggle value={provider} onChange={setProvider} />
            <button
              type="button"
              onClick={() => setDeep((v) => !v)}
              aria-pressed={deep}
              className={
                "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 font-medium transition active:scale-95 " +
                (deep
                  ? "border-coral-500/50 bg-coral-500/15 text-coral-200"
                  : "border-white/10 bg-white/[0.03] text-steel-400 hover:text-steel-200")
              }
            >
              <SparkIcon className="h-3.5 w-3.5" />
              Deep
            </button>
            <span className="text-steel-500">escalate hard questions to the stronger model</span>
          </div>
        </div>
      </footer>

      {/* Flagged-questions review + verified-answers drawer (slide-over). */}
      <ReviewQueue open={reviewOpen} onClose={() => setReviewOpen(false)} />

      {/* Local conversation-history drawer (slide-over). */}
      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        threads={threads}
        activeId={activeId}
        onSelect={handleSelectThread}
        onDelete={handleDeleteThread}
        onSetMatter={handleSetMatter}
        knownMatters={knownMatters(threads)}
      />
    </div>
  );
}

/* ----------------------------------------------------------- subcomponents -- */

/** Segmented Local | Anthropic provider control. `null` keeps the backend default. */
function ProviderToggle({ value, onChange }: { value: Provider; onChange: (p: Provider) => void }) {
  const opts: { label: string; val: Provider }[] = [
    { label: "Local", val: "local" },
    { label: "OpenAI", val: "openai" },
    { label: "Anthropic", val: "anthropic" },
  ];
  return (
    <div className="inline-flex items-center overflow-hidden rounded-md border border-white/10 bg-white/[0.03]" role="group" aria-label="Generation provider">
      <span className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-steel-500">Provider</span>
      {opts.map((o) => {
        const active = value === o.val;
        return (
          <button
            key={o.label}
            type="button"
            onClick={() => onChange(active ? null : o.val)}
            aria-pressed={active}
            className={
              "border-l border-white/10 px-2.5 py-1.5 font-medium transition-colors " +
              (active ? "bg-coral-500 text-white" : "text-steel-400 hover:bg-white/[0.05] hover:text-steel-200")
            }
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * EditionSelector — a compact, on-theme native <select> for choosing which stored
 * code-edition collection to search. The value is the collection NAME; picking the
 * active collection resolves to `null` (the caller then omits `collection`, so the
 * backend uses its own active edition). Native select = keyboard-accessible for free.
 */
function EditionSelector({
  collections,
  selected,
  onChange,
  label,
}: {
  collections: Collection[];
  selected: string | null;
  onChange: (name: string | null) => void;
  label: (c: Collection) => string;
}) {
  const active = collections.find((c) => c.active);
  return (
    <select
      aria-label="Code edition"
      title="Code edition to search"
      // Empty value = the active edition (stored as null).
      value={selected ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      className={
        "glass cursor-pointer appearance-none rounded-full px-3 py-1.5 text-xs font-medium " +
        "text-steel-200 transition-colors hover:text-steel-100 focus:outline-none " +
        (selected ? "text-coral-200" : "")
      }
    >
      {/* The active edition — no name passed, so the backend uses its default. */}
      <option value="" className="bg-navy-900 text-steel-100">
        {active ? `${label(active)} · active` : "Active edition"}
      </option>
      {collections
        .filter((c) => !c.active)
        .map((c) => (
          <option key={c.name} value={c.name} className="bg-navy-900 text-steel-100">
            {label(c)} (legacy)
          </option>
        ))}
    </select>
  );
}

/** Futuristic first-run state with example prompts. */
function EmptyState({ onPick }: { onPick: (ex: string) => void }) {
  const examples = [
    "When is a sprinkler system required for an existing Group R-2?",
    "What's the minimum egress width for a B occupancy with 120 occupants?",
    "Does the CT amendment change fire-rated corridor requirements?",
  ];
  return (
    <div className="mx-auto mt-10 max-w-prose text-center animate-rise">
      <div className="mx-auto mb-5 grid h-16 w-16 place-items-center rounded-2xl bg-navy-800 text-coral-500 shadow-glow ring-1 ring-white/10 animate-glowpulse">
        <BrandMark className="h-9 w-9" />
      </div>
      <h2 className="text-xl font-semibold tracking-tight text-white">
        Ask your adopted fire &amp; building codes
      </h2>
      <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-steel-400">
        Answers are pinned to the currently adopted Connecticut editions, cite the exact section,
        and show the source text so you can verify. Decision support — you remain the AHJ.
      </p>
      <div className="mx-auto mt-6 grid max-w-md gap-2 text-left">
        {examples.map((ex) => (
          <button
            key={ex}
            type="button"
            onClick={() => onPick(ex)}
            className="group flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5 text-sm text-steel-300 transition active:scale-[0.98] hover:border-coral-500/40 hover:bg-white/[0.06] hover:text-steel-100"
          >
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-coral-500/70 transition group-hover:bg-coral-400" />
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}
