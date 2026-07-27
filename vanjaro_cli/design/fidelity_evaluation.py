"""Assemble the six fidelity dimensions into section and page scores (VF-007).

The individual metrics in `fidelity_layout`, `fidelity_color`, `fidelity_type`,
and `fidelity_media` each answer one question. This module combines them into
the `SectionFidelityScore` records the gate consumes, and provides the
`score_hook` that `run_visual_quality_gate` calls.

Expected observations come from the design; observed observations come from the
build. Both sides use the same shape so the comparison stays source-neutral —
a Figma frame and a live page produce the same bundle.

This module is pure: no network, filesystem, or model calls.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vanjaro_cli.design.fidelity import (
    CURRENT_REGIME_VERSION,
    BreakpointFidelityScore,
    DimensionScore,
    FidelityDimension,
    SectionFidelityScore,
    aggregate_breakpoint,
)
from vanjaro_cli.design.fidelity_color import SectionPalette, score_section_color
from vanjaro_cli.design.fidelity_layout import (
    PageGeometry,
    SectionGeometry,
    score_section_layout,
)
from vanjaro_cli.design.fidelity_media import (
    IntegrityObservation,
    SectionMedia,
    score_section_integrity,
    score_section_media,
)
from vanjaro_cli.design.fidelity_type import (
    SectionSpacing,
    SectionTypography,
    score_section_spacing,
    score_section_typography,
)
from vanjaro_cli.design.models import BreakpointName

__all__ = [
    "PageObservation",
    "SectionObservation",
    "score_breakpoint_fidelity",
    "score_hook_from_observations",
    "score_section_fidelity",
]


class _EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SectionObservation(_EvaluationModel):
    """Everything measurable about one section, as designed or as built."""

    geometry: SectionGeometry
    palette: SectionPalette = Field(default_factory=SectionPalette)
    typography: SectionTypography = Field(default_factory=SectionTypography)
    spacing: SectionSpacing = Field(default_factory=SectionSpacing)
    media: SectionMedia = Field(default_factory=SectionMedia)
    # Integrity has no design-side counterpart; only the build can be defective.
    integrity: IntegrityObservation | None = None

    @property
    def section_id(self) -> str:
        return self.geometry.section_id


class PageObservation(_EvaluationModel):
    """All section observations for one page at one breakpoint."""

    viewport_width: float = Field(gt=0)
    sections: tuple[SectionObservation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_sections(self) -> "PageObservation":
        identifiers = [section.section_id.casefold() for section in self.sections]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("section IDs must be unique within a page observation")
        return self

    def geometry(self) -> PageGeometry:
        return PageGeometry(
            viewport_width=self.viewport_width,
            sections=tuple(section.geometry for section in self.sections),
        )

    def by_id(self) -> dict[str, SectionObservation]:
        return {section.section_id: section for section in self.sections}


def _absent_dimension(dimension: FidelityDimension, section_id: str) -> DimensionScore:
    return DimensionScore(
        dimension=dimension,
        score=0.0,
        detail=f"section {section_id!r} is absent from the build",
    )


def score_section_fidelity(
    expected: SectionObservation,
    observed: SectionObservation | None,
    *,
    breakpoint: BreakpointName,
    expected_viewport_width: float,
    observed_viewport_width: float,
    section_count: int,
) -> SectionFidelityScore:
    """Score one section across every dimension that has evidence."""

    layout = score_section_layout(
        expected.geometry,
        observed.geometry if observed is not None else None,
        expected_viewport_width=expected_viewport_width,
        observed_viewport_width=observed_viewport_width,
        section_count=section_count,
    )

    if observed is None:
        # A section that was never built fails every comparable dimension
        # rather than quietly reducing to a single layout zero.
        dimensions = (
            layout,
            _absent_dimension(FidelityDimension.COLOR, expected.section_id),
            _absent_dimension(FidelityDimension.TYPOGRAPHY, expected.section_id),
            _absent_dimension(FidelityDimension.SPACING, expected.section_id),
            _absent_dimension(FidelityDimension.MEDIA, expected.section_id),
        )
    else:
        dimensions = (
            layout,
            score_section_color(expected.palette, observed.palette),
            score_section_typography(expected.typography, observed.typography),
            score_section_spacing(expected.spacing, observed.spacing),
            score_section_media(expected.media, observed.media),
        )
        if observed.integrity is not None:
            dimensions = (*dimensions, score_section_integrity(observed.integrity))

    return SectionFidelityScore(
        regime_version=CURRENT_REGIME_VERSION,
        section_id=expected.section_id,
        breakpoint=breakpoint,
        dimensions=dimensions,
    )


def score_breakpoint_fidelity(
    expected: PageObservation,
    observed: PageObservation,
    *,
    breakpoint: BreakpointName,
) -> BreakpointFidelityScore:
    """Score every designed section at one breakpoint."""

    observed_by_id = observed.by_id()
    section_count = len(expected.sections)
    return aggregate_breakpoint(
        breakpoint,
        [
            score_section_fidelity(
                section,
                observed_by_id.get(section.section_id),
                breakpoint=breakpoint,
                expected_viewport_width=expected.viewport_width,
                observed_viewport_width=observed.viewport_width,
                section_count=section_count,
            )
            for section in expected.sections
        ],
    )


def score_hook_from_observations(
    expected: dict[BreakpointName, PageObservation],
    observed: dict[BreakpointName, PageObservation],
):
    """Build the gate's `ScoreHook` from per-breakpoint observations.

    Raises when a breakpoint has no observations rather than returning a
    default score. The gate must never receive an invented number for a
    breakpoint that was not measured.
    """

    from vanjaro_cli.design.fidelity import to_viewport_visual_score

    def hook(capture):
        breakpoint = capture.breakpoint
        expected_page = expected.get(breakpoint)
        observed_page = observed.get(breakpoint)
        if expected_page is None or observed_page is None:
            missing = "design" if expected_page is None else "build"
            raise ValueError(
                f"no {missing} observations for {breakpoint.value}; "
                "the gate cannot score an unmeasured breakpoint"
            )
        return to_viewport_visual_score(
            score_breakpoint_fidelity(
                expected_page, observed_page, breakpoint=breakpoint
            )
        )

    return hook


def serialize_breakpoint_scores(
    scores: Iterable[BreakpointFidelityScore],
) -> list[dict]:
    """Render breakpoint scores as plain JSON-ready records."""

    return [score.model_dump(mode="json") for score in scores]
