"""A Figma section's designed height reaches the built block.

A Figma page frame is a fixed-size drawing, but the adapter kept each
section's box only on provenance. Nothing downstream read it, so a template
built at whatever height its content needed: a 664px hero came out 152px and
a 131px navigation bar came out 53px. The adapter now records the drawn height
as a minimum height; the planner carries it as scoped CSS, the library composer
emits it on the block root, and the header composer emits it on the header.

Every test goes through the real adapter, planner, and composers on a trimmed
Figma payload.
"""

from __future__ import annotations

import json

import pytest

from vanjaro_cli.design.figma_adapter import analyze_figma_document
from vanjaro_cli.design.global_plan import split_global_sections
from vanjaro_cli.design.models import (
    BreakpointName,
    ContentElement,
    ContentKind,
    EvidenceStatus,
    LayoutKind,
    LayoutObservation,
    Section,
    StyleObservation,
    StyleProperty,
    StyleSet,
)
from vanjaro_cli.design.planner import emit_library_plan, plan_design_document
from vanjaro_cli.design.style_translation import TranslationLayer
from vanjaro_cli.portal.block_library import compose_project_library
from vanjaro_cli.portal.global_blocks import compose_project_global_blocks
from vanjaro_cli.portal.global_header_matching import compose_header_block


def _box(x: float, y: float, width: float, height: float) -> dict:
    return {"x": x, "y": y, "width": width, "height": height}


def _text(node_id: str, characters: str, bounds: dict) -> dict:
    return {
        "id": node_id, "type": "TEXT", "name": characters, "characters": characters,
        "absoluteBoundingBox": bounds,
        "style": {"fontFamily": "Inter", "fontSize": 40, "fontWeight": 700},
    }


def _band(node_id: str, name: str, bounds: dict, *texts: tuple[str, str, dict]) -> dict:
    return {
        "id": node_id, "type": "FRAME", "name": name, "absoluteBoundingBox": bounds,
        "children": [_text(*text) for text in texts],
    }


def _page(name: str, width: int, height: int, *bands: dict) -> dict:
    return {
        "id": f"page:{name}", "type": "FRAME", "name": name,
        "absoluteBoundingBox": _box(0, 0, width, height), "children": list(bands),
    }


def _payload(*pages: dict) -> dict:
    return {
        "name": "Section Height Fixture",
        "document": {
            "id": "0:0", "type": "DOCUMENT",
            "children": [{"id": "1:0", "type": "CANVAS", "name": "Canvas", "children": list(pages)}],
        },
    }


def _desktop_payload() -> dict:
    return _payload(
        _page(
            "Home Desktop", 1440, 1327,
            _band("10:1", "Navigation", _box(0, 0, 1440, 131), ("10:2", "Home", _box(40, 40, 60, 20))),
            _band(
                "11:1", "Hero", _box(0, 131, 1440, 664),
                ("11:2", "Music for everyone", _box(300, 400, 800, 60)),
            ),
            _band(
                "12:1", "Footer", _box(0, 795, 1440, 532),
                ("12:2", "All rights reserved", _box(40, 900, 300, 20)),
            ),
        )
    )


def _analyze(payload: dict | None = None):
    return analyze_figma_document(payload or _desktop_payload(), file_key="height-fixture")


def _section(document, role: str):
    return next(s for s in document.pages[0].sections if s.semantic_role == role)


def _minimum_heights(style: StyleSet) -> list[StyleObservation]:
    return [item for item in style.observations if item.property is StyleProperty.MIN_HEIGHT]


# -- the adapter records the drawn height --


def test_a_designed_frame_records_its_height_as_a_minimum_height():
    document = _analyze()

    hero = _minimum_heights(_section(document, "hero").style)
    navigation = _minimum_heights(_section(document, "navigation").style)

    assert [item.value for item in hero] == ["664px"]
    assert [item.value for item in navigation] == ["131px"]
    assert hero[0].status is EvidenceStatus.OBSERVED
    assert hero[0].condition is None
    assert hero[0].provenance[0].element_node_id == "11:1"
    assert hero[0].provenance[0].viewport is BreakpointName.DESKTOP


