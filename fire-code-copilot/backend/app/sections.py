"""Section-number utilities shared by the retriever (amendment matching) and the citation
validator. Code sections are hierarchical dotted numbers (903, 903.2, 903.2.8, 903.2.8.4).
Treating them as plain strings is the root of two bugs we fix elsewhere:
  - "903.2" should match its child "903.2.8" for amendment precedence (ancestor governs);
  - "903.2" must NOT be considered "present" just because "903.2.8" is (substring false-positive).
These helpers give one normalization + a precise ancestor/descendant relation.
"""
from __future__ import annotations
import re

_KEYWORDS = re.compile(r"(?i)\b(sections?|sec\.?|tables?|chapters?|chap\.?|appendix|annex)\b")
_PURE_NUMBER = re.compile(r"^\d+[A-Z]?(?:\.\d+)*$")
_FIRST_NUMBER = re.compile(r"\d+(?:\.\d+)*")


def canonical(s: str | None) -> str:
    """Normalize a section reference so '§903.2.8', 'Section 903.2.8.', 'Table 903.2.8' and
    '903.2.8' all compare equal. Non-section labels (e.g. 'NFPA 13') are upper-cased as-is."""
    s = _KEYWORDS.sub(" ", s or "")
    s = s.replace("§", " ")
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s.strip(" .,:;")


def numeric_tuple(s: str | None) -> tuple[str, ...] | None:
    """Return the dotted components of a pure section number, else None.

    '903.2.8' -> ('903','2','8'); 'NFPA 13' -> None (a standard label, not a dotted section)."""
    c = canonical(s)
    if not c or not _PURE_NUMBER.match(c):
        return None
    return tuple(c.split("."))


def relates(a: str | None, b: str | None) -> bool:
    """True if a and b are the same section, or one is an ancestor/descendant of the other
    (sharing at least chapter+section, so a bare chapter like '903' doesn't sweep in everything)."""
    ca, cb = canonical(a), canonical(b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    ta, tb = numeric_tuple(ca), numeric_tuple(cb)
    if ta and tb:
        n = min(len(ta), len(tb))
        return n >= 2 and ta[:n] == tb[:n]
    return False


def section_tokens(text: str) -> set[str]:
    """Every distinct dotted section number that literally appears in `text` (canonicalized),
    e.g. from a chunk body. Used for word-boundary 'is this section present?' checks."""
    return {m.group(0) for m in _FIRST_NUMBER.finditer(text or "") if "." in m.group(0)}
