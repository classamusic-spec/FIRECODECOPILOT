/**
 * threads.ts — LOCAL conversation persistence (localStorage only; nothing leaves
 * the machine). A "thread" is one saved conversation: an id, a title, timestamps,
 * and its turns. App.tsx keeps only thin wrappers around these helpers so its
 * component body stays readable.
 *
 * All access is wrapped in try/catch: corrupt or oversized storage degrades to a
 * clean empty state rather than crashing the app. On a quota error we shed the
 * oldest threads and retry.
 */
import type { Turn } from "./types";

const THREADS_KEY = "fcc.threads.v1";
const ACTIVE_KEY = "fcc.activeThread.v1";

/** One saved conversation. */
export interface Thread {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  turns: Turn[];
}

let _seq = 0;
/** A short, collision-resistant id (mirrors App's uid). */
export function newThreadId(): string {
  return `t-${Date.now().toString(36)}-${(_seq++).toString(36)}`;
}

/** Derive a thread title from its first user turn, truncated to ~60 chars. */
export function titleFor(turns: Turn[]): string {
  const first = turns.find((t) => t.role === "user");
  const text = first && first.role === "user" ? first.text.trim() : "";
  if (!text) return "New conversation";
  return text.length > 60 ? text.slice(0, 57).trimEnd() + "…" : text;
}

/** Load all threads (most-recently-updated first). Never throws. */
export function loadThreads(): Thread[] {
  try {
    const raw = localStorage.getItem(THREADS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    // Keep only well-formed entries; sort newest-updated first.
    const ok = parsed.filter(isThread);
    return ok.sort((a, b) => b.updatedAt - a.updatedAt);
  } catch {
    return [];
  }
}

/** Read the active thread id, or null. Never throws. */
export function loadActiveId(): string | null {
  try {
    return localStorage.getItem(ACTIVE_KEY);
  } catch {
    return null;
  }
}

/** Persist the active thread id. Never throws. */
export function saveActiveId(id: string | null): void {
  try {
    if (id) localStorage.setItem(ACTIVE_KEY, id);
    else localStorage.removeItem(ACTIVE_KEY);
  } catch {
    /* ignore — persistence is best-effort */
  }
}

/**
 * Write the full thread list, newest-first. On a quota error, drop the oldest
 * threads one at a time and retry so a full store still saves the recent ones.
 */
export function saveThreads(threads: Thread[]): void {
  const sorted = [...threads].sort((a, b) => b.updatedAt - a.updatedAt);
  let attempt = sorted;
  for (;;) {
    try {
      localStorage.setItem(THREADS_KEY, JSON.stringify(attempt));
      return;
    } catch {
      if (attempt.length <= 1) return; // give up rather than loop forever
      attempt = attempt.slice(0, -1); // drop the oldest and retry
    }
  }
}

/**
 * Upsert a thread's turns: if `turns` is empty (a fresh, unused thread) it is NOT
 * persisted. Returns the updated thread list (newest-first).
 */
export function upsertThread(threads: Thread[], id: string, turns: Turn[]): Thread[] {
  if (turns.length === 0) return threads;
  const now = Date.now();
  const existing = threads.find((t) => t.id === id);
  const merged: Thread = existing
    ? { ...existing, turns, title: titleFor(turns), updatedAt: now }
    : { id, title: titleFor(turns), createdAt: now, updatedAt: now, turns };
  const rest = threads.filter((t) => t.id !== id);
  const next = [merged, ...rest];
  saveThreads(next);
  return next;
}

/** Remove a thread by id, persist, and return the new list. */
export function removeThread(threads: Thread[], id: string): Thread[] {
  const next = threads.filter((t) => t.id !== id);
  saveThreads(next);
  return next;
}

/** Narrow an unknown value to a Thread (defensive against corrupt storage). */
function isThread(v: unknown): v is Thread {
  if (!v || typeof v !== "object") return false;
  const t = v as Record<string, unknown>;
  return (
    typeof t.id === "string" &&
    typeof t.title === "string" &&
    typeof t.createdAt === "number" &&
    typeof t.updatedAt === "number" &&
    Array.isArray(t.turns)
  );
}
