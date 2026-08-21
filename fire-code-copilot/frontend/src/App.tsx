/**
 * App — the chat shell for Fire Code CoPilot ("navy cockpit" theme).
 *
 * Layout (top to bottom):
 *   - Header: brand mark + jurisdiction/provider (from GET /health) + CycleBanner.
 *   - Message log: alternating user questions and assistant answers, scrollable.
 *   - Composer dock: textarea (Enter sends, Shift+Enter newline), coral send button,
 *     a runtime oMLX generator switcher, thinking-off/deep-off badges, and a collapsible
 *     building-context field.
 *
 * Flow: send -> push a user turn + a loading assistant turn -> POST /ask -> fill it in.
 * If response.needs_clarification, ChatMessage renders ClarifyingChips; answering posts
 * /clarify (original question + assembled answers) and replaces that turn.
 */
import { useEffect, useRef, useState } from "react";
import { askStream, clarify, getHealth, getCollections, getModelConfig, getRuntimeStatus, ApiError, type AskResponse, type Collection, type Health, type ModelConfig } from "./lib/api";
import type { Turn, AssistantTurn } from "./lib/types";
import { DEMO, DEMO_VARIANT, demoAnswer, demoClarify } from "./demo";
import {
  type Thread,
  loadThreads,
  loadActiveId,
  saveActiveId,
  upsertThread,
  saveStartedThread,
  removeThread,
  newThreadId,
  setThreadMatter,
  knownMatters,
  groupByMatter,
} from "./lib/threads";
import ChatMessage from "./components/ChatMessage";
import CycleBanner from "./components/CycleBanner";
import ReviewQueue from "./components/ReviewQueue";
import LibraryDrawer from "./components/LibraryDrawer";
import HistoryDrawer from "./components/HistoryDrawer";
import RuntimeDrawer from "./components/RuntimeDrawer";
import { SendIcon, StopIcon, ChevronIcon, BrandMark, ListIcon, PlusIcon, ClockIcon, BookIcon } from "./components/icons";

let _seq = 0;
const uid = () => `${Date.now().toString(36)}-${(_seq++).toString(36)}`;

/** Distance (px) from the bottom within which we treat the log as "at bottom". */
const NEAR_BOTTOM_PX = 140;

/**
 * The last few completed Q&A exchanges, oldest-first — sent with each request so the backend
 * can resolve follow-ups ("what about existing buildings?") against what they refer to.
 */
function recentExchanges(turns: Turn[]): { question: string; answer: string }[] {
  const out: { question: string; answer: string }[] = [];
  for (let i = 0; i < turns.length - 1; i++) {
    const u = turns[i];
    const a = turns[i + 1];
    if (u.role === "user" && a.role === "assistant" && a.status === "done" && a.response?.answer) {
      out.push({ question: u.text, answer: a.response.answer });
    }
  }
  return out.slice(-3);
}

/**
 * Repair turns restored from storage after an interrupted session: a turn saved while
 * streaming/loading (tab closed mid-answer) would render a caret forever AND block the
 * persistence effect for the whole thread; a persisted `clarifying: true` leaves the chips
 * stuck on a disabled "Working…" button. Both become inert, explained states.
 */