def test_a_fractional_frame_height_rounds_to_whole_pixels():
    payload = _desktop_payload()
    payload["document"]["children"][0]["children"][0]["children"][1]["absoluteBoundingBox"]["height"] = 652.63

    hero = _section(_analyze(payload), "hero")

    assert [item.value for item in _minimum_heights(hero.style)] == ["653px"]


@pytest.mark.parametrize("height", [0, 0.4])
def test_a_frame_with_no_usable_height_records_no_minimum(height):
    payload = _desktop_payload()
    payload["document"]["children"][0]["children"][0]["children"][1]["absoluteBoundingBox"]["height"] = height

    hero = _section(_analyze(payload), "hero")

    assert hero.style.observations == []


def test_a_frame_with_no_box_records_no_minimum():
    payload = _desktop_payload()
    del payload["document"]["children"][0]["children"][0]["children"][1]["absoluteBoundingBox"]

    hero = _section(_analyze(payload), "hero")

    assert hero.style.observations == []


def test_a_height_taken_from_a_guessed_section_boundary_is_marked_inferred():
    flat = _page(
        "Home Desktop", 1440, 1500,
        _text("20:1", "Welcome to the studio", _box(100, 20, 600, 50)),
        _text("20:2", "Learn more", _box(100, 100, 200, 30)),
        _text("20:3", "Join now", _box(100, 160, 200, 30)),
        _text("20:4", "Register now", _box(100, 220, 200, 30)),
        _text("20:5", "Latest news", _box(100, 1200, 600, 50)),
        _text("20:6", "Read more about it", _box(100, 1260, 400, 30)),
    )

    sections = _analyze(_payload(flat)).pages[0].sections
    inferred = [
        item
        for section in sections
        for item in _minimum_heights(section.style)
        if item.status is EvidenceStatus.INFERRED
    ]

    assert inferred, "a flat frame is cut into guessed sections"
    assert {item.confidence for item in inferred} == {0.78}
    assert all(item.provenance[0].method.value == "inferred" for item in inferred)


def test_a_designed_mobile_frame_supplies_that_breakpoints_own_height():
    payload = _payload(
        _page(
            "Home Desktop", 1440, 795,
            _band(
                "11:1", "Hero", _box(0, 0, 1440, 664),
                ("11:2", "Music for everyone", _box(300, 300, 800, 60)),
            ),
        ),
        _page(
            "Home Mobile", 390, 420,
            _band(
                "31:1", "Hero", _box(0, 0, 390, 420),
                ("31:2", "Music for everyone", _box(20, 150, 340, 60)),
            ),
        ),
    )

    hero = _section(_analyze(payload), "hero")
    mobile = next(item for item in hero.responsive if item.breakpoint is BreakpointName.MOBILE)

    assert [item.value for item in _minimum_heights(hero.style)] == ["664px"]
    assert [item.value for item in _minimum_heights(mobile.style)] == ["420px"]
    assert mobile.status is EvidenceStatus.OBSERVED


# -- the planner and library composer carry it to the block root --


def _planned_body():
    document = _analyze()
    body, global_plan, _ = split_global_sections(document)
    return document, body, global_plan, plan_design_document(body)


def _hero_entry(plan):
    return next(entry for entry in plan.entries if entry.source_section_id.endswith("hero"))


def test_the_plan_carries_the_hero_height_as_a_scoped_minimum_height():
    _, _, _, plan = _planned_body()

    entry = _hero_entry(plan)

    assert dict(entry.scoped_css) == {"min-height": "664px"}
    assert entry.css_scope
    decision = next(item for item in entry.style_decisions if item.property is StyleProperty.MIN_HEIGHT)
    assert decision.layer is TranslationLayer.SCOPED_CSS
    assert decision.target == "min-height:664px"


