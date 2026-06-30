/**
 * App — the chat shell for Fire Code CoPilot.
 *
 * Layout (top to bottom):
 *   - Header: app name + jurisdiction/provider (from GET /health) + CycleBanner.
 *   - Message log: alternating user questions and assistant answers, scrollable.
 *   - Composer: textarea (Enter sends, Shift+Enter newline), send button, a
 *     provider toggle (Local | Anthropic), a "Deep" checkbox, and a collapsible
 *     free-text "building context" field.
 *
 * Flow:
 *   send -> push a user turn + a loading assistant turn -> POST /ask -> fill it in.
 *   If response.needs_clarification, ChatMessage renders ClarifyingChips; when the
 *   marshal answers, onClarify POSTs /clarify (original question + assembled
 *   answers) and replaces that turn's response with the final answer.
 */
import { useEffect, useRef, useState } from "react";
import {
  ask,
  clarify,
  getHealth,
  ApiError,
  type Health,
  type Provider,
} from "./lib/api";
import type { Turn, AssistantTurn } from "./lib/types";
import ChatMessage from "./components/ChatMessage";
import CycleBanner from "./components/CycleBanner";
import { SendIcon, ChevronIcon } from "./components/icons";

/** Small unique-id helper (no dependency needed). */
let _seq = 0;
const uid = () => `${Date.now().toString(36)}-${(_seq++).toString(36)}`;

