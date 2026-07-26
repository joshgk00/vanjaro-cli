"""Focused tests for the extracted Figma tree and section-boundary modules."""

from __future__ import annotations

from vanjaro_cli.design.figma_sections import segment_frame
from vanjaro_cli.design.figma_tree import box, has_meaningful_content, node_text, walk


def _text(node_id: str, value: str, *, x: int, y: int) -> dict:
    return {
        "id": node_id,
        "type": "TEXT",
        "name": "Heading",
        "characters": value,
        "absoluteBoundingBox": {"x": x, "y": y, "width": 400, "height": 50},
    }


def test_tree_helpers_preserve_visual_reading_order_and_visibility() -> None:
    hidden = _text("hidden", "Hidden", x=10, y=10)
    hidden["visible"] = False
    frame = {
        "id": "page",
        "type": "FRAME",
        "children": [
            _text("second", "Second", x=20, y=200),
            hidden,
            _text("first", "First", x=40, y=100),
        ],
    }

    assert [node["id"] for node in walk(frame)] == ["page", "second", "hidden", "first"]
    assert [value for _, _, value in node_text(frame)] == ["First", "Second"]
    assert has_meaningful_content(frame) is True
    assert box(frame) is None


def test_segment_frame_keeps_structured_sections_in_visual_order() -> None:
    frame = {
        "id": "page",
        "type": "FRAME",
        "layoutMode": "VERTICAL",
        "children": [
            {
                "id": "later",
                "type": "FRAME",
                "name": "CTA",
                "absoluteBoundingBox": {"x": 0, "y": 500, "width": 1000, "height": 240},
                "children": [_text("later-title", "Get started", x=100, y=560)],
            },
            {
                "id": "earlier",
                "type": "FRAME",
                "name": "Hero",
                "absoluteBoundingBox": {"x": 0, "y": 80, "width": 1000, "height": 320},
                "children": [_text("earlier-title", "Welcome", x=100, y=160)],
            },
        ],
    }

    assert [section["id"] for section in segment_frame(frame)] == ["earlier", "later"]


def test_segment_frame_infers_flat_painted_bands_deterministically() -> None:
    frame = {
        "id": "page",
        "type": "FRAME",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1000, "height": 900},
        "children": [
            {
                "id": "hero-bg",
                "type": "RECTANGLE",
                "name": "Hero background",
                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1000, "height": 360},
                "fills": [{"type": "SOLID"}],
            },
            _text("hero-title", "Welcome", x=100, y=120),
            {
                "id": "cta-bg",
                "type": "RECTANGLE",
                "name": "CTA background",
                "absoluteBoundingBox": {"x": 0, "y": 520, "width": 1000, "height": 300},
                "fills": [{"type": "SOLID"}],
            },
            _text("cta-title", "Join us today", x=100, y=620),
        ],
    }

    first = segment_frame(frame)
    second = segment_frame(frame)

    assert first == second
    assert len(first) == 2
    assert [section["_vanjaro_inferred_boundary"] for section in first] == [
        "background_band",
        "background_band",
    ]
    assert [[child["id"] for child in section["children"]] for section in first] == [
        ["hero-title"],
        ["cta-title"],
    ]
