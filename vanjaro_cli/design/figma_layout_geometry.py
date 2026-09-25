"""Generic geometry inference for content media beside a text cluster.

Figma freeform sections (no auto-layout) sometimes place one dominant piece
of media — a photo, illustration, or similar — to one side of a frame while
supporting copy stacks vertically on the other side, at y-positions that
never share a common row. A pure row-clustering column count (grouping
children whose `y` values are close together) never recognizes that shape:
every text box lands in its own one-item row, and the layout is reported as
a single, unstructured column with no media side at all.

This module looks for that specific, bounded pattern directly from
`absoluteBoundingBox` geometry — one non-decorative, non-full-bleed image
that clearly dominates any other image candidate in area, sitting beside a
cluster of text boxes that mostly falls outside its horizontal span. It
deliberately stays silent (returns `None`) whenever the evidence does not
clear that bar: missing or invalid bounds, an oversized/full-bleed image,
multiple similarly sized images (an ambiguous collage), or text that mostly
overlaps the image (a centered or text-over-background composition). It
never uses node names, ids, exact pixel coordinates, or item counts as a
shortcut — every decision is a relative comparison against the enclosing
section's own measured box.

The same helper backs both the call-to-action side-media case (an existing,
narrower capability) and any other freeform section — hero, split media,
testimonial feature, and so on — so the two never diverge in behavior.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from vanjaro_cli.design.figma_tree import (
    box as _box,
    children as _children,
    is_decorative as _is_decorative,
    visible as _visible,
)
from vanjaro_cli.design.models import BoundingBox

__all__ = ["SideMediaObservation", "infer_side_media"]

# A side-media region must read as a deliberate, dedicated visual zone: wide
# enough to not be a small icon or badge, but narrow enough that it cannot be
# a full-bleed background fill (that case is excluded separately, below, by
# area and edge-to-edge width so a tall-but-narrow side image is not caught
# by a height-only rule).
_MIN_MEDIA_WIDTH_FRACTION = 0.15
_MAX_MEDIA_WIDTH_FRACTION = 0.62
_MIN_MEDIA_HEIGHT_FRACTION = 0.25
_MIN_MEDIA_AREA_FRACTION = 0.05

# A full-bleed fill spans (close to) the section's full width, or covers
# most of its area outright; either is treated as background, never as side
# media, regardless of the width/height bounds above.
_FULL_BLEED_WIDTH_FRACTION = 0.85
_FULL_BLEED_AREA_FRACTION = 0.72

# The strongest media candidate must clearly dominate any runner-up in area,
# or the composition reads as an ambiguous multi-image collage rather than
# one identifiable side-media region.
_MEDIA_DOMINANCE_RATIO = 1.8

# A text box still "belongs" to the side opposite the media as long as most
# of its own width sits outside the media's horizontal span — a headline
# nudging a little way over the edge of a photo is not disqualifying, but a
# box that mostly sits on top of (or centered across) the media is.
_MAX_TEXT_OVERLAP_FRACTION = 0.35

# Side-by-side media and text must actually co-occur vertically. Without
# this, a media region placed below (or above) a text stack — a vertical
# arrangement, not a side-by-side one — would still read as "the other side"
# on x alone, because moving something down a page does not change its x.
_MIN_VERTICAL_OVERLAP_FRACTION = 0.3

_BASE_CONFIDENCE = 0.86
_OVERLAP_CONFIDENCE_PENALTY = 0.06


def _visible_descendants(node: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield descendants of `node`, pruning any subtree an ancestor hides.

    A node nested under an invisible group is not part of the visible
    design regardless of its own `visible`/`opacity` attributes, so this
    stops descending as soon as a node fails `_visible`.
    """

    for child in _children(node):
        if not _visible(child):
            continue
        yield child
        yield from _visible_descendants(child)


@dataclass(frozen=True)
class SideMediaObservation:
    """A bounded, evidence-backed side-media reading of a freeform section."""

    media_position: str  # "left" or "right"
    confidence: float
    text_box_count: int
    had_overlap: bool


def _area(box: BoundingBox) -> float:
    return box.width * box.height


def _is_full_bleed(box: BoundingBox, section_box: BoundingBox) -> bool:
    section_area = max(1.0, _area(section_box))
    if section_box.width <= 0:
        return True
    width_fraction = box.width / section_box.width
    area_fraction = _area(box) / section_area
    return width_fraction >= _FULL_BLEED_WIDTH_FRACTION or area_fraction >= _FULL_BLEED_AREA_FRACTION


