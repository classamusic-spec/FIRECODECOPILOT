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
_LABELED_QUICK_PICK = re.compile(
    r"was\s+the\s+original\s+(?:building\s+)?permit\s+issued\s+before\s+"
    r"j(?:an(?:uary)?)?\.?\s*1(?:st)?[,]?\s*2006\?\s*:\s*(?P<answer>[^;\n]+)",
    re.IGNORECASE,
)
_PERMIT_YEAR = re.compile(
    r"\b(?:original(?:ly)?\s+(?:building\s+)?"
    r"(?:permit(?:ted)?|permit\s+(?:was\s+)?issued|constructed|built)|"
    r"(?:building|structure|property)\s+(?:was\s+)?originally\s+"
    r"(?:permitted|constructed|built))"
    r"(?:\s+(?:was|in|on|during|the\s+year))*\s+((?:18|19|20)\d{2})\b",
    re.IGNORECASE,
)
_ORIGINAL_CUTOFF_OWNER = re.compile(
    r"(?:\boriginal(?:ly)?\s+(?:building\s+)?permit(?:ted)?"
    r"(?:\s+(?:(?:was\s+)?issued|was|is|date(?:\s+(?:was|is))?))?|"
    r"\boriginal(?:ly)?\s+(?:constructed|built)|"
    r"\b(?:building|structure|property)\s+(?:was\s+)?originally\s+"
    r"(?:permitted|constructed|built))\s*$",
    re.IGNORECASE,
)


def original_permit_period(text: str, *, allow_bare_cutoff: bool = False) -> str | None:
    """Return ``pre_2006`` / ``post_2005`` only when the user's wording supplies the fact."""
    value = text or ""
    # The frontend serializes a chip response as ``question: selected answer``. Parse the
    # selected side structurally so the question's "before" cannot conflict with a
    # post-cutoff selection.
    if allow_bare_cutoff:
        for labeled in _LABELED_QUICK_PICK.finditer(value):
            selected = labeled.group("answer").strip(" .;:")
            if _PRE_CUTOFF.fullmatch(selected):
                return "pre_2006"
            if _POST_CUTOFF.fullmatch(selected):
                return "post_2005"
    # A concrete original permit/construction year is stronger than other dates in the sentence.
    # If the user gives contradictory original years, do not silently choose either code layer.
    year_periods = set()
    for match in _PERMIT_YEAR.finditer(value):
        clause_start = max(
            value.rfind(";", 0, match.start()),
            value.rfind(",", 0, match.start()),
            value.rfind("\n", 0, match.start()),
        ) + 1
        clause_prefix = value[clause_start:match.start()].strip()
        owner_phrase = match.group(0)
        # A leading noun owns "originally constructed/permitted". Accept the shorthand only
        # when it starts the clause; otherwise require building/structure/property in the matched
        # owner phrase. This rejects alarm panels, pumps, detectors, and unknown future components
        # without relying on an inevitably incomplete component denylist.
        if (clause_prefix
                and not re.fullmatch(r"the", clause_prefix, re.I)
                and not re.search(r"\b(?:building|structure|property)\b", owner_phrase, re.I)):
            continue
        subject_prefix = value[max(0, match.start() - 50):match.start()]
        if re.search(
            r"\b(?:addition|alteration|renovation|fit[- ]?out|sprinkler|fire alarm|"
            r"system|equipment|installation)(?:\s+(?:system|work|permit|was|is))*\s*$",
            subject_prefix,
            re.IGNORECASE,
        ):
            continue
        year_periods.add(
            "pre_2006" if int(match.group(1)) < _CUTOFF_YEAR else "post_2005"
        )
    if len(year_periods) == 1:
        return year_periods.pop()
    if len(year_periods) > 1:
        return None

    def has_original_building_context(match: re.Match) -> bool:
        # Ownership must be grammatical, not merely nearby. This rejects constructions such
        # as "original permit pending; sprinkler installed before 2006".
        clause_start = max(
            value.rfind(";", 0, match.start()),
            value.rfind(",", 0, match.start()),
            value.rfind("\n", 0, match.start()),
        ) + 1
        return bool(_ORIGINAL_CUTOFF_OWNER.search(value[clause_start:match.start()]))

    def is_bare_quick_pick(match: re.Match) -> bool:
        if not allow_bare_cutoff:
            return False
        line_start = value.rfind("\n", 0, match.start()) + 1
        line_end = value.find("\n", match.end())
        line = value[line_start:line_end if line_end >= 0 else len(value)].strip(" .;:")
        return bool(_PRE_CUTOFF.fullmatch(line) or _POST_CUTOFF.fullmatch(line))

    def is_serialized_question_cue(match: re.Match) -> bool:
        line_start = value.rfind("\n", 0, match.start()) + 1
        line_end = value.find("\n", match.end())
        line_end = line_end if line_end >= 0 else len(value)
        colon = value.find(":", match.end(), line_end)
        if colon < 0:
            return False
        label = value[line_start:colon]
        return bool(re.search(r"\boriginal\s+(?:building\s+)?permit\b", label, re.I))

    def cue_is_owned(match: re.Match) -> bool:
        return (not is_serialized_question_cue(match)
                and (is_bare_quick_pick(match) or has_original_building_context(match)))

    pre_ok = any(cue_is_owned(match) for match in _PRE_CUTOFF.finditer(value))
    post_ok = any(cue_is_owned(match) for match in _POST_CUTOFF.finditer(value))
    if pre_ok == post_ok:  # neither cue, or conflicting cues
        return None
    return "pre_2006" if pre_ok else "post_2005"
