"""Query rewriting/expansion — the cheapest recall win for code retrieval.

The bi-encoder embeds the marshal's words literally, so "R-2", "IFC", or "AHJ" don't pull in
the chunks that spell those concepts out. We APPEND (never replace) a few deterministic
expansions for terms we recognize, so the query vector also covers the spelled-out forms.
Deterministic + table-driven so it's testable and never invents domain facts.
"""
from __future__ import annotations
import re

from .settings import settings
from .applicability import original_permit_period

# Occupancy groups and common subgroups (IBC/IFC Chapter 3). "R-2" -> "Group R-2 residential...".
_OCCUPANCY = {
    "A": "Group A assembly", "A-1": "Group A-1 assembly", "A-2": "Group A-2 assembly dining",
    "A-3": "Group A-3 assembly", "B": "Group B business", "E": "Group E educational",
    "F": "Group F factory industrial", "H": "Group H high-hazard",
    "I": "Group I institutional", "I-1": "Group I-1", "I-2": "Group I-2 hospital nursing",
    "M": "Group M mercantile", "R": "Group R residential",
    "R-1": "Group R-1 hotel transient", "R-2": "Group R-2 apartment multifamily residential",
    "R-3": "Group R-3 dwelling", "R-4": "Group R-4 residential care",
    "S": "Group S storage", "U": "Group U utility miscellaneous",
}

# Acronyms / abbreviations the marshal uses that the books spell out.
_TERMS = {
    "ifc": "International Fire Code", "ibc": "International Building Code",
    "iebc": "International Existing Building Code", "imc": "International Mechanical Code",
    "csfsc": "Connecticut State Fire Safety Code", "csbc": "Connecticut State Building Code",
    "ahj": "authority having jurisdiction", "nfpa": "National Fire Protection Association",
    "occ": "occupancy", "sprinklered": "automatic sprinkler system",
    "egress": "means of egress exit", "standpipe": "standpipe system",
    "fire area": "fire area separation", "occupant load": "occupant load factor",
}

# Exact code-book identifiers need richer expansion than the generic "NFPA" acronym. Keep these
# regex-based so "NFPA 1" never fires inside "NFPA 101". Connecticut part labels also lift the
# controlling amendment documents into the candidates alongside the requested model code.
_PRIMARY_CODE_BOOKS = (
    ("nfpa:101", re.compile(r"\bnfpa\s*101\b", re.IGNORECASE),
     "NFPA 101 Life Safety Code 2021 Connecticut State Fire Safety Code Part IV"),
    ("nfpa:1", re.compile(r"\bnfpa\s*1(?!\d)\b", re.IGNORECASE),
     "NFPA 1 Fire Code 2021 Connecticut State Fire Prevention Code"),
    ("ifc", re.compile(r"\b(?:ifc|international fire code)\b", re.IGNORECASE),
     "2021 International Fire Code Connecticut State Fire Safety Code Part III"),
    ("iebc", re.compile(r"\b(?:iebc|international existing building code)\b", re.IGNORECASE),
     "2021 International Existing Building Code Connecticut State Building Code"),
    ("ibc", re.compile(r"\b(?:ibc|international building code)\b", re.IGNORECASE),
     "2021 International Building Code Connecticut State Building Code"),
)
_ANY_CODE_BOOK_RE = re.compile(
    r"\b(?:NFPA\s*\d+|IFC|IBC|IEBC|International\s+(?:Fire|Building|Existing Building)\s+Code)\b",
    re.IGNORECASE,
)
_EDITION_YEAR = r"(?:19|20)\d{2}"

_OPERATIONAL_CUES = re.compile(
    r"\b(?:hot work|fire watch|hazardous materials?|flammable (?:and )?combustible liquids?|"
    r"commercial cooking|hood systems?|fire protection systems? maintenance|"
    r"inspection[,/ ]+testing[,/ ]+(?:and )?maintenance)\b",
    re.IGNORECASE,
)
_CURRENT_WORK_CUES = re.compile(
    r"\b(?:brand[- ]new|new construction|new building|additions?|alterations?|renovations?|"
    r"change of (?:occupancy|use))\b",
    re.IGNORECASE,
)

# "R-2", "R2", "Group R-2", "Group A" ... captured so we can map the occupancy code. A bare
# single letter only counts WITH the "Group" prefix; unanchored it matched the English words
# "a" and "I" ("do i need a permit?"), appending "Group A assembly / Group I institutional" to
# almost every natural-language query and skewing recall toward the wrong occupancy chapters.
_OCC_RE = re.compile(r"\b(?:group\s+([ABEFHIMRSU])(?:-?([1-4]))?|([ABEFHIMRSU])-?([1-4]))\b",
                     re.IGNORECASE)


