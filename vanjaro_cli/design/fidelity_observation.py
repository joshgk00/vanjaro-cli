"""Derive fidelity observations from a rendered build (VF-009, observed side).

The expected side reads a Design Document; this side reads the page that was
actually built. Both produce `SectionObservation` bundles with identical sample
keys, so `score_section_fidelity` can compare them without either side knowing
where the other came from.

Section identity is not guessed from DOM structure. Every component the project
pipeline composes carries `data-agency-section` with the design section ID (see
`portal/page_composition._namespace_components`), so the rendered page states
its own correspondence to the design.

Measurement is split in two:

* `RenderedPage` and friends are plain data — the raw numbers a browser read off
  the page. Everything in this module that turns them into observations is pure
  and testable without a browser.
* `PageMeasurer` is the thin protocol a real browser implements, mirroring how
  `fidelity_capture.PageRenderer` isolates Playwright.

This module adds no browser stack of its own: the Playwright measurer reuses the
same settled session the capture harness uses.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from vanjaro_cli.design.fidelity_color import ColorRole, SectionPalette
from vanjaro_cli.design.fidelity_evaluation import PageObservation, SectionObservation
from vanjaro_cli.design.fidelity_layout import BoundingBox, SectionGeometry
from vanjaro_cli.design.fidelity_media import (
    IntegrityObservation,
    MediaSample,
    SectionMedia,
)
from vanjaro_cli.design.fidelity_type import (
    SectionSpacing,
    SectionTypography,
    SpacingSample,
    TypeSample,
)
from vanjaro_cli.design.models import BreakpointName

__all__ = [
    "PageMeasurer",
    "RenderedMedia",
    "RenderedPage",
    "RenderedSection",
    "RenderedText",
    "observe_built_page",
    "observe_built_section",
]


class _RenderedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RenderedText(_RenderedModel):
    """Computed type for one sampled element."""

    family: str | None = None
    size_px: float | None = Field(default=None, gt=0)
    weight: int | None = Field(default=None, ge=1, le=1000)
    # A build that refused a font substitution is reporting a known gap, not a
    # mismatch; the type metric treats it as unavailable rather than wrong.
    substitution_refused: bool = False


class RenderedMedia(_RenderedModel):
    """One rendered image, as measured in the page."""

    rendered_width: float = Field(gt=0)
    rendered_height: float = Field(gt=0)
    natural_width: float | None = Field(default=None, gt=0)
    natural_height: float | None = Field(default=None, gt=0)
    focal_x: float | None = Field(default=None, ge=0, le=1)
    focal_y: float | None = Field(default=None, ge=0, le=1)


class RenderedSection(_RenderedModel):
    """Everything a browser measured for one section."""

    section_id: str = Field(min_length=1)
    order: int = Field(ge=0)
    bounds: BoundingBox | None = None
    columns: int | None = Field(default=None, ge=1)
    background_color: str | None = None
    text_color: str | None = None
    accent_color: str | None = None
    typography: Mapping[str, RenderedText] = Field(default_factory=dict)
    padding_top: float | None = Field(default=None, ge=0)
    padding_bottom: float | None = Field(default=None, ge=0)
    element_gap: float | None = Field(default=None, ge=0)
    media: Sequence[RenderedMedia] = ()
    horizontal_overflow_px: float | None = Field(default=None, ge=0)
    empty_slot_count: int | None = Field(default=None, ge=0)
    placeholder_leaks: tuple[str, ...] = ()


class RenderedPage(_RenderedModel):
    """All measurements for one built page at one viewport."""

    viewport_width: float = Field(gt=0)
    sections: tuple[RenderedSection, ...] = ()
    console_error_count: int | None = Field(default=None, ge=0)


class PageMeasurer(Protocol):
    """Measures one built URL at one viewport on a settled page."""

    def measure(self, url: str, breakpoint: BreakpointName) -> RenderedPage:
        ...


def observe_built_page(rendered: RenderedPage) -> PageObservation | None:
    """Convert browser measurements into an observation bundle.

    Returns ``None`` when nothing was measured: `PageObservation` requires at
    least one section, and an empty page is a capture failure for the gate to
    report rather than a page that scores zero.
    """

    if not rendered.sections:
        return None
    ordered = sorted(rendered.sections, key=lambda item: (item.order, item.section_id))
    return PageObservation(
        viewport_width=rendered.viewport_width,
        sections=tuple(
            observe_built_section(section, console_error_count=rendered.console_error_count)
            for section in ordered
        ),
    )


def observe_built_section(
    section: RenderedSection,
    *,
    console_error_count: int | None = None,
) -> SectionObservation:
    """Convert one section's measurements into an observation."""

    return SectionObservation(
        geometry=SectionGeometry(
            section_id=section.section_id,
            order=section.order,
            bounds=section.bounds,
            columns=section.columns,
        ),
        palette=_palette(section),
        typography=_typography(section),
        spacing=SectionSpacing(
            spacing=SpacingSample(
                padding_top=section.padding_top,
                padding_bottom=section.padding_bottom,
                element_gap=section.element_gap,
            )
        ),
        media=_media(section),
        integrity=IntegrityObservation(
            horizontal_overflow_px=section.horizontal_overflow_px,
            empty_slot_count=section.empty_slot_count,
            console_error_count=console_error_count,
            placeholder_leaks=tuple(section.placeholder_leaks),
        ),
    )


def _palette(section: RenderedSection) -> SectionPalette:
    colors: dict[ColorRole, str] = {}
    for role, value in (
        (ColorRole.BACKGROUND, section.background_color),
        (ColorRole.TEXT, section.text_color),
        (ColorRole.ACCENT, section.accent_color),
    ):
        if isinstance(value, str) and value.strip():
            colors[role] = value.strip()
    return SectionPalette(colors=colors)


def _typography(section: RenderedSection) -> SectionTypography:
    samples = {
        key: TypeSample(
            family=sample.family,
            size_px=sample.size_px,
            weight=sample.weight,
            substitution_refused=sample.substitution_refused,
        )
        for key, sample in section.typography.items()
    }
    return SectionTypography(samples=samples)


def _media(section: RenderedSection) -> SectionMedia:
    """Key media by position so both sides address the same slot.

    The expected side numbers image elements in document order; the render is
    numbered the same way, so `media_2` means the second image in both.
    """

    media: dict[str, MediaSample] = {}
    for index, sample in enumerate(section.media, start=1):
        media[f"media_{index}"] = MediaSample(
            aspect_ratio=sample.rendered_width / sample.rendered_height,
            focal_x=sample.focal_x,
            focal_y=sample.focal_y,
            crop_coverage=_crop_coverage(sample),
        )
    return SectionMedia(media=media)


def _crop_coverage(sample: RenderedMedia) -> float | None:
    """Fraction of the source image still visible after cover-cropping.

    Unavailable without the image's intrinsic size — the rendered box alone
    cannot say how much of the source was cut away.
    """

    if not sample.natural_width or not sample.natural_height:
        return None
    natural = sample.natural_width / sample.natural_height
    rendered = sample.rendered_width / sample.rendered_height
    if natural <= 0 or rendered <= 0:
        return None
    coverage = min(natural / rendered, rendered / natural)
    return min(1.0, coverage)
