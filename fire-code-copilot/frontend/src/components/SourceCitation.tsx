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
        "overflow-hidden rounded-xl border text-sm transition-colors " +
        (isAmendment
          ? "border-coral-500/40 bg-coral-500/[0.07]"
          : meta.verified
            ? "border-verified-500/30 bg-verified-500/[0.06]"
            : "border-white/10 bg-white/[0.03] hover:bg-white/[0.05]")
      }
    >
      {/* Header row: click to expand/collapse the quoted text. */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition active:scale-[0.99]"
      >
        <ChevronIcon className={"shrink-0 text-steel-500 transition-transform " + (open ? "rotate-90" : "")} />
        <span className="shrink-0 font-mono text-xs text-steel-500">[{index}]</span>
        <span className="truncate font-medium text-steel-100">{referenceLine(meta)}</span>

        {/* Status badges, pushed to the right. */}
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          {meta.is_table && (
            <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-steel-300">Table</span>
          )}
          {meta.verified && (
            <span className="rounded-full border border-verified-500/30 bg-verified-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-verified-700">Verified</span>
          )}
          {isAmendment && (
            <span className="rounded-full bg-coral-500 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white shadow-glow-sm">
              CT Amendment · controlling
            </span>
          )}
        </span>
      </button>

      {/* Quoted source text — monospace, scrollable, verbatim from the code book. */}
      {open && (
        <div className="border-t border-white/10 bg-navy-950/50 px-3 py-2.5">
          <pre className="scroll-thin max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[12.5px] leading-relaxed text-steel-300">
            {source.text}
          </pre>
        </div>
      )}
    </div>
  );
}