def primary_edition_intents(query: str) -> dict[str, set[str]]:
    """Return explicit edition years attached to each primary code family occurrence."""
    value = query or ""
    intents: dict[str, set[str]] = {}
    occurrences = [
        (match.start(), match.end(), family)
        for family, pattern, _full in _PRIMARY_CODE_BOOKS
        for match in pattern.finditer(value)
    ]
    occurrences.sort()
    for start, end, family in occurrences:
        years = intents.setdefault(family, set())
        previous_book_end = max(
            (book.end() for book in _ANY_CODE_BOOK_RE.finditer(value, 0, start)),
            default=max(value.rfind(";", 0, start), value.rfind("\n", 0, start)) + 1,
        )
        before = value[previous_book_end:start]
        before_match = re.search(
            rf"(?P<years>{_EDITION_YEAR}(?:\s*(?:,|and|or|/)\s*{_EDITION_YEAR})*)"
            r"\s*(?:-?\s*editions?(?:\s+of)?)?\s*$",
            before,
            re.IGNORECASE,
        )
        if before_match:
            years.update(re.findall(_EDITION_YEAR, before_match.group("years")))

        next_book = _ANY_CODE_BOOK_RE.search(value, end)
        after = value[end:next_book.start() if next_book else len(value)]
        immediate = re.match(
            rf"\s*[-,(/]?\s*(?P<years>{_EDITION_YEAR}"
            rf"(?:\s*(?:,|and|or|/)\s*{_EDITION_YEAR})*)\b",
            after,
            re.IGNORECASE,
        )
        if immediate:
            years.update(re.findall(_EDITION_YEAR, immediate.group("years")))
        for distant in re.finditer(
            rf"\b(?:from|under|in|using)\s+(?:the\s+)?({_EDITION_YEAR})\s+edition\b",
            after,
            re.IGNORECASE,
        ):
            years.add(distant.group(1))
    return intents


def primary_family_allows_active(query: str, family: str) -> bool:
    """Whether active-cycle retrieval is valid for this explicitly named family."""
    years = primary_edition_intents(query).get(family)
    return not years or "2021" in years


def has_any_nonactive_primary_edition(query: str) -> bool:
    """Whether any named primary family is explicitly historical/future without active 2021."""
    return any(
        years and "2021" not in years
        for years in primary_edition_intents(query).values()
    )


def has_explicit_nonactive_primary_edition(query: str) -> bool:
    """True only when every explicitly named primary family excludes active 2021."""
    intents = primary_edition_intents(query)
    return bool(intents) and all(years and "2021" not in years for years in intents.values())


def expand_query(q: str) -> str:
    """Return the query with recognized occupancy codes and acronyms spelled out (appended)."""
    if not settings.expand_queries or not q.strip():
        return q
    additions: list[str] = []
    seen: set[str] = set()

    low = q.lower()
    period = original_permit_period(q)
    if period == "pre_2006" and primary_family_allows_active(q, "nfpa:101"):
        full = "NFPA 101 Life Safety Code 2021 Connecticut State Fire Safety Code Part IV"
        additions.append(full)
        seen.add(full)
    elif period == "post_2005" and primary_family_allows_active(q, "ifc"):
        full = "2021 International Fire Code Connecticut State Fire Safety Code Part III"
        additions.append(full)
        seen.add(full)

    if (_OPERATIONAL_CUES.search(q)
            and primary_family_allows_active(q, "nfpa:1")):
        full = "NFPA 1 Fire Code 2021 Connecticut State Fire Prevention Code"
        if full not in seen:
            additions.append(full)
            seen.add(full)
    if (_CURRENT_WORK_CUES.search(q)
            and primary_family_allows_active(q, "ifc")):
        full = "2021 International Fire Code Connecticut State Fire Safety Code Part III"
        if full not in seen:
            additions.append(full)
            seen.add(full)

    for family, pattern, full in _PRIMARY_CODE_BOOKS:
        match = pattern.search(q)
        if (match and primary_family_allows_active(q, family)
                and full.lower() not in low and full not in seen):
            additions.append(full)
            seen.add(full)

    for abbr, full in _TERMS.items():
        if abbr in low and full.lower() not in low and full not in seen:
            additions.append(full)
            seen.add(full)

    for m in _OCC_RE.finditer(q):
        letter = (m.group(1) or m.group(3)).upper()      # "Group X" branch or "X-2" branch
        digit = m.group(2) or m.group(4)
        key = f"{letter}-{digit}" if digit else letter
        full = _OCCUPANCY.get(key) or _OCCUPANCY.get(letter)
        if full and full not in seen:
            additions.append(full)
            seen.add(full)

    return f"{q}  [{'; '.join(additions)}]" if additions else q
