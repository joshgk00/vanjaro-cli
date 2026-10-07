"""Turn a design footer section into the content the footer builder lays out.

The builder renders columns, a band colour, and a legal strip. This module
decides what goes in each from the design itself: elements are grouped into
columns by where they sit on the page, the strip is the element row standing on
the bottom colour bar, and the colours come from the painted bands behind the
text. A design with no positions falls back to one flat list, as before.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from vanjaro_cli.design.css_color import normalize_css_color
from vanjaro_cli.design.models import (
    AssetRecord,
    BoundingBox,
    ContentElement,
    ContentKind,
    Section,
    StyleProperty,
)
from vanjaro_cli.utils.image_links import is_safe_link_href

__all__ = ["footer_builder_content"]

_COLUMN_GAP_RATIO = 0.03
_COLUMN_GAP_MINIMUM = 24.0
_PARAGRAPH_LENGTH = 100
_LABEL_LENGTH = 40
_LABEL_SIZE_MARGIN = 1.0
_WHITESPACE = re.compile(r"\s+")


def footer_builder_content(
    section: Section, assets: Mapping[str, AssetRecord]
) -> dict[str, Any]:
    """Build the footer content dict: columns and strip when positions exist."""

    background = _background_color(section)
    elements = sorted(section.content, key=lambda value: (value.order, value.id))
    boxes = [_bounds(element) for element in elements]
    if elements and all(box is not None for box in boxes):
        placed = [(element, box) for element, box in zip(elements, boxes) if box is not None]
        strip, body = _split_strip(section, placed)
        content: dict[str, Any] = {"columns": _columns(body, assets, _body_width(section, body))}
        if strip:
            content["bottom_bar"] = {
                "background_color": _band(section, "bottom_bar")["color"],
                "entries": [entry for element, _ in strip if (entry := _entry(element, assets))],
            }
    else:
        content = _flat_content(elements, assets)
    if background:
        content["background_color"] = background
    return content


def _band(section: Section, role: str) -> dict[str, Any]:
    bands = section.metadata.get("background_bands")
    for band in bands if isinstance(bands, list) else []:
        if isinstance(band, dict) and band.get("role") == role:
            return band
    return {}


def _background_color(section: Section) -> str | None:
    base = _band(section, "base").get("color")
    if isinstance(base, str) and base:
        return base
    for observation in section.style.observations:
        if observation.property == StyleProperty.BACKGROUND_COLOR:
            return normalize_css_color(observation.value)
    return None


def _bounds(element: ContentElement) -> BoundingBox | None:
    for record in element.provenance:
        if record.bounds is not None:
            return record.bounds
    return None


def _split_strip(
    section: Section, placed: list[tuple[ContentElement, BoundingBox]]
) -> tuple[list[tuple[ContentElement, BoundingBox]], list[tuple[ContentElement, BoundingBox]]]:
    """Separate the elements standing on the bottom colour bar from the rest."""

    raw = _band(section, "bottom_bar").get("bounds")
    if not isinstance(raw, dict):
        return [], placed
    bar = BoundingBox(**raw)
    strip = [
        item for item in placed
        if bar.y <= item[1].y + item[1].height / 2 <= bar.y + bar.height
    ]
    strip_ids = {element.id for element, _ in strip}
    return strip, [item for item in placed if item[0].id not in strip_ids]


def _body_width(section: Section, body: list[tuple[ContentElement, BoundingBox]]) -> float:
    raw = _band(section, "base").get("bounds")
    if isinstance(raw, dict) and raw.get("width"):
        return float(raw["width"])
    if not body:
        return 0.0
    return max(box.x + box.width for _, box in body) - min(box.x for _, box in body)


def _columns(
    body: list[tuple[ContentElement, BoundingBox]],
    assets: Mapping[str, AssetRecord],
    width: float,
) -> list[dict[str, Any]]:
    """Group elements into left-to-right columns, top to bottom within each."""

    gap = max(_COLUMN_GAP_MINIMUM, width * _COLUMN_GAP_RATIO)
    clusters: list[list[tuple[ContentElement, BoundingBox]]] = []
    right_edge = 0.0
    for item in sorted(body, key=lambda value: (value[1].x, value[1].y)):
        box = item[1]
        if clusters and box.x - right_edge <= gap:
            clusters[-1].append(item)
            right_edge = max(right_edge, box.x + box.width)
        else:
            clusters.append([item])
            right_edge = box.x + box.width

    columns: list[dict[str, Any]] = []
    for cluster in clusters:
        ordered = sorted(cluster, key=lambda value: (value[1].y, value[1].x))
        label_floor = _label_floor([element for element, _ in ordered])
        entries = [
            entry
            for element, _ in ordered
            if (entry := _entry(element, assets, label_floor=label_floor))
        ]
        if entries:
            columns.append({"entries": entries})
    return columns


def _font_size(element: ContentElement) -> float | None:
    value = element.attributes.get("font_size")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _label_floor(elements: Sequence[ContentElement]) -> float | None:
    """The body text size of a column; a short line set larger is its label."""

    sizes = [
        size for element in elements
        if element.kind in {ContentKind.TEXT, ContentKind.OTHER, ContentKind.HEADING}
        and (size := _font_size(element)) is not None
    ]
    return min(sizes) if len(sizes) >= 2 else None


def _clean(value: object) -> str:
    return _WHITESPACE.sub(" ", str(value or "")).strip()


def _entry(
    element: ContentElement,
    assets: Mapping[str, AssetRecord],
    *,
    label_floor: float | None = None,
) -> dict[str, str] | None:
    text = _clean(element.value)
    if element.kind == ContentKind.IMAGE:
        asset = assets.get(element.asset_id or "")
        src = (asset.source_url or asset.local_path) if asset is not None else None
        if not src:
            return None
        return {"kind": "image", "src": src, "alt": (asset.alt_text or "") if asset else ""}
    if not text:
        return None
    if element.kind == ContentKind.HEADING:
        return {"kind": "heading", "text": text}
    if element.kind in {ContentKind.BUTTON, ContentKind.LINK}:
        href = str(element.attributes.get("href") or "").strip()
        if href and is_safe_link_href(href):
            return {"kind": "link", "text": text, "href": href}
        return {"kind": "text", "text": text}
    if len(text) > _PARAGRAPH_LENGTH:
        return {"kind": "paragraph", "text": text}
    size = _font_size(element)
    if (
        label_floor is not None
        and size is not None
        and size >= label_floor + _LABEL_SIZE_MARGIN
        and len(text) <= _LABEL_LENGTH
    ):
        return {"kind": "heading", "text": text}
    return {"kind": "text", "text": text}


def _flat_content(
    elements: Sequence[ContentElement], assets: Mapping[str, AssetRecord]
) -> dict[str, Any]:
    """One undifferentiated list per kind, for a design that carries no positions."""

    headings: list[str] = []
    list_items: list[str] = []
    paragraphs: list[str] = []
    images: list[dict[str, str]] = []
    links: list[dict[str, str]] = []
    for element in elements:
        text = str(element.value or "").strip()
        if element.kind == ContentKind.IMAGE and element.asset_id in assets:
            asset = assets[element.asset_id]
            src = asset.source_url or asset.local_path
            if src:
                images.append({"src": src, "alt": asset.alt_text or ""})
        elif element.kind == ContentKind.HEADING and text:
            headings.append(text)
        elif element.kind in {ContentKind.BUTTON, ContentKind.LINK} and text:
            href = str(element.attributes.get("href") or "")
            links.append({"text": text, "href": href})
            list_items.append(text)
        elif text:
            if len(text) > _PARAGRAPH_LENGTH:
                paragraphs.append(text)
            else:
                list_items.append(text)
    return {
        "headings": headings,
        "list_items": list_items,
        "paragraphs": paragraphs,
        "images": images,
        "links": links,
    }
