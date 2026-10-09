"""Band and image-shape evidence read from Figma paint, radius, and mask fields.

A Figma page frame is often flat: a section's colour is a separate full-width
rectangle sitting behind its text, and an avatar is an ellipse with an image
fill. Neither shows up as text or as an image of its own, so the adapter used
to drop both. This module reads them straight from the node fields.

The same paint fields also say what colour a text node is filled with, which
cards and panels are painted, and whether a darkening layer sits over a
background photo. Each is recorded only when one opaque or one translucent solid
paint states it outright; a gradient, a stack of paints, or mixed character
fills carry no single value, so they are left out instead of guessed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from vanjaro_cli.design.figma_tree import (
    box as _box,
    children as _children,
    visible as _visible,
)
from vanjaro_cli.design.models import BoundingBox, StyleProperty
from vanjaro_cli.design.surface_rules import SurfaceCandidate, select_surfaces
from vanjaro_cli.utils.figma_tokens import figma_color_to_hex

__all__ = [
    "background_bands",
    "background_overlay",
    "image_shape_style",
    "parent_index",
    "surface_fills",
    "text_fill_color",
]

_BAND_MIN_WIDTH_RATIO = 0.8
_BAND_MIN_HEIGHT = 8.0
_BASE_BAND_MIN_AREA_RATIO = 0.4
_BAR_MAX_HEIGHT = 120.0
_BAR_MAX_HEIGHT_RATIO = 0.25
_BAR_ADJACENCY_TOLERANCE = 4.0
_SQUARE_TOLERANCE = 0.02
_MASK_OVERLAP_RATIO = 0.9
_PAINTED_TYPES = frozenset({"RECTANGLE", "FRAME", "GROUP", "VECTOR", "INSTANCE", "COMPONENT"})
_PHOTO_MIN_SECTION_COVERAGE = 0.6
_OVERLAY_MIN_PHOTO_COVERAGE = 0.8
_OVERLAY_MAX_PHOTO_AREA_RATIO = 1.5
_OVERLAY_MIN_OPACITY = 0.01
_FILL_FIT = {"FILL": "cover", "FIT": "contain"}


def parent_index(root: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Map every descendant id to its parent node."""

    parents: dict[str, Mapping[str, Any]] = {}
    stack: list[Mapping[str, Any]] = [root]
    while stack:
        current = stack.pop()
        for child in _children(current):
            if child.get("id") is not None:
                parents[str(child["id"])] = current
            stack.append(child)
    return parents


def _solid_color(node: Mapping[str, Any]) -> str | None:
    """Return the hex colour when the node's whole visible paint is one opaque solid."""

    if node.get("type") not in _PAINTED_TYPES:
        return None
    return _opaque_solid_hex(node)


def _opaque_solid_hex(node: Mapping[str, Any]) -> str | None:
    if not _visible(node) or float(node.get("opacity", 1) or 0) < 1:
        return None
    paints = [
        fill for fill in (node.get("fills") or [])
        if isinstance(fill, Mapping) and fill.get("visible") is not False
    ]
    if len(paints) != 1:
        return None
    paint = paints[0]
    color = paint.get("color")
    if (
        paint.get("type") != "SOLID"
        or not isinstance(color, Mapping)
        or float(paint.get("opacity", 1) or 0) < 1
        or float(color.get("a", 1) or 0) < 1
    ):
        return None
    return figma_color_to_hex(dict(color))


def _band_record(node: Mapping[str, Any], color: str, bounds: BoundingBox) -> dict[str, Any]:
    return {
        "color": color,
        "node_id": str(node.get("id")),
        "bounds": {
            "x": bounds.x, "y": bounds.y, "width": bounds.width, "height": bounds.height,
        },
    }


