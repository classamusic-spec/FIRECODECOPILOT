/**
 * ReviewQueue — a right-anchored slide-over with TWO tabs:
 *
 *   - "Review":   the 👎 / low-confidence turns the marshal pushed back on
 *                 (GET /review-queue). Each card shows the question, a rating
 *                 badge, the correction note, the building context, when it was
 *                 flagged, and the original answer in a collapsible block.
 *   - "Verified": the marshal-confirmed Verified Answer Library (GET /verified).
 *                 Each entry shows the question, answer, governing-section chips,
 *                 and when it was verified — with a per-entry delete (confirm-on-click).
 *
 * Behaviour: fetches the active tab's data when it (re-)opens or the tab changes.
 * The shared Drawer shell handles Esc / backdrop / focus. Loading, error, and empty
 * states all render in the navy-cockpit language.
 */
import { useEffect, useState } from "react";
import {
  getReviewQueue,
  getVerified,
  deleteVerified,
  ApiError,
  type ReviewItem,
  type VerifiedItem,
} from "../lib/api";
import { ChevronIcon, ThumbDownIcon, ShieldIcon, TrashIcon } from "./icons";
import Drawer from "./Drawer";

interface Props {
  open: boolean;
  onClose: () => void;
}

type Tab = "review" | "verified";

export default function ReviewQueue({ open, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("review");

  return (
    <Drawer
      open={open}
      onClose={onClose}
      label="Review and verified answers"
      header={
        <>
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-navy-800 text-coral-400 ring-1 ring-white/10">
            {tab === "review" ? <ThumbDownIcon className="h-4 w-4" /> : <ShieldIcon className="h-4 w-4" />}
          </span>
          <div className="leading-tight">
            <h2 className="text-[15px] font-semibold tracking-tight text-white">Marshal desk</h2>
            <p className="text-xs text-steel-400">Flagged questions &amp; verified answers</p>
          </div>
        </>
      }
    >
      {/* Tab switcher. */}
      <div className="mb-4 inline-flex rounded-lg border border-white/10 bg-white/[0.03] p-0.5 text-xs font-medium">
        <TabButton active={tab === "review"} onClick={() => setTab("review")}>Review</TabButton>
        <TabButton active={tab === "verified"} onClick={() => setTab("verified")}>Verified</TabButton>
      </div>

      {open && tab === "review" && <ReviewTab />}
      {open && tab === "verified" && <VerifiedTab />}
    </Drawer>
  );
}

/* ----------------------------------------------------------- tab switcher -- */

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={
        "rounded-md px-3 py-1.5 transition-colors " +
        (active ? "bg-coral-500 text-white shadow-glow-sm" : "text-steel-400 hover:text-steel-200")
      }
    >
      {children}
    </button>
  );
}

/* -------------------------------------------------------------- Review tab -- */

function ReviewTab() {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch once on mount (the tab remounts each time it becomes active).
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    getReviewQueue()
      .then((q) => alive && setItems(q.items))
      .catch((e) => alive && setError(e instanceof ApiError ? e.message : "Could not load the review queue."))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const count = items?.length ?? 0;

  if (loading) return <SkeletonList />;
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (count === 0) {
    return (
      <EmptyNote icon={<ThumbDownIcon className="h-5 w-5" />}>
        No flagged questions yet — 👎 and corrections show up here.
      </EmptyNote>
    );
  }
  return (
    <ul className="space-y-3">
      {items!.map((item) => (
        <li key={item.id}>
          <ReviewCard item={item} />
        </li>
      ))}
    </ul>
  );
}

