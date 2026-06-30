"""Section-aware chunking for code books.

Codes are numbered (903.2.8, Table 509, NFPA 13...). Fixed-size chunking shreds that and
produces wrong citations. We split on section boundaries, keep section/page metadata on every
chunk, tag Connecticut amendments as controlling, and only sub-split sections that are too long.
"""
from __future__ import annotations
import re

# A line that begins a new code section, e.g. "903.2.8 Group R" or "1004.5 Occupant load".
SECTION_HEADING = re.compile(r"^\s*(\d{3,4}(?:\.\d+)*)\s+[A-Z(]")
# Other headings we want to start a fresh chunk on.
SECTION_KEYWORD = re.compile(r"^\s*(SECTION|CHAPTER|TABLE)\s+([0-9A-Z.\-]+)", re.IGNORECASE)
# Inline markers CT (and other amenders) use to flag changed text.
AMENDMENT_MARKER = re.compile(r"\((?:amd|add|del|sub)\)|\bamend(?:ed|ment)?\b|"
                              r"\b(add|delete|substitute) the following\b", re.IGNORECASE)

TARGET_WORDS = 450        # ~600 tokens
OVERLAP_WORDS = 60


def _is_heading(line: str) -> tuple[str | None, bool]:
    """Return (section_number_or_None, is_table)."""
    m = SECTION_HEADING.match(line)
    if m:
        return m.group(1), False
    m = SECTION_KEYWORD.match(line)
    if m:
        kw, num = m.group(1).upper(), m.group(2)
        return num, kw == "TABLE"
    return None, False


def chunk_pages(pages: list[tuple[int, str]], book_meta: dict) -> list[dict]:
    """pages: list of (page_number, page_text). book_meta: {book, edition, is_amendment_doc}.

    Returns chunks: [{"text": str, "metadata": {book, edition, section, page, is_amendment,
    is_table}}].
    """
    chunks: list[dict] = []
    cur_section = "(preamble)"
    cur_is_table = False
    cur_lines: list[str] = []
    cur_page = pages[0][0] if pages else 1

    def flush():
        nonlocal cur_lines
        text = "\n".join(cur_lines).strip()
        if text:
            for piece in _split_long(text):
                is_amd = bool(book_meta.get("is_amendment_doc")) or bool(AMENDMENT_MARKER.search(piece))
                chunks.append({
                    "text": piece,
                    "metadata": {
                        "book": book_meta.get("book", "?"),
                        "edition": book_meta.get("edition", "?"),
                        "section": cur_section,
                        "page": cur_page,
                        "is_amendment": is_amd,
                        "is_table": cur_is_table,
                    },
                })
        cur_lines = []

    for page_no, text in pages:
        for line in text.splitlines():
            section, is_table = _is_heading(line)
            if section is not None:
                flush()                      # close out the previous section
                cur_section, cur_is_table, cur_page = section, is_table, page_no
            cur_lines.append(line)
        # keep page roughly aligned with where the current section started
    flush()
    return chunks


def _split_long(text: str) -> list[str]:
    """Sub-split a section that exceeds TARGET_WORDS, with overlap; never split tiny sections."""
    words = text.split()
    if len(words) <= TARGET_WORDS:
        return [text]
    out, start = [], 0
    while start < len(words):
        end = min(start + TARGET_WORDS, len(words))
        out.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - OVERLAP_WORDS
    return out