def _has_image_fill(node: Mapping[str, Any]) -> bool:
    fills = node.get("fills") or []
    return any(
        isinstance(fill, Mapping) and fill.get("type") == "IMAGE" and fill.get("visible") is not False
        for fill in fills
    )


def _media_candidates(
    descendants: list[dict[str, Any]], section_box: BoundingBox,
) -> list[tuple[dict[str, Any], BoundingBox]]:
    candidates: list[tuple[dict[str, Any], BoundingBox]] = []
    for current in descendants:
        if not _has_image_fill(current):
            continue
        if _is_decorative(current):
            continue
        current_box = _box(current)
        if current_box is None or current_box.width <= 0 or current_box.height <= 0:
            continue
        if _is_full_bleed(current_box, section_box):
            continue
        width_fraction = current_box.width / section_box.width if section_box.width else 0.0
        height_fraction = current_box.height / section_box.height if section_box.height else 0.0
        area_fraction = _area(current_box) / max(1.0, _area(section_box))
        if not (_MIN_MEDIA_WIDTH_FRACTION <= width_fraction <= _MAX_MEDIA_WIDTH_FRACTION):
            continue
        if height_fraction < _MIN_MEDIA_HEIGHT_FRACTION:
            continue
        if area_fraction < _MIN_MEDIA_AREA_FRACTION:
            continue
        candidates.append((current, current_box))
    return candidates


def _horizontal_overlap_fraction(media: BoundingBox, text: BoundingBox) -> float:
    if text.width <= 0:
        return 1.0
    overlap = max(0.0, min(media.x + media.width, text.x + text.width) - max(media.x, text.x))
    return overlap / text.width


def _vertical_overlap_fraction(media: BoundingBox, text: BoundingBox) -> float:
    smaller_height = min(media.height, text.height)
    if smaller_height <= 0:
        return 0.0
    overlap = max(0.0, min(media.y + media.height, text.y + text.height) - max(media.y, text.y))
    return overlap / smaller_height


def infer_side_media(
    node: Mapping[str, Any],
    section_box: BoundingBox | None,
) -> SideMediaObservation | None:
    """Return a side-media reading of `node`, or `None` when the evidence is too weak.

    `section_box` is the measured bounds of the section being classified
    (never a page or frame box). It must come from real
    `absoluteBoundingBox` data — this function never fabricates geometry for
    a section that lacks it. Candidate media and text are gathered from
    `node`'s own visible descendants, honoring ancestor visibility (a node
    nested under a hidden group is not visible evidence merely because its
    own `visible` flag is unset).
    """

    if section_box is None or section_box.width <= 0 or section_box.height <= 0:
        return None

    descendants = list(_visible_descendants(node))
    text_boxes = [
        box for current in descendants
        if current.get("type") == "TEXT" and (box := _box(current)) is not None
    ]

    candidates = _media_candidates(descendants, section_box)
    if not candidates:
        return None

    candidates.sort(key=lambda item: _area(item[1]), reverse=True)
    _, media_box = candidates[0]
    if len(candidates) > 1:
        runner_up_area = _area(candidates[1][1])
        if runner_up_area * _MEDIA_DOMINANCE_RATIO > _area(media_box):
            return None  # Ambiguous multi-image collage; stay conservative.

    if not text_boxes:
        return None

    qualifying = [
        box for box in text_boxes
        if _horizontal_overlap_fraction(media_box, box) <= _MAX_TEXT_OVERLAP_FRACTION
        and _vertical_overlap_fraction(media_box, box) >= _MIN_VERTICAL_OVERLAP_FRACTION
    ]
    # The opposite-side reading only holds if it explains most of the text,
    # not a lone box in an otherwise centered, overlapping, or vertically
    # stacked (media above/below the copy, not beside it) composition.
    if not qualifying or 2 * len(qualifying) < len(text_boxes):
        return None

    media_center = media_box.x + media_box.width / 2
    text_center = sum(box.x + box.width / 2 for box in qualifying) / len(qualifying)
    if media_center == text_center:
        return None  # No horizontal separation; not a side-media composition.

    had_overlap = any(
        _horizontal_overlap_fraction(media_box, box) > 0 for box in qualifying
    )
    confidence = _BASE_CONFIDENCE - (_OVERLAP_CONFIDENCE_PENALTY if had_overlap else 0.0)
    media_position = "left" if media_center < text_center else "right"
    return SideMediaObservation(
        media_position=media_position,
        confidence=confidence,
        text_box_count=len(qualifying),
        had_overlap=had_overlap,
    )
