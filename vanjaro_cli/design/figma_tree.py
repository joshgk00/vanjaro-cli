"""Pure helpers for traversing and classifying Figma REST node trees."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

from vanjaro_cli.design.models import BoundingBox


CONTAINER_TYPES = frozenset({"FRAME", "GROUP", "INSTANCE", "COMPONENT", "SECTION"})
DECORATIVE_WORDS = frozenset(
    {
        "background",
        "blob",
        "decoration",
        "decorative",
        "divider",
        "doodle",
        "glow",
        "gradient",
        "overlay",
        "pattern",
        "shape",
        "sparkle",
        "texture",
    }
)


def children(node: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return dictionary children from a Figma node."""

    raw_children = node.get("children") or []
    return [child for child in raw_children if isinstance(child, dict)]


def walk(node: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield a Figma node tree in pre-order."""

    if isinstance(node, dict):
        yield node
    for child in children(node):
        yield from walk(child)


def visible(node: Mapping[str, Any]) -> bool:
    """Return whether a node participates in visible design evidence."""

    return node.get("visible") is not False and float(node.get("opacity", 1) or 0) > 0


def box(node: Mapping[str, Any]) -> BoundingBox | None:
    """Parse a node's absolute bounding box when valid."""

    raw = node.get("absoluteBoundingBox")
    if not isinstance(raw, Mapping):
        return None
    try:
        return BoundingBox(
            x=float(raw.get("x", 0)),
            y=float(raw.get("y", 0)),
            width=float(raw.get("width", 0)),
            height=float(raw.get("height", 0)),
        )
    except (TypeError, ValueError):
        return None


def is_decorative(node: Mapping[str, Any]) -> bool:
    """Conservatively classify a node as decorative rather than content."""

    name_words = set(re.findall(r"[a-z]+", str(node.get("name", "")).lower()))
    if name_words.intersection(DECORATIVE_WORDS):
        return True
    node_type = node.get("type")
    if node_type in {"VECTOR", "STAR", "LINE", "BOOLEAN_OPERATION"}:
        return not name_words.intersection({"logo", "icon", "photo", "portrait"})
    return False


def has_meaningful_content(node: Mapping[str, Any]) -> bool:
    """Return whether a subtree contains visible text or non-decorative imagery."""

    for current in walk(node):
        if not visible(current):
            continue
        if current.get("type") == "TEXT" and str(current.get("characters", "")).strip():
            return True
        if any(
            fill.get("type") == "IMAGE" and fill.get("visible") is not False
            for fill in (current.get("fills") or [])
            if isinstance(fill, Mapping)
        ) and not is_decorative(current):
            return True
    return False


def union_box(nodes: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    """Return the smallest bounding box containing all positioned nodes."""

    boxes = [bounds for node in nodes if (bounds := box(node)) is not None]
    if not boxes:
        return {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
    left = min(bounds.x for bounds in boxes)
    top = min(bounds.y for bounds in boxes)
    right = max(bounds.x + bounds.width for bounds in boxes)
    bottom = max(bounds.y + bounds.height for bounds in boxes)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def node_text(node: Mapping[str, Any]) -> list[tuple[float, float, str]]:
    """Return visible text values in visual reading order."""

    values: list[tuple[float, float, str]] = []
    for current in walk(node):
        if not visible(current) or current.get("type") != "TEXT":
            continue
        value = str(current.get("characters", "")).strip()
        if not value:
            continue
        bounds = box(current)
        values.append((bounds.y if bounds else 0.0, bounds.x if bounds else 0.0, value))
    return sorted(values)


__all__ = [
    "CONTAINER_TYPES",
    "box",
    "children",
    "has_meaningful_content",
    "is_decorative",
    "node_text",
    "union_box",
    "visible",
    "walk",
]