def background_bands(
    section_node: Mapping[str, Any], section_box: BoundingBox | None,
) -> list[dict[str, Any]]:
    """Find the full-width painted bands that make up a section's background.

    Returns the ``base`` band (the dominant background) and, when a thin strip
    of another colour sits flush under it, the ``bottom_bar`` (a copyright or
    legal strip). A section with no solid full-width rectangle returns nothing.
    """

    if section_box is None or section_box.width <= 0 or section_box.height <= 0:
        return []
    candidates: list[tuple[Mapping[str, Any], str, BoundingBox]] = []
    for node in (section_node, *_children(section_node)):
        color = _solid_color(node)
        bounds = _box(node)
        if color is None or bounds is None:
            continue
        if bounds.width < section_box.width * _BAND_MIN_WIDTH_RATIO or bounds.height < _BAND_MIN_HEIGHT:
            continue
        candidates.append((node, color, bounds))
    if not candidates:
        return []

    base_node, base_color, base_bounds = max(
        candidates, key=lambda item: item[2].width * item[2].height
    )
    section_area = section_box.width * section_box.height
    if base_bounds.width * base_bounds.height < section_area * _BASE_BAND_MIN_AREA_RATIO:
        return []
    bands = [{"role": "base", **_band_record(base_node, base_color, base_bounds)}]

    base_bottom = base_bounds.y + base_bounds.height
    bar_limit = min(_BAR_MAX_HEIGHT, section_box.height * _BAR_MAX_HEIGHT_RATIO)
    bars = [
        (node, color, bounds) for node, color, bounds in candidates
        if node is not base_node
        and color != base_color
        and bounds.height <= bar_limit
        and bounds.y >= base_bottom - _BAR_ADJACENCY_TOLERANCE
    ]
    if bars:
        bar_node, bar_color, bar_bounds = min(bars, key=lambda item: item[2].y)
        bands.append({"role": "bottom_bar", **_band_record(bar_node, bar_color, bar_bounds)})
    return bands


def _has_character_fill_overrides(node: Mapping[str, Any]) -> bool:
    """True when some characters of a text node are filled differently from the rest."""

    overrides = node.get("characterStyleOverrides") or []
    table = node.get("styleOverrideTable") or {}
    if not isinstance(overrides, Sequence) or not isinstance(table, Mapping):
        return False
    for key in {str(index) for index in overrides if index}:
        style = table.get(key)
        if isinstance(style, Mapping) and style.get("fills"):
            return True
    return False


def text_fill_color(node: Mapping[str, Any]) -> str | None:
    """Return a text node's fill colour when one opaque solid paint colours every character."""

    if node.get("type") != "TEXT" or _has_character_fill_overrides(node):
        return None
    return _opaque_solid_hex(node)


