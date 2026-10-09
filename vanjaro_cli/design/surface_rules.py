"""Rules for which painted boxes count as a section's surfaces.

A card or panel is a painted box that holds text and is smaller than the band it
sits on. The Figma adapter applies these rules to the solid-filled nodes it
reads from the API, and the fidelity scorer applies the same rules to the painted
elements a browser reports for the build. One shared rule set is what keeps the
two sides comparing the same kind of thing: a rule that differed would score
every card as a mismatch.

This module is pure: no network, filesystem, or model calls.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = [
    "SURFACE_LIMIT",
    "SurfaceCandidate",
    "select_surfaces",
]

# A band spans most of the section; a card does not. Anything at least this wide
# is the section's own background, which the colour dimension scores separately.
SURFACE_MAX_WIDTH_RATIO = 0.8
SURFACE_MIN_WIDTH_RATIO = 0.12
SURFACE_MIN_AREA_RATIO = 0.02
# Keeps a button or a tag chip out: those are the accent role's business.
SURFACE_MIN_SIDE_PX = 64.0
# A card drawn as a frame holding a same-sized rectangle is one card, not two.
SURFACE_DUPLICATE_OVERLAP = 0.9
SURFACE_LIMIT = 24


@dataclass(frozen=True)
class SurfaceCandidate:
    """One painted box, in the coordinate space of its section."""

    color: str
    x: float
    y: float
    width: float
    height: float
    has_text: bool
    reference: str | None = None


def _overlap_share(first: SurfaceCandidate, second: SurfaceCandidate) -> float:
    width = min(first.x + first.width, second.x + second.width) - max(first.x, second.x)
    height = min(first.y + first.height, second.y + second.height) - max(first.y, second.y)
    if width <= 0 or height <= 0:
        return 0.0
    smaller = min(first.width * first.height, second.width * second.height)
    return (width * height) / smaller if smaller > 0 else 0.0


def select_surfaces(
    candidates: Iterable[SurfaceCandidate],
    section_width: float,
    section_height: float,
) -> list[SurfaceCandidate]:
    """Pick the cards and panels from a section's painted boxes, in reading order.

    Two sections of the same page can be compared box for box because both sides
    answer the same three questions: does it hold text, is it narrower than a
    band, and is it big enough to be seen as a card. A duplicate of the same
    colour on top of an earlier box is dropped.
    """

    if section_width <= 0 or section_height <= 0:
        return []
    section_area = section_width * section_height
    usable = [
        candidate
        for candidate in candidates
        if candidate.has_text
        and candidate.width >= section_width * SURFACE_MIN_WIDTH_RATIO
        and candidate.width < section_width * SURFACE_MAX_WIDTH_RATIO
        and candidate.height >= SURFACE_MIN_SIDE_PX
        and candidate.width * candidate.height >= section_area * SURFACE_MIN_AREA_RATIO
    ]
    usable.sort(key=lambda candidate: (candidate.y, candidate.x))
    kept: list[SurfaceCandidate] = []
    for candidate in usable:
        if any(
            existing.color == candidate.color
            and _overlap_share(existing, candidate) >= SURFACE_DUPLICATE_OVERLAP
            for existing in kept
        ):
            continue
        kept.append(candidate)
    return kept[:SURFACE_LIMIT]
