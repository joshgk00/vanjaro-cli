"""Deterministic copy-presence metric (RT-37).

Scores whether the words a design states show up in the section that was built.
A card title the build left out, or set in white on a white card, costs points
the same way a missing photo does. Layout, colour, and type can all match while
the page says nothing, and nothing else in the regime would notice.

The design side lists the lines of text it states, each with a weight: a heading
or a stat figure counts three times a line of body copy, because it is what a
visitor reads first. The build side is the section's rendered text, already
reduced to the runs a visitor can actually see. Matching works on whole words,
ignores case and punctuation, and uses each stretch of rendered text once, so
four "Learn More" buttons need four in the build. A long passage earns partial
credit for the share of its words that are present, so a light edit to a
paragraph is not scored as a deleted paragraph. A short line is present or it is
not.

This module is pure: no network, filesystem, or model calls.
"""

from __future__ import annotations

from collections import defaultdict
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from vanjaro_cli.design.fidelity import DimensionScore, FidelityDimension

__all__ = [
    "BODY_WEIGHT",
    "HEADLINE_WEIGHT",
    "PLACEHOLDER_COPY",
    "CopyExpectation",
    "SectionCopy",
    "score_section_copy",
    "tokenize_copy",
]

# A heading or a stat figure is read before anything else on the band.
HEADLINE_WEIGHT = 3
BODY_WEIGHT = 1
# Passages at least this long are scored by the share of their words present.
# Shorter lines are titles, labels, and buttons, where a missing word is a
# different line.
_PARTIAL_CREDIT_MIN_TOKENS = 6
_LISTED_LIMIT = 5

_WORD = re.compile(r"[^\W_]+")

# Sample text a design carries until someone writes the real copy. The build never
# ships it -- the planner rejects or clears it and the integrity dimension zeroes a
# section that leaks it -- so a build without it is following the rule, not missing
# words. Kept identical to the planner's vocabulary.
PLACEHOLDER_COPY = re.compile(
    r"(?:placehold\.co|placeholder(?:\s+(?:text|image))?|lorem\s+ipsum|example\.com)",
    re.IGNORECASE,
)


class _CopyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CopyExpectation(_CopyModel):
    """One line of text the design states, and how much it matters."""

    text: str = Field(min_length=1)
    weight: int = Field(default=BODY_WEIGHT, ge=1)


class SectionCopy(_CopyModel):
    """What a section is meant to say, or what it was seen to say.

    The design side fills `expected`; the build side fills `rendered`, the text a
    visitor can see. ``rendered=None`` means the measurement did not report it
    (a design, or evidence recorded before the signal existed), and is never read
    as an empty page. An empty string is a measured page with no visible text.
    """

    expected: tuple[CopyExpectation, ...] = ()
    rendered: str | None = None


def tokenize_copy(text: str) -> list[str]:
    """Split text into lowercase words, dropping punctuation and compatibility forms."""

    return _WORD.findall(unicodedata.normalize("NFKC", text).casefold())


def _find_run(needle: list[str], haystack: list[str], taken: list[bool]) -> int | None:
    """Return where `needle` appears in `haystack` over unused words, or None."""

    size = len(needle)
    for start in range(len(haystack) - size + 1):
        if all(
            haystack[start + offset] == needle[offset] and not taken[start + offset]
            for offset in range(size)
        ):
            return start
    return None


def _credit(lines: list[list[str]], rendered: list[str]) -> list[float]:
    """Give each line a credit from 0 to 1, using every rendered word at most once."""

    taken = [False] * len(rendered)
    credit = [0.0] * len(lines)
    # Longest first, so "Learn More About Us" claims its words before a
    # "Learn More" button can borrow them.
    order = sorted(range(len(lines)), key=lambda index: (-len(lines[index]), index))

    for index in order:
        start = _find_run(lines[index], rendered, taken)
        if start is not None:
            for position in range(start, start + len(lines[index])):
                taken[position] = True
            credit[index] = 1.0

    for index in order:
        words = lines[index]
        if credit[index] or len(words) < _PARTIAL_CREDIT_MIN_TOKENS:
            continue
        free: dict[str, list[int]] = defaultdict(list)
        for position, word in enumerate(rendered):
            if not taken[position]:
                free[word].append(position)
        matched = 0
        for word in words:
            if free[word]:
                taken[free[word].pop(0)] = True
                matched += 1
        credit[index] = matched / len(words)
    return credit


def _shown(text: str) -> str:
    collapsed = " ".join(text.split())
    return f"{collapsed[:40]}..." if len(collapsed) > 40 else collapsed


def score_section_copy(expected: SectionCopy, observed: SectionCopy) -> DimensionScore:
    """Score how much of the designed wording the built section shows."""

    lines = [
        (words, item)
        for item in expected.expected
        if (words := tokenize_copy(item.text))
    ]
    if not lines:
        return DimensionScore(
            dimension=FidelityDimension.COPY,
            score=None,
            detail="the design states no copy for this section",
        )
    if observed.rendered is None:
        return DimensionScore(
            dimension=FidelityDimension.COPY,
            score=None,
            detail="the build did not report its rendered text",
        )

    credit = _credit([words for words, _ in lines], tokenize_copy(observed.rendered))
    weights = [item.weight for _, item in lines]
    score = round(100.0 * sum(c * w for c, w in zip(credit, weights)) / sum(weights), 4)

    absent = [_shown(item.text) for (_, item), c in zip(lines, credit) if c == 0.0]
    partial = sum(1 for c in credit if 0.0 < c < 1.0)
    details: list[str] = []
    if absent:
        listed = ", ".join(repr(text) for text in absent[:_LISTED_LIMIT])
        more = len(absent) - _LISTED_LIMIT
        details.append(
            f"copy absent from the build: {listed}" + (f" and {more} more" if more > 0 else "")
        )
    if partial:
        details.append(f"{partial} passage(s) only partly present")

    return DimensionScore(
        dimension=FidelityDimension.COPY,
        score=score,
        detail="; ".join(details) if details else None,
    )
