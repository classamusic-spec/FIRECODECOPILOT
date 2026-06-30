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
    <div className="flex flex-col gap-2">
      {/* Reminder banner — only when the backend reports a pending/overdue cycle. */}
      {hasReminder && (
        <div
          role="status"
          className="flex items-start gap-2.5 rounded-xl border border-coral-500/30 bg-coral-500/[0.08] px-3 py-2.5 text-sm text-coral-100 animate-rise"
        >
          <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-coral-500/20 text-coral-300">
            <InfoIcon className="h-3.5 w-3.5" />
          </span>
          <p className="flex-1 leading-snug">{status.reminder}</p>
          <button
            type="button"
            onClick={() => setDismissed(true)}
            aria-label="Dismiss reminder"
            className="shrink-0 rounded-md p-0.5 text-coral-300 hover:bg-coral-500/15"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Always-available "active editions" disclosure. */}
      {status.active && (
        <div className="text-xs">
          <button
            type="button"
            onClick={() => setShowActive((v) => !v)}
            aria-expanded={showActive}
            title={status.active}
            className="inline-flex items-center gap-1 rounded text-steel-500 transition-colors hover:text-steel-300"
          >
            <InfoIcon className="h-3.5 w-3.5" />
            Adopted editions
          </button>
          {showActive && (
            <pre className="scroll-thin glass-inset mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap px-3 py-2 font-mono text-[11.5px] leading-relaxed text-steel-300">
              {status.active}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
