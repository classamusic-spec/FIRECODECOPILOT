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
      | (?:(?:Sections?|Sec\.?|§|Table|Chapter|Chap\.?)\s*) # a keyword...
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
_CITATION_IDENTIFIER_RE = re.compile(r"(?:[A-Z]\.)?\d+[A-Z]?(?:\.\d+)*", re.IGNORECASE)
_CITATION_LEAD = r"(?:Sections?|Sec\.?|§{1,2}|Table|Chapter|Chap\.?)"
_CITATION_LEAD_RE = re.compile(_CITATION_LEAD, re.IGNORECASE)
_CODE_OWNER = (
    r"(?:NFPA\s*\d+|IFC|IBC|IEBC|"
    r"International\s+(?:Fire|Building|Existing\s+Building)\s+Code)"
)
_CODE_OWNER_RE = re.compile(rf"\b(?P<owner>{_CODE_OWNER})\b", re.IGNORECASE)
_PREFIX_CODE_CITATION_RE = re.compile(
    rf"\b(?P<owner>{_CODE_OWNER})\b"
    rf"\s*(?:Life Safety Code|Fire Code)?\s*"
    rf"(?:\(?\b(?:19|20)\d{{2}}\b\)?(?:\s+edition)?)?\s*[,():-]*\s*"
    rf"(?P<lead>{_CITATION_LEAD})\s*",
    re.IGNORECASE,
)
_PREFIX_CODE_BARE_SECTION_RE = re.compile(
    rf"\b(?P<owner>{_CODE_OWNER})\b"
    r"\s*(?:Life Safety Code|Fire Code)?\s*"
    r"(?:\(?\b(?:19|20)\d{2}\b\)?(?:\s+edition)?)?\s*[,():-]*\s*"
    r"(?P<section>(?:[A-Z]\.)?\d+[A-Z]?(?:\.\d+)+)",
    re.IGNORECASE,
)
_POSTFIX_CODE_CITATION_RE = re.compile(
    rf"(?P<lead>{_CITATION_LEAD})\s*(?P<body>.*?)\s+of\s+(?:the\s+)?"
    rf"(?P<owner>{_CODE_OWNER})\b",
    re.IGNORECASE,
)
_SENTENCE_BREAK_RE = re.compile(r"(?<=[!?])\s+|(?<=\.)\s+(?=[A-Z])")


def _standard_tokens(text: str) -> set[str]:
    """Canonical 'NFPA <n>' tokens in `text` (spacing-insensitive: 'NFPA13' == 'NFPA 13')."""
    return {f"NFPA {m.group(1)}" for m in STANDARD_RE.finditer(text or "")}


def _canonical_owner(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip()).upper()
    if match := re.match(r"NFPA\s*(\d+)", normalized):
        return f"NFPA {match.group(1)}"
    if normalized == "IEBC" or "EXISTING BUILDING" in normalized:
        return "IEBC"
    if normalized == "IFC" or "FIRE CODE" in normalized:
        return "IFC"
    if normalized == "IBC" or "BUILDING CODE" in normalized:
        return "IBC"
    return normalized


def _paired_code_sections(text: str) -> dict[str, set[str]]:
    """Map explicitly attributed sections to their owning NFPA/ICC code book.

    Ownership is grammatical and sentence-local. Coordinated mixed-book text such as
    ``IFC Section 903 and Section 31 of NFPA 101`` is split at the repeated citation lead so each
    section remains paired with only its explicit owner.
    """
    out: dict[str, set[str]] = {}

    def add_sections(body: str, owner_value: str) -> None:
        owner = _canonical_owner(owner_value)
        for section_match in _CITATION_IDENTIFIER_RE.finditer(body):
            section = canonical(section_match.group(0))
            if section:
                out.setdefault(section, set()).add(owner)

    for sentence in _SENTENCE_BREAK_RE.split(text or ""):
        postfix_starts: list[int] = []
        for match in _POSTFIX_CODE_CITATION_RE.finditer(sentence):
            body = match.group("body")
            segment_start = match.start()
            if _CODE_OWNER_RE.search(sentence[:match.start()]):
                # The earlier owner keeps the first citation phrase. The repeated lead begins the
                # postfix-owned phrase: ``IFC Section 903 and Section 31 of NFPA 101``.
                if nested_lead := _CITATION_LEAD_RE.search(body):
                    segment_start = match.start("body") + nested_lead.start()
                    body = body[nested_lead.end():]
            postfix_starts.append(segment_start)
            add_sections(body, match.group("owner"))

        for match in _PREFIX_CODE_CITATION_RE.finditer(sentence):
            end = len(sentence)
            if next_owner := _CODE_OWNER_RE.search(sentence, match.end()):
                end = min(end, next_owner.start())
            for postfix_start in postfix_starts:
                if match.end() <= postfix_start < end:
                    end = postfix_start
            add_sections(sentence[match.end():end], match.group("owner"))

        for match in _PREFIX_CODE_BARE_SECTION_RE.finditer(sentence):
            add_sections(match.group("section"), match.group("owner"))

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
    candidates = [(m.start(), m.group(0)) for m in SECTION_RE.finditer(text)]
    candidates.extend(
        (m.start("section"), m.group("section"))
        for m in _PREFIX_CODE_BARE_SECTION_RE.finditer(text)
    )
    for _position, citation in sorted(candidates):
        norm = _normalize(citation)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(citation.strip())
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


def _metadata_owners(meta: dict) -> set[str]:
    owners = _standard_tokens(f"{meta.get('book', '')} {meta.get('source', '')}")
    family_owner = {
        "nfpa:101": "NFPA 101",
        "nfpa:1": "NFPA 1",
        "ifc": "IFC",
        "ibc": "IBC",
        "iebc": "IEBC",
    }
    if family := family_owner.get(str(meta.get("code_family", "")).lower()):
        owners.add(family)

    label = f"{meta.get('book', '')} {meta.get('source', '')}"
    if re.search(r"\bIEBC\b|International\s+Existing\s+Building\s+Code", label, re.I):
        owners.add("IEBC")
    elif re.search(r"\bIBC\b|International\s+Building\s+Code", label, re.I):
        owners.add("IBC")
    if re.search(r"\bIFC\b|International\s+Fire\s+Code", label, re.I):
        owners.add("IFC")
    return owners


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
    sections_by_owner: dict[str, set[str]] = {}
    for c in source_chunks:
        text = c.get("text", "")
        meta = c.get("metadata", {}) or {}
        chunk_sections = section_tokens(text)
        if meta_section := _normalize(str(meta.get("section", ""))):
            chunk_sections.add(meta_section)
        present |= chunk_sections
        present |= _standard_tokens(text)
        owner_books = _metadata_owners(meta)
        present |= {owner for owner in owner_books if owner.startswith("NFPA ")}
        for owner in owner_books:
            sections_by_owner.setdefault(owner, set()).update(chunk_sections)
    source_loose = _loose(" ".join(c.get("text", "") for c in source_chunks))

    check = CitationCheck(cited=extract_citations(answer))
    paired = _paired_code_sections(answer)
    for c in check.cited:
        cited_std = _standard_tokens(c)          # {'NFPA 13'} when c is a standard ref, else empty
        normalized = _normalize(c)
        paired_owners = paired.get(normalized, set())
        if paired_owners:
            # A book name and section number form one provenance claim. Never allow a section from
            # another retrieved code to verify an explicitly attributed NFPA/IFC/IBC/IEBC citation.
            ok = all(normalized in sections_by_owner.get(owner, set())
                     for owner in paired_owners)
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
