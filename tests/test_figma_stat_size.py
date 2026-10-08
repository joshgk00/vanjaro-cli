"""A Figma stat figure keeps the size it was drawn at (RT-35).

The adapter kept each text's font size only as an attribute, so a 100px "80+"
came out at the template heading's 32px. The adapter now records the size of a
stat figure as a style observation, the planner binds it to that figure's own
heading slot, and an overlay-added figure (outlined vector text) copies the
size its siblings agree on.

Adapter, planner, and composer tests run on a trimmed Figma payload.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from vanjaro_cli.design.figma_adapter import analyze_figma_document
from vanjaro_cli.design.global_plan import split_global_sections
from vanjaro_cli.design.models import (
    ContentElement,
    ContentKind,
    EvidenceStatus,
    ObservationMethod,
    RepeatGroup,
    RepeatGroupItem,
    RepeatGroupKind,
    StyleObservation,
    StyleProperty,
    StyleSet,
)
from vanjaro_cli.design.overlays import (
    DesignOverlay,
    DesignOverlaySet,
    OverlayOperation,
    apply_design_overlays,
)
from vanjaro_cli.design.planner import emit_library_plan, plan_design_document
from vanjaro_cli.design.sources import HtmlSourceRequest, analyze_source
from vanjaro_cli.portal.block_library import compose_project_library


def _box(x: float, y: float, width: float, height: float) -> dict:
    return {"x": x, "y": y, "width": width, "height": height}


def _text(node_id: str, characters: str, bounds: dict, size: object) -> dict:
    return {
        "id": node_id, "type": "TEXT", "name": characters, "characters": characters,
        "absoluteBoundingBox": bounds,
        "style": {"fontFamily": "Genova", "fontSize": size, "fontWeight": 900},
    }


def _payload(figure_size: object = 100) -> dict:
    hero = {
        "id": "11:1", "type": "FRAME", "name": "Hero", "absoluteBoundingBox": _box(0, 0, 1440, 500),
        "children": [_text("11:2", "Music for everyone", _box(300, 200, 800, 60), 56)],
    }
    stats = {
        "id": "12:1", "type": "FRAME", "name": "Stats", "absoluteBoundingBox": _box(0, 500, 1440, 265),
        "children": [
            _text("12:2", "10", _box(70, 560, 150, 140), figure_size),
            _text("12:3", "Professional Instructors", _box(70, 700, 200, 40), 30),
            _text("12:4", "50+", _box(560, 560, 150, 140), figure_size),
            _text("12:5", "Happy Students", _box(560, 700, 200, 40), 30),
            _text("12:6", "80+", _box(1040, 560, 230, 140), figure_size),
            _text("12:7", "Combined Years of Experience", _box(1040, 700, 300, 40), 30),
        ],
    }
    page = {
        "id": "page:home", "type": "FRAME", "name": "Home Desktop",
        "absoluteBoundingBox": _box(0, 0, 1440, 1000), "children": [hero, stats],
    }
    return {
        "name": "Stat Size Fixture",
        "document": {
            "id": "0:0", "type": "DOCUMENT",
            "children": [{"id": "1:0", "type": "CANVAS", "name": "Canvas", "children": [page]}],
        },
    }


def _analyze(figure_size: object = 100):
    return analyze_figma_document(_payload(figure_size), file_key="stat-size-fixture")


def _section(document, role: str):
    return next(section for section in document.pages[0].sections if section.semantic_role == role)


def _sizes(element: ContentElement) -> list[StyleObservation]:
    return [item for item in element.style.observations if item.property is StyleProperty.FONT_SIZE]


# -- the adapter records the drawn size of a stat figure --


def test_a_stat_figure_keeps_the_size_it_was_drawn_at():
    figures = [e for e in _section(_analyze(), "stats").content if e.role == "stat_value"]

    assert [e.value for e in figures] == ["10", "50+", "80+"]
    for figure in figures:
        (size,) = _sizes(figure)
        assert size.value == "100px"
        assert size.status is EvidenceStatus.OBSERVED
        assert size.condition is None
        assert size.provenance[0].element_node_id == figure.attributes["figma_node_id"]


def test_a_fractional_figure_size_is_kept_as_drawn():
    figure = next(e for e in _section(_analyze(40.5), "stats").content if e.role == "stat_value")

    assert [item.value for item in _sizes(figure)] == ["40.5px"]


def test_stat_labels_and_other_text_carry_no_size():
    document = _analyze()
    others = [
        element
        for section in document.pages[0].sections
        for element in section.content
        if element.role != "stat_value"
    ]

    assert others
    assert all(not element.style.observations for element in others)


@pytest.mark.parametrize("size", [None, 0, -4, True, "big"])
def test_a_figure_without_a_usable_size_carries_none(size):
    figures = [e for e in _section(_analyze(size), "stats").content if e.role == "stat_value"]

    assert figures
    assert all(not element.style.observations for element in figures)


# -- the planner and composer land it on each figure's own heading --


def _planned_stats():
    body, _, _ = split_global_sections(_analyze())
    plan = plan_design_document(body)
    return plan, next(entry for entry in plan.entries if entry.source_section_id.endswith("stats"))


def _walk(component: dict):
    yield component
    for child in component.get("components") or []:
        yield from _walk(child)


def test_the_plan_binds_each_figure_size_to_that_figures_heading_slot():
    plan, stats = _planned_stats()

    assert [(action.slot, dict(action.scoped_css)) for action in stats.element_styles] == [
        ("heading_2", {"font-size": "100px"}),
        ("heading_3", {"font-size": "100px"}),
        ("heading_4", {"font-size": "100px"}),
    ]
    hero = next(entry for entry in plan.entries if entry.source_section_id.endswith("hero"))
    assert hero.element_styles == ()


def test_the_built_block_sizes_the_three_figures_and_nothing_else():
    plan, _ = _planned_stats()
    composed = compose_project_library(json.loads(json.dumps(emit_library_plan(plan))))
    block = next(item for item in composed if item["key"].endswith("stats"))
    components = [part for root in block["content_json"] for part in _walk(root)]
    sized_ids = {
        rule["selectors"][0]["name"]
        for rule in block["style_json"]
        if rule["style"] == {"font-size": "100px"}
    }

    assert {
        part["content"] for part in components if part["attributes"].get("id") in sized_ids
    } == {"10", "50+", "80+"}
    assert [rule["style"] for rule in block["style_json"] if "font-size" not in rule["style"]] == [
        {"min-height": "265px"}
    ]


# -- an added figure copies the size its siblings agree on --


_HTML = "<html><body><main><section><h1>Results</h1></section></main></body></html>"


def _sized(element: ContentElement, size: str | None) -> ContentElement:
    observations = (
        [StyleObservation(property=StyleProperty.FONT_SIZE, value=size)] if size else []
    )
    return element.model_copy(update={"style": StyleSet(observations=observations)})


def _stat_document(*sibling_sizes: str | None):
    """A stats group with one figure per size given and one bare item to fill."""

    document = analyze_source(HtmlSourceRequest(html=_HTML, source_url="https://example.test/"))
    section = document.pages[0].sections[0]
    template = section.content[0]
    figures = [
        _sized(
            template.model_copy(
                update={"id": f"figure-{n}", "kind": ContentKind.STAT, "role": "stat_value",
                        "value": str(n), "order": n}
            ),
            size,
        )
        for n, size in enumerate(sibling_sizes)
    ]
    labels = [
        template.model_copy(update={"id": f"label-{n}", "role": "stat_label", "order": 10 + n})
        for n in range(len(figures) + 1)
    ]
    items = [
        RepeatGroupItem(
            id=f"item-{n}",
            fields={"value": figures[n].id, "label": labels[n].id} if n < len(figures)
            else {"label": labels[n].id},
            provenance=template.provenance,
        )
        for n in range(len(figures) + 1)
    ]
    group = RepeatGroup(
        id="stats-group", kind=RepeatGroupKind.STAT, items=items, provenance=section.provenance
    )
    section = section.model_copy(update={"content": [*figures, *labels], "groups": [group]})
    page = document.pages[0].model_copy(update={"sections": [section]})
    return document.model_copy(update={"pages": [page]}), items[-1].id


def _infinity_overlay(target_id: str) -> DesignOverlaySet:
    return DesignOverlaySet(
        overlays=[
            DesignOverlay(
                id="stats-infinity",
                operation=OverlayOperation.ADD_REPEAT_FIELD,
                target_id=target_id,
                field="value",
                content_kind=ContentKind.STAT,
                value="∞",
                author="curator",
                reason="Layer is outlined vector text; the render shows an infinity sign.",
                created_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
            )
        ]
    )


def _added(document) -> ContentElement:
    return next(
        element
        for element in document.pages[0].sections[0].content
        if element.metadata.get("design_overlay_id") == "stats-infinity"
    )


def test_an_added_figure_copies_the_size_its_siblings_agree_on():
    document, target = _stat_document("100px", "100px")

    added = _added(apply_design_overlays(document, _infinity_overlay(target)))

    (size,) = _sizes(added)
    assert size.value == "100px"
    assert size.status is EvidenceStatus.INFERRED
    assert size.provenance[0].method is ObservationMethod.MANUAL
    assert size.provenance[0].metadata["author"] == "curator"


def test_an_added_figure_ignores_siblings_that_list_several_elements_for_the_field():
    document, target = _stat_document("100px", "100px")
    section = document.pages[0].sections[0]
    group = section.groups[0]
    listed = [
        item.model_copy(update={"fields": {**item.fields, "value": [item.fields["value"]]}})
        if "value" in item.fields
        else item
        for item in group.items
    ]
    section = section.model_copy(update={"groups": [group.model_copy(update={"items": listed})]})
    page = document.pages[0].model_copy(update={"sections": [section]})
    document = document.model_copy(update={"pages": [page]})

    added = _added(apply_design_overlays(document, _infinity_overlay(target)))

    assert added.style.observations == []


@pytest.mark.parametrize("sibling_sizes", [("100px", "64px"), (None, None), ()])
def test_an_added_figure_copies_no_size_when_siblings_give_none_to_copy(sibling_sizes):
    document, target = _stat_document(*sibling_sizes)

    added = _added(apply_design_overlays(document, _infinity_overlay(target)))

    assert added.style.observations == []
