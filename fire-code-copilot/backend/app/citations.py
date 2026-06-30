"""Citation validator — the safety net that makes fabricated citations structurally hard.

After the model drafts an answer, we extract every section it cited and confirm each one
actually appears in the retrieved source chunks (by section metadata OR literal text match).
Any citation we can't verify is flagged, not silently trusted. For fire-code work this matters
more than any model upgrade: a wrong section number is worse than "I don't know."
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

# Matches common code-citation shapes:
#   903.2.8   §1004.5   Section 1004.5   Table 509   NFPA 13   NFPA 101   IFC 903.2
SECTION_RE = re.compile(
    r"""
    (?:
        (?:NFPA\s*\d+)                                   # NFPA 13, NFPA 101
      | (?:(?:Section|Sec\.?|§|Table|Chapter|Chap\.?)\s*) # a keyword...
        \d+[A-Z]?(?:\.\d+)*                              # ...followed by a number
      | (?<![\w.])\d{3,4}(?:\.\d+)+                       # bare dotted section like 903.2.8
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _normalize(s: str) -> str:
    """Strip keywords/punctuation so '§903.2.8', 'Section 903.2.8', '903.2.8' compare equal."""
    s = re.sub(r"(?i)\b(section|sec\.?|table|chapter|chap\.?)\b", " ", s)
    s = s.replace("§", " ")
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s


def extract_citations(text: str) -> list[str]:
    """Return the distinct section citations the model used, in order of appearance."""
    seen, out = set(), []
    for m in SECTION_RE.finditer(text):
        norm = _normalize(m.group(0))
        if norm and norm not in seen:
            seen.add(norm)
            out.append(m.group(0).strip())
    return out


@dataclass
class CitationCheck:
    cited: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unverified


def validate(answer: str, source_chunks: list[dict]) -> CitationCheck:
    """Check every citation in `answer` against the retrieved chunks.

    A citation is verified if its normalized form appears in any chunk's `section` metadata
    OR literally in any chunk's text. Everything else is unverified (possible fabrication).
    """
    # Build a haystack of everything the model was actually shown.
    sections = {_normalize(str(c.get("metadata", {}).get("section", ""))) for c in source_chunks}
    sections.discard("")
    text_blob = _normalize(" ".join(c.get("text", "") for c in source_chunks))

    check = CitationCheck(cited=extract_citations(answer))
    for c in check.cited:
        n = _normalize(c)
        if n in sections or n in text_blob:
            check.verified.append(c)
        else:
            check.unverified.append(c)
    return check


def annotate(answer: str, check: CitationCheck) -> str:
    """If anything is unverified, append an explicit warning instead of hiding it."""
    if check.ok:
        return answer
    flagged = ", ".join(check.unverified)
    return (
        f"{answer}\n\n"
        f"⚠️ UNVERIFIED CITATION(S): {flagged}. These section references were not found in "
        f"your loaded code books and may be incorrect. Verify directly in the adopted code "
        f"before relying on them."
    )
