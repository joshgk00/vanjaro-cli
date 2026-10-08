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
    Provenance,
    Section,
    SourceKind,
    StyleProperty,
    StyleSet,
    Viewport,
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

# A Figma page frame with no designed sections is cut into bands from the boxes
# of the nodes it holds. Those section records say `inferred` because the
# *grouping* is a guess, yet every coordinate on them is the union of boxes the
# Figma API measured -- unlike an inferred layout, which has no measured box
# behind it. Only these boundary kinds carry measured geometry.
_MEASURED_BOUNDARY_INFERENCES = frozenset(
    {"flat_geometry", "whitespace_geometry", "background_band"}
)

# Stable sample keys, so both sides of a comparison agree without round-tripping
# element identity through the build.
TYPOGRAPHY_SAMPLE_KEYS = ("heading", "body")

_ACTION_KINDS = frozenset({ContentKind.BUTTON, ContentKind.LINK})
_HEADING_KINDS = frozenset({ContentKind.HEADING})
_BODY_KINDS = frozenset({ContentKind.TEXT})
# A stat's big numeral is the display text of its band and the build renders it
# as a heading, so the build's most prominent heading is what it is compared
# against. A repeated line such as a marquee item is a Figma list item, and the
# build's first leaf text is that line.
_FIGMA_HEADING_KINDS = _HEADING_KINDS | {ContentKind.STAT}
_FIGMA_BODY_KINDS = _BODY_KINDS | {ContentKind.LIST_ITEM}
_BACKGROUND_MEDIA_ROLE = "background_media"
_PIXEL_VALUE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(?:px)?\s*$")


def observe_expected_page(
    page: Page,
    document: DesignDocument,
    breakpoint: BreakpointName,
    viewport: Viewport | None = None,
) -> PageObservation | None:
    """Build the expected observation for one page at one breakpoint.

    Returns ``None`` for a page with no sections: `PageObservation` requires at
    least one, and an empty bundle would score nothing anyway.

    `viewport` overrides the canonical breakpoint viewport with an explicit
    one -- e.g. a validated source reference's own declared width -- without
    resizing or inventing any other geometry. Every existing caller omits it
    and keeps the canonical lookup unchanged.
    """

    if not page.sections:
        return None
    assets = {asset.id: asset for asset in document.assets}
    resolved_viewport = viewport if viewport is not None else CANONICAL_VIEWPORTS[breakpoint]
    frames = _page_frames(page)
    return PageObservation(
        viewport_width=float(resolved_viewport.width),
        sections=tuple(
            observe_expected_section(section, assets, breakpoint, frames)
            for section in sorted(page.sections, key=lambda item: (item.order, item.id))
        ),
        # A Figma frame is one static drawing of the page. A build cannot
        # reproduce its vertical rhythm exactly, so each section is judged on
        # its own size rather than on where upstream sections left it.
        vertical_offset_tolerated=breakpoint in frames,
    )


def observe_expected_section(
    section: Section,
    assets: Mapping[str, AssetRecord],
    breakpoint: BreakpointName,
    frames: Mapping[BreakpointName, LayoutBox] | None = None,
) -> SectionObservation:
    """Build the expected observation for one section at one breakpoint.

    `frames` holds each Figma page frame's own box by breakpoint. A Figma node
    reports its box in canvas coordinates, so a section is only comparable to a
    rendered page once it is placed relative to the frame that holds it.
    """

    return SectionObservation(
        geometry=_geometry(section, breakpoint, frames or {}),
        palette=_palette(section),
        typography=_typography(section),
        spacing=_spacing(section, breakpoint),
        media=_media(section, assets, breakpoint),
        # Integrity has no design-side counterpart; only a build can be defective.
        integrity=None,
    )


def _geometry(
    section: Section,
    breakpoint: BreakpointName,
    frames: Mapping[BreakpointName, LayoutBox],
) -> SectionGeometry:
    return SectionGeometry(
        section_id=section.id,
        order=section.order,
        bounds=_bounds(section, breakpoint, frames),
        columns=_columns(section, breakpoint),
    )


