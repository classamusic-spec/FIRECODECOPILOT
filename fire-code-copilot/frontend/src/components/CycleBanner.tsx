/**
 * CycleBanner — code-cycle awareness in the header.
 *
 * Fetches GET /cycle-status on mount:
 *   - `active`   : the currently adopted editions text (always available on
 *                  hover/expand via the info control).
 *   - `reminder` : if non-null, a "new edition due" notice -> dismissible banner.
 *
 * When there's no reminder we still expose the active editions behind a small
 * info button so the marshal can confirm what the answers are pinned to.
 */
import { useEffect, useState } from "react";
import { getCycleStatus, type CycleStatus } from "../lib/api";
import { InfoIcon, CloseIcon } from "./icons";

export default function CycleBanner() {
  const [status, setStatus] = useState<CycleStatus | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [showActive, setShowActive] = useState(false);
  /** The reminder is clamped to one line; this reveals the full text in place. */
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let alive = true;
    getCycleStatus()
      .then((s) => alive && setStatus(s))
      .catch(() => {
        // Non-fatal: the banner simply stays hidden if the endpoint is unreachable.
      });
    return () => {
      alive = false;
    };
  }, []);

  if (!status) return null;

  const hasReminder = Boolean(status.reminder) && !dismissed;

  return (
    <div className="flex min-w-0 items-center gap-2">
      {/* Reminder strip — a forward-looking cycle notice, not an error, so it reads as one calm
          status line. It stays clamped to a single line (it used to wrap into a six-line block on
          narrow windows and dominate the header); clicking expands the full text. */}
      {hasReminder && (
        <div
          role="status"
          className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-coral-500/20 bg-coral-500/[0.06] py-1.5 pl-2.5 pr-1.5 text-[12.5px] text-coral-100/90 animate-rise"
        >
          <span className="shrink-0 text-coral-300/90">
            <InfoIcon className="h-3.5 w-3.5" />
          </span>
          <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.16em] text-coral-300/70">
            Cycle
          </span>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            title={status.reminder ?? undefined}
            className={
              "min-w-0 flex-1 rounded text-left leading-snug transition-colors hover:text-coral-100 " +
              (expanded ? "" : "truncate")
            }
          >
            {status.reminder}
          </button>
          <button
            type="button"
            onClick={() => setDismissed(true)}
            aria-label="Dismiss reminder"
            className="shrink-0 rounded-md p-0.5 text-coral-300/70 transition-colors hover:bg-coral-500/15 hover:text-coral-200"
          >
            <CloseIcon className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Always-available "active editions" disclosure. */}
      {status.active && (
        <div className="relative shrink-0 text-xs">
          <button
            type="button"
            onClick={() => setShowActive((v) => !v)}
            aria-expanded={showActive}
            aria-label="Adopted editions"
            title={status.active}
            className="inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1 py-0.5 text-steel-500 transition-colors hover:text-steel-300"
          >
            <InfoIcon className="h-3.5 w-3.5 shrink-0" />
            {/* Label collapses to the icon on narrow screens so it can't push the header wider. */}
            <span className="hidden sm:inline">Adopted editions</span>
          </button>
          {showActive && (
            // Anchored right so the panel can't overflow the viewport on small screens.
            <pre className="scroll-thin glass-inset absolute right-0 top-full z-30 mt-1.5 max-h-40 w-[min(20rem,calc(100vw-2rem))] overflow-auto whitespace-pre-wrap px-3 py-2 font-mono text-[11.5px] leading-relaxed text-steel-300">
              {status.active}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
