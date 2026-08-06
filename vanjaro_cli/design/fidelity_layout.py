"""Deterministic layout and geometry fidelity metric (VF-002).

Compares where sections actually landed against where the design put them:
bounding-box overlap, column count, and section order. Layout carries the
heaviest weight in the scoring regime because a section in the wrong place or
with the wrong column count reads as broken regardless of colour or type.

Two absences are deliberately distinguished:

* A section present in the design but **absent from the build** is a real
  failure and scores zero.
* A section that was built but whose **geometry could not be measured** is
  unavailable and is excluded from the weighted mean.

Collapsing those would let a failed capture look like a missing section, or
worse, let a missing section disappear from the score entirely.

This module is pure: no network, filesystem, or model calls.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vanjaro_cli.design.fidelity import DimensionScore, FidelityDimension
from vanjaro_cli.design.models import BoundingBox

__all__ = [
    "BOUNDS_WEIGHT",
    "COLUMNS_WEIGHT",
    "ORDER_WEIGHT",
    "PageGeometry",
    "SectionGeometry",
    "normalized_iou",
    "score_page_layout",
    "score_section_layout",
]

# Sub-weights within the layout dimension. Part of the frozen regime: changing
# them requires a regime version bump and a full re-baseline.
BOUNDS_WEIGHT = 0.60
COLUMNS_WEIGHT = 0.25
ORDER_WEIGHT = 0.15


class _LayoutModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SectionGeometry(_LayoutModel):
    """One section's measurable placement at one breakpoint.

    `bounds` of ``None`` means the section exists but its geometry was not
    captured. That is unavailable evidence, not a zero.
    """

    section_id: str = Field(min_length=1)
    order: int = Field(ge=0)
    bounds: BoundingBox | None = None
    columns: int | None = Field(default=None, ge=1)


class PageGeometry(_LayoutModel):
    """All section geometry for one page at one breakpoint.

    `viewport_width` scales pixel coordinates so a 1440px design and a 1280px
    render compare proportionally rather than registering a false offset.
    """

    viewport_width: float = Field(gt=0)
    sections: tuple[SectionGeometry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_sections(self) -> "PageGeometry":
        identifiers = [section.section_id.casefold() for section in self.sections]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("section IDs must be unique within a page geometry")
        return self

    def by_id(self) -> Mapping[str, SectionGeometry]:
        return {section.section_id: section for section in self.sections}


def _round(value: float) -> float:
    return round(value + 0.0, 4)


def _scaled(box: BoundingBox, viewport_width: float) -> tuple[float, float, float, float]:
    # Uniform scale by viewport width preserves aspect ratio, so a
    # proportionally identical layout at a different width scores 100.
    scale = viewport_width
    return (
        box.x / scale,
        box.y / scale,
        box.width / scale,
        box.height / scale,
    )


def normalized_iou(
    expected: BoundingBox,
    observed: BoundingBox,
    *,
    expected_viewport_width: float,
    observed_viewport_width: float,
) -> float:
    """Intersection over union of two boxes, each scaled to its own viewport."""

    ex, ey, ew, eh = _scaled(expected, expected_viewport_width)
    ox, oy, ow, oh = _scaled(observed, observed_viewport_width)

    expected_area = ew * eh
    observed_area = ow * oh
    if expected_area == 0 and observed_area == 0:
        # Two degenerate boxes in the same place are a match; elsewhere, not.
        return 1.0 if (ex, ey) == (ox, oy) else 0.0

    overlap_width = max(0.0, min(ex + ew, ox + ow) - max(ex, ox))
    overlap_height = max(0.0, min(ey + eh, oy + oh) - max(ey, oy))
    intersection = overlap_width * overlap_height
    union = expected_area + observed_area - intersection
    if union <= 0:
        return 0.0
    return _round(intersection / union)


def _columns_subscore(expected: int | None, observed: int | None) -> float | None:
    if expected is None or observed is None:
        return None
    if expected == observed:
        return 100.0
    # Ratio rather than all-or-nothing: a 3-column band rendered as 2 is closer
    # to correct than one rendered as 12.
    return _round(100.0 * min(expected, observed) / max(expected, observed))


def _order_subscore(expected: int, observed: int, *, section_count: int) -> float:
    if expected == observed:
        return 100.0
    span = max(section_count - 1, 1)
    displacement = min(abs(expected - observed), span)
    return _round(100.0 * (1 - displacement / span))


def _combine(parts: Iterable[tuple[float, float | None]]) -> float | None:
    total = 0.0
    total_weight = 0.0
    for weight, value in parts:
        if value is None:
            continue
        total += weight * value
        total_weight += weight
    if total_weight == 0:
        return None
    return _round(total / total_weight)


def score_section_layout(
    expected: SectionGeometry,
    observed: SectionGeometry | None,
    *,
    expected_viewport_width: float,
    observed_viewport_width: float,
    section_count: int,
) -> DimensionScore:
    """Score one section's placement against its design geometry."""

    if observed is None:
        return DimensionScore(
            dimension=FidelityDimension.LAYOUT,
            score=0.0,
            detail=f"section {expected.section_id!r} is absent from the build",
        )

    bounds_subscore: float | None = None
    if expected.bounds is not None and observed.bounds is not None:
        bounds_subscore = _round(
            100.0
            * normalized_iou(
                expected.bounds,
                observed.bounds,
                expected_viewport_width=expected_viewport_width,
                observed_viewport_width=observed_viewport_width,
            )
        )

    columns_subscore = _columns_subscore(expected.columns, observed.columns)
    order_subscore = _order_subscore(
        expected.order, observed.order, section_count=section_count
    )

    score = _combine(
        (
            (BOUNDS_WEIGHT, bounds_subscore),
            (COLUMNS_WEIGHT, columns_subscore),
            (ORDER_WEIGHT, order_subscore),
        )
    )

    unavailable = []
    if bounds_subscore is None:
        unavailable.append("bounds")
    if columns_subscore is None:
        unavailable.append("columns")

    detail = None
    if unavailable:
        detail = "no geometry evidence for " + ", ".join(unavailable)

    subscores = (bounds_subscore, columns_subscore, order_subscore)
    return DimensionScore(
        dimension=FidelityDimension.LAYOUT,
        score=score,
        detail=detail,
        measured_subscores=sum(1 for entry in subscores if entry is not None),
        total_subscores=len(subscores),
    )


def score_page_layout(
    expected: PageGeometry,
    observed: PageGeometry,
) -> dict[str, DimensionScore]:
    """Score every designed section, keyed by section ID.

    Sections present in the build but absent from the design are ignored here;
    unplanned extra content is a planning concern, not a layout measurement.
    """

    observed_by_id = observed.by_id()
    section_count = len(expected.sections)
    return {
        section.section_id: score_section_layout(
            section,
            observed_by_id.get(section.section_id),
            expected_viewport_width=expected.viewport_width,
            observed_viewport_width=observed.viewport_width,
            section_count=section_count,
        )
        for section in expected.sections
    }