/** One flagged question, with its correction, context, timestamp + answer. */
function ReviewCard({ item }: { item: ReviewItem }) {
  const [showAnswer, setShowAnswer] = useState(false);
  const isDown = item.rating === "down";

  return (
    <div className="glass-inset p-3.5">
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

      {item.note && (
        <p className="mt-2.5 rounded-lg border border-coral-500/30 bg-coral-500/[0.08] px-3 py-2 text-[13px] leading-snug text-coral-100">
          {item.note}
        </p>
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[11px]">
        {item.building_context && (
          <span className="rounded bg-white/[0.05] px-2 py-0.5 font-mono text-steel-300">{item.building_context}</span>
        )}
        <span className="text-steel-500">{formatFlagged(item.created_at)}</span>
      </div>

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

/* ------------------------------------------------------------ Verified tab -- */

function VerifiedTab() {
  const [items, setItems] = useState<VerifiedItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    getVerified()
      .then((q) => alive && setItems(q.items))
      .catch((e) => alive && setError(e instanceof ApiError ? e.message : "Could not load verified answers."))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  /** Optimistically drop an entry after a successful delete. */
  function remove(id: string) {
    setItems((prev) => (prev ? prev.filter((v) => v.id !== id) : prev));
  }

  const count = items?.length ?? 0;

  if (loading) return <SkeletonList />;
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (count === 0) {
    return (
      <EmptyNote icon={<ShieldIcon className="h-5 w-5" />}>
        No verified answers yet — promote a correction from an answer's feedback bar.
      </EmptyNote>
    );
  }
  return (
    <ul className="space-y-3">
      {items!.map((item) => (
        <li key={item.id}>
          <VerifiedCard item={item} onDeleted={() => remove(item.id)} />
        </li>
      ))}
    </ul>
  );
}

/** One verified answer, with governing-section chips and a confirm-on-click delete. */
function VerifiedCard({ item, onDeleted }: { item: VerifiedItem; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function doDelete() {
    setBusy(true);
    setError(null);
    try {
      await deleteVerified(item.id);
      onDeleted(); // optimistic removal on success
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not delete.");
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <div className="glass-inset p-3.5">
      <div className="flex items-start gap-2">
        <p className="flex-1 text-sm font-medium leading-snug text-white">{item.question}</p>
        {/* Confirm-on-click delete: first click asks, second confirms. */}
        {confirming ? (
          <span className="inline-flex shrink-0 items-center gap-1.5 text-[11px]">
            <button
              type="button"
              onClick={doDelete}
              disabled={busy}
              className="rounded border border-critical-200 bg-critical-50 px-1.5 py-0.5 font-semibold text-critical-700 transition-colors hover:bg-critical-600/15 disabled:opacity-50"
            >
              Delete?
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              disabled={busy}
              className="rounded px-1.5 py-0.5 text-steel-400 transition-colors hover:text-steel-200"
            >
              Cancel
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            aria-label="Delete verified answer"
            className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-steel-500 transition-colors hover:bg-critical-600/15 hover:text-critical-600"
          >
            <TrashIcon className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      <p className="mt-2.5 rounded-lg border border-verified-500/20 bg-verified-500/[0.06] px-3 py-2 text-[13px] leading-snug text-steel-200">
        {item.answer}
      </p>

      {/* Governing-section chips. */}
      {item.sections.length > 0 && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          {item.sections.map((s) => (
            <span
              key={s}
              className="rounded-full border border-coral-500/30 bg-coral-500/10 px-2 py-0.5 font-mono text-[11px] text-coral-200"
            >
              §{s}
            </span>
          ))}
        </div>
      )}

      <p className="mt-2.5 text-[11px] text-steel-500">{formatVerified(item.verified_at)}</p>
      {error && <p className="mt-1.5 text-[11px] text-critical-600">{error}</p>}
    </div>
  );
}

/* ----------------------------------------------------------- shared bits -- */

function ErrorNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-critical-200 bg-critical-50 px-3.5 py-3 text-sm text-critical-700">
      {children}
    </div>
  );
}

function EmptyNote({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="mt-10 text-center text-sm text-steel-400">
      <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-navy-800 text-steel-500 ring-1 ring-white/10">
        {icon}
      </div>
      {children}
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

/** Format an ISO timestamp into a short "Flagged …" line. */
function formatFlagged(iso: string): string {
  return "Flagged " + shortWhen(iso, iso);
}

/** Format an ISO timestamp into a short "Verified …" line. */
function formatVerified(iso: string): string {
  return "Verified " + shortWhen(iso, iso);
}

function shortWhen(iso: string, fallback: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return fallback;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
