/**
 * HistoryDrawer — a right-anchored slide-over listing saved conversations (local
 * only). Click a thread to load it into the chat; delete one with the trash button
 * (confirm-on-click). The active thread is highlighted. Uses the shared Drawer shell.
 *
 * All data comes from the parent (App owns the thread list + persistence); this
 * component is presentational and calls back on select/delete.
 */
import { useState } from "react";
import type { Thread } from "../lib/threads";
import { ClockIcon, TrashIcon } from "./icons";
import Drawer from "./Drawer";

interface Props {
  open: boolean;
  onClose: () => void;
  threads: Thread[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

export default function HistoryDrawer({ open, onClose, threads, activeId, onSelect, onDelete }: Props) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      label="Conversation history"
      header={
        <>
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-navy-800 text-coral-400 ring-1 ring-white/10">
            <ClockIcon className="h-4 w-4" />
          </span>
          <div className="leading-tight">
            <h2 className="text-[15px] font-semibold tracking-tight text-white">History</h2>
            <p className="text-xs text-steel-400">Your saved conversations (this device)</p>
          </div>
          {threads.length > 0 && (
            <span className="ml-1 rounded-full bg-coral-500/15 px-2 py-0.5 font-mono text-[11px] font-semibold text-coral-300">
              {threads.length}
            </span>
          )}
        </>
      }
    >
      {threads.length === 0 ? (
        <div className="mt-10 text-center text-sm text-steel-400">
          <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-navy-800 text-steel-500 ring-1 ring-white/10">
            <ClockIcon className="h-5 w-5" />
          </div>
          No saved conversations yet — ask a question and it'll be kept here.
        </div>
      ) : (
        <ul className="space-y-2">
          {threads.map((t) => (
            <li key={t.id}>
              <ThreadRow
                thread={t}
                active={t.id === activeId}
                onSelect={() => { onSelect(t.id); onClose(); }}
                onDelete={() => onDelete(t.id)}
              />
            </li>
          ))}
        </ul>
      )}
    </Drawer>
  );
}

/** One conversation row: title, timestamp + message count, confirm-on-click delete. */
function ThreadRow({
  thread,
  active,
  onSelect,
  onDelete,
}: {
  thread: Thread;
  active: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const count = thread.turns.filter((t) => t.role === "user").length;

  return (
    <div
      className={
        "glass-inset flex items-center gap-2 p-3 transition-colors " +
        (active ? "ring-1 ring-coral-500/40" : "")
      }
    >
      <button type="button" onClick={onSelect} className="min-w-0 flex-1 text-left">
        <p className="truncate text-sm font-medium text-white">{thread.title}</p>
        <p className="mt-0.5 text-[11px] text-steel-500">
          {relativeTime(thread.updatedAt)} · {count} {count === 1 ? "message" : "messages"}
          {active && <span className="ml-1.5 text-coral-300">· current</span>}
        </p>
      </button>

      {confirming ? (
        <span className="inline-flex shrink-0 items-center gap-1.5 text-[11px]">
          <button
            type="button"
            onClick={onDelete}
            className="rounded border border-critical-200 bg-critical-50 px-1.5 py-0.5 font-semibold text-critical-700 transition-colors hover:bg-critical-600/15"
          >
            Delete?
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="rounded px-1.5 py-0.5 text-steel-400 transition-colors hover:text-steel-200"
          >
            Cancel
          </button>
        </span>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          aria-label="Delete conversation"
          className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-steel-500 transition-colors hover:bg-critical-600/15 hover:text-critical-600"
        >
          <TrashIcon className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

/** Short relative time (e.g. "just now", "5m ago", "3h ago", "Jun 24"). */
function relativeTime(ms: number): string {
  const diff = Date.now() - ms;
  if (Number.isNaN(diff)) return "";
  const sec = Math.round(diff / 1000);
  if (sec < 45) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day}d ago`;
  return new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
