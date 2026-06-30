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
    <div className="rounded-lg border border-safety-200 bg-safety-50/60 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-safety-700">
        A few details change the answer
      </p>

      {/* The questions the marshal needs to resolve. */}
      {questions.length > 0 && (
        <ul className="mt-2 space-y-1 text-sm text-ink">
          {questions.map((q, i) => (
            <li key={i} className="flex gap-2">
              <span className="select-none text-safety-600">•</span>
              <span>{q}</span>
            </li>
          ))}
        </ul>
      )}

      {/* One row of quick-pick chips per category. */}
      {categories.length > 0 && (
        <div className="mt-4 space-y-3">
          {categories.map((category) => (
            <div key={category}>
              <div className="mb-1.5 text-xs font-medium text-ink-muted">
                {category}
              </div>
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
                        "rounded-full border px-3 py-1 text-xs font-medium transition-colors " +
                        (active
                          ? "border-slate-900 bg-slate-900 text-white"
                          : "border-slate-300 bg-white text-ink-muted hover:border-slate-400 hover:bg-slate-50")
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

      {/* Optional free-text for anything the chips don't cover. */}
      <div className="mt-4">
        <label
          htmlFor="clarify-free"
          className="mb-1.5 block text-xs font-medium text-ink-muted"
        >
          Anything else (optional)
        </label>
        <input
          id="clarify-free"
          type="text"
          value={freeText}
          onChange={(e) => setFreeText(e.target.value)}
          placeholder="e.g. 4 stories, ~28,000 sq ft, built 1996"
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-slate-400"
          onKeyDown={(e) => {
            if (e.key === "Enter" && canContinue) onContinue(answers);
          }}
        />
      </div>

      {/* Live preview of the assembled answers string, then Continue. */}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => onContinue(answers)}
          disabled={!canContinue}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Working…" : "Continue"}
        </button>
        {answers && (
          <span className="font-mono text-xs text-ink-muted">{answers}</span>
        )}
      </div>
    </div>
  );
}
