/**
 * AmendmentDiff — a side-by-side "model code vs. Connecticut amendment" card.
 *
 * When a turn's sources contain BOTH a controlling CT amendment and the related
 * base model-code provision it amends, we surface the pair explicitly so the
 * marshal sees, at a glance, exactly what Connecticut changed and that the
 * amendment governs. Renders null when no such pairs exist.
 *
 * Pairing rule: an amendment source (metadata.is_amendment || .controlling) is
 * matched to a base source (NOT an amendment, NOT a verified-library entry) whose
 * section is RELATED per lib/sections.sectionsRelate. Paired sources still also
 * appear in the Sources list below — this is an emphasis view, not a replacement.
 */
import type { Source } from "../lib/api";
import { sectionsRelate } from "../lib/sections";
import { SparkIcon } from "./icons";

interface Props {
  sources: Source[];
}

interface Pair {
  amendment: Source;
  base: Source;
}

/** Is this source a controlling CT amendment? */
function isAmendment(s: Source): boolean {
  const m = s.metadata ?? {};
  return Boolean(m.is_amendment || m.controlling);
}

/** Is this a plain base model-code source (not an amendment, not verified)? */
function isBase(s: Source): boolean {
  const m = s.metadata ?? {};
  return !isAmendment(s) && !m.verified;
}

/** Compact "BOOK ed" label, falling back to something non-empty. */
function bookLabel(s: Source): string {
  const m = s.metadata ?? {};
  return [m.book, m.edition].filter(Boolean).join(" ed ") || "Code";
}

/**
 * Find amendment↔base pairs. Each amendment matches the first related base that
 * hasn't already been paired, so we don't emit duplicate/overlapping cards.
 */
function findPairs(sources: Source[]): Pair[] {
  const pairs: Pair[] = [];
  const usedBase = new Set<number>();
  sources.forEach((amd) => {
    if (!isAmendment(amd)) return;
    for (let i = 0; i < sources.length; i++) {
      if (usedBase.has(i)) continue;
      const base = sources[i];
      if (!isBase(base)) continue;
      if (sectionsRelate(amd.metadata?.section, base.metadata?.section)) {
        pairs.push({ amendment: amd, base });
        usedBase.add(i);
        break;
      }
    }
  });
  return pairs;
}

export default function AmendmentDiff({ sources }: Props) {
  const pairs = findPairs(sources ?? []);
  if (pairs.length === 0) return null;

  return (
    <div className="mt-4 space-y-2.5">
      <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-steel-500">
        <SparkIcon className="h-3.5 w-3.5 text-coral-400" />
        Connecticut amendments
      </p>
      {pairs.map((p, i) => (
        <div key={i} className="glass-inset overflow-hidden">
          <div className="grid gap-px sm:grid-cols-2">
            {/* Left: the base model-code text (muted). */}
            <div className="bg-white/[0.02] px-3.5 py-3">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-steel-500">
                Model code · {bookLabel(p.base)}
                {p.base.metadata?.section && (
                  <span className="ml-1 font-mono text-steel-400">§{p.base.metadata.section}</span>
                )}
              </p>
              <p className="mt-1.5 text-[13px] leading-relaxed text-steel-400">{p.base.text}</p>
            </div>

            {/* Right: the controlling CT amendment (coral emphasis). */}
            <div className="border-t border-coral-500/30 bg-coral-500/[0.06] px-3.5 py-3 sm:border-l sm:border-t-0">
              <p className="flex flex-wrap items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-coral-300">
                Connecticut amendment
                {p.amendment.metadata?.section && (
                  <span className="font-mono">§{p.amendment.metadata.section}</span>
                )}
                <span className="rounded-full bg-coral-500 px-1.5 py-0.5 text-white shadow-glow-sm">controlling</span>
              </p>
              <p className="mt-1.5 text-[13px] leading-relaxed text-coral-100">{p.amendment.text}</p>
            </div>
          </div>
          <p className="border-t border-white/10 bg-navy-950/40 px-3.5 py-1.5 text-[11px] font-medium text-coral-200">
            The Connecticut amendment governs.
          </p>
        </div>
      ))}
    </div>
  );
}
