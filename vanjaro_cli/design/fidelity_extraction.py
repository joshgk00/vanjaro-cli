"""Derive fidelity observations from a Design Document (VF-009, expected side).

`score_section_fidelity` compares two `SectionObservation` bundles of the same
shape. This module produces the *expected* one — what the design says the page
should be — from the source-neutral Design Document, so a Figma frame and a
crawled page yield the same structure.

Two disciplines run through every extractor here:

* **Absence is not zero.** A signal the document does not carry is emitted as
  `None`, which the metrics report as unavailable and exclude from the weighted
  mean. Defaulting would invent agreement that was never measured.
* **Inference is not measurement.** `SectionGeometry` has no field for the
  observation method, so an inferred bounding box cannot be labelled as such
  downstream. Rather than let a guess score as a measurement against 0.60 of the
  layout dimension, inferred geometry is dropped to `None` — see
  `MEASURED_METHODS`.

This module is pure: no network, filesystem, or model calls.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from vanjaro_cli.design.css_color import normalize_css_color
from vanjaro_cli.design.fidelity_color import ColorRole, SectionPalette
from vanjaro_cli.design.fidelity_evaluation import PageObservation, SectionObservation
from vanjaro_cli.design.fidelity_layout import BoundingBox as LayoutBox
from vanjaro_cli.design.fidelity_layout import SectionGeometry
from vanjaro_cli.design.fidelity_media import MediaSample, SectionMedia
from vanjaro_cli.design.fidelity_type import (
    SectionSpacing,
    SectionTypography,
    SpacingSample,
    TypeSample,
)
from vanjaro_cli.design.models import (
    AssetRecord,
    BreakpointName,
    ContentElement,
    ContentKind,
    DesignDocument,
    EvidenceStatus,
    ObservationMethod,
    Page,
    Section,
    StyleProperty,
    StyleSet,
)
from vanjaro_cli.design.visual_gate import CANONICAL_VIEWPORTS

__all__ = [
    "MEASURED_METHODS",
    "TYPOGRAPHY_SAMPLE_KEYS",
    "observe_expected_page",
    "observe_expected_section",
]


# Methods that actually measure geometry. STATIC parsing never produces bounds;
# INFERRED, LEGACY, and MANUAL produce values that were not measured from a
# rendered surface and must not be scored as if they were.
MEASURED_METHODS = frozenset({ObservationMethod.RENDERED, ObservationMethod.API})

# Stable sample keys, so both sides of a comparison agree without round-tripping
# element identity through the build.
TYPOGRAPHY_SAMPLE_KEYS = ("heading", "body")

_ACTION_KINDS = frozenset({ContentKind.BUTTON, ContentKind.LINK})
_HEADING_KINDS = frozenset({ContentKind.HEADING})
_BODY_KINDS = frozenset({ContentKind.TEXT})
_PIXEL_VALUE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(?:px)?\s*$")


def observe_expected_page(
    page: Page,
    document: DesignDocument,
    breakpoint: BreakpointName,
) -> PageObservation | None:
    """Build the expected observation for one page at one breakpoint.

    Returns ``None`` for a page with no sections: `PageObservation` requires at
    least one, and an empty bundle would score nothing anyway.
    """

    if not page.sections:
        return None
    assets = {asset.id: asset for asset in document.assets}
    viewport = CANONICAL_VIEWPORTS[breakpoint]
    return PageObservation(
        viewport_width=float(viewport.width),
        sections=tuple(
            observe_expected_section(section, assets, breakpoint)
            for section in sorted(page.sections, key=lambda item: (item.order, item.id))
        ),
    )


def observe_expected_section(
    section: Section,
    assets: Mapping[str, AssetRecord],
    breakpoint: BreakpointName,
) -> SectionObservation:
    """Build the expected observation for one section at one breakpoint."""

    return SectionObservation(
        geometry=_geometry(section, breakpoint),
        palette=_palette(section),
        typography=_typography(section),
        spacing=_spacing(section, breakpoint),
        media=_media(section, assets),
        # Integrity has no design-side counterpart; only a build can be defective.
        integrity=None,
    )


def _geometry(section: Section, breakpoint: BreakpointName) -> SectionGeometry:
    return SectionGeometry(
        section_id=section.id,
        order=section.order,
        bounds=_bounds(section, breakpoint),
        columns=_columns(section, breakpoint),
    )


def _bounds(section: Section, breakpoint: BreakpointName) -> LayoutBox | None:
    """Return measured geometry for this breakpoint, or None.

    Geometry lives on provenance rather than on the section itself. Only a
    record measured at the requested viewport counts: reusing a desktop box for
    mobile would fabricate a layout the design never stated.
    """

    for record in section.provenance:
        if record.bounds is None or record.method not in MEASURED_METHODS:
            continue
        if record.viewport == breakpoint:
            return _to_layout_box(record.bounds)

    # A rendered crawl measures every breakpoint and records the non-desktop
    # boxes on the responsive observation rather than on the section, because
    # the section's own provenance describes its base layout. Reading only the
    # section left tablet and mobile with no geometry, so layout scored on
    # columns and order alone — 100 on two subscores while desktop compared
    # real boxes. That made the least-measured breakpoints look like the best
    # ones, and mobile carries its own floor on the ship gate.
    for observation in section.responsive:
        if observation.breakpoint != breakpoint:
            continue
        for record in observation.provenance:
            if record.bounds is not None and record.method in MEASURED_METHODS:
                return _to_layout_box(record.bounds)

    # A record with no viewport describes the base layout, which is desktop.
    if breakpoint is BreakpointName.DESKTOP:
        for record in section.provenance:
            if (
                record.bounds is not None
                and record.method in MEASURED_METHODS
                and record.viewport is None
            ):
                return _to_layout_box(record.bounds)
    return None


def _to_layout_box(bounds: object) -> LayoutBox:
    return LayoutBox(
        x=bounds.x,  # type: ignore[attr-defined]
        y=bounds.y,  # type: ignore[attr-defined]
        width=bounds.width,  # type: ignore[attr-defined]
        height=bounds.height,  # type: ignore[attr-defined]
    )


def _columns(section: Section, breakpoint: BreakpointName) -> int | None:
    columns = section.layout.columns
    for observation in section.responsive:
        if observation.breakpoint != breakpoint:
            continue
        candidate = observation.layout_changes.get("columns")
        if isinstance(candidate, int) and candidate >= 1:
            columns = candidate
    return columns


def _palette(section: Section) -> SectionPalette:
    """Build the expected palette, normalizing whatever dialect the source used.

    A rendered Design Document carries the browser's `rgb()` values, so the
    design side needs the same normalization the observed side has always had.
    A colour that cannot be normalized is left out rather than guessed, which
    costs one role and never fabricates one.
    """

    colors: dict[ColorRole, str] = {}
    background = normalize_css_color(_style_value(section.style, StyleProperty.BACKGROUND_COLOR))
    if background is not None:
        colors[ColorRole.BACKGROUND] = background
    text = normalize_css_color(_style_value(section.style, StyleProperty.TEXT_COLOR))
    if text is not None:
        colors[ColorRole.TEXT] = text
    accent = normalize_css_color(_accent(section))
    if accent is not None:
        colors[ColorRole.ACCENT] = accent
    return SectionPalette(colors=colors)


def _accent(section: Section) -> str | None:
    """Take the accent from the first action element that declares a colour."""

    for element in _ordered(section.content):
        if element.kind not in _ACTION_KINDS:
            continue
        for prop in (StyleProperty.BACKGROUND_COLOR, StyleProperty.TEXT_COLOR):
            value = _style_value(element.style, prop)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _typography(section: Section) -> SectionTypography:
    samples: dict[str, TypeSample] = {}
    for key, kinds in (("heading", _HEADING_KINDS), ("body", _BODY_KINDS)):
        element = next(
            (item for item in _ordered(section.content) if item.kind in kinds), None
        )
        if element is None:
            continue
        sample = _type_sample(element.style)
        if sample is not None:
            samples[key] = sample
    return SectionTypography(samples=samples)


def _type_sample(style: StyleSet) -> TypeSample | None:
    family = _style_value(style, StyleProperty.FONT_FAMILY)
    size = _positive_pixels(_style_value(style, StyleProperty.FONT_SIZE))
    weight = _weight(_style_value(style, StyleProperty.FONT_WEIGHT))
    if family is None and size is None and weight is None:
        return None
    return TypeSample(
        family=family.strip() if isinstance(family, str) and family.strip() else None,
        size_px=size,
        weight=weight,
    )


def _effective_style(section: Section, breakpoint: BreakpointName) -> StyleSet:
    """Section styles with a breakpoint's measured changes applied.

    A rendered crawl records responsive styles as *changes from desktop*, so a
    property absent from the delta was measured and found equal — not left
    unknown. Replacing the whole set with the delta discarded every unchanged
    property, which is why spacing scored at desktop only while tablet and
    mobile were measured and thrown away.

    Only rendered observations are merged, because only that adapter computes
    the delta. Absence carries no such meaning from a source without the
    contract, and importing desktop values there would be the cross-viewport
    borrow VF-009 refuses.
    """

    merged = {
        observation.property: observation for observation in section.style.observations
    }
    for observation in section.responsive:
        if observation.breakpoint != breakpoint:
            continue
        if not any(
            record.method is ObservationMethod.RENDERED
            for record in observation.provenance
        ):
            continue
        for entry in observation.style.observations:
            merged[entry.property] = entry
    return StyleSet(observations=list(merged.values()))


def _spacing(section: Section, breakpoint: BreakpointName) -> SectionSpacing:
    style = _effective_style(section, breakpoint)
    top, bottom = _padding(_style_value(style, StyleProperty.PADDING))
    gap = _pixels(_style_value(style, StyleProperty.ROW_GAP))
    return SectionSpacing(
        spacing=SpacingSample(padding_top=top, padding_bottom=bottom, element_gap=gap)
    )


def _padding(value: object) -> tuple[float | None, float | None]:
    """Read vertical padding from a scalar or a CSS shorthand.

    Anything this cannot read confidently returns unavailable rather than a
    guess — a wrong padding scores as a real mismatch.
    """

    single = _pixels(value)
    if single is not None:
        return single, single
    if not isinstance(value, str):
        return None, None
    parts = [_pixels(part) for part in value.split()]
    if not parts or any(part is None for part in parts):
        return None, None
    if len(parts) in {1, 2}:
        return parts[0], parts[0]
    if len(parts) in {3, 4}:
        return parts[0], parts[2]
    return None, None


def _media(section: Section, assets: Mapping[str, AssetRecord]) -> SectionMedia:
    """Derive per-slot media from asset intrinsics.

    Only the aspect ratio is knowable from a design: focal point and crop
    coverage describe how a build placed the image, so both stay unavailable
    until the render supplies them on both sides.
    """

    media: dict[str, MediaSample] = {}
    index = 0
    for element in _ordered(section.content):
        if element.kind != ContentKind.IMAGE or element.asset_id is None:
            continue
        asset = assets.get(element.asset_id)
        if asset is None:
            continue
        index += 1
        if not asset.width or not asset.height:
            continue
        media[f"media_{index}"] = MediaSample(
            aspect_ratio=asset.width / asset.height
        )
    return SectionMedia(media=media)


def _ordered(content: Iterable[ContentElement]) -> list[ContentElement]:
    return sorted(content, key=lambda element: (element.order, element.id))


def _style_value(style: StyleSet, prop: StyleProperty) -> object | None:
    """Return an observed style value, ignoring inferred ones.

    An inferred colour or font is a reconstruction, and the metrics have no way
    to weight it differently once it is in the bundle.
    """

    for observation in style.observations:
        if observation.property is prop and observation.status is EvidenceStatus.OBSERVED:
            return observation.value
    return None


def _pixels(value: object) -> float | None:
    """Read a non-negative pixel length. Zero is a measurement, not absence."""

    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else None
    if isinstance(value, str):
        match = _PIXEL_VALUE.match(value)
        if match:
            number = float(match.group(1))
            return number if number >= 0 else None
    return None


def _positive_pixels(value: object) -> float | None:
    """Read a length that must be positive to be meaningful, such as font size."""

    pixels = _pixels(value)
    return pixels if pixels is not None and pixels > 0 else None


def _weight(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = int(value)
    elif isinstance(value, str):
        match = _PIXEL_VALUE.match(value)
        if not match:
            return None
        number = int(float(match.group(1)))
    else:
        return None
    return number if 1 <= number <= 1000 else None
