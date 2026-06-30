/**
 * SourceCitation — one retrieved code chunk, shown as a scannable citation badge.
 *
 * Collapsed: a compact line "BOOK ed · §section · p.page" plus status badges.
 * Expanded: the quoted source `text` in a monospace, scrollable panel so the
 * marshal can verify the answer against the actual code text in one glance.
 *
 * Status emphasis (per design language — these must be instantly visible):
 *   - controlling / is_amendment  -> amber "CT AMENDMENT — controlling" badge
 *   - verified                    -> "VERIFIED" badge
 *   - is_table                    -> small "TABLE" tag
 */
import { useState } from "react";
import type { Source } from "../lib/api";
import { ChevronIcon } from "./icons";

interface Props {
  source: Source;
  /** 1-based index for a stable, human-readable reference label. */
  index: number;
}

/** Build the "BOOK ed · §section · p.page" reference line from metadata. */
function referenceLine(meta: Source["metadata"]): string {
  const parts: string[] = [];
  const head = [meta.book, meta.edition].filter(Boolean).join(" ");
  if (head) parts.push(head);
  if (meta.section) parts.push(`§${meta.section}`);
  if (meta.page !== undefined && meta.page !== "") parts.push(`p.${meta.page}`);
  // Fall back to something non-empty so a chunk is never unlabeled.
  return parts.join("  ·  ") || "Source";
}

export default function SourceCitation({ source, index }: Props) {
  const [open, setOpen] = useState(false);
  const meta = source.metadata ?? {};

  // An amendment is "controlling" CT-adopted text; either flag triggers the badge.
  const isAmendment = Boolean(meta.is_amendment || meta.controlling);

  return (
    <div
      className={
        "rounded-md border text-sm transition-colors " +
        (isAmendment
          ? "border-safety-200 bg-safety-50"
          : "border-slate-200 bg-white")
      }
    >
      {/* Header row: click to expand/collapse the quoted text. */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <ChevronIcon
          className={
            "shrink-0 text-ink-faint transition-transform " +
            (open ? "rotate-90" : "")
          }
        />
        <span className="shrink-0 font-mono text-xs text-ink-faint">
          [{index}]
        </span>
        <span className="truncate font-medium text-ink">
          {referenceLine(meta)}
        </span>

        {/* Status badges, pushed to the right. */}
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          {meta.is_table && (
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-muted">
              Table
            </span>
          )}
          {meta.verified && (
            <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-800">
              Verified
            </span>
          )}
          {isAmendment && (
            <span className="rounded bg-safety-500 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">
              CT Amendment — controlling
            </span>
          )}
        </span>
      </button>

      {/* Quoted source text — monospace, scrollable, verbatim from the code book. */}
      {open && (
        <div className="border-t border-slate-200/80 px-3 py-2">
          <pre className="scroll-thin max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[12.5px] leading-relaxed text-ink-muted">
            {source.text}
          </pre>
        </div>
      )}
    </div>
  );
}
