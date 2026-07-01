/**
 * HistoryDrawer — a right-anchored slide-over listing saved conversations (local only), grouped
 * into "matters" (a street address or permit #) so the marshal can keep a job's questions
 * together. Click a thread to load it; delete with the trash button (confirm-on-click); file a
 * thread under a matter with the tag control. The active thread is highlighted.
 *
 * All data comes from the parent (App owns the thread list + persistence); this component is
 * presentational and calls back on select/delete/set-matter.
 */
import { useState } from "react";
import type { Thread } from "../lib/threads";
import { groupByMatter } from "../lib/threads";
import { ClockIcon, TrashIcon, TagIcon } from "./icons";
import Drawer from "./Drawer";

interface Props {
  open: boolean;
  onClose: () => void;
  threads: Thread[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onSetMatter: (id: string, matter: string) => void;
  /** Existing matter labels, for autocomplete when filing a conversation. */
  knownMatters: string[];
}

export default function HistoryDrawer({
  open,
  onClose,
  threads,
  activeId,
  onSelect,
  onDelete,
  onSetMatter,
  knownMatters,
}: Props) {
  const groups = groupByMatter(threads);
  const listId = "fcc-matter-suggestions";

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
            <p className="text-xs text-steel-400">Saved conversations, grouped by matter (this device)</p>
          </div>
          {threads.length > 0 && (
            <span className="ml-1 rounded-full bg-coral-500/15 px-2 py-0.5 font-mono text-[11px] font-semibold text-coral-300">
              {threads.length}
            </span>
          )}
        </>
      }
    >
      {/* Shared autocomplete of existing matters for every row's editor. */}
      <datalist id={listId}>
        {knownMatters.map((m) => (
          <option key={m} value={m} />
        ))}
      </datalist>

      {threads.length === 0 ? (
        <div className="mt-10 text-center text-sm text-steel-400">
          <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-navy-800 text-steel-500 ring-1 ring-white/10">
            <ClockIcon className="h-5 w-5" />
          </div>
          No saved conversations yet — ask a question and it'll be kept here.
        </div>
      ) : (
        <div className="space-y-5">
          {groups.map((g) => (
            <section key={g.matter ?? "__unfiled__"}>
              <h3 className="mb-1.5 flex items-center gap-1.5 px-0.5 text-[11px] font-semibold uppercase tracking-wider text-steel-500">
                {g.matter ? (
                  <>
                    <TagIcon className="h-3 w-3 text-coral-400" />
                    <span className="truncate text-steel-300">{g.matter}</span>
                  </>
                ) : (
                  <span>Unfiled</span>
                )}
                <span className="ml-1 rounded-full bg-white/10 px-1.5 py-0.5 text-[10px] text-steel-400">
                  {g.threads.length}
                </span>
              </h3>
              <ul className="space-y-2">
                {g.threads.map((t) => (
                  <li key={t.id}>
                    <ThreadRow
                      thread={t}
                      active={t.id === activeId}
                      datalistId={listId}
                      onSelect={() => {
                        onSelect(t.id);
                        onClose();
                      }}
                      onDelete={() => onDelete(t.id)}
                      onSetMatter={(m) => onSetMatter(t.id, m)}
                    />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Drawer>
  );
}

/** One conversation row: title, timestamp + message count, matter editor, confirm-on-click delete. */
function ThreadRow({
  thread,
  active,
  datalistId,
  onSelect,
  onDelete,
  onSetMatter,
}: {
  thread: Thread;
  active: boolean;
  datalistId: string;
  onSelect: () => void;
  onDelete: () => void;
  onSetMatter: (matter: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(thread.matter ?? "");
  const count = thread.turns.filter((t) => t.role === "user").length;

  const save = () => {
    onSetMatter(draft);
    setEditing(false);
  };

  return (
    <div
      className={
        "glass-inset p-3 transition-colors " + (active ? "ring-1 ring-coral-500/40" : "")
      }
    >
      <div className="flex items-center gap-2">
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
          <span className="inline-flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={() => {
                setDraft(thread.matter ?? "");
                setEditing((v) => !v);
              }}
              aria-label={thread.matter ? "Change matter" : "File under a matter"}
              title={thread.matter ? "Change matter" : "File under a matter"}
              className={
                "grid h-7 w-7 place-items-center rounded-lg transition-colors hover:bg-coral-500/15 " +
                (thread.matter ? "text-coral-400" : "text-steel-500 hover:text-coral-300")
              }
            >
              <TagIcon className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setConfirming(true)}
              aria-label="Delete conversation"
              className="grid h-7 w-7 place-items-center rounded-lg text-steel-500 transition-colors hover:bg-critical-600/15 hover:text-critical-600"
            >
              <TrashIcon className="h-3.5 w-3.5" />
            </button>
          </span>
        )}
      </div>

      {/* Inline matter editor — address or permit #, with autocomplete of existing matters. */}
      {editing && (
        <div className="mt-2 flex items-center gap-1.5">
          <input
            autoFocus
            list={datalistId}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") save();
              else if (e.key === "Escape") setEditing(false);
            }}
            placeholder="Address or permit # (blank to unfile)"
            className="min-w-0 flex-1 rounded-lg border border-white/10 bg-navy-950/60 px-2.5 py-1.5 text-[13px] text-steel-100 placeholder:text-steel-600 focus:border-coral-500/50 focus:outline-none"
          />
          <button
            type="button"
            onClick={save}
            className="shrink-0 rounded-lg bg-coral-500 px-2.5 py-1.5 text-[12px] font-semibold text-white transition-colors hover:bg-coral-400"
          >
            Save
          </button>
        </div>
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
