"""Query rewriting/expansion — the cheapest recall win for code retrieval.

The bi-encoder embeds the marshal's words literally, so "R-2", "IFC", or "AHJ" don't pull in
the chunks that spell those concepts out. We APPEND (never replace) a few deterministic
expansions for terms we recognize, so the query vector also covers the spelled-out forms.
Deterministic + table-driven so it's testable and never invents domain facts.
"""
from __future__ import annotations
import re

from .settings import settings

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

# "R-2", "R2", "Group R-2", "A-3" ... captured so we can map the occupancy code.
_OCC_RE = re.compile(r"\b(?:group\s+)?([ABEFHIMRSU])-?([1-4])?\b", re.IGNORECASE)


def expand_query(q: str) -> str:
    """Return the query with recognized occupancy codes and acronyms spelled out (appended)."""
    if not settings.expand_queries or not q.strip():
        return q
    additions: list[str] = []
    seen: set[str] = set()

    low = q.lower()
    for abbr, full in _TERMS.items():
        if abbr in low and full.lower() not in low and full not in seen:
            additions.append(full)
            seen.add(full)

    for m in _OCC_RE.finditer(q):
        letter = m.group(1).upper()
        key = f"{letter}-{m.group(2)}" if m.group(2) else letter
        full = _OCCUPANCY.get(key) or _OCCUPANCY.get(letter)
        if full and full not in seen:
            additions.append(full)
            seen.add(full)

    return f"{q}  [{'; '.join(additions)}]" if additions else q
