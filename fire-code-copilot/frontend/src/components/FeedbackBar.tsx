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
import { ThumbUpIcon, ThumbDownIcon, CheckIcon } from "./icons";

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
        // governing_sections is optional per the contract; we send none here.
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
    "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors";

  return (
    <div className="mt-3 border-t border-slate-200/70 pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => rate("up")}
          aria-pressed={rated === "up"}
          aria-label="Helpful"
          className={
            ratingBtn +
            (rated === "up"
              ? " border-emerald-300 bg-emerald-50 text-emerald-700"
              : " border-slate-200 text-ink-muted hover:bg-slate-50")
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
              ? " border-critical-200 bg-critical-50 text-critical-700"
              : " border-slate-200 text-ink-muted hover:bg-slate-50")
          }
        >
          <ThumbDownIcon className="h-3.5 w-3.5" />
          Not helpful
        </button>

        <button
          type="button"
          onClick={() => setShowCorrection((v) => !v)}
          aria-expanded={showCorrection}
          className="ml-1 text-xs font-medium text-slate-700 underline underline-offset-2 hover:text-slate-900"
        >
          {showCorrection ? "Hide correction" : "Correct this"}
        </button>

        {confirm && (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
            <CheckIcon className="h-3.5 w-3.5" />
            {confirm}
          </span>
        )}
      </div>

      {/* Collapsible correction editor + "save as verified" path. */}
      {showCorrection && (
        <div className="mt-3 space-y-2">
          <label
            htmlFor={`correct-${question.length}`}
            className="block text-xs font-medium text-ink-muted"
          >
            Provide the correct answer or note. You can also promote it to the
            Verified Answer Library.
          </label>
          <textarea
            id={`correct-${question.length}`}
            value={correction}
            onChange={(e) => setCorrection(e.target.value)}
            rows={4}
            placeholder="e.g. Per CT amendment to IFC §903.2.8, an existing Group R-2 requires sprinklers when…"
            className="scroll-thin w-full resize-y rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-slate-400"
          />
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={submitCorrection}
              disabled={busy || !correction.trim()}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Submit correction
            </button>
            <button
              type="button"
              onClick={saveVerified}
              disabled={busy || !correction.trim()}
              className="rounded-md border border-safety-600 bg-safety-50 px-3 py-1.5 text-xs font-semibold text-safety-700 transition-colors hover:bg-safety-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Save as verified answer
            </button>
            {verifiedNote && (
              <span className="inline-flex items-center gap-1 text-xs text-safety-700">
                <CheckIcon className="h-3.5 w-3.5" />
                {verifiedNote}
              </span>
            )}
          </div>
        </div>
      )}

      {error && (
        <p className="mt-2 text-xs text-critical-700" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
