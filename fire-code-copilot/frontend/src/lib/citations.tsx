/**
 * citations.tsx — turn the section references inside an answer into clickable links, and
 * locate the cited line inside a source chunk so it can be highlighted.
 *
 * Pure + dependency-light so the matching logic is easy to reason about and reuse. The React
 * bits (linkify + the ReactMarkdown component overrides) live here too so ChatMessage stays lean.
 */
import React from "react";

// Section references we make clickable: "§903.2.8", "Section 903.2.8", "Table 509.1".
// Deliberately NOT bare numbers — matching "3.2" inside prose would create false links.
const CITATION_RE = /(§\s*\d+(?:\.\d+)*|\b(?:Section|Sections|Table)\s+\d+(?:\.\d+)*)/g;

/** The canonical dotted section number inside a matched token, e.g. "§ 903.2.8" -> "903.2.8". */
export function sectionFromMatch(token: string): string {
  const nums = token.match(/\d+(?:\.\d+)*/g);
  return nums ? nums[0] : token.trim();
}

/** Distinct section numbers referenced in a block of answer text (order-preserving). */
export function extractCitedSections(text: string): string[] {
  const out: string[] = [];
  for (const m of text.matchAll(CITATION_RE)) {
    const s = sectionFromMatch(m[0]);
    if (!out.includes(s)) out.push(s);
  }
  return out;
}

/**
 * Locate the line inside a source chunk that carries a given section number, returned as
 * [start, end) offsets so the caller can wrap it in a highlight. Matches the number as a
 * standalone token (so "903.2" does not match inside "903.2.8"). No regex lookbehind, so it
 * behaves the same across every webview. Returns null when the section isn't in the text.
 */
export function findCitedSpan(text: string, section: string): { start: number; end: number } | null {
  const target = section.replace(/\s+/g, "");
  if (!target) return null;
  let idx = -1;
  for (let from = 0; ; ) {
    const p = text.indexOf(target, from);
    if (p === -1) break;
    const before = text[p - 1];
    const after = text[p + target.length];
    const okBefore = p === 0 || !/[\d.]/.test(before);
    const okAfter = after === undefined || !/\d/.test(after);
    if (okBefore && okAfter) {
      idx = p;
      break;
    }
    from = p + 1;
  }
  if (idx === -1) return null;
  const start = text.lastIndexOf("\n", idx) + 1;    // start of the line containing the match
  let end = text.indexOf("\n", idx);
  if (end === -1) end = text.length;
  return { start, end };
}

/** Split a string into text + clickable section-reference buttons. */
export function linkifyCitations(text: string, onCite: (section: string) => void): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of text.matchAll(CITATION_RE)) {
    const start = m.index ?? 0;
    if (start > last) nodes.push(text.slice(last, start));
    const token = m[0];
    const section = sectionFromMatch(token);
    nodes.push(
      <button
        key={`cite-${key++}`}
        type="button"
        data-cite={section}
        onClick={(e) => {
          e.preventDefault();
          onCite(section);
        }}
        title={`Jump to §${section} in the sources`}
        className="cursor-pointer rounded-[3px] font-medium text-coral-300 underline decoration-coral-500/40 decoration-dotted underline-offset-2 transition-colors hover:bg-coral-500/15 hover:text-coral-200 hover:decoration-coral-400"
      >
        {token}
      </button>,
    );
    last = start + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes.length ? nodes : [text];
}

function mapChildren(children: React.ReactNode, onCite: (section: string) => void): React.ReactNode {
  return React.Children.map(children, (child) =>
    typeof child === "string" ? linkifyCitations(child, onCite) : child,
  );
}

/**
 * ReactMarkdown `components` that linkify section references inside the text-bearing elements an
 * answer actually uses (paragraphs, list items, bold/italic runs, table cells). Nested elements
 * are rendered by their own override, so a `§` inside **bold** still becomes a link.
 */
export function makeCitationComponents(onCite: (section: string) => void) {
  const wrap =
    (Tag: keyof JSX.IntrinsicElements) =>
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ({ node: _node, children, ...props }: any) =>
      React.createElement(Tag, props, mapChildren(children, onCite));
  return { p: wrap("p"), li: wrap("li"), strong: wrap("strong"), em: wrap("em"), td: wrap("td") };
}
