"""Deterministic Connecticut code-applicability cues used before retrieval.

This module does not make a code determination. It only recognizes an original building-permit
period the marshal explicitly supplied so retrieval can search the correct Part III/Part IV layer.
"""
from __future__ import annotations

import re

_CUTOFF_YEAR = 2006

_PRE_CUTOFF = re.compile(
    r"\b(?:pre[- ]?2006|before|prior\s+to)\s*(?:j(?:an(?:uary)?)\.?\s*1(?:st)?[,]?\s*)?2006\b",
    re.IGNORECASE,
)
_POST_CUTOFF = re.compile(
    r"\b(?:post[- ]?2005|(?:on\s+or\s+)?after)\s*(?:j(?:an(?:uary)?)\.?\s*1(?:st)?[,]?\s*)?2006\b|"
    r"\bj(?:an(?:uary)?)\.?\s*1(?:st)?[,]?\s*2006\s+or\s+later\b",
    re.IGNORECASE,
)
_PERMIT_YEAR = re.compile(
    r"\b(?:(?:original(?:ly)?\s+)?(?:building\s+)?"
    r"(?:permit(?:ted)?|permit\s+(?:was\s+)?issued)|"
    r"(?:original(?:ly)?\s+|(?:building|structure|property)\s+(?:was\s+)?)"
    r"(?:constructed|built))"
    r"(?:\s+(?:was|in|on|during|the\s+year))*\s+((?:18|19|20)\d{2})\b",
    re.IGNORECASE,
)


def original_permit_period(text: str, *, allow_bare_cutoff: bool = False) -> str | None:
    """Return ``pre_2006`` / ``post_2005`` only when the user's wording supplies the fact."""
    value = text or ""
    # A concrete original permit/construction year is stronger than other dates in the sentence.
    # If the user gives contradictory original years, do not silently choose either code layer.
    year_periods = {
        "pre_2006" if int(match.group(1)) < _CUTOFF_YEAR else "post_2005"
        for match in _PERMIT_YEAR.finditer(value)
    }
    if len(year_periods) == 1:
        return year_periods.pop()
    if len(year_periods) > 1:
        return None

    def has_original_building_context(match: re.Match) -> bool:
        window = value[max(0, match.start() - 60):min(len(value), match.end() + 60)]
        return bool(re.search(
            r"\b(?:original(?:ly)?\s+(?:building\s+)?permit|permit(?:ted)?|"
            r"original(?:ly)?\s+(?:constructed|built)|"
            r"(?:building|structure|property)\s+(?:was\s+)?(?:constructed|built))\b",
            window,
            re.IGNORECASE,
        ))

    bare_ok = allow_bare_cutoff or "building details:" in value.lower()
    pre = _PRE_CUTOFF.search(value)
    post = _POST_CUTOFF.search(value)
    pre_ok = bool(pre and (bare_ok or has_original_building_context(pre)))
    post_ok = bool(post and (bare_ok or has_original_building_context(post)))
    if pre_ok == post_ok:  # neither cue, or conflicting cues
        return None
    return "pre_2006" if pre_ok else "post_2005"
