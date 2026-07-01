/**
 * exportAnswer.ts — "Export answer to PDF" for the inspection file.
 *
 * A single pure function that takes ONE finished answer plus the sources IT cites
 * and opens a clean, light-themed, print-friendly document in a new window, then
 * fires the browser's print dialog (the marshal chooses "Save as PDF").
 *
 * Copyright guardrail (see CLAUDE.md §1): this exports ONLY the current answer and
 * its own cited sources — never a corpus dump. Callers must pass exactly the one
 * answer's `sources`.
 *
 * Everything is composed as an isolated HTML string with its OWN inline <style>
 * (light theme, for print/paper) — we deliberately do NOT reuse the app's dark CSS.
 *
 * Security: all user/source text is HTML-escaped before it touches the document,
 * and the tiny markdown renderer only emits a fixed set of safe tags. No raw HTML
 * from the answer or sources is ever passed through.
 */
import type { Source } from "./api";

/** Escape the four HTML-significant characters so text can never inject markup. */
function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Inline markdown → safe HTML: bold, italic, and `code`. Operates on
 * already-escaped text, so it only introduces the tags it emits itself.
 */
function inline(escaped: string): string {
  return escaped
    .replace(/`([^`]+)`/g, "<code>$1</code>") // `code`
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>") // **bold**
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>"); // *italic*
}

/**
 * Minimal, dependency-free markdown → HTML for the answer body. Supports the
 * subset answers actually use: ATX headings, unordered/ordered lists, and
 * paragraphs, plus inline bold/italic/code. Input is escaped FIRST, so no HTML
 * from the source can survive.
 */
function markdownToHtml(md: string): string {
  const lines = esc(md).replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let listType: "ul" | "ol" | null = null;
  let para: string[] = [];

  const flushPara = () => {
    if (para.length) {
      out.push(`<p>${inline(para.join(" "))}</p>`);
      para = [];
    }
  };
  const closeList = () => {
    if (listType) {
      out.push(`</${listType}>`);
      listType = null;
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();

    // Blank line → break the current paragraph/list block.
    if (!line.trim()) {
      flushPara();
      closeList();
      continue;
    }

    // ATX heading: #, ##, ###…
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      flushPara();
      closeList();
      const level = Math.min(h[1].length, 6);
      out.push(`<h${level}>${inline(h[2])}</h${level}>`);
      continue;
    }

    // Unordered list item: -, *, +
    const ul = /^\s*[-*+]\s+(.*)$/.exec(line);
    if (ul) {
      flushPara();
      if (listType !== "ul") {
        closeList();
        listType = "ul";
        out.push("<ul>");
      }
      out.push(`<li>${inline(ul[1])}</li>`);
      continue;
    }

    // Ordered list item: 1. 2) …
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (ol) {
      flushPara();
      if (listType !== "ol") {
        closeList();
        listType = "ol";
        out.push("<ol>");
      }
      out.push(`<li>${inline(ol[1])}</li>`);
      continue;
    }

    // Otherwise: part of a paragraph.
    closeList();
    para.push(line.trim());
  }

  flushPara();
  closeList();
  return out.join("\n");
}

/** Build the "[n] BOOK ed · §section · p.page" reference line from metadata. */
function referenceLine(index: number, meta: Source["metadata"]): string {
  const parts: string[] = [];
  const head = [meta.book, meta.edition].filter(Boolean).join(" ");
  if (head) parts.push(head);
  if (meta.section) parts.push(`§${meta.section}`);
  if (meta.page !== undefined && meta.page !== "") parts.push(`p.${meta.page}`);
  const ref = parts.join(" · ") || "Source";
  return `[${index}] ${ref}`;
}

/** Compose the Sources section — one block per cited source. */
function sourcesHtml(sources: Source[]): string {
  if (!sources.length) return "";
  const blocks = sources
    .map((s, i) => {
      const meta = s.metadata ?? {};
      const isAmendment = Boolean(meta.is_amendment || meta.controlling);
      const badges: string[] = [];
      if (isAmendment) badges.push('<span class="badge badge-amend">CT AMENDMENT — controlling</span>');
      if (meta.verified) badges.push('<span class="badge badge-verified">VERIFIED</span>');
      if (meta.is_table) badges.push('<span class="badge badge-table">TABLE</span>');
      return `      <div class="source">
        <div class="source-head">
          <span class="source-ref">${esc(referenceLine(i + 1, meta))}</span>
          ${badges.join(" ")}
        </div>
        <pre class="source-text">${esc(s.text ?? "")}</pre>
      </div>`;
    })
    .join("\n");

  return `    <section class="sources">
      <h2 class="section-title">Sources</h2>
