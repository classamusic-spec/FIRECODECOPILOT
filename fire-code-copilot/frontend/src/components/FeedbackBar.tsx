/**
 * FeedbackBar — the learning loop at the bottom of an assistant answer.
 *
 *   👍 / 👎        -> POST /feedback with the rating.
 *   "Correct this" -> a collapsible textarea; on submit POSTs /feedback with the
 *                     note, AND offers "Save as verified answer" -> POST /verify
 *                     (sends the corrected_answer; governing_sections optional).
 *
 * All network calls go through lib/api. We surface small inline confirmations
 * and never block the rest of the UI.
 */
import { useState } from "react";
import {
  sendFeedback,
  verifyAnswer,
  ApiError,
  type Source,
  type Rating,
} from "../lib/api";
import { ThumbUpIcon, ThumbDownIcon, CheckIcon, CopyIcon, ExportIcon } from "./icons";
import { exportAnswer } from "../lib/exportAnswer";

interface Props {
  question: string;
  answer: string;
  sources: Source[];
  buildingContext: string;
}

export default function FeedbackBar({
  question,
  answer,
  sources,
  buildingContext,
}: Props) {
  // Which rating (if any) has been recorded this session.
  const [rated, setRated] = useState<Rating | null>(null);
  const [showCorrection, setShowCorrection] = useState(false);
  const [correction, setCorrection] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Short confirmation strings shown inline after a successful action.
  const [confirm, setConfirm] = useState<string | null>(null);
  const [verifiedNote, setVerifiedNote] = useState<string | null>(null);

  // Brief "Copied" state after copying the raw answer markdown (~1.5s, then revert).
  const [copied, setCopied] = useState(false);

  // Whether the Clipboard API is usable here (absent in insecure/legacy contexts).
  const canCopy =
    typeof navigator !== "undefined" && typeof navigator.clipboard?.writeText === "function";

  /** Copy the raw answer markdown to the clipboard. No-ops where the API is absent. */
  async function copyAnswer() {
    if (!canCopy) return;
    try {
      await navigator.clipboard.writeText(answer);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked (permissions/insecure context) — fail quietly */
    }
  }

  /** Record a 👍/👎. Optimistically mark it; revert on failure. */
  async function rate(rating: Rating) {
    setError(null);
    const prev = rated;
    setRated(rating);
    try {
      const res = await sendFeedback({
        question,
        answer,
        rating,
        building_context: buildingContext,
        sources,
      });
      setConfirm(
        res.queued_for_review
          ? "Thanks — flagged for review."
          : "Thanks — feedback recorded.",
      );
    } catch (e) {
      setRated(prev);
      setError(e instanceof ApiError ? e.message : "Could not send feedback.");
    }
  }

  /** Submit the correction note as down-rated feedback. */
  async function submitCorrection() {
    const note = correction.trim();
    if (!note) return;
    setBusy(true);
    setError(null);
    try {
      await sendFeedback({
        question,
        answer,
        rating: "down", // a correction implies the answer needed fixing
        note,
        building_context: buildingContext,
        sources,
      });
      setRated("down");
      setConfirm("Correction submitted.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not submit correction.");
    } finally {
      setBusy(false);
    }
  }

  /**
   * The distinct "real" governing sections behind this answer: the metadata.section
   * values from the sources, minus falsies, the "(preamble)" placeholder, and any
   * verified-library entries (those aren't primary-source sections).
   */
  function governingSections(): string[] {
    const seen = new Set<string>();
    for (const s of sources) {
      const m = s.metadata ?? {};
      const sec = m.section;
      if (!sec || sec === "(preamble)" || m.verified) continue;
      seen.add(sec);
    }
    return [...seen];
  }

  /** Promote the corrected text into the Verified Answer Library. */
  async function saveVerified() {
    const corrected = correction.trim();
    if (!corrected) return;
    setBusy(true);
    setError(null);
    try {
      const res = await verifyAnswer({
        question,
        corrected_answer: corrected,
        // Attach the answer's governing sections so the library entry is pinned to them.
        governing_sections: governingSections(),
      });
      const where = res.sections.length
        ? ` (§${res.sections.join(", §")})`
        : "";
      setVerifiedNote(`Saved to ${res.collection}${where}.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save verified answer.");
    } finally {
      setBusy(false);
    }
  }

  const ratingBtn =
    "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors";

  return (
    <div className="mt-4 border-t border-white/10 pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => rate("up")}
          aria-pressed={rated === "up"}
          aria-label="Helpful"
          className={
            ratingBtn +
            (rated === "up"
              ? " border-verified-500/40 bg-verified-500/15 text-verified-700"
              : " border-white/10 bg-white/[0.03] text-steel-400 hover:text-steel-200")
          }
        >
          <ThumbUpIcon className="h-3.5 w-3.5" />
          Helpful
        </button>

        <button
          type="button"
          onClick={() => rate("down")}
          aria-pressed={rated === "down"}
          aria-label="Not helpful"
          className={
            ratingBtn +
            (rated === "down"
              ? " border-critical-200 bg-critical-600/15 text-critical-600"
              : " border-white/10 bg-white/[0.03] text-steel-400 hover:text-steel-200")
          }
        >
          <ThumbDownIcon className="h-3.5 w-3.5" />
          Not helpful
        </button>

        <button
          type="button"
          onClick={() => setShowCorrection((v) => !v)}
          aria-expanded={showCorrection}
          className="ml-1 text-xs font-medium text-coral-300 underline decoration-coral-500/40 underline-offset-2 hover:text-coral-200"
        >
          {showCorrection ? "Hide correction" : "Correct this"}
        </button>

        {confirm && (
          <span className="inline-flex items-center gap-1 text-xs text-verified-700">
            <CheckIcon className="h-3.5 w-3.5" />
            {confirm}
          </span>
        )}

        {/* Right-aligned actions: Export this answer to PDF, then Copy the raw
            markdown. Both are unobtrusive and share the same subtle styling. */}
        <div className="ml-auto flex items-center gap-2">
          {/* Export ONLY this answer + its cited sources to a printable PDF (for the
              inspection file). Pure client-side — works in demo mode too. Shown only
              when there's an answer to export. */}
          {answer && (
            <button
              type="button"
              onClick={() => exportAnswer({ question, answer, sources })}
              aria-label="Export answer to PDF"
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-xs font-medium text-steel-400 transition active:scale-95 hover:text-steel-200"
            >
              <ExportIcon className="h-3.5 w-3.5" />
              Export
            </button>
          )}

          {/* Copy the raw answer markdown. Hidden where the Clipboard API isn't
              available (e.g. insecure contexts). */}
          {canCopy && (
            <button
              type="button"
              onClick={copyAnswer}
              aria-label="Copy answer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-xs font-medium text-steel-400 transition active:scale-95 hover:text-steel-200"
            >
              {copied ? <CheckIcon className="h-3.5 w-3.5 text-verified-700" /> : <CopyIcon className="h-3.5 w-3.5" />}
              {copied ? "Copied" : "Copy"}
            </button>
          )}
        </div>
      </div>

      {/* Collapsible correction editor + "save as verified" path. */}
      {showCorrection && (
        <div className="mt-3 space-y-2">
          <label htmlFor={`correct-${question.length}`} className="block text-[11px] font-semibold uppercase tracking-wider text-steel-400">
            Provide the correct answer or note — you can also promote it to the Verified Answer Library.
          </label>
          <textarea
            id={`correct-${question.length}`}
            value={correction}
            onChange={(e) => setCorrection(e.target.value)}
            rows={4}
            placeholder="e.g. Per CT amendment to IFC §903.2.8, an existing Group R-2 requires sprinklers when…"
            className="scroll-thin w-full resize-y rounded-lg border border-white/10 bg-navy-950/60 px-3 py-2 text-sm text-steel-100 placeholder:text-steel-500 focus:border-coral-500/50"
          />
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={submitCorrection}
              disabled={busy || !correction.trim()}
              className="rounded-lg bg-steel-700 px-3 py-1.5 text-xs font-semibold text-steel-100 transition-colors hover:bg-steel-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Submit correction
            </button>
            <button
              type="button"
              onClick={saveVerified}
              disabled={busy || !correction.trim()}
              className="rounded-lg border border-coral-500/50 bg-coral-500/10 px-3 py-1.5 text-xs font-semibold text-coral-200 transition-colors hover:bg-coral-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Save as verified answer
            </button>
            {verifiedNote && (
              <span className="inline-flex items-center gap-1 text-xs text-coral-200">
                <CheckIcon className="h-3.5 w-3.5" />
                {verifiedNote}
              </span>
            )}
          </div>
        </div>
      )}

      {error && (
        <p className="mt-2 text-xs text-critical-600" role="alert">{error}</p>
      )}
    </div>
  );
}
