/**
 * sections.ts — code-section string helpers (frontend mirror of the backend
 * `sections.relates`). Kept pure + dependency-free so it's trivial to test.
 */

/**
 * Canonicalize a section label for comparison: strip the "§" / "Section" /
 * "Table" prefixes, all whitespace, and any trailing dot, then uppercase.
 * e.g. "§ 903.2.8." -> "903.2.8", "Table 1020.1" -> "1020.1".
 */
function canon(s: string): string {
  return s
    .replace(/§/g, "")
    .replace(/\bSection\b/gi, "")
    .replace(/\bTable\b/gi, "")
    .replace(/\s+/g, "")
    .replace(/\.+$/, "")
    .toUpperCase();
}

/** True for a pure dotted-number section like "903", "903.2", "903.2.8". */
function isDotted(s: string): boolean {
  return /^\d+(\.\d+)*$/.test(s);
}

/**
 * Do two section labels refer to related provisions? True when they canonicalize
 * to the same value, OR when both are pure dotted numbers and one is an
 * ancestor/descendant of the other sharing at least two leading components
 * (e.g. "903.2.8" relates to "903.2.8.4", but "903.2" does not relate to "903.3").
 * Mirrors the backend `sections.relates`.
 */
export function sectionsRelate(a?: string, b?: string): boolean {
  if (!a || !b) return false;
  const ca = canon(a);
  const cb = canon(b);
  if (!ca || !cb) return false;
  if (ca === cb) return true;
  if (!isDotted(ca) || !isDotted(cb)) return false;

  const pa = ca.split(".");
  const pb = cb.split(".");
  const shorter = pa.length <= pb.length ? pa : pb;
  const longer = pa.length <= pb.length ? pb : pa;

  // The shorter must be a prefix of the longer, sharing >= 2 leading components.
  if (shorter.length < 2) return false;
  for (let i = 0; i < shorter.length; i++) {
    if (shorter[i] !== longer[i]) return false;
  }
  return true;
}