def test_the_library_plan_and_block_root_state_the_height():
    _, _, _, plan = _planned_body()

    library_plan = emit_library_plan(plan)
    hero_plan = next(item for item in library_plan if item["key"].endswith("hero"))
    composed = compose_project_library(json.loads(json.dumps(library_plan)))
    hero = next(item for item in composed if item["key"].endswith("hero"))
    root = hero["content_json"][0]
    root_id = root["attributes"]["id"]

    assert hero_plan["style_declarations"] == {"min-height": "664px"}
    assert [(rule["selectors"][0]["name"], rule["style"]) for rule in hero["style_json"]] == [
        (root_id, {"min-height": "664px"})
    ]


def test_a_section_without_a_height_gets_no_minimum_height_rule():
    _, body, _, _ = _planned_body()
    stripped = body.model_copy(
        update={
            "pages": [
                page.model_copy(
                    update={
                        "sections": [
                            section.model_copy(update={"style": StyleSet()})
                            for section in page.sections
                        ]
                    }
                )
                for page in body.pages
            ]
        }
    )

    plan = plan_design_document(stripped)

    assert all(dict(entry.scoped_css) == {} for entry in plan.entries)
    assert all(entry.css_scope is None for entry in plan.entries)


def test_an_unsafe_height_value_is_not_turned_into_css():
    _, body, _, _ = _planned_body()
    hostile = StyleSet(
        observations=[
            StyleObservation(property=StyleProperty.MIN_HEIGHT, value="664px; background:url(x)")
        ]
    )
    tampered = body.model_copy(
        update={
            "pages": [
                body.pages[0].model_copy(
                    update={
                        "sections": [
                            section.model_copy(update={"style": hostile})
                            for section in body.pages[0].sections
                        ]
                    }
                )
            ]
        }
    )

    plan = plan_design_document(tampered)

    assert all(dict(entry.scoped_css) == {} for entry in plan.entries)
    assert any(
        decision.layer is TranslationLayer.MANUAL
        for entry in plan.entries
        for decision in entry.style_decisions
    )


# -- the header composer states it too --


def _header_section(*observations: StyleObservation) -> Section:
    return Section(
        id="home.header",
        order=0,
        semantic_role="navigation",
        role_confidence=1,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.FLEX, contained=True),
        content=[
            ContentElement(
                id="nav-1", order=1, kind=ContentKind.LINK, role="navigation_item",
                value="Work", attributes={"href": "/work"}, provenance=[], confidence=1,
            )
        ],
        groups=[],
        style=StyleSet(observations=list(observations)),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )


def _minimum(value: object) -> StyleObservation:
    return StyleObservation(property=StyleProperty.MIN_HEIGHT, value=value)


def test_a_header_with_a_designed_height_carries_it_on_its_root():
    built = compose_header_block(_header_section(_minimum("131px")), {}, brand_text="Northstar")

    root_id = built["components"][0]["attributes"]["id"]

    assert [(rule["selectors"][0]["name"], rule["style"]) for rule in built["styles"]] == [
        (root_id, {"min-height": "131px"})
    ]


def test_a_header_with_no_designed_height_gets_no_rule():
    built = compose_header_block(_header_section(), {}, brand_text="Northstar")

    assert built["styles"] == []


@pytest.mark.parametrize("value", ["auto", "0px", "0", "50%", "131px; color:red", 131, None])
def test_a_header_ignores_a_minimum_that_is_not_a_positive_pixel_length(value):
    built = compose_header_block(_header_section(_minimum(value)), {}, brand_text="Northstar")

    assert built["styles"] == []


def test_a_global_header_keeps_its_height_rule_aimed_at_the_namespaced_root():
    document = _analyze()
    body, global_plan, _ = split_global_sections(document)
    entries = [
        {**entry, "name": f"project / Site {entry['kind'].title()}", "category": "Agency - project"}
        for entry in global_plan["entries"]
    ]

    desired = compose_project_global_blocks(
        document, {**global_plan, "entries": entries}, project_id="height-fixture"
    )
    header = next(item for item in desired if item["kind"] == "header")
    footer = next(item for item in desired if item["kind"] == "footer")

    root_id = header["components"][0]["attributes"]["id"]
    assert [(rule["selectors"][0]["name"], rule["style"]) for rule in header["styles"]] == [
        (root_id, {"min-height": "131px"})
    ]
    assert footer["styles"] == []
