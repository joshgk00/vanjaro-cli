"""Boundary coverage for element-owned conditional styles and malformed
``element_styles`` metadata.

Two independently reproduced defects motivate this file:

1. An element's own conditional ``StyleObservation`` (a real source
   ``condition``) could still resolve to an unscoped theme/platform-utility/
   template-modifier/agency-utility class, because ``translate_style_set``
   always calls the shared translator with ``breakpoint=None`` -- the layer
   functions never looked at the *observation's own* ``condition`` at all.
   ``design/style_translation.py::_translate_observations`` now gates every
   one of those layers on ``observation.condition`` instead, so this covers
   each configured layer, not only the one text-align scenario the root
   artifact test proves.
2. ``apply_element_styles`` treated an explicit ``element_styles: null`` the
   same as the field being entirely absent. Absence and an explicit empty
   list remain valid legacy/no-op shapes; every other explicit malformed
   value must reject at composition with an actionable
   ``BlockLibraryError``.

Every scenario runs through the real production functions ownership itself
depends on (``translate_element_styles``, ``emit_element_style_payload``,
``apply_element_styles``, ``apply_overrides_with_owners``, or the full
``plan_design_document`` -> ``emit_library_plan`` -> ``compose_project_library``
-> ``compose_project_pages`` pipeline), never assertions against
intermediate models alone.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from vanjaro_cli.design.composition import SemanticBinding
from vanjaro_cli.design.element_style_transport import (
    apply_element_styles,
    emit_element_style_payload,
    translate_element_styles,
)
from vanjaro_cli.design.models import (
    ConditionBound,
    ContentElement,
    ContentKind,
    ResponsiveCondition,
    ResponsiveConditionKind,
    ResponsiveConditionStatus,
    StyleObservation,
    StyleProperty,
    StyleSet,
)
from vanjaro_cli.design.planner import emit_library_plan, plan_design_document
from vanjaro_cli.design.style_translation import StyleTranslationConfig
from vanjaro_cli.portal.block_library import BlockLibraryError, compose_project_library
from vanjaro_cli.portal.page_composition import compose_project_pages
from vanjaro_cli.utils.block_compose import apply_overrides_with_owners

from tests.test_design_planner import CATALOG, _document, _entry, _feature_section

FEATURE_CARDS_ENTRY = _entry("feature-cards-3up.json")


def _observed_condition(threshold_px: int) -> ResponsiveCondition:
    return ResponsiveCondition(
        bounds=[ConditionBound(kind=ResponsiveConditionKind.MAX_WIDTH, threshold_px=threshold_px)],
        status=ResponsiveConditionStatus.OBSERVED,
        rule_order=0,
    )


def _element(property_name: StyleProperty, value: str, *, condition: ResponsiveCondition | None = None) -> ContentElement:
    return ContentElement(
        id="el-1",
        kind=ContentKind.TEXT,
        role="card_body",
        value="Body",
        order=0,
        provenance=[],
        confidence=1.0,
        style=StyleSet(observations=[StyleObservation(property=property_name, value=value, condition=condition)]),
    )


def _simple_template(component: dict) -> dict:
    return {
        "name": "Element Style Boundary Test",
        "category": "test",
        "template": {
            "type": "section",
            "attributes": {"id": "sec"},
            "components": [component],
        },
    }


# --------------------------------------------------------------------------
# Conditional platform mapping, through the real production pipeline: a
# conditional child alignment on a repeated card title (not just the one
# section-heading scenario the root artifact test proves) must never turn
# into an unconditional utility class.
# --------------------------------------------------------------------------


def test_conditional_child_element_binds_scoped_rule_to_its_own_owner() -> None:
    section = _feature_section()
    title = next(item for item in section.content if item.role == "card_title")
    styled = title.model_copy(
        update={
            "style": StyleSet(
                observations=[
                    StyleObservation(
                        property=StyleProperty.TEXT_ALIGN,
                        value="right",
                        condition=_observed_condition(480),
                    )
                ]
            )
        }
    )
    section = section.model_copy(
        update={"content": [styled if item.id == title.id else item for item in section.content]}
    )
    document = _document(section)
    plan = plan_design_document(document, catalog=CATALOG)
    library = compose_project_library(emit_library_plan(plan))
    page = compose_project_pages(
        document, library, {"entries": []}, project_id="conditional-card-title", isolated=True
    )[0]

    soup = BeautifulSoup(page["content_html"], "html.parser")
    heading = next(
        node
        for node in soup.find_all(["h1", "h2", "h3", "h4"])
        if node.get_text(" ", strip=True) == "Service 1"
    )
    assert "text-end" not in heading.get("class", []), "conditional alignment leaked as an unconditional class"

    rules = [rule for rule in page["styles"] if rule.get("style", {}).get("text-align") == "right"]
    assert rules, "the supported conditional alignment was dropped instead of transported"
    assert all(rule.get("mediaText") == "(max-width: 480px)" for rule in rules), rules

    # And a sibling card title (untouched) must be unaffected -- no stray
    # text-align rule and no text-end class picked up from the conditional one.
    other_heading = next(
        node
        for node in soup.find_all(["h1", "h2", "h3", "h4"])
        if node.get_text(" ", strip=True) == "Service 2"
    )
    assert "text-end" not in other_heading.get("class", [])


# --------------------------------------------------------------------------
# Conditional platform mapping, at the transport layer directly: a property
# other than text-align, proving the fix is not special-cased to one
# property/utility pair.
# --------------------------------------------------------------------------


def test_conditional_display_utility_stays_scoped_not_applied_as_platform_class() -> None:
    element = _element(StyleProperty.DISPLAY, "none", condition=_observed_condition(480))
    binding = SemanticBinding(semantic_field="item.body", slot="text_1", source_element_ids=("el-1",), value="Body")

    actions, _warnings = translate_element_styles(
        [element], [binding], FEATURE_CARDS_ENTRY.capabilities, StyleTranslationConfig(),
        css_scope=".proj .sec",
    )
    assert len(actions) == 1
    assert any(key.startswith("cond-max480:") and key.endswith("display") for key in actions[0].scoped_css)
    assert not any(decision.layer.value == "platform_utility" for decision in actions[0].style_decisions)

    payload = emit_element_style_payload(actions)
    template = _simple_template({"type": "text", "content": "Body", "attributes": {"id": "t1"}})
    rendered, owners = apply_overrides_with_owners(template, {"text_1": "Body"})
    apply_element_styles(rendered, owners, payload, library_key="k")

    classes = [entry["name"] for entry in owners["text_1"].get("classes", [])]
    assert "d-none" not in classes
    rule = rendered["styles"][0]
    assert rule.get("mediaText") == "(max-width: 480px)"
    assert rule["style"]["display"] == "none"


# --------------------------------------------------------------------------
# Conditional configured agency mapping.
# --------------------------------------------------------------------------


def test_conditional_agency_utility_stays_scoped_not_applied_unconditionally() -> None:
    config = StyleTranslationConfig(agency_utilities={"border_radius:24px": "agency-rounded"})
    element = _element(StyleProperty.BORDER_RADIUS, "24px", condition=_observed_condition(480))
    binding = SemanticBinding(semantic_field="item.body", slot="text_1", source_element_ids=("el-1",), value="Body")

    actions, _warnings = translate_element_styles(
        [element], [binding], FEATURE_CARDS_ENTRY.capabilities, config, css_scope=".proj .sec",
    )
    assert len(actions) == 1
    assert any(key.startswith("cond-max480:") and key.endswith("border-radius") for key in actions[0].scoped_css)
    assert not any(decision.layer.value == "agency_utility" for decision in actions[0].style_decisions)

    payload = emit_element_style_payload(actions, agency_utilities=config.agency_utilities)
    template = _simple_template({"type": "text", "content": "Body", "attributes": {"id": "t1"}})
    rendered, owners = apply_overrides_with_owners(template, {"text_1": "Body"})
    apply_element_styles(rendered, owners, payload, library_key="k", agency_utilities=config.agency_utilities)

    classes = [entry["name"] for entry in owners["text_1"].get("classes", [])]
    assert "agency-rounded" not in classes
    rule = rendered["styles"][0]
    assert rule.get("mediaText") == "(max-width: 480px)"
    assert rule["style"]["border-radius"] == "24px"


# --------------------------------------------------------------------------
# Conditional theme candidate.
# --------------------------------------------------------------------------


def test_conditional_theme_candidate_stays_scoped_not_applied_as_theme_class() -> None:
    config = StyleTranslationConfig(palette={"primary": "#ff0000"})
    element = _element(StyleProperty.BACKGROUND_COLOR, "#ff0101", condition=_observed_condition(480))
    binding = SemanticBinding(semantic_field="item.body", slot="text_1", source_element_ids=("el-1",), value="Body")

    actions, _warnings = translate_element_styles(
        [element], [binding], FEATURE_CARDS_ENTRY.capabilities, config, css_scope=".proj .sec",
    )
    assert len(actions) == 1
    assert any(key.startswith("cond-max480:") and key.endswith("background-color") for key in actions[0].scoped_css)
    assert not any(decision.layer.value == "theme" for decision in actions[0].style_decisions)

    payload = emit_element_style_payload(actions)
    template = _simple_template({"type": "text", "content": "Body", "attributes": {"id": "t1"}})
    rendered, owners = apply_overrides_with_owners(template, {"text_1": "Body"})
    apply_element_styles(rendered, owners, payload, library_key="k")

    classes = [entry["name"] for entry in owners["text_1"].get("classes", [])]
    assert "bg-primary" not in classes
    rule = rendered["styles"][0]
    assert rule.get("mediaText") == "(max-width: 480px)"
    assert rule["style"]["background-color"] == "#ff0101"


# --------------------------------------------------------------------------
# Unresolved condition disclosure: gathered evidence, unproven attribution,
# and no breakpoint context to fall back to (the element-style path always
# translates with breakpoint=None) must stay an explicit diagnostic -- never
# an unconditioned rule.
# --------------------------------------------------------------------------


def test_unresolved_condition_without_breakpoint_becomes_manual_diagnostic() -> None:
    condition = ResponsiveCondition(
        bounds=[],
        status=ResponsiveConditionStatus.UNRESOLVED,
        rule_order=0,
        reason="an unsupported media/container expression may win the cascade",
    )
    element = _element(StyleProperty.TEXT_ALIGN, "right", condition=condition)
    binding = SemanticBinding(semantic_field="item.body", slot="text_1", source_element_ids=("el-1",), value="Body")

    actions, warnings = translate_element_styles(
        [element], [binding], FEATURE_CARDS_ENTRY.capabilities, StyleTranslationConfig(),
        css_scope=".proj .sec",
    )

    assert actions == ()
    assert any("manual review" in warning and "el-1" in warning for warning in warnings)

    # Nothing to apply: confirm the null result rather than an invented rule.
    payload = emit_element_style_payload(actions)
    assert payload == []


# --------------------------------------------------------------------------
# Unchanged base native utility: an unconditioned sibling observation keeps
# resolving to its native utility class exactly as before, and the
# conditional fix stays scoped to the element that actually carries a
# condition -- no global change to an unrelated element.
# --------------------------------------------------------------------------


def test_unconditioned_sibling_keeps_native_utility_class_untouched() -> None:
    conditional = _element(StyleProperty.TEXT_ALIGN, "right", condition=_observed_condition(480))
    unconditioned = ContentElement(
        id="el-2",
        kind=ContentKind.TEXT,
        role="card_body",
        value="Other",
        order=1,
        provenance=[],
        confidence=1.0,
        style=StyleSet(observations=[StyleObservation(property=StyleProperty.TEXT_ALIGN, value="center")]),
    )
    bindings = [
        SemanticBinding(semantic_field="item.body", slot="text_1", source_element_ids=("el-1",), value="Body"),
        SemanticBinding(semantic_field="item.body", slot="text_2", source_element_ids=("el-2",), value="Other"),
    ]

    actions, _warnings = translate_element_styles(
        [conditional, unconditioned], bindings, FEATURE_CARDS_ENTRY.capabilities, StyleTranslationConfig(),
        css_scope=".proj .sec",
    )
    by_source = {action.source_element_id: action for action in actions}
    assert by_source["el-1"].scoped_css
    assert not any(decision.layer.value == "platform_utility" for decision in by_source["el-1"].style_decisions)
    assert not by_source["el-2"].scoped_css
    assert any(
        decision.layer.value == "platform_utility" and decision.target == "text-center"
        for decision in by_source["el-2"].style_decisions
    )

    payload = emit_element_style_payload(actions)
    template = _simple_template(
        {
            "type": "default",
            "components": [
                {"type": "text", "content": "Body", "attributes": {"id": "t1"}},
                {"type": "text", "content": "Other", "attributes": {"id": "t2"}},
            ],
        }
    )
    rendered, owners = apply_overrides_with_owners(template, {"text_1": "Body", "text_2": "Other"})
    apply_element_styles(rendered, owners, payload, library_key="k")

    assert "text-end" not in [entry["name"] for entry in owners["text_1"].get("classes", [])]
    assert "text-center" in [entry["name"] for entry in owners["text_2"].get("classes", [])]
    assert len(rendered["styles"]) == 1
    assert rendered["styles"][0]["style"]["text-align"] == "right"


# --------------------------------------------------------------------------
# Absence and empty-list compatibility.
# --------------------------------------------------------------------------


def test_absent_and_empty_list_element_styles_remain_valid_noop() -> None:
    document = _document(_feature_section())
    plan = emit_library_plan(plan_design_document(document, catalog=CATALOG))
    assert len(plan) == 1
    assert "element_styles" not in plan[0]

    composed_absent = compose_project_library(plan)
    assert composed_absent

    with_empty_list = [dict(plan[0])]
    with_empty_list[0]["element_styles"] = []
    composed_empty = compose_project_library(with_empty_list)
    assert composed_empty[0]["content_json"] == composed_absent[0]["content_json"]
    assert composed_empty[0]["style_json"] == composed_absent[0]["style_json"]


# --------------------------------------------------------------------------
# Malformed metadata: an explicit non-list value is never coerced, always an
# actionable rejection at composition.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("malformed", [None, False, 0, "", "oops", {}, {"slot": "text_1"}, 5, [{"bad": "shape"}]])
def test_malformed_element_styles_rejected_at_composition(malformed) -> None:
    document = _document(_feature_section())
    plan = emit_library_plan(plan_design_document(document, catalog=CATALOG))
    assert len(plan) == 1
    plan[0]["element_styles"] = malformed

    with pytest.raises(BlockLibraryError, match="element.styles|element_styles"):
        compose_project_library(plan)