def _page_frames(page: Page) -> dict[BreakpointName, LayoutBox]:
    """Collect the Figma page frames' own boxes, keyed by the breakpoint they draw."""

    frames: dict[BreakpointName, LayoutBox] = {}
    for record in page.provenance:
        if (
            record.source_kind is SourceKind.FIGMA
            and record.method in MEASURED_METHODS
            and record.bounds is not None
            and record.viewport is not None
            and record.element_node_id == record.frame_node_id
        ):
            frames.setdefault(record.viewport, _to_layout_box(record.bounds))
    return frames


def _measures_geometry(record: Provenance) -> bool:
    if record.bounds is None:
        return False
    if record.method in MEASURED_METHODS:
        return True
    return (
        record.source_kind is SourceKind.FIGMA
        and record.method is ObservationMethod.INFERRED
        and record.metadata.get("inference") in _MEASURED_BOUNDARY_INFERENCES
    )


def _placed_box(
    record: Provenance,
    breakpoint: BreakpointName,
    frames: Mapping[BreakpointName, LayoutBox],
) -> LayoutBox | None:
    """Turn a record's box into page coordinates, or None when it cannot be placed.

    A Figma box is relative to the canvas, not the page, so it is shifted to the
    frame's origin and clipped to the frame -- the frame is all a visitor sees,
    and a rendered page cannot be wider than its viewport. With no frame to
    anchor it the box stays unavailable: canvas coordinates compared against
    page coordinates would read as a gross mismatch that was never measured.
    """

    assert record.bounds is not None
    box = _to_layout_box(record.bounds)
    if record.source_kind is not SourceKind.FIGMA:
        return box
    frame = frames.get(record.viewport or breakpoint)
    if frame is None:
        return None
    left = max(box.x - frame.x, 0.0)
    top = max(box.y - frame.y, 0.0)
    right = min(box.x - frame.x + box.width, frame.width)
    bottom = min(box.y - frame.y + box.height, frame.height)
    if right <= left or bottom <= top:
        return None
    return LayoutBox(x=left, y=top, width=right - left, height=bottom - top)


def _bounds(
    section: Section,
    breakpoint: BreakpointName,
    frames: Mapping[BreakpointName, LayoutBox],
) -> LayoutBox | None:
    """Return measured geometry for this breakpoint, or None.

    Geometry lives on provenance rather than on the section itself. Only a
    record measured at the requested viewport counts: reusing a desktop box for
    mobile would fabricate a layout the design never stated.
    """

    for record in section.provenance:
        if not _measures_geometry(record):
            continue
        if record.viewport == breakpoint:
            return _placed_box(record, breakpoint, frames)

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
                return _placed_box(record, breakpoint, frames)

    # A record with no viewport describes the base layout, which is desktop.
    if breakpoint is BreakpointName.DESKTOP:
        for record in section.provenance:
            if _measures_geometry(record) and record.viewport is None:
                return _placed_box(record, breakpoint, frames)
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
    background = normalize_css_color(
        _style_value(section.style, StyleProperty.BACKGROUND_COLOR)
    ) or _band_background(section)
    if background is not None:
        colors[ColorRole.BACKGROUND] = background
    text = normalize_css_color(_style_value(section.style, StyleProperty.TEXT_COLOR))
    if text is not None:
        colors[ColorRole.TEXT] = text
    accent = normalize_css_color(_accent(section))
    if accent is not None:
        colors[ColorRole.ACCENT] = accent
    return SectionPalette(colors=colors)


