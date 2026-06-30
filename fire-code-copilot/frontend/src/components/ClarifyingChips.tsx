/**
 * ClarifyingChips — shown for a turn when the backend asked for more facts
 * before it will answer (response.needs_clarification === true).
 *
 * Renders each clarifying question, then ALL chip groups from `chips` (a map of
 * category -> options, e.g. { Occupancy: ["R-2","B"], Sprinklered: ["Yes","No"] }).
 * Selecting chips plus an optional free-text builds an `answers` string like
 * "Occupancy: R-2; Sprinklered: No" and "Continue" hands it back to App, which
 * POSTs /clarify with the original question + assembled answers.
 */
import { useMemo, useState } from "react";

interface Props {
  questions: string[];
  /** category -> quick-pick options */
  chips: Record<string, string[]>;
  /** disabled while the /clarify request is in flight */
  busy?: boolean;
  /** App POSTs /clarify with this assembled answers string */
  onContinue: (answers: string) => void;
}

export default function ClarifyingChips({
  questions,
  chips,
  busy = false,
  onContinue,
}: Props) {
  // Selected chip per category (single-select per group keeps the answer crisp).
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [freeText, setFreeText] = useState("");

  const categories = Object.keys(chips);

  /** Toggle a chip: clicking the active one clears it. */
  function pick(category: string, value: string) {
    setSelected((prev) => {
      const next = { ...prev };
      if (next[category] === value) delete next[category];
      else next[category] = value;
      return next;
    });
  }

  // Assemble "Category: value; Category: value" + any free-text addendum.
  const answers = useMemo(() => {
    const parts = categories
      .filter((c) => selected[c])
      .map((c) => `${c}: ${selected[c]}`);
    const extra = freeText.trim();
    if (extra) parts.push(extra);
    return parts.join("; ");
  }, [categories, selected, freeText]);

  const canContinue = answers.length > 0 && !busy;

  return (
    <div className="rounded-xl border border-coral-500/30 bg-coral-500/[0.06] p-4">
      <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-coral-300">
        <span className="h-1.5 w-1.5 rounded-full bg-coral-500" />
        A few details change the answer
      </p>

      {questions.length > 0 && (
        <ul className="mt-2.5 space-y-1.5 text-sm text-steel-100">
          {questions.map((q, i) => (
            <li key={i} className="flex gap-2">
              <span className="select-none text-coral-400">•</span>
              <span>{q}</span>
            </li>
          ))}
        </ul>
      )}

      {categories.length > 0 && (
        <div className="mt-4 space-y-3">
          {categories.map((category) => (
            <div key={category}>
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-steel-400">{category}</div>
              <div className="flex flex-wrap gap-1.5">
                {chips[category].map((opt) => {
                  const active = selected[category] === opt;
                  return (
                    <button
                      key={opt}
                      type="button"
                      onClick={() => pick(category, opt)}
                      aria-pressed={active}
                      className={
                        "rounded-full border px-3 py-1 text-xs font-medium transition active:scale-95 " +
                        (active
                          ? "border-coral-500 bg-coral-500 text-white shadow-glow-sm"
                          : "border-white/15 bg-white/[0.04] text-steel-300 hover:border-coral-500/40 hover:text-steel-100")
                      }
                    >
                      {opt}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mt-4">
        <label htmlFor="clarify-free" className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-steel-400">
          Anything else (optional)
        </label>
        <input
          id="clarify-free"
          type="text"
          value={freeText}
          onChange={(e) => setFreeText(e.target.value)}
          placeholder="e.g. 4 stories, ~28,000 sq ft, built 1996"
          className="w-full rounded-lg border border-white/10 bg-navy-950/60 px-3 py-2 text-sm text-steel-100 placeholder:text-steel-500 focus:border-coral-500/50"
          onKeyDown={(e) => { if (e.key === "Enter" && canContinue) onContinue(answers); }}
        />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => onContinue(answers)}
          disabled={!canContinue}
          className="rounded-lg bg-coral-500 px-4 py-2 text-sm font-semibold text-white shadow-glow transition active:scale-95 hover:bg-coral-400 disabled:cursor-not-allowed disabled:bg-steel-700 disabled:text-steel-500 disabled:shadow-none disabled:active:scale-100"
        >
          {busy ? "Working…" : "Continue"}
        </button>
        {answers && <span className="font-mono text-xs text-steel-400">{answers}</span>}
      </div>
    </div>
  );
}