function sanitizeRestoredTurns(turns: Turn[]): Turn[] {
  let changed = false;
  const out = turns.map((t) => {
    if (t.role !== "assistant") return t;
    if (t.status === "streaming" || t.status === "loading") {
      changed = true;
      return { ...t, status: "error" as const, streamText: "",
               error: "This answer was interrupted (the app closed while it was streaming). Ask again." };
    }
    if (t.clarifying) {
      changed = true;
      return { ...t, clarifying: false };
    }
    return t;
  });
  // Same reference when clean, so loading a thread for viewing isn't mistaken for an edit
  // (the persistence effect skips reference-identical turns and won't bump updatedAt).
  return changed ? out : turns;
}

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

  // Provider/deep are intentionally fixed: grounded answers use local oMLX with deep disabled.
  const [showContext, setShowContext] = useState(false);
  const [buildingContext, setBuildingContext] = useState("");

  const [health, setHealth] = useState<Health | null>(null);
  const [engineState, setEngineState] = useState<"checking" | "online" | "offline">("checking");
  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(null);
  const [selectedGenerator, setSelectedGenerator] = useState<string>("");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [runtimeOpen, setRuntimeOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

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
  const didAutoScroll = useRef(false);

  useEffect(() => {
    let alive = true;
    getHealth()
      .then((h) => {
        if (!alive) return;
        setHealth(h);
        setSelectedGenerator((current) => current || h.generator_model || h.model || "");
        // API health only proves the app backend is reachable. The runtime endpoint tells us
        // whether oMLX itself is actually running, so the header never promises a live engine
        // while the model server is stopped.
        getRuntimeStatus()
          .then((runtime) => alive && setEngineState(runtime.running ? "online" : "offline"))
          .catch(() => alive && setEngineState(h.ok ? "online" : "offline"));
      })
      .catch(() => {
        if (alive) setEngineState("offline");
      });
    getModelConfig()
      .then((m) => {
        if (!alive) return;
        setModelConfig(m);
        setSelectedGenerator((current) => current || m.active_generator || m.generator_models[0] || "");
      })
      .catch(() => {/* model switcher shows fallback from health */});
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
      setTurns(sanitizeRestoredTurns(active.turns));
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
    // The demo is an intentional first impression, so it should open at the answer
    // rather than automatically jumping past it to the feedback controls. In real
    // conversations, keep the usual follow-the-latest behavior.
    if (!didAutoScroll.current) {
      didAutoScroll.current = true;
      if (DEMO) return;
    }
    if (atBottom) scrollToBottom();
  }, [turns, atBottom]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 3800);
    return () => window.clearTimeout(timer);
  }, [notice]);

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
    const userTurn: Turn = { id: uid(), role: "user", text: question, buildingContext: ctx };
    // Snapshot follow-up memory BEFORE appending the new turns.
    const history = recentExchanges(turns);

    // Save synchronously before generation starts. Keeping the localStorage write outside a React
    // updater guarantees the question is durable before askStream runs; demo/showcase turns must
    // never enter the user's real Saved Chats store.
    if (!DEMO) {
      const startedThreads = saveStartedThread(threads, activeId, turns, userTurn);
      setThreads(startedThreads);
      saveActiveId(activeId);
    }
    setTurns((prev) => [
      ...prev,
      userTurn,
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
        { question, building_context: ctx || undefined, deep: false, provider: "local",
          generator_model: selectedGenerator || undefined,
          collection: selectedCollection ?? undefined,
          history: history.length ? history : undefined },
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
                  trace: m.trace,
                };
                return { ...turn, status: "done", response };
              }),
            ),
          // Guarded on status: if the meta already finalized this turn (done, with the full
          // answer + sources), a late transport error or Stop click must not clobber it.
          onError: (msg) =>
            setTurns((prev) =>
              prev.map((turn) =>
                turn.id === assistantId && turn.role === "assistant" && turn.status === "streaming"
                  ? { ...turn, status: "error", error: msg }
                  : turn,
              ),
            ),
          // Stopped by the user: finalize the turn using whatever streamed so far
          // as the answer (with a faint "(stopped)" note iff there was any text).
          onAbort: () =>
            setTurns((prev) =>
              prev.map((turn) => {
                if (turn.id !== assistantId || turn.role !== "assistant" || turn.status !== "streaming") return turn;
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

  // A /clarify round-trip is in flight for some turn. Like `sending`, switching threads while
  // it's pending would resolve the answer against the wrong conversation and drop it.
  const clarifyBusy = turns.some((t) => t.role === "assistant" && t.clarifying);

  /** New chat: persist the current turns (if any), then open a fresh empty thread. */
  function handleNewChat() {
    if (sending || clarifyBusy) return; // don't switch away mid-stream / mid-clarify
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
    if (sending || clarifyBusy) return;
    const t = threads.find((x) => x.id === id);
    if (!t) return;
    setActiveId(id);
    setTurns(sanitizeRestoredTurns(t.turns));
    saveActiveId(id);
    setAtBottom(true);
  }

  /** Delete a saved conversation; if it was active, drop to a fresh empty thread. */
  function handleDeleteThread(id: string) {
    if (id === activeId && (sending || clarifyBusy)) {
      // Deleting the conversation under an active stream would leave the stream running
      // invisibly with the composer locked. Stop it first; the user can delete after.
      abortRef.current?.abort();
      return;
    }
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
        deep: false,
        provider: "local",
        generator_model: selectedGenerator || undefined,
        // The follow-up must search the SAME edition the original question did.
        collection: selectedCollection ?? undefined,
        history: recentExchanges(turns),
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

  function handleRuntimeChange(running: boolean, activeModel: string, message: string) {
    setEngineState(running ? "online" : "offline");
    if (activeModel) {
      setSelectedGenerator(activeModel);
      setModelConfig((current) => current ? { ...current, active_generator: activeModel, thinking: "off" } : current);
    }
    setNotice(message);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const providerLabel =
    engineState === "online" ? "oMLX local"
      : engineState === "checking" ? "Checking local engine"
        : "Engine unavailable";
  const activeGenerator = selectedGenerator || modelConfig?.active_generator || health?.generator_model || health?.model || "";

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
    <div className="app-shell flex h-screen overflow-hidden">
      {!DEMO && (
        <SavedChatsSidebar
          threads={threads}
          activeId={activeId}
          sending={sending || clarifyBusy}
          onNew={handleNewChat}
          onSelect={handleSelectThread}
          onDelete={handleDeleteThread}
        />
      )}
      <div className="flex min-w-0 flex-1 flex-col">
      {/* ----------------------------------------------------------- Header */}
      <header className="sticky top-0 z-20 border-b border-white/10 bg-navy-950/70 backdrop-blur-xl">
        <div className="mx-auto w-full max-w-6xl px-3 py-3 sm:px-5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-navy-800 text-coral-500 shadow-glow-sm ring-1 ring-white/10">
                <BrandMark className="h-6 w-6" />
              </span>
              <div className="min-w-0 leading-tight">
                {/* The wordmark never truncates — the controls give up their labels first. */}
                <h1 className="whitespace-nowrap text-[15px] font-semibold tracking-tight text-white">
                  Fire Code <span className="text-coral-400">CoPilot</span>
                </h1>
                {/* Truncates instead of wrapping: a long jurisdiction string used to stack into a
                    ragged column on narrow screens and triple the header's height. Hidden on the
                    smallest widths, where the controls need the room more than the subtitle does. */}
                <p className="hidden truncate text-xs text-steel-400 sm:block">
                  {health?.jurisdiction ?? "Hartford, Connecticut"} · decision support
                </p>
              </div>
            </div>

            {/* shrink-0 so the controls keep their full size and the brand truncates instead —
                without it the pills overlapped the wordmark on a phone-width window. */}
            <div className="flex shrink-0 items-center justify-end gap-2">
              {/* New chat — save the current conversation and start a fresh one.
                  Hidden in demo mode (persistence is off there). */}
              {!DEMO && (
                <button
                  type="button"
                  onClick={handleNewChat}
                  disabled={sending}
                  aria-label="New conversation"
                  title="New conversation"
                  className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-steel-300 transition-colors hover:border-coral-500/40 hover:bg-white/[0.07] hover:text-steel-100 disabled:cursor-not-allowed disabled:opacity-50 lg:hidden"
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
                  className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-steel-300 transition-colors hover:border-coral-500/40 hover:bg-white/[0.07] hover:text-steel-100 lg:hidden"
                >
                  <ClockIcon className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">History</span>
                </button>
              )}

              {/* Open the flagged-questions review drawer. */}
              {/* Library — books, editions, and indexing. */}
              <button
                type="button"
                onClick={() => setLibraryOpen(true)}
                aria-label="Open the code-book library"
                title="Library"
                className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-steel-300 transition-colors hover:border-coral-500/40 hover:bg-white/[0.07] hover:text-steel-100"
              >
                <BookIcon className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Library</span>
              </button>

              <button
                type="button"
                onClick={() => setReviewOpen(true)}
                aria-label="Open review queue"
                className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-steel-300 transition-colors hover:border-coral-500/40 hover:bg-white/[0.07] hover:text-steel-100"
              >
                <ListIcon className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Review</span>
              </button>

              {/* Code-edition selector — search a legacy cycle for existing-building
                  questions. Only shown when the backend exposes ≥2 collections. */}
              {/* Hidden on phone widths — the pill is wide and the runtime chip and Library
                  take priority there. The active edition is still shown in "Adopted editions". */}
              {showEditionSelector && (
                <div className="hidden lg:block">
                  <EditionSelector
                    collections={collections}
                    selected={selectedCollection}
                    onChange={setSelectedCollection}
                    label={editionLabel}
                  />
                </div>
              )}

              <div
                className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-2 py-1.5 sm:gap-2 sm:px-3"
                title="Local runtime controls"
                aria-live="polite"
                aria-label={`${providerLabel}${activeGenerator ? `, ${shortModel(activeGenerator)}` : ""}`}
              >
                <span className={"h-1.5 w-1.5 shrink-0 rounded-full " + (engineState === "online" ? "bg-verified-500 shadow-[0_0_8px] shadow-verified-500/70" : engineState === "offline" ? "bg-critical-600" : "bg-steel-500 animate-blink")} />
                {/* Below sm the status dot alone carries engine state, so the model id keeps its
                    tap target instead of the chip pushing the wordmark out of the header. */}
                <span className="hidden text-[11px] font-medium text-steel-200 sm:inline lg:hidden">{engineState === "online" ? "Local" : engineState === "checking" ? "Checking" : "Offline"}</span>
                <span className="hidden text-xs font-medium text-steel-200 lg:inline">{providerLabel}</span>
                <button
                  type="button"
                  onClick={() => setRuntimeOpen(true)}
                  className="max-w-[68px] truncate rounded-md px-1 font-mono text-[10px] text-steel-300 transition hover:bg-white/[0.06] hover:text-steel-100 focus:outline-none sm:max-w-[190px] sm:text-[11px]"
                  aria-label="Open local model picker"
                  title={activeGenerator ? `Open model picker (active: ${shortModel(activeGenerator)})` : "Open model picker"}
                >
                  {activeGenerator ? shortModel(activeGenerator) : "Choose model"}
                </button>
                {engineState === "online" && <span className="hidden rounded-full border border-verified-500/20 bg-verified-500/10 px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-[0.14em] text-verified-700 xl:inline-flex">grounded</span>}
              </div>
            </div>
          </div>

          <div className="mt-2.5">
            <CycleBanner />
          </div>
        </div>
      </header>

      {notice && (
        <div role="status" aria-live="polite" className="fixed right-5 top-[5.5rem] z-30 max-w-sm rounded-xl border border-white/10 bg-navy-800/95 px-3.5 py-2.5 text-sm text-steel-100 shadow-card backdrop-blur-xl animate-rise">
          {notice}
        </div>
      )}

      {/* ------------------------------------------------------- Message log */}
      <main ref={logRef} onScroll={onLogScroll} className="scroll-thin flex-1 overflow-y-auto">
        {/* max-w-3xl + px-4 gives a 736px inner column — the exact width of the answer card's
            `max-w-prose`, so messages and the composer below share one aligned reading column. */}
        <div className={"mx-auto flex w-full max-w-3xl flex-col space-y-5 px-4 py-6" + (turns.length === 0 ? " min-h-full justify-center" : "")}>
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

        <div className="mx-auto w-full max-w-3xl px-4 py-4">
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
              // Short placeholder: the long "(Enter to send…)" hint used to wrap and get clipped by
              // the input's min-height on narrow screens. The hint now lives in the helper row below.
              placeholder="Ask a code question…"
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

          {/* Compact privacy cue — generator selection lives in the top runtime bar. The send hint
              sits here (right-aligned on wider screens) rather than inside the placeholder. */}
          <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-steel-500">
            <span className="font-medium text-steel-400">Local-only workspace</span>
            <span aria-hidden="true">·</span>
            <span>sources stay on this workstation</span>
            <span aria-hidden="true">·</span>
            <span>thinking off</span>
            <span className="ml-auto hidden sm:inline">
              <kbd className="font-mono text-steel-400">Enter</kbd> to send ·{" "}
              <kbd className="font-mono text-steel-400">Shift+Enter</kbd> for a new line
            </span>
          </div>
        </div>
      </footer>

      {/* Flagged-questions review + verified-answers drawer (slide-over). */}
      <ReviewQueue open={reviewOpen} onClose={() => setReviewOpen(false)} />

      {/* Code-book Library: setup checklist, manifest editor, indexing with live progress. */}
      <LibraryDrawer
        open={libraryOpen}
        onClose={() => setLibraryOpen(false)}
        onIndexed={() => {
          getCollections()
            .then((r) => setCollections(r.collections))
            .catch(() => {/* selector just keeps its previous list */});
        }}
      />

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
      <RuntimeDrawer
        open={runtimeOpen}
        onClose={() => setRuntimeOpen(false)}
        onRuntimeChange={handleRuntimeChange}
      />
      </div>
    </div>
  );
}

/* ----------------------------------------------------------- subcomponents -- */

function shortModel(id: string): string {
  return id.split("/").pop() ?? id;
}

/** Left rail — saved local chats are first-class, not hidden in a drawer. */
function SavedChatsSidebar({
  threads,
  activeId,
  sending,
  onNew,
  onSelect,
  onDelete,
}: {
  threads: Thread[];
  activeId: string;
  sending: boolean;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const groups = groupByMatter(threads);
  return (
    <aside className="hidden w-[310px] shrink-0 border-r border-white/[0.07] bg-navy-950/70 px-4 py-5 backdrop-blur-2xl lg:flex lg:flex-col">
      <div className="mb-5 px-2">
        <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-coral-300/80">Hartford AHJ</div>
        <div className="mt-1 font-serif text-[30px] leading-none text-white">
          Fire Code <span className="italic text-coral-300">studio</span>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-steel-400">
          Saved chats, local code books, and oMLX runtime controls. Nothing leaves the workstation.
        </p>
      </div>

      <button
        type="button"
        onClick={onNew}
        disabled={sending}
        className="mb-4 inline-flex h-11 items-center justify-center gap-2 rounded-2xl border border-coral-400/30 bg-coral-500/15 px-4 text-sm font-semibold text-coral-100 shadow-glow-sm transition hover:bg-coral-500/20 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
      >
        <PlusIcon className="h-4 w-4" />
        New inspection chat
      </button>

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="mb-2 flex items-center justify-between px-1">
          <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-steel-500">Saved chats</span>
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 font-mono text-[10px] text-steel-400">{threads.length}</span>
        </div>
        {threads.length === 0 ? (
          <div className="glass rounded-2xl p-4 text-sm leading-relaxed text-steel-400">
            Ask your first question and it will appear here automatically.
          </div>
        ) : (
          <div className="space-y-4">
            {groups.map((group) => (
              <section key={group.matter ?? "unfiled"}>
                <div className="mb-2 px-1 font-mono text-[10px] uppercase tracking-[0.18em] text-coral-300/70">
                  {group.matter ?? "Unfiled"}
                </div>
                <div className="space-y-2">
                  {group.threads.map((t) => {
                    const active = t.id === activeId;
                    return (
                      <div
                        key={t.id}
                        className={
                          "group relative rounded-2xl border transition " +
                          (active
                            ? "border-coral-400/35 bg-coral-500/12 shadow-glow-sm"
                            : "border-white/[0.07] bg-white/[0.035] hover:border-white/15 hover:bg-white/[0.06]")
                        }
                      >
                        <button
                          type="button"
                          onClick={() => onSelect(t.id)}
                          disabled={sending}
                          aria-current={active ? "page" : undefined}
                          className="w-full rounded-2xl p-3 pr-10 text-left transition active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {active && <span className="absolute left-0 top-3 bottom-3 w-[2px] rounded-r bg-coral-300 shadow-[0_0_10px] shadow-coral-400" />}
                          <div className="flex items-start gap-3">
                            <div className="mt-0.5 h-8 w-8 shrink-0 rounded-full bg-[radial-gradient(circle_at_32%_28%,rgba(255,255,255,.9),transparent_24%),radial-gradient(circle_at_60%_70%,rgba(255,92,66,.7),rgba(255,92,66,.15)_58%,rgba(255,255,255,.06))] shadow-[0_0_18px_rgba(255,92,66,.28)]" />
                            <div className="min-w-0 flex-1">
                              <div className="line-clamp-2 text-sm font-semibold leading-snug text-steel-100">{t.title}</div>
                              <div className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-steel-500">
                                {new Date(t.updatedAt).toLocaleDateString([], { month: "short", day: "numeric" })} · {t.turns.length} turns
                              </div>
                            </div>
                          </div>
                        </button>
                        <button
                          type="button"
                          onClick={() => onDelete(t.id)}
                          disabled={sending}
                          className="absolute right-2 top-2 rounded-lg px-2 py-1 text-xs text-steel-500 opacity-0 transition hover:bg-white/10 hover:text-critical-700 focus:opacity-100 group-hover:opacity-100 disabled:cursor-not-allowed"
                          aria-label={`Delete ${t.title}`}
                          title="Delete saved chat"
                        >
                          ×
                        </button>
                      </div>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>

      <div className="mt-4 rounded-2xl border border-white/[0.07] bg-white/[0.035] p-3">
        <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-coral-300/80">Wired</div>
        <div className="mt-2 flex items-center justify-between text-xs text-steel-400">
          <span>localStorage only</span>
          <span className="h-1.5 w-1.5 rounded-full bg-verified-500 shadow-[0_0_10px] shadow-verified-500/70" />
        </div>
      </div>
    </aside>
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
    // No top margin: the log centers this block vertically when the conversation is empty,
    // instead of stranding it in the upper third with a large void underneath.
    <div className="mx-auto w-full max-w-prose text-center animate-rise">
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
            className="group flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5 text-left text-sm text-steel-300 transition active:scale-[0.98] hover:border-coral-500/40 hover:bg-white/[0.06] hover:text-steel-100"
          >
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-coral-500/70 transition group-hover:bg-coral-400" />
            {/* Explicit span + text-left: as a bare flex child the wrapped second line inherited
                the parent's `text-center` and rendered ragged inside the chip. */}
            <span className="text-left">{ex}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