def _band_background(section: Section) -> str | None:
    """Read the section's background from the solid band Figma measured behind it.

    A flat Figma frame draws a section's colour as a separate full-width
    rectangle, so the section itself carries no `background_color` style. The
    adapter records that rectangle's fill as the `base` band; leaving it unread
    left every Figma section's background unmeasured, and a build that painted
    the wrong colour scored the same as one that painted the right one.
    """

    bands = section.metadata.get("background_bands")
    for band in bands if isinstance(bands, list) else []:
        if isinstance(band, dict) and band.get("role") == "base":
            return normalize_css_color(band.get("color"))
    return None


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
    ordered = _ordered(section.content)
    samples: dict[str, TypeSample] = {}
    for key, kinds, figma_kinds in (
        ("heading", _HEADING_KINDS, _FIGMA_HEADING_KINDS),
        ("body", _BODY_KINDS, _FIGMA_BODY_KINDS),
    ):
        element = next((item for item in ordered if item.kind in kinds), None)
        sample = _type_sample(element.style) if element is not None else None
        if sample is None:
            sample = _figma_type_sample(ordered, figma_kinds)
        if sample is not None:
            samples[key] = sample
    return SectionTypography(samples=samples)


def _figma_type_sample(
    ordered: Iterable[ContentElement], kinds: frozenset[ContentKind]
) -> TypeSample | None:
    """Sample the first Figma text node of these kinds from its API-measured type.

    The Figma adapter keeps a text node's `fontSize` and `fontWeight` in the
    element's attributes, not in its style set, so the style-based reader above
    found nothing and typography was unmeasured on every Figma section. A heading
    drawn at 80px and built at 40px scored as if the sizes agreed.

    The family is left out on purpose. Figma fonts are usually unregistered
    (`FIGMA_FONT_SOURCE_UNRESOLVED`), so the build shows a stand-in, and scoring
    that mismatch on every section would charge a known, separately warned gap
    to each of them.
    """

    element = next((item for item in ordered if item.kind in kinds), None)
    if element is None or not _is_figma_measured(element):
        return None
    size = _positive_pixels(element.attributes.get("font_size"))
    weight = _weight(element.attributes.get("font_weight"))
    if size is None and weight is None:
        return None
    return TypeSample(size_px=size, weight=weight)


def _is_figma_measured(element: ContentElement) -> bool:
    return any(
        record.source_kind is SourceKind.FIGMA and record.method in MEASURED_METHODS
        for record in element.provenance
    )


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


def _media(
    section: Section,
    assets: Mapping[str, AssetRecord],
    breakpoint: BreakpointName,
) -> SectionMedia:
    """Derive per-slot media aspect, keyed the way the render keys its slots.

    Only the aspect ratio is knowable from a design: focal point and crop
    coverage describe how a build placed the image, so both stay unavailable
    until the render supplies them on both sides.

    A background photo is its own slot. The build paints it as a CSS background
    on the section, which is not an `<img>`, so numbering it among the images
    would shift every later `media_N` out of step with the render.
    """

    media: dict[str, MediaSample] = {}
    image_index = 0
    background_index = 0
    for element in _ordered(section.content):
        if element.kind != ContentKind.IMAGE or element.asset_id is None:
            continue
        asset = assets.get(element.asset_id)
        if asset is None:
            continue
        if element.role == _BACKGROUND_MEDIA_ROLE:
            background_index += 1
            key = f"background_{background_index}"
        else:
            image_index += 1
            key = f"media_{image_index}"
        aspect_ratio = _image_aspect_ratio(element, asset, breakpoint)
        if aspect_ratio is None:
            continue
        media[key] = MediaSample(aspect_ratio=aspect_ratio)
    return SectionMedia(media=media)


def _image_aspect_ratio(
    element: ContentElement, asset: AssetRecord, breakpoint: BreakpointName
) -> float | None:
    """Prefer the shape this element was drawn at over the asset's recorded size.

    A Figma asset record keeps the size of the first node that used the image,
    so a picture reused elsewhere (a video poster over a banner's background)
    was judged against the other node's frame. The element's own measured box
    is the shape the design gave this slot.
    """

    for record in element.provenance:
        if (
            record.source_kind is SourceKind.FIGMA
            and record.method in MEASURED_METHODS
            and record.bounds is not None
            and record.bounds.width > 0
            and record.bounds.height > 0
            and (record.viewport or BreakpointName.DESKTOP) == breakpoint
        ):
            return record.bounds.width / record.bounds.height
    if asset.width and asset.height:
        return asset.width / asset.height
    return None


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
