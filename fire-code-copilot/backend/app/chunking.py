"""Section-aware chunking for code books.

Codes are numbered (903.2.8, Table 509, NFPA 13...). Fixed-size chunking shreds that and
produces wrong citations. We split on section boundaries, keep section/page metadata on every
chunk, tag Connecticut amendments as controlling, and only sub-split sections that are too long.

Tuned against how PyMuPDF actually extracts typeset code pages. Five things real PDFs do that
naive splitting gets wrong, and how we handle each:

  1. Running headers/footers ("2021 INTERNATIONAL FIRE CODE") and bare page numbers repeat on
     every page. We detect lines that recur across pages and drop them before chunking.
  2. Inline cross-references ("...as required by Section 903.2.") look like headings. We only
     treat SECTION/CHAPTER/TABLE as a heading when it is UPPERCASE (real headings are), so a
     title-case "Section 903.2" inside a sentence is never mistaken for a new section.
  3. Tables ("TABLE 903.2.11.6") have numbered rows that look like sub-sections. We keep a
     table together as one chunk and tag every part is_table.
  4. Bare heading lines ("SECTION 903 AUTOMATIC SPRINKLER SYSTEMS") carry no body. We fold them
     forward as context onto the next real subsection instead of emitting useless tiny chunks.
  5. Connecticut amendments mark changes with (Amd)/(Add)/(Del). We tag those chunks so the
     retriever can treat the amended text as controlling.
"""
from __future__ import annotations
import math
import re
from collections import defaultdict

# A line that begins a new numbered code section, e.g. "903.2.8 Group R" or "1004.5 Occupant".
SECTION_HEADING = re.compile(r"^\s*(\d{3,4}(?:\.\d+)*)\s+[A-Z(]")
# Structural headings. CASE-SENSITIVE on purpose: real headings are "SECTION 903" / "TABLE 509",
# while body text says "see Section 903.2" — matching case keeps cross-refs from faking headings.
SECTION_KEYWORD = re.compile(r"^\s*(SECTION|CHAPTER|TABLE|APPENDIX|ANNEX)\s+([0-9A-Z][0-9A-Z.\-]*)")
# Inline markers CT (and other amenders) use to flag changed text. ONLY the explicit
# parenthetical markers count: base model-code text routinely says "as amended" / "the amendment
# to..." in prose, and tagging on those words made base chunks masquerade as the controlling CT
# text — the exact wrong-determination failure the amendment layer exists to prevent. Amendment
# DOCUMENTS are tagged wholesale via is_amendment_doc, so prose phrasing there needs no regex.
AMENDMENT_MARKER = re.compile(r"\((?:amd|add|del|sub)\)", re.IGNORECASE)

TARGET_WORDS = 450        # fallback word window when tiktoken isn't available
TARGET_TOKENS = 600       # the real budget: what TARGET_WORDS≈450 was approximating
OVERLAP_WORDS = 60        # FIXED overlap between windows — parent stitching depends on it
HEADER_MAX_WORDS = 12     # running headers/footers are short; don't strip long lines as boilerplate
PROSE_MIN_WORDS = 12      # a line this long (or sentence-final) reads as body, not a table row


def _heading(line: str) -> tuple[str | None, str | None]:
    """Classify a line. Returns (section_number_or_None, kind) where kind is one of
    'numeric' | 'section' | 'chapter' | 'table' | 'appendix' | None."""
    m = SECTION_KEYWORD.match(line)
    if m:
        kw = m.group(1).upper()
        num = m.group(2).rstrip(".")          # "903.2." -> "903.2"
        kind = {"SECTION": "section", "CHAPTER": "chapter", "TABLE": "table",
                "APPENDIX": "appendix", "ANNEX": "appendix"}[kw]
        return num, kind
    m = SECTION_HEADING.match(line)
    if m:
        return m.group(1).rstrip("."), "numeric"
    return None, None


def _is_prose(line: str) -> bool:
    """Does this line read like a sentence/body rather than a short table row or label?"""
    words = line.split()
    return len(words) >= PROSE_MIN_WORDS or (line.rstrip().endswith(".") and len(words) >= 6)


