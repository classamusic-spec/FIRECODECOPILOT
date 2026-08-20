"""Citation validator — the safety net that makes fabricated citations structurally hard.

Two independent checks, because a wrong section number is worse than "I don't know":

  1. SECTION grounding — every section the model cites must actually be present in the
     retrieved sources, compared as a WHOLE token (so a cited "903.2" is NOT considered
     present just because "903.2.8" was shown — that substring slip used to pass).
  2. QUOTE grounding — any substantial passage the model puts in quotes must actually appear
     in the retrieved source text. The agent prompt tells the model to quote the code verbatim;
     this catches a real-looking quote that the model invented (correct section #, wrong words).

Anything we can't verify is flagged, never silently trusted.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from .sections import canonical, section_tokens

# Matches common code-citation shapes:
#   903.2.8   §1004.5   Section 1004.5   Table 509   NFPA 13   NFPA 101
SECTION_RE = re.compile(
    r"""
    (?:
        (?:NFPA\s*\d+)                                   # NFPA 13, NFPA 101
      | (?:(?:Section|Sec\.?|§|Table|Chapter|Chap\.?)\s*) # a keyword...
        (?:[A-Z]\.)?\d+[A-Z]?(?:\.\d+)*                  # ...number, incl. Annex A.31.1
      | (?<![\w.])(?:\d{3,4}(?:\.\d+)+|(?:[A-Z]\.)?\d{1,2}(?:\.\d+){2,})
                                                              # bare 903.2.8 / 31.1.1 / A.31.1
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Standard references ("NFPA 13") in SOURCE text — used to verify a cited standard the same way
# dotted section numbers are verified. Without this, a correctly grounded "NFPA 13" citation
# could never verify (present-sections held only dotted numerics), so routine sprinkler/alarm
# answers carried a false "UNVERIFIED CITATION" warning — alarm fatigue that trains the marshal
# to ignore the one warning guarding against real fabrications.
STANDARD_RE = re.compile(r"\bNFPA\s*(\d+)\b", re.IGNORECASE)
PAIRED_STANDARD_SECTION_RE = re.compile(
    r"\bNFPA\s*(\d+)\b\s*,?\s*(?:Section|Sec\.?|§)\s*"
    r"((?:[A-Z]\.)?\d+[A-Z]?(?:\.\d+)*)",
    re.IGNORECASE,
)


def _standard_tokens(text: str) -> set[str]:
    """Canonical 'NFPA <n>' tokens in `text` (spacing-insensitive: 'NFPA13' == 'NFPA 13')."""
    return {f"NFPA {m.group(1)}" for m in STANDARD_RE.finditer(text or "")}


def _paired_standard_sections(text: str) -> dict[str, set[str]]:
    """Map a cited section to every NFPA standard it is explicitly paired with."""
    out: dict[str, set[str]] = {}
    for match in PAIRED_STANDARD_SECTION_RE.finditer(text or ""):
        section = canonical(match.group(2))
        out.setdefault(section, set()).add(f"NFPA {match.group(1)}")
    return out

# Text the model placed in straight or curly double quotes.
QUOTE_RE = re.compile(r"[\"“]([^\"“”]{1,500})[\"”]")
# A quote shorter than this (in words) is a term/label, not a claim worth grounding.
MIN_QUOTE_WORDS = 6


def _normalize(s: str) -> str:
    """Canonical section form ('§903.2.8' / 'Section 903.2.8' / '903.2.8' -> '903.2.8')."""
    return canonical(s)


def _loose(text: str) -> str:
    """Lowercase + collapse every run of non-alphanumerics to one space, for robust quote
    containment that ignores punctuation, smart quotes, and line-wrapping differences."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def extract_citations(text: str) -> list[str]:
    """Return the distinct section citations the model used, in order of appearance."""
    seen, out = set(), []
    for m in SECTION_RE.finditer(text):
        norm = _normalize(m.group(0))
        if norm and norm not in seen:
            seen.add(norm)
            out.append(m.group(0).strip())
    return out


def extract_quotes(text: str) -> list[str]:
    """Substantial quoted passages the model presented as verbatim code text."""
    out = []
    for m in QUOTE_RE.finditer(text):
        q = m.group(1).strip()
        if len(q.split()) >= MIN_QUOTE_WORDS:
            out.append(q)
    return out


@dataclass
class CitationCheck:
    cited: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)            # substantial quotes that were checked
    unverified_quotes: list[str] = field(default_factory=list)  # quotes not found in the sources

    @property
    def ok(self) -> bool:
        return not self.unverified and not self.unverified_quotes


def validate(answer: str, source_chunks: list[dict]) -> CitationCheck:
    """Check every cited section and every substantial quote in `answer` against the sources.

    A section is verified if its canonical form equals a source chunk's `section` metadata OR a
    section token that literally appears in some chunk's text (whole-token, not substring). A
    quote is verified if it appears (punctuation-insensitively) in the retrieved source text.
    """
    # Present sections: from metadata, plus every section number literally in the shown text,
    # plus standard references ("NFPA 13"). A split NFPA chapter export does not repeat the book
    # name in every chunk, so its authoritative `book`/`source` metadata must count too; otherwise
    # an answer correctly naming NFPA 101 gets a false "not found in loaded books" warning.
    present: set[str] = set()
    sections_by_standard: dict[str, set[str]] = {}
    for c in source_chunks:
        text = c.get("text", "")
        meta = c.get("metadata", {}) or {}
        chunk_sections = section_tokens(text)
        if meta_section := _normalize(str(meta.get("section", ""))):
            chunk_sections.add(meta_section)
        present |= chunk_sections
        present |= _standard_tokens(text)
        owner_standards = _standard_tokens(f"{meta.get('book', '')} {meta.get('source', '')}")
        present |= owner_standards
        for standard in owner_standards:
            sections_by_standard.setdefault(standard, set()).update(chunk_sections)
    source_loose = _loose(" ".join(c.get("text", "") for c in source_chunks))

    check = CitationCheck(cited=extract_citations(answer))
    paired = _paired_standard_sections(answer)
    for c in check.cited:
        cited_std = _standard_tokens(c)          # {'NFPA 13'} when c is a standard ref, else empty
        normalized = _normalize(c)
        paired_standards = paired.get(normalized, set())
        if paired_standards:
            # A book name and section number form one provenance claim. Do not allow an NFPA 101
            # chunk plus an unrelated NFPA 1 section to validate "NFPA 101 §31.1.1.1".
            ok = all(normalized in sections_by_standard.get(standard, set())
                     for standard in paired_standards)
        else:
            ok = normalized in present or (bool(cited_std) and cited_std <= present)
        (check.verified if ok else check.unverified).append(c)

    for q in extract_quotes(answer):
        check.quotes.append(q)
        # Allow a trailing ellipsis on a quoted excerpt.
        needle = _loose(q.rstrip(" .…"))
        if needle and needle not in source_loose:
            check.unverified_quotes.append(q)
    return check


def annotate(answer: str, check: CitationCheck) -> str:
    """If anything is unverified, append an explicit warning instead of hiding it."""
    if check.ok:
        return answer
    parts = [answer, ""]
    if check.unverified:
        parts.append(
            f"⚠️ UNVERIFIED CITATION(S): {', '.join(check.unverified)}. These section references "
            f"were not found in your loaded code books and may be incorrect. Verify directly in "
            f"the adopted code before relying on them."
        )
    if check.unverified_quotes:
        shown = "; ".join(f'“{q[:80]}…”' if len(q) > 80 else f'“{q}”'
                          for q in check.unverified_quotes)
        parts.append(
            f"⚠️ UNVERIFIED QUOTE(S): {shown} — this wording was not found verbatim in the "
            f"retrieved sources. Treat as paraphrase and confirm against the code text."
        )
    return "\n".join(parts)
