"""Text normalization and fuzzy set matching for migration verification.

All functions here are stdlib-only so Phase 5 verify can score text similarity
without pulling in an NLP dependency. The matching is deliberately simple:
greedy, per-item, based on :func:`difflib.SequenceMatcher.ratio`.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

__all__ = [
    "TextMatchResult",
    "fuzzy_set_match",
    "normalize_text",
    "score_text_match",
]


_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class TextMatchResult:
    """Per-page text comparison outcome."""

    score: float = 1.0
    threshold: float = 0.9
    passed: bool = True
    matched_headings: int = 0
    missing_headings: list[str] = field(default_factory=list)
    matched_paragraphs: int = 0
    missing_paragraphs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "threshold": self.threshold,
            "passed": self.passed,
            "matched_headings": self.matched_headings,
            "missing_headings": list(self.missing_headings),
            "matched_paragraphs": self.matched_paragraphs,
            "missing_paragraphs": list(self.missing_paragraphs),
        }


def normalize_text(raw: str) -> str:
    """Collapse whitespace runs and decode HTML entities. Keep case and punctuation."""
    if not isinstance(raw, str):
        return ""
    decoded = html.unescape(raw)
    collapsed = _WHITESPACE_RE.sub(" ", decoded)
    return collapsed.strip()


def fuzzy_set_match(
    source_items: list[str],
    migrated_items: list[str],
    min_ratio: float = 0.85,
) -> tuple[list[str], list[str]]:
    """Greedy one-to-one matching between two lists of strings.

    Returns ``(matched, missing)`` — both in source order. Each migrated
    item can match at most one source item, so a section reordered across
    the page still counts as matched. The per-item ``min_ratio`` is the
    :func:`difflib.SequenceMatcher.ratio` cut-off for calling two strings
    "the same block, reordered"; it is separate from the page-level
    threshold that gates overall pass/fail.
    """
    normalized_migrated = [normalize_text(item) for item in migrated_items]
    remaining = [index for index, value in enumerate(normalized_migrated) if value]

    matched: list[str] = []
    missing: list[str] = []

    for source_item in source_items:
        source_normalized = normalize_text(source_item)
        best_index = -1

        if source_normalized:
            best_ratio = min_ratio
            source_length = len(source_normalized)
            for index in remaining:
                candidate = normalized_migrated[index]
                # Exact match is the common case on a clean migration — skip
                # SequenceMatcher entirely when we find one.
                if candidate == source_normalized:
                    best_index = index
                    best_ratio = 1.0
                    break
                # ratio() cannot exceed 2*min(la,lb)/(la+lb). Skip candidates
                # whose length alone puts them below the current best ratio.
                candidate_length = len(candidate)
                total_length = source_length + candidate_length
                if total_length == 0:
                    continue
                ceiling = (2 * min(source_length, candidate_length)) / total_length
                if ceiling < best_ratio:
                    continue
                ratio = SequenceMatcher(None, source_normalized, candidate).ratio()
                if ratio >= best_ratio:
                    best_ratio = ratio
                    best_index = index

        if best_index == -1:
            missing.append(source_item)
        else:
            matched.append(source_item)
            remaining.remove(best_index)

    return matched, missing


def score_text_match(
    source_headings: list[str],
    source_paragraphs: list[str],
    migrated_headings: list[str],
    migrated_paragraphs: list[str],
    threshold: float = 0.9,
) -> TextMatchResult:
    """Score headings and paragraphs together as a single weighted ratio."""
    matched_headings, missing_headings = fuzzy_set_match(
        source_headings, migrated_headings
    )
    matched_paragraphs, missing_paragraphs = fuzzy_set_match(
        source_paragraphs, migrated_paragraphs
    )

    total_source = len(source_headings) + len(source_paragraphs)
    if total_source == 0:
        return TextMatchResult(
            score=1.0,
            threshold=threshold,
            passed=True,
        )

    matched_total = len(matched_headings) + len(matched_paragraphs)
    score = matched_total / total_source

    return TextMatchResult(
        score=score,
        threshold=threshold,
        passed=score >= threshold,
        matched_headings=len(matched_headings),
        missing_headings=missing_headings,
        matched_paragraphs=len(matched_paragraphs),
        missing_paragraphs=missing_paragraphs,
    )
