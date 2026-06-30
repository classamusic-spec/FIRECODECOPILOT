/**
 * ReviewQueue — a right-anchored slide-over drawer of flagged questions.
 *
 * These are the 👎 / low-confidence turns the marshal pushed back on (GET
 * /review-queue). Each card shows the question, a rating badge, the correction
 * note, the building context, when it was flagged, and the original answer in a
 * collapsible block so the marshal can re-read what was said.
 *
 * Behaviour: fetches when `open` flips true (re-fetch on each open so the list is
 * fresh). Esc closes; the backdrop closes on click; the close button is focused on
 * open. Loading / error / empty states all render in the navy-cockpit language.
 */
import { useEffect, useRef, useState } from "react";
import { getReviewQueue, ApiError, type ReviewItem } from "../lib/api";
import { CloseIcon, ChevronIcon, ThumbDownIcon } from "./icons";

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function ReviewQueue({ open, onClose }: Props) {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  // Fetch on open; reset back to a clean slate so a re-open re-fetches.
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setLoading(true);
    setError(null);
    setItems(null);
    getReviewQueue()
      .then((q) => alive && setItems(q.items))
      .catch((e) =>
        alive && setError(e instanceof ApiError ? e.message : "Could not load the review queue."),
      )
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [open]);

  // Esc closes; focus the close button when the drawer opens.
  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const count = items?.length ?? 0;

  return (
    <div className="fixed inset-0 z-40">
      {/* Backdrop — click anywhere outside the panel to dismiss. */}
      <button
        type="button"
        aria-label="Close review queue"
        onClick={onClose}
        className="absolute inset-0 h-full w-full cursor-default bg-navy-950/70 backdrop-blur-sm"
      />

      {/* Panel — anchored right, full height, frosted glass. */}
      <div
        role="dialog"
        aria-label="Review queue"
        aria-modal="true"
        className="glass absolute right-0 top-0 flex h-full w-full max-w-[460px] flex-col rounded-none border-y-0 border-r-0 animate-rise"
      >
        {/* Header: title + count badge + close. */}
        <div className="flex items-center gap-2.5 border-b border-white/10 px-4 py-3.5">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-navy-800 text-coral-400 ring-1 ring-white/10">
            <ThumbDownIcon className="h-4 w-4" />
          </span>
          <div className="leading-tight">
            <h2 className="text-[15px] font-semibold tracking-tight text-white">Review queue</h2>
            <p className="text-xs text-steel-400">Flagged &amp; low-confidence questions</p>
          </div>
          {count > 0 && (
            <span className="ml-1 rounded-full bg-coral-500/15 px-2 py-0.5 font-mono text-[11px] font-semibold text-coral-300">
              {count}
            </span>
          )}
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ml-auto grid h-8 w-8 shrink-0 place-items-center rounded-lg text-steel-400 transition-colors hover:bg-white/[0.06] hover:text-steel-100"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>

        {/* Body: loading / error / empty / list. */}
        <div className="scroll-thin flex-1 overflow-y-auto px-4 py-4">
          {loading && <SkeletonList />}

          {!loading && error && (
            <div className="rounded-xl border border-critical-200 bg-critical-50 px-3.5 py-3 text-sm text-critical-700">
              {error}
            </div>
          )}

          {!loading && !error && count === 0 && (
            <div className="mt-10 text-center text-sm text-steel-400">
              <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-navy-800 text-steel-500 ring-1 ring-white/10">
                <ThumbDownIcon className="h-5 w-5" />
              </div>
              No flagged questions yet — 👎 and corrections show up here.
            </div>
          )}

          {!loading && !error && count > 0 && (
            <ul className="space-y-3">
              {items!.map((item) => (
                <li key={item.id}>
                  <ReviewCard item={item} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------- subcomponents -- */

/** One flagged question, with its correction, context, timestamp + answer. */
function ReviewCard({ item }: { item: ReviewItem }) {
  const [showAnswer, setShowAnswer] = useState(false);
  const isDown = item.rating === "down";

  return (
    <div className="glass-inset p-3.5">
      {/* Question + rating badge. */}
      <div className="flex items-start gap-2">
        <p className="flex-1 text-sm font-medium leading-snug text-white">{item.question}</p>
        {isDown ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-critical-200 bg-critical-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-critical-700">
            <ThumbDownIcon className="h-3 w-3" />
            Not helpful
          </span>
        ) : (
          <span className="shrink-0 rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-steel-300">
            Flagged
          </span>
        )}
      </div>

      {/* Correction note — coral-tinted, the marshal's fix. */}
      {item.note && (
        <p className="mt-2.5 rounded-lg border border-coral-500/30 bg-coral-500/[0.08] px-3 py-2 text-[13px] leading-snug text-coral-100">
          {item.note}
        </p>
      )}

      {/* Meta row: building context chip + flagged timestamp. */}
      <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[11px]">
        {item.building_context && (
          <span className="rounded bg-white/[0.05] px-2 py-0.5 font-mono text-steel-300">
            {item.building_context}
          </span>
        )}
        <span className="text-steel-500">{formatWhen(item.created_at)}</span>
      </div>

      {/* Original answer — collapsible, scrollable. */}
      {item.answer && (
        <div className="mt-2.5">
          <button
            type="button"
            onClick={() => setShowAnswer((v) => !v)}
            aria-expanded={showAnswer}
            className="inline-flex items-center gap-1 text-xs font-medium text-steel-400 transition-colors hover:text-steel-200"
          >
            <ChevronIcon className={"h-3.5 w-3.5 transition-transform " + (showAnswer ? "rotate-90" : "")} />
            Original answer
          </button>
          {showAnswer && (
            <pre className="scroll-thin glass-inset mt-1.5 max-h-56 overflow-auto whitespace-pre-wrap break-words px-3 py-2 font-mono text-[12px] leading-relaxed text-steel-300">
              {item.answer}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

/** Loading placeholder — a few pulsing inset cards. */
function SkeletonList() {
  return (
    <ul className="space-y-3">
      {[0, 1, 2].map((i) => (
        <li key={i} className="glass-inset animate-pulse p-3.5">
          <div className="h-3.5 w-3/4 rounded bg-white/[0.06]" />
          <div className="mt-3 h-8 w-full rounded bg-white/[0.04]" />
          <div className="mt-3 h-2.5 w-1/3 rounded bg-white/[0.04]" />
        </li>
      ))}
    </ul>
  );
}

/** Format an ISO timestamp into a short, readable "flagged" line. */
function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return (
    "Flagged " +
    d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    })
  );
}