${blocks}
    </section>`;
}

/**
 * Export one finished answer + its cited sources to a print-friendly PDF.
 * Returns false when a new window could not be opened (popup blocked).
 */
export function exportAnswer(input: {
  question: string;
  answer: string;
  sources: Source[];
}): boolean {
  const { question, answer, sources } = input;

  const win = window.open("", "_blank");
  if (!win) {
    // Popup blocked — tell the user plainly and bail (nothing was written).
    const msg = "Could not open the export window. Please allow pop-ups for this site and try again.";
    if (typeof alert === "function") alert(msg);
    else console.warn(msg);
    return false;
  }

  const now = new Date();
  const stamp = now.toLocaleString();

  const doc = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Fire Code CoPilot — Exported answer</title>
  <style>
    /* Self-contained LIGHT theme for print/paper — independent of the app's dark CSS. */
    :root { --ink: #14213d; --muted: #55627a; --line: #d7deea; --coral: #c72e16; --green: #1f7a5a; }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; }
    body {
      font-family: "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: var(--ink); background: #fff; line-height: 1.55; font-size: 14px;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }
    .page { max-width: 46rem; margin: 0 auto; padding: 32px 28px 48px; }
    .brand { display: flex; align-items: baseline; justify-content: space-between; gap: 12px;
      border-bottom: 2px solid var(--coral); padding-bottom: 10px; margin-bottom: 18px; }
    .brand h1 { font-size: 16px; margin: 0; letter-spacing: -0.01em; }
    .brand .tag { color: var(--muted); font-size: 12px; }
    .meta { color: var(--muted); font-size: 12px; margin: 0 0 22px; }
    .label { text-transform: uppercase; letter-spacing: 0.08em; font-size: 11px; font-weight: 700; color: var(--muted); margin: 0 0 6px; }
    .question { font-size: 15px; font-weight: 600; margin: 0 0 22px; padding: 10px 14px; background: #f4f6fb; border-left: 3px solid var(--coral); border-radius: 6px; }
    .answer > * + * { margin-top: 10px; }
    .answer h1, .answer h2, .answer h3, .answer h4 { line-height: 1.3; margin: 16px 0 6px; }
    .answer h1 { font-size: 17px; } .answer h2 { font-size: 15px; } .answer h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--coral); }
    .answer p { margin: 0 0 10px; } .answer ul, .answer ol { margin: 0 0 10px; padding-left: 22px; } .answer li { margin: 2px 0; }
    .answer code { font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace; font-size: 12.5px; background: #f0f2f7; padding: 1px 4px; border-radius: 3px; }
    .answer strong { font-weight: 700; }
    .section-title { font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); border-top: 1px solid var(--line); padding-top: 14px; margin: 28px 0 12px; }
    .source { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; margin: 0 0 10px; break-inside: avoid; }
    .source-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 8px; }
    .source-ref { font-weight: 600; font-size: 13px; }
    .badge { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; padding: 2px 7px; border-radius: 999px; }
    .badge-amend { background: var(--coral); color: #fff; }
    .badge-verified { background: #e5f6ef; color: var(--green); border: 1px solid #b9e5d4; }
    .badge-table { background: #eef1f7; color: var(--muted); }
    .source-text { font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace; font-size: 12px; line-height: 1.5;
      white-space: pre-wrap; word-break: break-word; margin: 0; color: #2a3247; background: #fafbfd; border: 1px solid #eef1f7; border-radius: 6px; padding: 8px 10px; }
    .footer { margin-top: 28px; border-top: 1px solid var(--line); padding-top: 12px; color: var(--muted); font-size: 11px; }
    @media print { .page { padding: 0.4in 0.5in; } body { font-size: 12.5px; } }
  </style>
</head>
<body>
  <main class="page">
    <div class="brand">
      <h1>Fire Code CoPilot</h1>
      <span class="tag">decision support, not an authority</span>
    </div>
    <p class="meta">Generated ${esc(stamp)}</p>

    <p class="label">Question</p>
    <div class="question">${esc(question)}</div>

    <p class="label">Answer</p>
    <div class="answer">${markdownToHtml(answer)}</div>

${sourcesHtml(sources)}

    <div class="footer">
      Generated by Fire Code CoPilot on ${esc(stamp)}. Verify against the official adopted code before
      making a determination. The marshal is the AHJ.
    </div>
  </main>
</body>
</html>`;

  win.document.open();
  win.document.write(doc);
  win.document.close();

  // Let the new document lay out before invoking print (some browsers need a tick).
  // Print exactly ONCE: Chrome fires onload for document.write'd content AND the timeout
  // fallback would run, popping a second print dialog after the user dismissed the first.
  win.focus();
  let printed = false;
  const printOnce = () => {
    if (printed) return;
    printed = true;
    try {
      win.print();
    } catch {
      /* window may already be closed by the user — ignore */
    }
  };
  win.onload = printOnce;
  // Fallback for browsers that don't fire onload for document.write'd content.
  setTimeout(printOnce, 400);

  return true;
}