def _strip_boilerplate(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Drop running headers/footers and bare page numbers so they don't pollute chunks/citations.

    A short line that recurs on multiple pages is boilerplate (publication title, chapter footer).
    We never strip a line that itself looks like a section heading, so a genuine repeated heading
    is preserved.
    """
    occur: dict[str, set[int]] = defaultdict(set)
    for idx, (_page, text) in enumerate(pages):
        for ln in text.splitlines():
            s = ln.strip()
            if s:
                occur[s].add(idx)

    npages = len(pages)
    # On long books require recurrence on a meaningful fraction; on short ones, 2 pages is enough.
    thresh = max(2, math.ceil(0.4 * npages)) if npages >= 5 else 2
    # A short line that recurs across pages is boilerplate. We do NOT exempt heading-shaped lines:
    # a genuine section number is unique and never repeats verbatim, whereas a publication header
    # like "2021 INTERNATIONAL FIRE CODE" is itself heading-shaped (year + caps) and must be cut.
    boiler = {
        s for s, idxs in occur.items()
        if len(idxs) >= thresh and len(s.split()) <= HEADER_MAX_WORDS
    }

    cleaned: list[tuple[int, str]] = []
    for page, text in pages:
        kept = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.isdigit() and len(s) <= 4:          # bare page number
                continue
            if s in boiler:                          # running header/footer
                continue
            kept.append(ln)
        cleaned.append((page, "\n".join(kept)))
    return cleaned


def chunk_pages(pages: list[tuple[int, str]], book_meta: dict) -> list[dict]:
    """pages: list of (page_number, page_text). book_meta: {book, edition, is_amendment_doc}.

    Returns chunks: [{"text": str, "metadata": {book, edition, section, page, is_amendment,
    is_table}}].
    """
    if not pages:
        return []
    pages = _strip_boilerplate(pages)

    # Flatten to (page, line) so we can look ahead (needed to tell a real section after a table
    # from another table row).
    lines: list[tuple[int, str]] = [(pg, ln) for pg, text in pages for ln in text.splitlines()]

    chunks: list[dict] = []
    carry: list[str] = []                 # heading-only context to prepend to the next real chunk
    cur_section = "(preamble)"
    cur_is_table = False
    cur_page = pages[0][0]
    cur_lines: list[str] = []
    parent_seq = 0                        # monotonic id for a split section (parent-document retrieval)

    def flush():
        """Emit the accumulated section. Heading-only blocks become carried context instead."""
        nonlocal cur_lines, carry, parent_seq
        body_lines = [l for l in cur_lines if l.strip()]
        if not body_lines:
            cur_lines = []
            return
        # A block with no prose/body line (just a heading) and not a table -> carry it forward.
        has_body = cur_is_table or any(_heading(l)[1] is None for l in body_lines)
        if not has_body:
            carry.extend(body_lines)
            cur_lines = []
            return

        full = carry + body_lines
        carry = []
        text = "\n".join(full).strip()
        pieces = _split_long(text)
        # When a section is long enough to split, link the pieces with a shared parent id so the
        # retriever can match a precise window but hand the model back the whole section (see
        # retriever._expand_to_parents). Single-piece sections already ARE the whole section.
        parent_id = None
        if len(pieces) > 1:
            parent_seq += 1
            parent_id = f"{book_meta.get('book','?')}|{cur_section}|{cur_page}|{parent_seq}"
        for part_idx, piece in enumerate(pieces):
            is_amd = bool(book_meta.get("is_amendment_doc")) or bool(AMENDMENT_MARKER.search(piece))
            meta = {
                "book": book_meta.get("book", "?"),
                "edition": book_meta.get("edition", "?"),
                "section": cur_section,
                "page": cur_page,
                "is_amendment": is_amd,
                "is_table": cur_is_table,
            }
            if parent_id:
                meta["parent_id"] = parent_id
                meta["part"] = part_idx
                meta["n_parts"] = len(pieces)
            chunks.append({"text": piece, "metadata": meta})
        cur_lines = []

    i = 0
    n = len(lines)
    while i < n:
        page_no, line = lines[i]
        section, kind = _heading(line)

        if kind is not None:
            if cur_is_table and kind == "numeric":
                # Inside a table, a numbered line is a row UNLESS the next line is clearly prose
                # (i.e. a real section starting right after the table). Peek ahead to decide.
                nxt = lines[i + 1][1] if i + 1 < n else ""
                if not _is_prose(nxt):
                    cur_lines.append(line)           # keep the row inside the table chunk
                    i += 1
                    continue
                # else: fall through and treat as a real new section (ends the table)

            flush()                                  # close out the previous block
            cur_section = section
            cur_is_table = (kind == "table")
            cur_page = page_no

        cur_lines.append(line)
        i += 1

    flush()
    return chunks


_encoder = None


def _token_ratio(text: str) -> float | None:
    """Tokens-per-word for `text` via tiktoken, or None when unavailable. Legal prose runs
    ~1.3 tokens/word, but token-dense content (dotted section numbers, tables) runs far higher —
    a word-count window alone lets those chunks blow past the model's budget."""
    global _encoder
    try:
        if _encoder is None:
            import tiktoken
            _encoder = tiktoken.get_encoding("cl100k_base")
        words = len(text.split())
        return len(_encoder.encode(text)) / max(1, words)
    except Exception:
        return None


def _split_long(text: str) -> list[str]:
    """Sub-split an over-budget section into windows, with overlap; never split tiny sections.

    The split DECISION is token-aware (window sized so each piece lands near TARGET_TOKENS);
    the split MECHANICS stay word-based with a FIXED OVERLAP_WORDS, because parent-document
    stitching (retriever._stitch_parent) reconstructs the section by dropping exactly that many
    words from each subsequent window — variable overlap would corrupt the reconstruction.
    """
    words = text.split()
    ratio = _token_ratio(text)
    window = TARGET_WORDS if ratio is None else int(TARGET_TOKENS / ratio)
    window = max(2 * OVERLAP_WORDS, min(TARGET_WORDS, window))   # sane bounds; > overlap
    if len(words) <= window:
        return [text]
    out, start = [], 0
    while start < len(words):
        end = min(start + window, len(words))
        out.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - OVERLAP_WORDS
    return out
