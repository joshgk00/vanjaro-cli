"""Deterministic section-boundary inference for Figma page frames."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from vanjaro_cli.design.figma_tree import (
    CONTAINER_TYPES as _CONTAINER_TYPES,
    box as _box,
    children as _children,
    has_meaningful_content as _has_meaningful_content,
    node_text as _node_text,
    union_box as _union_box,
    visible as _visible,
    walk as _walk,
)
from vanjaro_cli.design.models import BoundingBox


def _boundary_identity(
    nodes: list[dict[str, Any]], index: int, *, role_hint: str | None = None,
) -> tuple[str, str | None]:
    """Return a useful inferred name and conservative semantic role hint."""

    texts = [value for node in nodes for _, _, value in _node_text(node)]
    lowered = " ".join(texts).casefold()
    node_names = " ".join(str(node.get("name", "")) for node in nodes).casefold()
    combined = f"{node_names} {lowered}"
    image_count = sum(
        any(
            isinstance(fill, Mapping) and fill.get("type") == "IMAGE"
            and fill.get("visible") is not False
            for fill in (current.get("fills") or [])
        )
        for node in nodes
        for current in _walk(node)
    )
    action_count = sum(
        any(word in value.casefold() for word in ("learn more", "join now", "register", "load more", "get started", "schedule"))
        for value in texts
    )
    number_count = sum(
        bool(re.fullmatch(r"[\d\s,.+%kmbd-]+", value.casefold()))
        for value in texts
    )

    inferred_role = role_hint
    if inferred_role is None and any(word in combined for word in ("navigation", "navbar", "main menu")):
        inferred_role = "navigation"
    if inferred_role is None and any(word in lowered for word in ("all rights reserved", "privacy policy", "quick links")):
        inferred_role = "footer"
    if inferred_role is None and number_count >= 2:
        inferred_role = "stats"
    if inferred_role is None and ("instructor" in lowered or "meet the team" in lowered or "our team" in lowered):
        inferred_role = "team_grid"
    if inferred_role is None and any(word in lowered for word in ("blogs", "latest news", "articles")):
        inferred_role = "blog_cards"
    if inferred_role is None and any(
        lowered.count(phrase) >= 2
        for phrase in ("music is magic", "announcement", "breaking news")
    ):
        inferred_role = "marquee"
    if inferred_role is None and any(word in lowered for word in ("classes", "courses", "programs", "services")) and image_count >= 2:
        inferred_role = "class_cards"
    if inferred_role is None and any(word in lowered for word in ("our media", "watch", "video")) and image_count:
        inferred_role = "video_feature"
    if inferred_role is None and any(
        word in lowered
        for word in ("prepare yourself", "join us", "get started", "register now", "schedule")
    ):
        inferred_role = "call_to_action"
    if inferred_role is None and image_count and len(texts) >= 3:
        inferred_role = "split_media"
    if inferred_role is None and action_count and len(texts) >= 2:
        inferred_role = "call_to_action"

    preferred = next(
        (
            value for value in texts
            if len(value) <= 90
            and not any(action == value.casefold() for action in ("learn more", "join now", "load more"))
        ),
        texts[0] if texts else f"section {index}",
    )
    name = f"Inferred {inferred_role or preferred}"
    return name, inferred_role


def _synthetic_section(
    frame: Mapping[str, Any], index: int, nodes: list[dict[str, Any]], *,
    boundary: str, role_hint: str | None = None,
) -> dict[str, Any]:
    ordered = sorted(
        {str(node.get("id", id(node))): node for node in nodes}.values(),
        key=lambda node: (
            _box(node).y if _box(node) else 0.0,
            _box(node).x if _box(node) else 0.0,
        ),
    )
    name, inferred_role = _boundary_identity(ordered, index, role_hint=role_hint)
    result: dict[str, Any] = {
        "id": f"{frame.get('id')}:inferred-{index}",
        "type": "GROUP",
        "name": name,
        "children": ordered,
        "absoluteBoundingBox": _union_box(ordered),
        "_vanjaro_inferred_boundary": boundary,
    }
    if inferred_role:
        result["_vanjaro_role_hint"] = inferred_role
    return result


def _flat_frame_sections(
    frame: Mapping[str, Any], direct_children: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Infer section bands from a flat, manually positioned page frame."""

    page_box = _box(frame)
    if page_box is None:
        return []
    meaningful = [child for child in direct_children if _has_meaningful_content(child)]
    gap_threshold = min(96.0, max(64.0, page_box.width * 0.055))

    painted: list[dict[str, Any]] = []
    explicit: list[dict[str, Any]] = []
    for child in direct_children:
        box = _box(child)
        if box is None:
            continue
        wide = box.width >= page_box.width * 0.80
        fills = [fill for fill in (child.get("fills") or []) if isinstance(fill, Mapping)]
        painted_fill = any(
            fill.get("visible") is not False
            and fill.get("type") in {"SOLID", "GRADIENT_LINEAR", "GRADIENT_RADIAL", "IMAGE"}
            for fill in fills
        )
        if wide and box.height >= 40 and child.get("type") != "TEXT" and painted_fill:
            painted.append(child)
        elif (
            wide and child.get("type") in _CONTAINER_TYPES
            and _has_meaningful_content(child)
        ):
            explicit.append(child)

    # Collapse layered backgrounds and adjacent thin footer/copyright strips.
    painted_groups: list[list[dict[str, Any]]] = []
    for child in sorted(painted, key=lambda item: (_box(item).y, _box(item).x)):  # type: ignore[union-attr]
        box = _box(child)
        assert box is not None
        merged = False
        for group in painted_groups:
            group_box = BoundingBox(**_union_box(group))
            vertical_overlap = max(
                0.0,
                min(box.y + box.height, group_box.y + group_box.height)
                - max(box.y, group_box.y),
            )
            overlap_ratio = vertical_overlap / max(1.0, min(box.height, group_box.height))
            gap = max(box.y - (group_box.y + group_box.height), group_box.y - (box.y + box.height), 0.0)
            horizontal_overlap = max(
                0.0,
                min(box.x + box.width, group_box.x + group_box.width)
                - max(box.x, group_box.x),
            )
            horizontal_ratio = horizontal_overlap / max(1.0, min(box.width, group_box.width))
            adjacent_strip = gap <= 4 and min(box.height, group_box.height) <= 96
            if horizontal_ratio >= 0.80 and (overlap_ratio >= 0.55 or adjacent_strip):
                group.append(child)
                merged = True
                break
        if not merged:
            painted_groups.append([child])

    anchors: list[dict[str, Any]] = []
    for nodes in painted_groups:
        anchors.append({"nodes": nodes, "box": BoundingBox(**_union_box(nodes)), "explicit": False})
    for child in explicit:
        anchors.append({"nodes": [child], "box": _box(child), "explicit": True})
    anchors.sort(key=lambda item: (item["box"].y, item["box"].x))

    consumed = {str(node.get("id")) for anchor in anchors for node in anchor["nodes"]}
    remaining: list[dict[str, Any]] = []
    for child in meaningful:
        if str(child.get("id")) in consumed:
            continue
        box = _box(child)
        if box is None:
            remaining.append(child)
            continue
        center = box.y + box.height / 2
        matches = []
        for anchor in anchors:
            anchor_box: BoundingBox = anchor["box"]
            margin = min(120.0, anchor_box.height * 0.18) if anchor["explicit"] else 0.0
            if anchor_box.y - margin <= center <= anchor_box.y + anchor_box.height + margin:
                matches.append(anchor)
        if matches:
            target = min(
                matches,
                key=lambda anchor: abs(
                    center - (anchor["box"].y + anchor["box"].height / 2)
                ),
            )
            target["nodes"].append(child)
        else:
            remaining.append(child)

    clusters: list[list[dict[str, Any]]] = []
    last_bottom: float | None = None
    for child in sorted(
        remaining,
        key=lambda item: (_box(item).y if _box(item) else 0.0, _box(item).x if _box(item) else 0.0),
    ):
        child_box = _box(child)
        if child_box is None:
            if clusters:
                clusters[-1].append(child)
            continue
        if last_bottom is None or child_box.y - last_bottom > gap_threshold:
            clusters.append([child])
        else:
            clusters[-1].append(child)
        last_bottom = max(last_bottom or child_box.y, child_box.y + child_box.height)

    # Tiny controls and copyright rows belong to the previous semantic band;
    # large nearby sections stay independent.
    combined: list[dict[str, Any]] = anchors + [
        {"nodes": cluster, "box": BoundingBox(**_union_box(cluster)), "explicit": False}
        for cluster in clusters
    ]
    combined.sort(key=lambda item: (item["box"].y, item["box"].x))
    merged: list[dict[str, Any]] = []
    for item in combined:
        if merged:
            previous = merged[-1]
            gap = item["box"].y - (previous["box"].y + previous["box"].height)
            if (
                item["box"].height <= 96
                and 0 <= gap <= gap_threshold * 1.5
                and not item.get("explicit")
            ):
                previous["nodes"].extend(item["nodes"])
                previous["box"] = BoundingBox(**_union_box(previous["nodes"]))
                continue
        merged.append(item)

    sections: list[dict[str, Any]] = []
    for index, item in enumerate(merged, 1):
        role_hint = None
        texts = " ".join(value for node in item["nodes"] for _, _, value in _node_text(node)).casefold()
        if index == 1 and any("navigation" in str(node.get("name", "")).casefold() for node in item["nodes"]):
            role_hint = "navigation"
        elif index == 2 and any(
            any(isinstance(fill, Mapping) and fill.get("type") == "IMAGE" for fill in (node.get("fills") or []))
            for node in item["nodes"]
        ):
            role_hint = "hero"
        elif index == len(merged) and any(word in texts for word in ("all rights", "privacy", "quick links")):
            role_hint = "footer"
        sections.append(
            _synthetic_section(
                frame, index, item["nodes"], boundary="flat_geometry",
                role_hint=role_hint,
            )
        )
    return sections


