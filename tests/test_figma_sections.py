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


def _figma_section(role: str, *, kind: str = "flex", columns: int | None = None,
                   overlap: bool | None = None, with_action: bool = False):
    from vanjaro_cli.design.models import (
        ContentElement, ContentKind, LayoutKind, LayoutObservation, Section,
    )
    content = []
    if with_action:
        content.append(ContentElement(
            id="s.action.1", kind=ContentKind.BUTTON, role="action", order=0,
            value="Donate", confidence=0.9, provenance=[],
        ))
    metadata = {} if overlap is None else {"overlap": overlap}
    return Section(
        id=f"s.{role}", order=0, semantic_role=role, role_confidence=0.9,
        candidate_roles=[], content=content, groups=[],
        layout=LayoutObservation(kind=LayoutKind(kind), contained=True,
                                 columns=columns, metadata=metadata),
        style={}, responsive=[], decorative_layers=[], interactions=[], provenance=[],
    )


def test_mobile_inference_collapses_any_grid_to_one_column() -> None:
    from vanjaro_cli.design.figma_adapter import _infer_mobile

    changes = _infer_mobile(_figma_section("feature_cards", kind="grid", columns=3))

    assert changes["columns"]["to"] == 1


def test_mobile_inference_reports_single_column_state_when_columns_unknown() -> None:
    from vanjaro_cli.design.figma_adapter import _infer_mobile

    # A responsive observation records the state at that breakpoint, so an
    # unknown desktop column count still yields one column on mobile.
    changes = _infer_mobile(_figma_section("stats", kind="freeform"))

    assert changes["columns"]["to"] == 1


def test_logo_bars_keep_two_columns_and_wrap_on_mobile() -> None:
    from vanjaro_cli.design.figma_adapter import _infer_mobile

    changes = _infer_mobile(_figma_section("logo_cloud", columns=3))

    assert changes["columns"]["to"] == 2
    assert changes["wrap"]["to"] is True


def test_freeform_overlap_always_flattens_on_mobile() -> None:
    from vanjaro_cli.design.figma_adapter import _infer_mobile

    overlapping = _infer_mobile(_figma_section("hero", kind="freeform", overlap=True))
    flat = _infer_mobile(_figma_section("hero", kind="freeform", overlap=False))

    assert overlapping["overlap"] == {"from": True, "to": False}
    assert flat["overlap"] == {"from": False, "to": False}


def test_call_to_action_stacks_vertically_and_fills_width() -> None:
    from vanjaro_cli.design.figma_adapter import _infer_mobile

    changes = _infer_mobile(_figma_section("call_to_action", with_action=True))

    assert changes["direction"]["to"] == "vertical"
    assert changes["button_width"]["to"] == "100%"


def test_call_to_action_without_an_action_omits_button_width() -> None:
    from vanjaro_cli.design.figma_adapter import _infer_mobile

    changes = _infer_mobile(_figma_section("call_to_action"))

    assert "button_width" not in changes


def test_tablet_inference_halves_wide_grids_only() -> None:
    from vanjaro_cli.design.figma_adapter import _infer_tablet

    assert _infer_tablet(_figma_section("feature_cards", columns=4))["columns"]["to"] == 2
    assert _infer_tablet(_figma_section("split_feature", columns=2)) == {}
