"""Focused acceptance tests for the Design Document v1 Figma adapter."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from vanjaro_cli.design.figma_adapter import FigmaAdapterError, analyze_figma_document
from vanjaro_cli.design.models import (
    AssetRole,
    BreakpointName,
    ContentKind,
    EvidenceStatus,
    LayoutKind,
    ObservationMethod,
    RepeatGroupKind,
)


CORPUS = Path(__file__).parents[1] / "fixtures" / "design-benchmarks"
CAPTURED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def _case(case_id: str) -> tuple[dict, dict]:
    root = CORPUS / "cases" / case_id
    return (
        json.loads((root / "source.json").read_text(encoding="utf-8")),
        json.loads((root / "annotations.json").read_text(encoding="utf-8")),
    )


@pytest.mark.parametrize("case_id", ["figma-auto-layout-saas", "figma-freeform-nonprofit"])
def test_benchmark_section_boundaries_roles_content_and_groups(case_id):
    source, annotation = _case(case_id)
    document = analyze_figma_document(source, file_key=case_id, captured_at=CAPTURED_AT)

    expected = annotation["expected"]["sections"]
    actual = document.pages[0].sections
    assert len(actual) == len(expected)
    assert [section.semantic_role for section in actual] == [section["semantic_role"] for section in expected]
    assert [section.order for section in actual] == list(range(len(expected)))

    expected_nodes = {section["boundary"]["value"] for section in expected}
    actual_nodes = {str(section.metadata["figma_node_id"]) for section in actual}
    assert actual_nodes == expected_nodes
    assert all(section.role_confidence >= 0.9 for section in actual)
    assert all(section.provenance[0].element_node_id in expected_nodes for section in actual)

    expected_values = {
        element["value"] for section in expected for element in section["content"]
        if element["value"] is not None
    }
    actual_values = {element.value for section in actual for element in section.content}
    assert expected_values.issubset(actual_values)
    assert sum(len(group.items) for section in actual for group in section.groups) == 8


def test_auto_layout_is_observed_and_freeform_layout_is_inferred_with_provenance():
    auto_source, _ = _case("figma-auto-layout-saas")
    auto = analyze_figma_document(auto_source, file_key="auto", captured_at=CAPTURED_AT)
    features = auto.pages[0].sections[2]
    assert features.layout.kind == LayoutKind.GRID
    assert features.layout.columns == 3
    assert features.layout.metadata == {"evidence": "figma_auto_layout", "confidence": 1.0}
    assert features.metadata["layout_evidence_status"] == "observed"

    free_source, _ = _case("figma-freeform-nonprofit")
    freeform = analyze_figma_document(free_source, file_key="free", captured_at=CAPTURED_AT)
    assert all(section.metadata["layout_evidence_status"] == "inferred" for section in freeform.pages[0].sections)
    assert all(section.layout.metadata["evidence"] == "inferred_from_geometry" for section in freeform.pages[0].sections)
    assert all(
        any(provenance.method == ObservationMethod.INFERRED for provenance in section.provenance)
        for section in freeform.pages[0].sections
    )


def test_component_instances_become_bound_repeat_items_and_staggered_geometry_is_grid():
    source = _minimal_file([
        {
            "id": "10:1", "type": "GROUP", "name": "Feature cards",
            "absoluteBoundingBox": {"x": 40, "y": 40, "width": 920, "height": 400},
            "children": [
                _instance("11:1", "Reusable card", "component:card", 40, "First"),
                _instance("12:1", "Reusable card", "component:card", 320, "Second", y=60),
                _instance("13:1", "Reusable card", "component:card", 600, "Third", y=50),
            ],
        }
    ])
    document = analyze_figma_document(source, file_key="instances", captured_at=CAPTURED_AT)
    section = document.pages[0].sections[0]
    assert section.layout.kind == LayoutKind.GRID
    assert section.layout.columns == 3
    assert section.groups[0].kind.value == "card"
    assert len(section.groups[0].items) == 3
    assert all(item.fields.get("title") for item in section.groups[0].items)
    assert {item.provenance[0].component_id for item in section.groups[0].items} == {"component:card"}
    assert all(item.provenance[0].metadata["component_properties"]["Title"]["value"] for item in section.groups[0].items)
    assert all(element.group_id == section.groups[0].id for element in section.content)


def test_image_fills_deduplicate_prefer_originals_and_keep_multiple_owners():
    source = _minimal_file([{
        "id": "20:1", "type": "FRAME", "name": "Gallery cards", "layoutMode": "HORIZONTAL",
        "children": [
            {"id": "21:1", "type": "RECTANGLE", "name": "Editorial photo one", "fills": [{"type": "IMAGE", "imageRef": "shared-original"}]},
            {"id": "22:1", "type": "RECTANGLE", "name": "Editorial photo two", "fills": [{"type": "IMAGE", "imageRef": "shared-original"}]},
        ],
    }])
    document = analyze_figma_document(
        source, file_key="assets", image_fill_urls={"shared-original": "https://signed.invalid/original.png"},
        captured_at=CAPTURED_AT,
    )
    assert len(document.assets) == 1
    asset = document.assets[0]
    assert asset.source_url == "figma://assets/shared-original"
    assert asset.metadata["original_available"] is True
    assert asset.role == AssetRole.EDITORIAL
    assert asset.metadata["resolution"] == "original_fill"
    assert asset.metadata["owner_node_ids"] == ["21:1", "22:1"]
    assert len(asset.provenance) == 2
    assert "FIGMA_IMAGE_FILL_UNRESOLVED" not in {warning.code for warning in document.warnings}


def test_decorative_overlap_does_not_create_section_and_vector_export_hook_is_used():
    source = _minimal_file([
        {"id": "30:0", "type": "GROUP", "name": "Decorative overlap", "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1000, "height": 200}, "children": [{"id": "30:1", "type": "VECTOR", "name": "Sparkle decoration"}]},
        {"id": "31:0", "type": "FRAME", "name": "Hero", "children": [
            {"id": "31:1", "type": "TEXT", "name": "Heading", "characters": "A useful heading"},
            {"id": "31:2", "type": "VECTOR", "name": "Wave decoration"},
        ]},
    ])
    document = analyze_figma_document(
        source, file_key="vectors", vector_resolver=lambda node: f"https://signed.invalid/{node['id']}.svg",
        captured_at=CAPTURED_AT,
    )
    assert len(document.pages[0].sections) == 1
    section = document.pages[0].sections[0]
    assert section.semantic_role == "hero"
    assert len(section.decorative_layers) == 1
    assert len(document.assets) == 1
    assert document.assets[0].source_url == "figma://vectors/node/31:2"
    assert document.assets[0].metadata["original_available"] is True
    assert document.assets[0].role == AssetRole.DECORATIVE


def test_background_bands_segment_flat_manual_frames_with_inferred_boundary_evidence():
    source = _minimal_file([
        {"id": "40:1", "type": "RECTANGLE", "name": "Hero background", "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1000, "height": 360}, "fills": [{"type": "SOLID", "color": {"r": 0.1, "g": 0.2, "b": 0.3}}]},
        {"id": "40:2", "type": "TEXT", "name": "Hero heading", "characters": "A flat-frame hero", "absoluteBoundingBox": {"x": 100, "y": 120, "width": 500, "height": 70}},
        {"id": "41:1", "type": "RECTANGLE", "name": "CTA background", "absoluteBoundingBox": {"x": 0, "y": 500, "width": 1000, "height": 300}, "fills": [{"type": "SOLID", "color": {"r": 0.8, "g": 0.4, "b": 0.2}}]},
        {"id": "41:2", "type": "TEXT", "name": "CTA heading", "characters": "A separated action", "absoluteBoundingBox": {"x": 100, "y": 600, "width": 500, "height": 70}},
    ])
    document = analyze_figma_document(source, file_key="bands", captured_at=CAPTURED_AT)
    assert [section.semantic_role for section in document.pages[0].sections] == ["hero", "call_to_action"]
    assert all(section.metadata["section_boundary_evidence"] == "inferred" for section in document.pages[0].sections)
    assert all(section.provenance[0].method == ObservationMethod.INFERRED for section in document.pages[0].sections)


def test_flat_frame_consolidates_misleading_containers_and_retains_direct_content():
    source = _minimal_file([
        {
            "id": "nav", "type": "INSTANCE", "name": "Navigation",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1000, "height": 80},
            "children": [{
                "id": "nav-label", "type": "TEXT", "name": "Menu item",
                "characters": "Home",
                "absoluteBoundingBox": {"x": 40, "y": 25, "width": 80, "height": 24},
            }],
        },
        {
            "id": "hero-background", "type": "RECTANGLE", "name": "Hero photo",
            "absoluteBoundingBox": {"x": 0, "y": 100, "width": 1000, "height": 320},
            "fills": [{"type": "IMAGE", "imageRef": "hero-ref"}],
        },
        {
            "id": "hero-title", "type": "TEXT", "name": "Hero heading",
            "characters": "Music for everyone",
            "absoluteBoundingBox": {"x": 160, "y": 180, "width": 680, "height": 60},
        },
        {
            "id": "hero-copy", "type": "TEXT", "name": "Hero body",
            "characters": "A welcoming introduction to the studio.",
            "absoluteBoundingBox": {"x": 220, "y": 270, "width": 560, "height": 40},
        },
        {
            "id": "about-photo", "type": "RECTANGLE", "name": "Student photo",
            "absoluteBoundingBox": {"x": 40, "y": 560, "width": 420, "height": 300},
            "fills": [{"type": "IMAGE", "imageRef": "student-ref"}],
        },
        {
            "id": "about-title", "type": "TEXT", "name": "Section heading",
            "characters": "Music is magic",
            "absoluteBoundingBox": {"x": 520, "y": 590, "width": 380, "height": 50},
        },
        {
            "id": "about-copy", "type": "TEXT", "name": "Section body",
            "characters": "Students build confidence through active participation.",
            "absoluteBoundingBox": {"x": 520, "y": 670, "width": 400, "height": 80},
        },
        {
            "id": "about-action", "type": "FRAME", "name": "Button",
            "absoluteBoundingBox": {"x": 520, "y": 790, "width": 180, "height": 48},
            "children": [{
                "id": "about-action-label", "type": "TEXT", "name": "Button label",
                "characters": "Learn more",
                "absoluteBoundingBox": {"x": 550, "y": 804, "width": 120, "height": 20},
            }],
        },
    ])

    document = analyze_figma_document(
        source,
        file_key="mixed-flat",
        image_fill_urls={
            "hero-ref": "https://signed.invalid/hero.png",
            "student-ref": "https://signed.invalid/student.png",
        },
        captured_at=CAPTURED_AT,
    )

    sections = document.pages[0].sections
    assert [section.semantic_role for section in sections] == [
        "navigation", "hero", "split_media",
    ]
    assert {
        element.value
        for section in sections
        for element in section.content
        if element.kind != ContentKind.IMAGE
    } == {
        "Home",
        "Music for everyone",
        "A welcoming introduction to the studio.",
        "Music is magic",
        "Students build confidence through active participation.",
        "Learn more",
    }
    assert sum(
        element.kind == ContentKind.IMAGE
        for section in sections
        for element in section.content
    ) == 2
    assert len(document.assets) == 2
    assert all(section.metadata["section_boundary_evidence"] == "inferred" for section in sections)


def test_flat_frame_deduplicates_painted_layers_without_promoting_colored_text():
    source = _minimal_file([
        {
            "id": "layer-a", "type": "RECTANGLE", "name": "Background layer A",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1000, "height": 300},
            "fills": [{"type": "SOLID", "color": {"r": 0.1, "g": 0.2, "b": 0.3}}],
        },
        {
            "id": "layer-b", "type": "RECTANGLE", "name": "Background layer B",
            "absoluteBoundingBox": {"x": 0, "y": 2, "width": 1000, "height": 296},
            "fills": [{"type": "SOLID", "color": {"r": 0.2, "g": 0.3, "b": 0.4}}],
        },
        {
            "id": "wide-title", "type": "TEXT", "name": "Heading",
            "characters": "One visual band",
            "absoluteBoundingBox": {"x": 40, "y": 70, "width": 920, "height": 60},
            "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1}}],
        },
        {
            "id": "first-copy", "type": "TEXT", "name": "Body",
            "characters": "Layered backgrounds must not duplicate the section.",
            "absoluteBoundingBox": {"x": 120, "y": 170, "width": 760, "height": 40},
        },
        {
            "id": "second-background", "type": "RECTANGLE", "name": "Action background",
            "absoluteBoundingBox": {"x": 0, "y": 500, "width": 1000, "height": 300},
            "fills": [{"type": "SOLID", "color": {"r": 0.8, "g": 0.4, "b": 0.2}}],
        },
        {
            "id": "second-title", "type": "TEXT", "name": "Heading",
            "characters": "Join us today",
            "absoluteBoundingBox": {"x": 180, "y": 590, "width": 640, "height": 60},
        },
        {
            "id": "second-action", "type": "TEXT", "name": "Button label",
            "characters": "Get started",
            "absoluteBoundingBox": {"x": 400, "y": 690, "width": 200, "height": 40},
        },
    ])

    document = analyze_figma_document(
        source, file_key="layered-bands", captured_at=CAPTURED_AT,
    )

    sections = document.pages[0].sections
    assert len(sections) == 2
    assert {
        element.value
        for section in sections
        for element in section.content
    } == {
        "One visual band",
        "Layered backgrounds must not duplicate the section.",
        "Join us today",
        "Get started",
    }
    assert sum(
        element.value == "One visual band"
        for section in sections
        for element in section.content
    ) == 1


def test_flat_blog_orphan_action_stays_with_repeat_group_not_following_cta():
    source = _minimal_file([
        {
            "id": "blog-heading", "type": "TEXT", "name": "Section heading",
            "characters": "Blogs",
            "style": {"fontSize": 42},
            "absoluteBoundingBox": {"x": 50, "y": 0, "width": 300, "height": 50},
        },
        {
            "id": "post-photo-a", "type": "RECTANGLE", "name": "Post photo",
            "absoluteBoundingBox": {"x": 50, "y": 100, "width": 400, "height": 200},
            "fills": [{"type": "IMAGE", "imageRef": "post-a"}],
        },
        {
            "id": "post-photo-b", "type": "RECTANGLE", "name": "Post photo",
            "absoluteBoundingBox": {"x": 550, "y": 100, "width": 400, "height": 200},
            "fills": [{"type": "IMAGE", "imageRef": "post-b"}],
        },
        {
            "id": "post-title-a", "type": "TEXT", "name": "Card title",
            "characters": "Practice makes progress", "style": {"fontSize": 28},
            "absoluteBoundingBox": {"x": 50, "y": 320, "width": 400, "height": 40},
        },
        {
            "id": "post-title-b", "type": "TEXT", "name": "Card title",
            "characters": "Choosing a first instrument", "style": {"fontSize": 28},
            "absoluteBoundingBox": {"x": 550, "y": 320, "width": 400, "height": 40},
        },
        {
            "id": "post-body-a", "type": "TEXT", "name": "Card body",
            "characters": "A useful routine for young musicians.", "style": {"fontSize": 16},
            "absoluteBoundingBox": {"x": 50, "y": 380, "width": 400, "height": 40},
        },
        {
            "id": "post-body-b", "type": "TEXT", "name": "Card body",
            "characters": "Questions to ask before the first lesson.", "style": {"fontSize": 16},
            "absoluteBoundingBox": {"x": 550, "y": 380, "width": 400, "height": 40},
        },
        {
            "id": "load-control", "type": "FRAME", "name": "Load more button",
            "absoluteBoundingBox": {"x": 400, "y": 500, "width": 200, "height": 40},
            "children": [{
                "id": "load-label", "type": "TEXT", "name": "Button label",
                "characters": "Load more",
                "absoluteBoundingBox": {"x": 445, "y": 510, "width": 110, "height": 20},
            }],
        },
        {
            "id": "next-cta", "type": "GROUP", "name": "Join CTA",
            "absoluteBoundingBox": {"x": 50, "y": 680, "width": 900, "height": 220},
            "children": [
                {
                    "id": "cta-title", "type": "TEXT", "name": "Heading",
                    "characters": "Join us at the studio",
                    "absoluteBoundingBox": {"x": 120, "y": 720, "width": 600, "height": 50},
                },
                {
                    "id": "cta-copy", "type": "TEXT", "name": "Body",
                    "characters": "Give your child the gift of music.",
                    "absoluteBoundingBox": {"x": 120, "y": 800, "width": 600, "height": 40},
                },
            ],
        },
    ])

    document = analyze_figma_document(
        source,
        file_key="blog-orphan-action",
        image_fill_urls={
            "post-a": "https://signed.invalid/post-a.png",
            "post-b": "https://signed.invalid/post-b.png",
        },
        captured_at=CAPTURED_AT,
    )

    sections = document.pages[0].sections
    assert [section.semantic_role for section in sections] == [
        "blog_cards", "call_to_action",
    ]
    blog = sections[0]
    assert len(blog.groups) == 1
    assert blog.groups[0].kind == RepeatGroupKind.BLOG_POST
    assert len(blog.groups[0].items) == 2
    assert all(
        {"media", "title", "body"}.issubset(item.fields)
        for item in blog.groups[0].items
    )
    load_more = next(element for element in blog.content if element.value == "Load more")
    assert load_more.kind == ContentKind.BUTTON
    assert load_more.role == "primary_action"
    assert load_more.group_id is None
    assert all(element.value != "Load more" for element in sections[1].content)


def test_long_join_headline_with_side_media_is_a_split_cta_not_a_button():
    source = _minimal_file([{
        "id": "join-cta", "type": "GROUP", "name": "Join CTA",
        "absoluteBoundingBox": {"x": 40, "y": 100, "width": 920, "height": 420},
        "children": [
            {
                "id": "join-title", "type": "TEXT", "name": "Heading",
                "characters": "Join us at Keys to Success Music Studio",
                "style": {"fontSize": 40},
                "absoluteBoundingBox": {"x": 80, "y": 150, "width": 500, "height": 80},
            },
            {
                "id": "join-subtitle", "type": "TEXT", "name": "Subtitle",
                "characters": "and give your child the gift of music.",
                "style": {"fontSize": 25},
                "absoluteBoundingBox": {"x": 80, "y": 240, "width": 500, "height": 40},
            },
            {
                "id": "join-body", "type": "TEXT", "name": "Body",
                "characters": "Our mobile studio brings music classes to your community.",
                "style": {"fontSize": 18},
                "absoluteBoundingBox": {"x": 80, "y": 300, "width": 500, "height": 60},
            },
            {
                "id": "join-image", "type": "RECTANGLE", "name": "Student illustration",
                "absoluteBoundingBox": {"x": 650, "y": 130, "width": 240, "height": 340},
                "fills": [{"type": "IMAGE", "imageRef": "join-ref"}],
            },
        ],
    }])

    document = analyze_figma_document(
        source,
        file_key="split-cta",
        image_fill_urls={"join-ref": "https://signed.invalid/join.png"},
        captured_at=CAPTURED_AT,
    )

    section = document.pages[0].sections[0]
    assert section.semantic_role == "call_to_action"
    assert section.layout.kind == LayoutKind.SPLIT
    assert section.layout.columns == 2
    title = next(element for element in section.content if element.role == "section_title")
    assert title.value == "Join us at Keys to Success Music Studio"
    assert not any(element.kind == ContentKind.BUTTON for element in section.content)
    assert {element.role for element in section.content}.issuperset({"subtitle", "body", "section_media"})


def test_typography_preserves_roles_and_multiple_families_with_actionable_warnings():
    source, _ = _case("figma-auto-layout-saas")
    styled = deepcopy(source)
    text_nodes = [node for node in _walk(styled["document"]) if node.get("type") == "TEXT"]
    for index, node in enumerate(text_nodes):
        node["style"] = {
            "fontFamily": "Display Serif" if index == 0 else "Interface Sans",
            "fontSize": 56 if index == 0 else (16 if "Body" in node.get("name", "") else 18),
            "fontWeight": 700 if index == 0 else 400,
            "lineHeightPx": 64 if index == 0 else 24,
        }
    document = analyze_figma_document(styled, file_key="fonts", captured_at=CAPTURED_AT)
    assert {token.font_family for token in document.tokens.typography} == {"Display Serif", "Interface Sans"}
    assert {token.role for token in document.tokens.typography}.issuperset({"display", "body", "button"})
    font_warnings = [warning for warning in document.warnings if warning.code == "FIGMA_FONT_SOURCE_UNRESOLVED"]
    assert {"Display Serif", "Interface Sans"} == {
        warning.message.split("'")[1] for warning in font_warnings
    }


def test_desktop_only_infers_mobile_while_paired_frames_are_observed():
    source, _ = _case("figma-auto-layout-saas")
    desktop_only = analyze_figma_document(source, file_key="desktop", captured_at=CAPTURED_AT)
    assert desktop_only.pages[0].breakpoints == [BreakpointName.DESKTOP]
    assert all(section.responsive[0].status == EvidenceStatus.INFERRED for section in desktop_only.pages[0].sections)
    assert "FIGMA_MOBILE_FRAME_MISSING" in {warning.code for warning in desktop_only.warnings}

    paired = _paired_file()
    responsive = analyze_figma_document(paired, file_key="paired", captured_at=CAPTURED_AT)
    assert responsive.pages[0].breakpoints == [BreakpointName.DESKTOP, BreakpointName.MOBILE]
    assert "FIGMA_MOBILE_FRAME_MISSING" not in {warning.code for warning in responsive.warnings}
    assert all(section.responsive for section in responsive.pages[0].sections)
    assert all(section.responsive[0].status == EvidenceStatus.OBSERVED for section in responsive.pages[0].sections)
    assert responsive.pages[0].sections[0].responsive[0].layout_changes["direction"] == {"from": "row", "to": "column"}


def test_ambiguous_responsive_pairing_records_alternatives_and_warning():
    source = _paired_file()
    mobile = source["document"]["children"][0]["children"][1]
    duplicate = deepcopy(mobile["children"][0])
    duplicate["id"] = "12:1"
    duplicate["name"] = "Capabilities"
    for child in duplicate["children"]:
        child["id"] = "12:" + child["id"].split(":")[-1]
    mobile["children"].insert(1, duplicate)
    document = analyze_figma_document(source, file_key="ambiguous", captured_at=CAPTURED_AT)
    pairing = document.pages[0].sections[0].metadata["responsive_pairing"]["mobile"]
    assert pairing["alternatives"]
    assert "FIGMA_RESPONSIVE_PAIR_AMBIGUOUS" in {warning.code for warning in document.warnings}


def test_invalid_payload_and_missing_requested_frame_are_actionable():
    with pytest.raises(FigmaAdapterError, match="document or nodes tree"):
        analyze_figma_document({}, file_key="bad", captured_at=CAPTURED_AT)
    source = _minimal_file([])
    with pytest.raises(FigmaAdapterError, match="was not found"):
        analyze_figma_document(source, file_key="bad", node_id="999:1", captured_at=CAPTURED_AT)


def _minimal_file(sections: list[dict]) -> dict:
    return {
        "name": "Synthetic Test",
        "document": {"id": "0:0", "type": "DOCUMENT", "children": [{
            "id": "1:0", "type": "CANVAS", "name": "Pages", "children": [{
                "id": "1:1", "type": "FRAME", "name": "Home Desktop",
                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1000, "height": 1600},
                "children": sections,
            }],
        }]},
    }


def _instance(node_id: str, name: str, component_id: str, x: int, title: str, y: int = 40) -> dict:
    return {
        "id": node_id, "type": "INSTANCE", "name": name, "componentId": component_id,
        "componentProperties": {"Title": {"type": "TEXT", "value": title}},
        "absoluteBoundingBox": {"x": x, "y": y, "width": 240, "height": 300},
        "children": [{"id": f"{node_id}-text", "type": "TEXT", "name": "Title", "characters": title}],
    }


def _paired_file() -> dict:
    def section(node_id: str, name: str, text: str, mode: str) -> dict:
        return {"id": node_id, "type": "FRAME", "name": name, "layoutMode": mode, "children": [
            {"id": f"{node_id}-text", "type": "TEXT", "name": "Heading", "characters": text},
            {"id": f"{node_id}-body", "type": "TEXT", "name": "Body", "characters": "Shared supporting copy"},
        ]}

    return {
        "name": "Responsive Test", "document": {"id": "0:0", "type": "DOCUMENT", "children": [{
            "id": "1:0", "type": "CANVAS", "name": "Pages", "children": [
                {"id": "2:1", "type": "FRAME", "name": "Home Desktop", "layoutMode": "VERTICAL", "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1440, "height": 1200}, "children": [
                    section("10:1", "Feature cards", "Shared feature title", "HORIZONTAL"),
                    section("20:1", "Final CTA", "Shared CTA title", "HORIZONTAL"),
                ]},
                {"id": "2:2", "type": "FRAME", "name": "Home Mobile", "layoutMode": "VERTICAL", "absoluteBoundingBox": {"x": 0, "y": 0, "width": 390, "height": 1200}, "children": [
                    section("11:1", "Benefits", "Shared feature title", "VERTICAL"),
                    section("21:1", "Action", "Shared CTA title", "VERTICAL"),
                ]},
            ],
        }]},
    }


def _walk(node: dict):
    yield node
    for child in node.get("children", []):
        yield from _walk(child)
