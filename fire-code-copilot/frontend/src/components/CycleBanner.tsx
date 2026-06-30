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
          className="flex items-start gap-2 rounded-md border border-safety-200 bg-safety-50 px-3 py-2 text-sm text-safety-900 animate-rise"
        >
          <InfoIcon className="mt-0.5 h-4 w-4 shrink-0 text-safety-600" />
          <p className="flex-1 leading-snug">{status.reminder}</p>
          <button
            type="button"
            onClick={() => setDismissed(true)}
            aria-label="Dismiss reminder"
            className="shrink-0 rounded p-0.5 text-safety-700 hover:bg-safety-100"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Always-available "active editions" disclosure. */}
      {status.active && (
        <div className="text-xs text-ink-muted">
          <button
            type="button"
            onClick={() => setShowActive((v) => !v)}
            aria-expanded={showActive}
            title={status.active}
            className="inline-flex items-center gap-1 rounded text-ink-faint hover:text-ink-muted"
          >
            <InfoIcon className="h-3.5 w-3.5" />
            Adopted editions
          </button>
          {showActive && (
            <pre className="scroll-thin mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-slate-100 px-2 py-1.5 font-mono text-[11.5px] leading-relaxed text-ink-muted">
              {status.active}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
