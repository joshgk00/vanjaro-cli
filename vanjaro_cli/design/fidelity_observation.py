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

from vanjaro_cli.design.fidelity_color import ColorRole, OverlaySample, SectionPalette
from vanjaro_cli.design.fidelity_copy import SectionCopy
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
from vanjaro_cli.design.surface_rules import SurfaceCandidate, select_surfaces

__all__ = [
    "PageMeasurer",
    "RenderedMedia",
    "RenderedOverlayLayer",
    "RenderedPage",
    "RenderedSection",
    "RenderedSurface",
    "RenderedText",
    "RenderedTextRun",
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
    # Whether the browser decoded pixels into this box. Distinct from a missing
    # natural size, which only says the measurement did not report one.
    loaded: bool | None = None


class RenderedTextRun(_RenderedModel):
    """One stretch of text the page rendered, and whether a visitor can read it.

    `legible` is False for text that is in the page but camouflaged: painted in
    the same colour as the opaque background directly behind it, or fully
    transparent. White text on a white card is rendered and still unseen.
    """

    text: str = Field(min_length=1)
    legible: bool = True


class RenderedSurface(_RenderedModel):
    """One element that paints an opaque background, placed within its section."""

    color: str
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    has_text: bool = False


class RenderedOverlayLayer(_RenderedModel):
    """A translucent painted layer, and the share of the section it spans."""

    color: str
    opacity: float = Field(gt=0, lt=1)
    coverage: float = Field(ge=0)


# A layer must span most of the section to read as a darkening of its photo
# rather than a tint on one corner of it.
_OVERLAY_MIN_COVERAGE = 0.8


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
    # The CSS background photo that paints the section's main band, if any.
    background_media: RenderedMedia | None = None
    # ``None`` means the measurement did not report it (evidence recorded before
    # these existed); an empty tuple means it looked and found none.
    text_runs: tuple[RenderedTextRun, ...] | None = None
    surfaces: tuple[RenderedSurface, ...] | None = None
    overlay_layers: tuple[RenderedOverlayLayer, ...] | None = None
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
        wording=_wording(section),
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
    return SectionPalette(
        colors=colors, surfaces=_surfaces(section), overlay=_overlay(section)
    )


def _surfaces(section: RenderedSection) -> tuple[str, ...] | None:
    """Pick the cards and panels from the painted elements, by the design side's rules."""

    if section.surfaces is None or section.bounds is None:
        return None
    selected = select_surfaces(
        (
            SurfaceCandidate(
                color=surface.color,
                x=surface.x,
                y=surface.y,
                width=surface.width,
                height=surface.height,
                has_text=surface.has_text,
            )
            for surface in section.surfaces
        ),
        section.bounds.width,
        section.bounds.height,
    )
    return tuple(candidate.color for candidate in selected)


def _overlay(section: RenderedSection) -> OverlaySample | None:
    """Report the layer that darkens the section, or that the build has none."""

    if section.overlay_layers is None:
        return None
    covering = [
        layer for layer in section.overlay_layers if layer.coverage >= _OVERLAY_MIN_COVERAGE
    ]
    if not covering:
        return OverlaySample(present=False)
    strongest = max(covering, key=lambda layer: (layer.coverage, layer.opacity))
    return OverlaySample(present=True, color=strongest.color, opacity=strongest.opacity)


def _wording(section: RenderedSection) -> SectionCopy:
    """Join the text a visitor can read; text camouflaged on its background is left out."""

    if section.text_runs is None:
        return SectionCopy()
    return SectionCopy(
        rendered=" ".join(run.text for run in section.text_runs if run.legible)
    )


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
    numbered the same way, so `media_2` means the second image in both. A CSS
    background photo is not an `<img>`, so it is keyed `background_1`, which is
    what the design side calls a section's background photo.
    """

    media: dict[str, MediaSample] = {}
    for index, sample in enumerate(section.media, start=1):
        media[f"media_{index}"] = _media_sample(sample)
    if section.background_media is not None:
        media["background_1"] = _media_sample(section.background_media)
    return SectionMedia(media=media)


def _media_sample(sample: RenderedMedia) -> MediaSample:
    return MediaSample(
        aspect_ratio=sample.rendered_width / sample.rendered_height,
        focal_x=sample.focal_x,
        focal_y=sample.focal_y,
        crop_coverage=_crop_coverage(sample),
        loaded=sample.loaded,
    )


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
