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
import { useEffect, useRef, useState } from "react";
import type { Source } from "../lib/api";
import { pageImageUrl } from "../lib/api";
import { DEMO } from "../demo";
import { ChevronIcon } from "./icons";
import { sectionsRelate } from "../lib/sections";
import { findCitedSpan } from "../lib/citations";
import type { CiteTarget } from "./ChatMessage";

interface Props {
  source: Source;
  /** 1-based index for a stable, human-readable reference label. */
  index: number;
  /** When a citation in the answer is clicked, the matching source scrolls into view + flashes. */
  highlight?: CiteTarget | null;
}

/** Render source text, wrapping the line that carries `section` in a highlight (if present). */
function renderSourceText(text: string, section?: string) {
  if (!section) return text;
  const span = findCitedSpan(text, section);
  if (!span) return text;
  return (
    <>
      {text.slice(0, span.start)}
      <mark className="rounded-[2px] bg-coral-500/25 text-coral-100">{text.slice(span.start, span.end)}</mark>
      {text.slice(span.end)}
    </>
  );
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

export default function SourceCitation({ source, index, highlight }: Props) {
  const [open, setOpen] = useState(false);
  const [flash, setFlash] = useState(false);
  const [showPage, setShowPage] = useState(false);
  const [pageError, setPageError] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const meta = source.metadata ?? {};

  // "View page" needs the source PDF filename + a numeric page, and a real backend (not demo).
  const pageNum = typeof meta.page === "number" ? meta.page : Number(meta.page);
  const canShowPage = !DEMO && Boolean(meta.source) && Number.isFinite(pageNum) && pageNum >= 1;

  // An amendment is "controlling" CT-adopted text; either flag triggers the badge.
  const isAmendment = Boolean(meta.is_amendment || meta.controlling);

  // Is THIS source the one the clicked citation refers to? (section-relation, so §903.2 in the
  // answer matches a retrieved §903.2.8 chunk, mirroring the backend merge logic).
  const isTarget = Boolean(highlight && sectionsRelate(meta.section, highlight.section));

  // React to a citation click: open, scroll into view, and flash once. Keyed on the nonce so
  // clicking the same citation again re-triggers it.
  useEffect(() => {
    if (!isTarget || !highlight) return;
    setOpen(true);
    cardRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    setFlash(true);
    const t = setTimeout(() => setFlash(false), 1600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlight?.nonce]);

  return (
    <div
      ref={cardRef}
      className={
        "overflow-hidden rounded-xl border text-sm transition-all duration-300 " +
        (flash ? "ring-2 ring-coral-400 ring-offset-2 ring-offset-navy-950 " : "") +
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

      {/* Quoted source text — monospace, scrollable, verbatim from the code book. When a citation
          was clicked, the line carrying that section number is highlighted for quick verification. */}
      {open && (
        <div className="border-t border-white/10 bg-navy-950/50 px-3 py-2.5">
          <pre className="scroll-thin max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[12.5px] leading-relaxed text-steel-300">
            {renderSourceText(source.text, isTarget ? highlight?.section : undefined)}
          </pre>

          {/* Verify against the REAL typeset page: renders the cited PDF page locally.
              The image is served by the local backend and never leaves the machine. */}
          {canShowPage && (
            <div className="mt-2">
              <button
                type="button"
                onClick={() => { setShowPage((v) => !v); setPageError(false); }}
                className="rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-steel-300 transition-colors hover:border-coral-500/40 hover:text-steel-100"
              >
                {showPage ? "Hide page" : `View page ${pageNum} in the book`}
              </button>
              {showPage && !pageError && (
                <img
                  src={pageImageUrl(String(meta.source), pageNum)}
                  alt={`${meta.book ?? "code book"} page ${pageNum}`}
                  loading="lazy"
                  onError={() => setPageError(true)}
                  className="mt-2 w-full rounded-lg border border-white/10 bg-white"
                />
              )}
              {showPage && pageError && (
                <p className="mt-2 text-[11px] text-steel-500">
                  Couldn't load the page image — the book may have moved or been renamed.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