def _visible_nodes(root: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Walk a subtree in paint order, skipping every hidden node and what it holds."""

    ordered: list[Mapping[str, Any]] = []
    stack: list[Mapping[str, Any]] = [root]
    while stack:
        current = stack.pop()
        if not _visible(current):
            continue
        ordered.append(current)
        stack.extend(reversed(_children(current)))
    return ordered


def _contains_point(bounds: BoundingBox, x: float, y: float) -> bool:
    return (
        bounds.x <= x <= bounds.x + bounds.width
        and bounds.y <= y <= bounds.y + bounds.height
    )


def surface_fills(
    section_node: Mapping[str, Any], section_box: BoundingBox | None,
    loose_nodes: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """List the solid-filled cards and panels that hold a section's text.

    A card is drawn either as a frame with a fill or, in a flat page frame, as a
    rectangle sitting behind its text, so the test is geometric: an opaque solid
    box, narrower than a band, that has text inside it. The rules that decide what
    counts are shared with the build side (`surface_rules`) so both compare the
    same kind of box.

    `loose_nodes` are page-frame nodes that sit inside this section's band but
    were not grouped into it. A card rectangle holds no text or photo of its own,
    so the section cut leaves it out; it still paints the card.
    """

    if section_box is None or section_box.width <= 0 or section_box.height <= 0:
        return []
    nodes = _visible_nodes(section_node)
    known = {id(node) for node in nodes}
    for loose in loose_nodes:
        nodes.extend(node for node in _visible_nodes(loose) if id(node) not in known)
    text_centres: list[tuple[float, float]] = []
    for node in nodes:
        bounds = _box(node)
        if (
            node.get("type") == "TEXT"
            and str(node.get("characters", "")).strip()
            and bounds is not None
        ):
            text_centres.append(
                (bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
            )

    candidates: list[SurfaceCandidate] = []
    for node in nodes:
        if node is section_node or node.get("isMask"):
            continue
        color = _solid_color(node)
        bounds = _box(node)
        if color is None or bounds is None:
            continue
        candidates.append(
            SurfaceCandidate(
                color=color,
                x=bounds.x - section_box.x,
                y=bounds.y - section_box.y,
                width=bounds.width,
                height=bounds.height,
                has_text=any(_contains_point(bounds, x, y) for x, y in text_centres),
                reference=str(node.get("id")),
            )
        )
    return [
        {
            "color": candidate.color,
            "node_id": candidate.reference,
            "bounds": {
                "x": candidate.x + section_box.x,
                "y": candidate.y + section_box.y,
                "width": candidate.width,
                "height": candidate.height,
            },
        }
        for candidate in select_surfaces(candidates, section_box.width, section_box.height)
    ]


def _translucent_solid(
    paint: Mapping[str, Any], node_opacity: float
) -> tuple[str, float] | None:
    """Return a solid paint's colour and the share of light it lets through."""

    color = paint.get("color")
    if paint.get("type") != "SOLID" or paint.get("visible") is False or not isinstance(color, Mapping):
        return None
    opacity = (
        float(paint.get("opacity", 1) or 0)
        * float(color.get("a", 1) or 0)
        * node_opacity
    )
    if not _OVERLAY_MIN_OPACITY <= opacity < 1:
        return None
    return figma_color_to_hex(dict(color)), round(opacity, 4)


def _coverage(inner: BoundingBox, outer: BoundingBox) -> float:
    """Share of `outer`'s area that `inner` covers."""

    width = max(0.0, min(inner.x + inner.width, outer.x + outer.width) - max(inner.x, outer.x))
    height = max(0.0, min(inner.y + inner.height, outer.y + outer.height) - max(inner.y, outer.y))
    return width * height / max(1.0, outer.width * outer.height)


def background_overlay(
    section_node: Mapping[str, Any], section_box: BoundingBox | None,
) -> dict[str, Any] | None:
    """Find the translucent solid layer drawn over a section's background photo.

    A designer darkens a photo behind text with a black rectangle at 40% opacity,
    or with a second paint stacked above the image paint on the same node. Both
    are API values: a colour and how much light it lets through. A gradient
    scrim has no single colour, so it is not reported.
    """

    if section_box is None or section_box.width <= 0 or section_box.height <= 0:
        return None
    nodes = _visible_nodes(section_node)
    section_area = section_box.width * section_box.height

    photo_index: int | None = None
    photo_area = 0.0
    for index, node in enumerate(nodes):
        bounds = _box(node)
        has_image = any(
            isinstance(paint, Mapping)
            and paint.get("type") == "IMAGE"
            and paint.get("visible") is not False
            for paint in (node.get("fills") or [])
        )
        if bounds is None or not has_image:
            continue
        area = bounds.width * bounds.height
        if area >= section_area * _PHOTO_MIN_SECTION_COVERAGE and area > photo_area:
            photo_index, photo_area = index, area
    if photo_index is None:
        return None

    photo = nodes[photo_index]
    photo_box = _box(photo)
    assert photo_box is not None
    node_opacity = float(photo.get("opacity", 1) or 0)

    paints = [
        paint for paint in (photo.get("fills") or [])
        if isinstance(paint, Mapping) and paint.get("visible") is not False
    ]
    image_position = next(
        (position for position, paint in enumerate(paints) if paint.get("type") == "IMAGE"),
        None,
    )
    if image_position is not None:
        for paint in paints[image_position + 1:]:
            found = _translucent_solid(paint, node_opacity)
            if found is not None:
                color, opacity = found
                return {
                    "color": color, "opacity": opacity,
                    "node_id": str(photo.get("id")), "image_node_id": str(photo.get("id")),
                }

    best: tuple[float, int, str, float, str] | None = None
    for index in range(photo_index + 1, len(nodes)):
        node = nodes[index]
        bounds = _box(node)
        paints = [
            paint for paint in (node.get("fills") or [])
            if isinstance(paint, Mapping) and paint.get("visible") is not False
        ]
        if (
            node.get("type") not in _PAINTED_TYPES
            or node.get("isMask")
            or bounds is None
            or len(paints) != 1
            or bounds.width * bounds.height > photo_area * _OVERLAY_MAX_PHOTO_AREA_RATIO
        ):
            continue
        coverage = _coverage(bounds, photo_box)
        found = _translucent_solid(paints[0], float(node.get("opacity", 1) or 0))
        if found is None or coverage < _OVERLAY_MIN_PHOTO_COVERAGE:
            continue
        candidate = (coverage, index, found[0], found[1], str(node.get("id")))
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None:
        return None
    _, _, color, opacity, node_id = best
    return {
        "color": color, "opacity": opacity,
        "node_id": node_id, "image_node_id": str(photo.get("id")),
    }


def _format_px(value: float) -> str:
    return f"{format(round(value, 2), 'g')}px"


def _is_square(bounds: BoundingBox) -> bool:
    longest = max(bounds.width, bounds.height)
    return longest > 0 and abs(bounds.width - bounds.height) / longest <= _SQUARE_TOLERANCE


def _corner_radius(node: Mapping[str, Any], bounds: BoundingBox | None) -> str | None:
    """CSS border-radius for a node's own shape: an ellipse, or its corner radii."""

    if node.get("type") == "ELLIPSE":
        arc = node.get("arcData")
        if isinstance(arc, Mapping) and float(arc.get("innerRadius", 0) or 0) > 0:
            return None
        return "50%"
    radii = node.get("rectangleCornerRadii")
    if isinstance(radii, Sequence) and not isinstance(radii, str) and len(radii) == 4:
        values = [float(value or 0) for value in radii]
    else:
        single = node.get("cornerRadius")
        values = [float(single)] * 4 if isinstance(single, (int, float)) and single else []
    if not values or not any(value > 0 for value in values):
        return None
    # A radius of half the side or more is a circle however the file spells it.
    if bounds is not None and _is_square(bounds) and min(values) >= bounds.width / 2:
        return "50%"
    if len(set(values)) == 1:
        return _format_px(values[0])
    return " ".join(_format_px(value) for value in values)


def _overlap_ratio(inner: BoundingBox, outer: BoundingBox) -> float:
    width = max(0.0, min(inner.x + inner.width, outer.x + outer.width) - max(inner.x, outer.x))
    height = max(0.0, min(inner.y + inner.height, outer.y + outer.height) - max(inner.y, outer.y))
    return width * height / max(1.0, inner.width * inner.height)


def _masking_shape(
    node: Mapping[str, Any], bounds: BoundingBox | None,
    parents: Mapping[str, Mapping[str, Any]],
) -> tuple[str | None, BoundingBox | None]:
    """Find a shape that clips the node: a mask sibling or a clipping parent."""

    parent = parents.get(str(node.get("id")))
    if parent is None or bounds is None:
        return None, None
    for sibling in _children(parent):
        if sibling is node:
            break
        sibling_box = _box(sibling)
        if (
            sibling.get("isMask")
            and sibling_box is not None
            and _overlap_ratio(bounds, sibling_box) >= _MASK_OVERLAP_RATIO
        ):
            radius = _corner_radius(sibling, sibling_box)
            if radius is not None:
                return radius, sibling_box
    parent_box = _box(parent)
    if parent.get("clipsContent") and parent_box is not None and _overlap_ratio(parent_box, bounds) >= _MASK_OVERLAP_RATIO:
        radius = _corner_radius(parent, parent_box)
        if radius is not None:
            return radius, parent_box
    return None, None


def image_shape_style(
    node: Mapping[str, Any], fill: Mapping[str, Any],
    parents: Mapping[str, Mapping[str, Any]],
) -> list[tuple[StyleProperty, str]]:
    """Style a photo needs to keep the crop the designer drew.

    A photo placed in an ellipse, a rounded rectangle, or under a mask is
    cropped to that shape in the design. Without these values the build shows
    the whole image at its own proportions. A circle also needs equal sides,
    otherwise the radius draws an oval.
    """

    bounds = _box(node)
    radius = _corner_radius(node, bounds)
    shape_bounds = bounds
    if radius is None:
        radius, masked_bounds = _masking_shape(node, bounds, parents)
        shape_bounds = masked_bounds or bounds
    if radius is None:
        return []

    style: list[tuple[StyleProperty, str]] = [(StyleProperty.BORDER_RADIUS, radius)]
    fit = _FILL_FIT.get(str(fill.get("scaleMode", "")))
    if fit is not None:
        style.append((StyleProperty.OBJECT_FIT, fit))
    if radius == "50%" and shape_bounds is not None and _is_square(shape_bounds):
        side = _format_px(shape_bounds.width)
        style.extend([(StyleProperty.WIDTH, side), (StyleProperty.HEIGHT, side)])
    return style