export default function App() {
  // ---- chat state ----
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  // ---- composer options ----
  const [provider, setProvider] = useState<Provider>(null); // null = backend default
  const [deep, setDeep] = useState(false);
  const [showContext, setShowContext] = useState(false);
  const [buildingContext, setBuildingContext] = useState("");

  // ---- header identity ----
  const [health, setHealth] = useState<Health | null>(null);

  // ---- refs ----
  const logRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Fetch backend identity once for the header.
  useEffect(() => {
    let alive = true;
    getHealth()
      .then((h) => alive && setHealth(h))
      .catch(() => {
        /* header simply shows defaults if /health is unreachable */
      });
    return () => {
      alive = false;
    };
  }, []);

  // Keep the log pinned to the latest message.
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  /** Patch a single assistant turn by id (immutably). */
  function patchTurn(id: string, patch: Partial<AssistantTurn>) {
    setTurns((prev) =>
      prev.map((t) =>
        t.id === id && t.role === "assistant" ? { ...t, ...patch } : t,
      ),
    );
  }

  /** Submit the current draft as a new question. */
  async function handleSend() {
    const question = draft.trim();
    if (!question || sending) return;

    const ctx = buildingContext.trim();
    const assistantId = uid();

    // Push the user's question and a loading assistant turn in one update.
    setTurns((prev) => [
      ...prev,
      { id: uid(), role: "user", text: question, buildingContext: ctx },
      {
        id: assistantId,
        role: "assistant",
        status: "loading",
        question,
        buildingContext: ctx,
      },
    ]);
    setDraft("");
    setSending(true);

    try {
      const res = await ask({
        question,
        building_context: ctx || undefined,
        deep,
        provider,
      });
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

  /**
   * Continue a clarified thread: POST /clarify with the original question and
   * the assembled answers, then replace this turn's response with the result.
   */
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

  /** Enter sends; Shift+Enter inserts a newline. */
  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const providerLabel =
    health?.generation_provider === "anthropic" ? "Anthropic" : "Local";

  return (
    <div className="flex h-screen flex-col bg-slate-50 text-ink">
      {/* ----------------------------------------------------------- Header */}
      <header className="border-b border-slate-200 bg-white/80 backdrop-blur">
        <div className="mx-auto w-full max-w-3xl px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              {/* Mark: a small amber square as the single accent in the wordmark. */}
              <span className="grid h-7 w-7 place-items-center rounded bg-slate-900 text-sm font-bold text-safety-500">
                FC
              </span>
              <div className="leading-tight">
                <h1 className="text-[15px] font-semibold tracking-tight text-ink">
                  Fire Code CoPilot
                </h1>
                <p className="text-xs text-ink-muted">
                  {health?.jurisdiction ?? "Hartford, CT"} · decision support,
                  not an authority
                </p>
              </div>
            </div>

            {/* Backend identity badge. */}
            <div className="hidden text-right text-xs text-ink-faint sm:block">
              <div>
                <span
                  className={
                    "inline-block h-1.5 w-1.5 rounded-full " +
                    (health?.ok ? "bg-emerald-500" : "bg-slate-300")
                  }
                />{" "}
                {providerLabel}
              </div>
              {health?.model && (
                <div className="font-mono text-[11px]">{health.model}</div>
              )}
            </div>
          </div>

          {/* Code-cycle awareness. */}
          <div className="mt-2">
            <CycleBanner />
          </div>
        </div>
      </header>

      {/* ------------------------------------------------------- Message log */}
      <main ref={logRef} className="scroll-thin flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-4 px-4 py-6">
          {turns.length === 0 ? (
            <EmptyState />
          ) : (
            turns.map((t) => (
              <ChatMessage key={t.id} turn={t} onClarify={handleClarify} />
            ))
          )}
        </div>
      </main>

      {/* ---------------------------------------------------------- Composer */}
      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto w-full max-w-3xl px-4 py-3">
          {/* Collapsible building-context field. */}
          <div className="mb-2">
            <button
              type="button"
              onClick={() => setShowContext((v) => !v)}
              aria-expanded={showContext}
              className="inline-flex items-center gap-1 text-xs font-medium text-ink-muted hover:text-ink"
            >
              <ChevronIcon
                className={
                  "h-3.5 w-3.5 transition-transform " +
                  (showContext ? "rotate-90" : "")
                }
              />
              Building context
              {buildingContext.trim() && !showContext && (
                <span className="ml-1 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-ink-muted">
                  set
                </span>
              )}
            </button>
            {showContext && (
              <textarea
                value={buildingContext}
                onChange={(e) => setBuildingContext(e.target.value)}
                rows={2}
                placeholder="Occupancy, new vs. existing, construction type, height/area, sprinklered… (applies to your questions)"
                className="scroll-thin mt-1.5 w-full resize-y rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-slate-400"
              />
            )}
          </div>

          {/* Input row. */}
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <label htmlFor="composer" className="sr-only">
                Ask a code question
              </label>
              <textarea
                id="composer"
                ref={textareaRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onKeyDown}
                rows={1}
                placeholder="Ask a code question…  (Enter to send · Shift+Enter for a new line)"
                className="scroll-thin max-h-40 w-full resize-none rounded-lg border border-slate-300 bg-white px-3.5 py-2.5 text-[15px] leading-relaxed text-ink placeholder:text-ink-faint focus:border-slate-400"
              />
            </div>
            <button
              type="button"
              onClick={handleSend}
              disabled={!draft.trim() || sending}
              aria-label="Send question"
              className="mb-0.5 grid h-11 w-11 shrink-0 place-items-center rounded-lg bg-slate-900 text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <SendIcon className="h-[18px] w-[18px]" />
            </button>
          </div>

          {/* Option toggles: provider + deep. */}
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
            <ProviderToggle value={provider} onChange={setProvider} />

            <label className="inline-flex cursor-pointer items-center gap-1.5 text-ink-muted">
              <input
                type="checkbox"
                checked={deep}
                onChange={(e) => setDeep(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-slate-300 text-slate-900 focus:ring-slate-900"
              />
              <span className="font-medium">Deep</span>
              <span className="text-ink-faint">
                (escalate hard questions to the stronger model)
              </span>
            </label>
          </div>
        </div>
      </footer>
    </div>
  );
}

/* ----------------------------------------------------------- subcomponents -- */

/** Segmented Local | Anthropic provider control. `null` keeps the backend default. */
function ProviderToggle({
  value,
  onChange,
}: {
  value: Provider;
  onChange: (p: Provider) => void;
}) {
  const opts: { label: string; val: Provider }[] = [
    { label: "Local", val: "local" },
    { label: "Anthropic", val: "anthropic" },
  ];
  return (
    <div
      className="inline-flex items-center overflow-hidden rounded-md border border-slate-200"
      role="group"
      aria-label="Generation provider"
    >
      <span className="px-2 py-1 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
        Provider
      </span>
      {opts.map((o) => {
        const active = value === o.val;
        return (
          <button
            key={o.label}
            type="button"
            onClick={() => onChange(active ? null : o.val)}
            aria-pressed={active}
            className={
              "border-l border-slate-200 px-2.5 py-1 font-medium transition-colors " +
              (active
                ? "bg-slate-900 text-white"
                : "bg-white text-ink-muted hover:bg-slate-50")
            }
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** Friendly first-run state with a couple of example prompts. */
function EmptyState() {
  return (
    <div className="mx-auto mt-10 max-w-prose text-center">
      <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-xl bg-slate-900 text-base font-bold text-safety-500">
        FC
      </div>
      <h2 className="text-lg font-semibold text-ink">
        Ask about your adopted fire & building codes
      </h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-ink-muted">
        Answers are pinned to the currently adopted Connecticut editions, cite
        the exact section, and show the source text so you can verify. This is
        decision support — you remain the authority having jurisdiction.
      </p>
      <div className="mx-auto mt-5 grid max-w-md gap-2 text-left">
        {[
          "When is a sprinkler system required for an existing Group R-2?",
          "What's the minimum egress width for a B occupancy with 120 occupants?",
          "Does the CT amendment change fire-rated corridor requirements?",
        ].map((ex) => (
          <div
            key={ex}
            className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-ink-muted"
          >
            {ex}
          </div>
        ))}
      </div>
    </div>
  );
}
