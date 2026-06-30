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
import { ask, clarify, getHealth, ApiError, type Health, type Provider } from "./lib/api";
import type { Turn, AssistantTurn } from "./lib/types";
import { DEMO, DEMO_VARIANT, demoAnswer, demoClarify } from "./demo";
import ChatMessage from "./components/ChatMessage";
import CycleBanner from "./components/CycleBanner";
import { SendIcon, ChevronIcon, BrandMark, SparkIcon } from "./components/icons";

let _seq = 0;
const uid = () => `${Date.now().toString(36)}-${(_seq++).toString(36)}`;

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

  const logRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let alive = true;
    getHealth()
      .then((h) => alive && setHealth(h))
      .catch(() => {/* header shows defaults if /health is unreachable */});
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

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
      { id: assistantId, role: "assistant", status: "loading", question, buildingContext: ctx },
    ]);
    setDraft("");
    setSending(true);
    try {
      const res = await ask({ question, building_context: ctx || undefined, deep, provider });
      patchTurn(assistantId, { status: "done", response: res });
    } catch (e) {
      patchTurn(assistantId, {
        status: "error",
        error: e instanceof ApiError ? e.message : "Unexpected error.",
      });
    } finally {
      setSending(false);
      textareaRef.current?.focus();
    }
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

  const providerLabel = health?.generation_provider === "anthropic" ? "Anthropic" : "Local";

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

          <div className="mt-2.5">
            <CycleBanner />
          </div>
        </div>
      </header>

      {/* ------------------------------------------------------- Message log */}
      <main ref={logRef} className="scroll-thin flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-5 px-4 py-6">
          {turns.length === 0 ? (
            <EmptyState onPick={(ex) => { setDraft(ex); textareaRef.current?.focus(); }} />
          ) : (
            turns.map((t) => <ChatMessage key={t.id} turn={t} onClarify={handleClarify} />)
          )}
        </div>
      </main>

      {/* ---------------------------------------------------------- Composer */}
      <footer className="border-t border-white/10 bg-navy-950/70 backdrop-blur-xl">
        <div className="mx-auto w-full max-w-3xl px-4 py-3">
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
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
              placeholder="Ask a code question…  (Enter to send · Shift+Enter for a new line)"
              className="scroll-thin max-h-40 min-h-[2.75rem] w-full resize-none bg-transparent px-2.5 py-2.5 text-[15px] leading-relaxed text-steel-100 placeholder:text-steel-500 focus:outline-none"
            />
            <button
              type="button"
              onClick={handleSend}
              disabled={!draft.trim() || sending}
              aria-label="Send question"
              className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-coral-500 text-white shadow-glow transition hover:bg-coral-400 disabled:cursor-not-allowed disabled:bg-steel-700 disabled:text-steel-500 disabled:shadow-none"
            >
              <SendIcon className="h-[18px] w-[18px]" />
            </button>
          </div>

          {/* Option toggles. */}
          <div className="mt-2.5 flex flex-wrap items-center gap-3 text-xs">
            <ProviderToggle value={provider} onChange={setProvider} />
            <button
              type="button"
              onClick={() => setDeep((v) => !v)}
              aria-pressed={deep}
              className={
                "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 font-medium transition-colors " +
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
    </div>
  );
}

/* ----------------------------------------------------------- subcomponents -- */

/** Segmented Local | Anthropic provider control. `null` keeps the backend default. */
function ProviderToggle({ value, onChange }: { value: Provider; onChange: (p: Provider) => void }) {
  const opts: { label: string; val: Provider }[] = [
    { label: "Local", val: "local" },
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
            className="group flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5 text-sm text-steel-300 transition-colors hover:border-coral-500/40 hover:bg-white/[0.06] hover:text-steel-100"
          >
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-coral-500/70 transition group-hover:bg-coral-400" />
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}