def segment_frame(frame: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return visually ordered, meaningful top-level section nodes."""

    direct_children = [child for child in _children(frame) if _visible(child)]
    meaningful_direct = [child for child in direct_children if _has_meaningful_content(child)]
    non_container_ratio = (
        len([child for child in meaningful_direct if child.get("type") not in _CONTAINER_TYPES])
        / len(meaningful_direct)
        if meaningful_direct else 0.0
    )
    if (
        frame.get("layoutMode") not in {"HORIZONTAL", "VERTICAL"}
        and len(meaningful_direct) >= 4
        and non_container_ratio >= 0.25
    ):
        inferred = _flat_frame_sections(frame, direct_children)
        if len(inferred) >= 2:
            return inferred
    candidates = [
        child for child in _children(frame)
        if _visible(child) and child.get("type") in _CONTAINER_TYPES
        and _has_meaningful_content(child)
    ]
    # Flat, manually positioned frames often use full-width painted rectangles
    # as section bands and place text/media beside them as siblings. Treat the
    # bands as inferred containers before falling back to whitespace clusters.
    if len(candidates) < 2:
        page_box = _box(frame)
        bands = []
        if page_box is not None:
            for child in direct_children:
                child_box = _box(child)
                visible_fill = any(
                    isinstance(fill, Mapping) and fill.get("visible") is not False
                    and fill.get("type") in {"SOLID", "GRADIENT_LINEAR", "IMAGE"}
                    for fill in (child.get("fills") or [])
                )
                if child_box and child_box.width >= page_box.width * 0.8 and child_box.height >= 96 and visible_fill:
                    bands.append(child)
        inferred_bands: list[dict[str, Any]] = []
        for band in bands:
            band_box = _box(band)
            if band_box is None:
                continue
            members = []
            for child in direct_children:
                if child is band or child in bands or not _has_meaningful_content(child):
                    continue
                child_box = _box(child)
                if child_box and band_box.y <= child_box.y + child_box.height / 2 <= band_box.y + band_box.height:
                    members.append(child)
            if members:
                inferred = dict(band)
                inferred["type"] = "GROUP"
                inferred["name"] = str(band.get("name") or f"Inferred band {band.get('id')}")
                inferred["children"] = members
                inferred["_vanjaro_inferred_boundary"] = "background_band"
                inferred_bands.append(inferred)
        if len(inferred_bands) >= 2:
            candidates = inferred_bands

    if not candidates:
        meaningful = [child for child in direct_children if _has_meaningful_content(child)]
        positioned = [(child, _box(child)) for child in meaningful if _box(child) is not None]
        clusters: list[list[dict[str, Any]]] = []
        last_bottom: float | None = None
        page_box = _box(frame)
        gap_threshold = max(80.0, (page_box.height * 0.035) if page_box else 80.0)
        for child, child_box in sorted(positioned, key=lambda item: (item[1].y, item[1].x)):  # type: ignore[union-attr]
            assert child_box is not None
            if last_bottom is None or child_box.y - last_bottom > gap_threshold:
                clusters.append([child])
            else:
                clusters[-1].append(child)
            last_bottom = max(last_bottom or child_box.y, child_box.y + child_box.height)
        if len(clusters) >= 2:
            candidates = []
            for index, cluster in enumerate(clusters, 1):
                candidates.append({
                    "id": f"{frame.get('id')}:inferred-{index}", "type": "GROUP",
                    "name": f"Inferred section {index}", "children": cluster,
                    "absoluteBoundingBox": {
                        "x": min(_box(child).x for child in cluster if _box(child)),
                        "y": min(_box(child).y for child in cluster if _box(child)),
                        "width": max((_box(child).x + _box(child).width) for child in cluster if _box(child)) - min(_box(child).x for child in cluster if _box(child)),
                        "height": max((_box(child).y + _box(child).height) for child in cluster if _box(child)) - min(_box(child).y for child in cluster if _box(child)),
                    },
                    "_vanjaro_inferred_boundary": "whitespace_geometry",
                })
        else:
            candidates = meaningful
    if not candidates and _has_meaningful_content(frame):
        candidates = [dict(frame)]

    positions = {id(child): index for index, child in enumerate(_children(frame))}
    return sorted(
        candidates,
        key=lambda node: (
            _box(node).y if _box(node) is not None else float(positions.get(id(node), 0)),
            _box(node).x if _box(node) is not None else 0,
            positions.get(id(node), 0),
        ),
    )


__all__ = ["segment_frame"]
