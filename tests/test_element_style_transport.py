"""Element-owned style translation through actual semantic binding ownership.

Covers the two root-confirmed failures (a section title losing its font-size,
a card action losing its background-color) and the ownership rules the
contract in ``docs/agency-element-style-ownership-contract.md`` requires:
never a sibling, never the section, never a stale slot after pruning. Every
scenario runs through the real production planning/composition functions
(``plan_design_document`` -> ``emit_library_plan`` -> ``compose_project_library``
-> ``compose_project_pages``), not assertions against intermediate models
alone, except where a scenario (ambiguous ownership, malformed untrusted
payloads, pruning identity) is most directly proven against the transport
functions themselves.
"""

from __future__ import annotations

import copy
import json

import pytest
from bs4 import BeautifulSoup

from vanjaro_cli.design.composition import (
    CompositionPlan,
    SemanticBinding,
    deserialize_composition_plan,
    serialize_composition_plan,
)
from vanjaro_cli.design.element_style_transport import (
    ElementStyleTransportError,
    apply_element_styles,
    emit_element_style_payload,
    translate_element_styles,
)
from vanjaro_cli.design.models import (
    Alignment,
    ConditionBound,
    ContentElement,
    ContentKind,
    LayoutKind,
    LayoutObservation,
    MediaPosition,
    RepeatGroup,
    RepeatGroupItem,
    RepeatGroupKind,
    ResponsiveCondition,
    ResponsiveConditionKind,
    ResponsiveConditionStatus,
    Section,
    StyleObservation,
    StyleProperty,
    StyleSet,
)
from vanjaro_cli.design.planner import bind_section, emit_library_plan, plan_design_document
from vanjaro_cli.design.style_translation import StyleTranslationConfig
from vanjaro_cli.portal.block_library import compose_project_library
from vanjaro_cli.portal.page_composition import compose_project_pages
from vanjaro_cli.utils.block_compose import apply_overrides_with_owners

from tests.test_design_planner import CATALOG, _document, _element, _entry, _feature_section


FEATURE_CARDS_ENTRY = _entry("feature-cards-3up.json")


def _style_rule_matches(page: dict, soup: BeautifulSoup, css_name: str, value: str) -> list:
    matches = []
    for rule in page["styles"]:
        if rule.get("style", {}).get(css_name) != value:
            continue
        for selector in rule.get("selectors", []):
            if isinstance(selector, dict):
                selector = ("#" if selector.get("type") == 2 else ".") + selector["name"]
            matches.extend(soup.select(selector))
    return matches


def _build_page(section: Section) -> dict:
    document = _document(section)
    plan = plan_design_document(document, catalog=CATALOG)
    library = compose_project_library(emit_library_plan(plan))
    return compose_project_pages(
        document, library, {"entries": []}, project_id="element-style-test", isolated=True
    )[0]


def _with_element_style(section: Section, element_id: str, style: StyleSet) -> Section:
    return section.model_copy(
        update={
            "content": [
                item.model_copy(update={"style": style}) if item.id == element_id else item
                for item in section.content
            ]
        }
    )


def _cards_section(count: int) -> Section:
    """A feature-cards section with ``count`` items -- enough to force repeat expansion."""

    content = [_element(1, ContentKind.HEADING, "section_title", "Our Services")]
    items = []
    next_index = 2
    for item_index in range(count):
        title = _element(next_index, ContentKind.HEADING, "card_title", f"Service {item_index + 1}")
        content.append(title)
        next_index += 1
        body = _element(next_index, ContentKind.TEXT, "card_body", f"Body {item_index + 1}")
        content.append(body)
        next_index += 1
        action = ContentElement(
            id=f"element-{next_index}",
            kind=ContentKind.BUTTON,
            role="card_action",
            value=f"Learn {item_index + 1}",
            attributes={"href": f"/service-{item_index + 1}"},
            order=next_index,
            provenance=[],
            confidence=1.0,
        )
        content.append(action)
        next_index += 1
        items.append(
            RepeatGroupItem(
                id=f"card-{item_index + 1}",
                fields={"title": title.id, "body": body.id, "action": action.id},
            )
        )
    return Section(
        id="home.services",
        order=0,
        semantic_role="feature_cards",
        role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(
            kind=LayoutKind.GRID,
            contained=True,
            columns=3,
            media_position=MediaPosition.TOP,
            alignment=Alignment.LEFT,
        ),
        content=content,
        groups=[RepeatGroup(id="cards", kind=RepeatGroupKind.CARD, items=items)],
        style=StyleSet(),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )


def _simple_template(component: dict) -> dict:
    return {
        "name": "Element Style Unit Test",
        "category": "test",
        "template": {
            "type": "section",
            "attributes": {"id": "sec"},
            "components": [component],
        },
    }


def _two_heading_template() -> dict:
    return _simple_template(
        {
            "type": "default",
            "components": [
                {"type": "heading", "tagName": "h2", "content": "Title A", "attributes": {"id": "h1"}},
                {"type": "heading", "tagName": "h3", "content": "Title B", "attributes": {"id": "h2"}},
            ],
        }
    )


def _linkable_image_template() -> dict:
    return _simple_template({"type": "image", "tagName": "img", "attributes": {"id": "img1", "src": "", "alt": ""}})


# --------------------------------------------------------------------------
# The two confirmed root failures, through the real plan -> library -> page
# pipeline.
# --------------------------------------------------------------------------


def test_section_heading_font_size_survives_to_its_generated_heading() -> None:
    section = _feature_section()
    target = next(item for item in section.content if item.role == "section_title")
    section = _with_element_style(
        section,
        target.id,
        StyleSet(observations=[StyleObservation(property=StyleProperty.FONT_SIZE, value="33.333px")]),
    )
    page = _build_page(section)
    soup = BeautifulSoup(page["content_html"], "html.parser")
    matches = _style_rule_matches(page, soup, "font-size", "33.333px")
    assert matches
    assert all(node.get_text(" ", strip=True) == "Our Services" for node in matches)


def test_card_action_background_color_survives_to_its_own_button() -> None:
    section = _feature_section()
    target = next(item for item in section.content if item.role == "card_action" and item.value == "Learn 1")
    section = _with_element_style(
        section,
        target.id,
        StyleSet(observations=[StyleObservation(property=StyleProperty.BACKGROUND_COLOR, value="rgb(12, 34, 56)")]),
    )
    page = _build_page(section)
    soup = BeautifulSoup(page["content_html"], "html.parser")
    matches = _style_rule_matches(page, soup, "background-color", "rgb(12, 34, 56)")
    assert matches
    assert all(node.get_text(" ", strip=True) == "Learn 1" for node in matches)


# --------------------------------------------------------------------------
# Ownership isolation: siblings, section-vs-child, repeat expansion.
# --------------------------------------------------------------------------


def test_differently_styled_sibling_cards_do_not_leak_across_owners() -> None:
    section = _feature_section()
    action1 = next(item for item in section.content if item.role == "card_action" and item.value == "Learn 1")
    action2 = next(item for item in section.content if item.role == "card_action" and item.value == "Learn 2")
    styled = {
        action1.id: StyleSet(observations=[StyleObservation(property=StyleProperty.BACKGROUND_COLOR, value="rgb(1, 2, 3)")]),
        action2.id: StyleSet(observations=[StyleObservation(property=StyleProperty.BACKGROUND_COLOR, value="rgb(9, 8, 7)")]),
    }
    section = section.model_copy(
        update={
            "content": [
                item.model_copy(update={"style": styled[item.id]}) if item.id in styled else item
                for item in section.content
            ]
        }
    )
    page = _build_page(section)
    soup = BeautifulSoup(page["content_html"], "html.parser")
    matches1 = _style_rule_matches(page, soup, "background-color", "rgb(1, 2, 3)")
    matches2 = _style_rule_matches(page, soup, "background-color", "rgb(9, 8, 7)")
    assert matches1 and all(node.get_text(" ", strip=True) == "Learn 1" for node in matches1)
    assert matches2 and all(node.get_text(" ", strip=True) == "Learn 2" for node in matches2)
    assert not set(id(node) for node in matches1) & set(id(node) for node in matches2)


def test_section_title_and_card_title_stay_distinct_heading_owners() -> None:
    section = _feature_section()
    section_title = next(item for item in section.content if item.role == "section_title")
    card_title = next(item for item in section.content if item.role == "card_title" and item.value == "Service 1")
    section = section.model_copy(
        update={
            "content": [
                item.model_copy(update={"style": StyleSet(observations=[
                    StyleObservation(property=StyleProperty.FONT_SIZE, value="40px")
                ])})
                if item.id == section_title.id
                else item.model_copy(update={"style": StyleSet(observations=[
                    StyleObservation(property=StyleProperty.FONT_SIZE, value="18px")
                ])})
                if item.id == card_title.id
                else item
                for item in section.content
            ]
        }
    )
    page = _build_page(section)
    soup = BeautifulSoup(page["content_html"], "html.parser")
    section_matches = _style_rule_matches(page, soup, "font-size", "40px")
    card_matches = _style_rule_matches(page, soup, "font-size", "18px")
    assert section_matches and all(node.get_text(" ", strip=True) == "Our Services" for node in section_matches)
    assert card_matches and all(node.get_text(" ", strip=True) == "Service 1" for node in card_matches)


def test_element_style_follows_correct_owner_after_repeat_expansion() -> None:
    section = _cards_section(4)  # exceeds the template's default of 3 -> clones a card unit
    target = next(item for item in section.content if item.role == "card_action" and item.value == "Learn 4")
    section = _with_element_style(
        section,
        target.id,
        StyleSet(observations=[StyleObservation(property=StyleProperty.BACKGROUND_COLOR, value="rgb(7, 7, 7)")]),
    )
    document = _document(section)
    plan = plan_design_document(document, catalog=CATALOG)
    assert not plan.entries[0].match.blocking
    page = compose_project_pages(
        document,
        compose_project_library(emit_library_plan(plan)),
        {"entries": []},
        project_id="element-style-test",
        isolated=True,
    )[0]
    soup = BeautifulSoup(page["content_html"], "html.parser")
    matches = _style_rule_matches(page, soup, "background-color", "rgb(7, 7, 7)")
    assert matches
    assert all(node.get_text(" ", strip=True) == "Learn 4" for node in matches)


# --------------------------------------------------------------------------
# Linked image ownership: wrapper vs. image child.
# --------------------------------------------------------------------------


def test_linked_image_wrapper_and_image_child_are_distinct_owners() -> None:
    template = _linkable_image_template()
    rendered, owners = apply_overrides_with_owners(
        template, {"image_1_src": "/photo.jpg", "image_1_href": "/dest"}
    )
    image_owner = owners["image_1_src"]
    wrapper_owner = owners["image_1_href"]
    assert image_owner is not wrapper_owner
    assert image_owner["type"] == "image"
    assert wrapper_owner["type"] == "link"
    assert image_owner in wrapper_owner["components"]

    apply_element_styles(
        rendered,
        owners,
        [
            {
                "slot": "image_1_src",
                "source_element_id": "el-img",
                "style_scope": ".proj .sec",
                "style_declarations": {"border-radius": "8px"},
            }
        ],
        library_key="k",
    )
    style_rules = rendered.get("styles", [])
    assert style_rules
    target_id = style_rules[0]["selectors"][0]["name"]
    assert image_owner["attributes"]["id"] == target_id
    assert wrapper_owner["attributes"]["id"] != target_id


def test_unwrapped_image_has_no_href_owner() -> None:
    template = _linkable_image_template()
    _, owners = apply_overrides_with_owners(template, {"image_1_src": "/photo.jpg"})
    assert "image_1_src" in owners
    assert "image_1_href" not in owners


# --------------------------------------------------------------------------
# Empty earlier-slot pruning must not renumber or misattribute a later owner.
# --------------------------------------------------------------------------


def test_pruned_earlier_slot_does_not_shift_a_later_owner_reference() -> None:
    template = _two_heading_template()
    rendered, owners = apply_overrides_with_owners(template, {"heading_1": "", "heading_2": "Second Heading"})
    assert "heading_1" not in owners
    assert owners["heading_2"]["content"] == "Second Heading"

    apply_element_styles(
        rendered,
        owners,
        [
            {
                "slot": "heading_2",
                "source_element_id": "el-2",
                "style_scope": ".proj .sec",
                "style_declarations": {"font-size": "22px"},
            }
        ],
        library_key="k",
    )
    assert any(rule["style"].get("font-size") == "22px" for rule in rendered["styles"])

    with pytest.raises(ElementStyleTransportError):
        apply_element_styles(
            rendered,
            owners,
            [
                {
                    "slot": "heading_1",
                    "source_element_id": "el-1",
                    "style_scope": ".proj .sec",
                    "style_declarations": {"font-size": "99px"},
                }
            ],
            library_key="k",
        )


# --------------------------------------------------------------------------
# Ambiguous source binding ownership: never guess, always report.
# --------------------------------------------------------------------------


def _styled_heading(element_id: str) -> ContentElement:
    return ContentElement(
        id=element_id,
        kind=ContentKind.HEADING,
        role="title",
        value="v",
        order=0,
        provenance=[],
        confidence=1.0,
        style=StyleSet(observations=[StyleObservation(property=StyleProperty.FONT_SIZE, value="20px")]),
    )


def test_many_to_one_binding_reports_ambiguous_ownership_and_skips_style() -> None:
    element = _styled_heading("el-1")
    other = ContentElement(id="el-2", kind=ContentKind.HEADING, role="title", value="v2", order=1, provenance=[], confidence=1.0)
    binding = SemanticBinding(
        semantic_field="item.title", slot="heading_1", source_element_ids=("el-1", "el-2"), value="v"
    )
    actions, warnings = translate_element_styles(
        [element, other], [binding], FEATURE_CARDS_ENTRY.capabilities, StyleTranslationConfig(),
        css_scope=".proj .sec",
    )
    assert actions == ()
    assert any("ambiguous" in warning for warning in warnings)


def test_one_to_many_binding_reports_ambiguous_ownership_and_skips_style() -> None:
    element = _styled_heading("el-1")
    binding_a = SemanticBinding(semantic_field="item.title", slot="heading_1", source_element_ids=("el-1",), value="v")
    binding_b = SemanticBinding(semantic_field="item.subtitle", slot="heading_2", source_element_ids=("el-1",), value="v")
    actions, warnings = translate_element_styles(
        [element], [binding_a, binding_b], FEATURE_CARDS_ENTRY.capabilities, StyleTranslationConfig(),
        css_scope=".proj .sec",
    )
    assert actions == ()
    assert any("more than one owner slot" in warning for warning in warnings)


def test_href_alias_binding_alone_is_not_treated_as_style_owner() -> None:
    """An element bound only through its `.href` alias has no owning content slot."""

    element = _styled_heading("el-1")
    binding = SemanticBinding(
        semantic_field="item.action.href", slot="button_1_href", source_element_ids=("el-1",), value="/x"
    )
    actions, warnings = translate_element_styles(
        [element], [binding], FEATURE_CARDS_ENTRY.capabilities, StyleTranslationConfig(),
        css_scope=".proj .sec",
    )
    assert actions == ()
    assert any("no owning content slot" in warning for warning in warnings)


# --------------------------------------------------------------------------
# Supported source-conditioned CSS lands on the exact owner, unmodified.
# --------------------------------------------------------------------------


def test_observed_condition_on_element_style_produces_media_scoped_rule_on_owner() -> None:
    condition = ResponsiveCondition(
        bounds=[ConditionBound(kind=ResponsiveConditionKind.MAX_WIDTH, threshold_px=1023)],
        status=ResponsiveConditionStatus.OBSERVED,
        rule_order=0,
    )
    element = ContentElement(
        id="el-1",
        kind=ContentKind.HEADING,
        role="section_title",
        value="Title",
        order=0,
        provenance=[],
        confidence=1.0,
        style=StyleSet(observations=[
            StyleObservation(property=StyleProperty.FONT_SIZE, value="12px", condition=condition)
        ]),
    )
    binding = SemanticBinding(semantic_field="section_title", slot="heading_1", source_element_ids=("el-1",), value="Title")
    actions, _warnings = translate_element_styles(
        [element], [binding], FEATURE_CARDS_ENTRY.capabilities, StyleTranslationConfig(),
        css_scope=".proj .sec",
    )
    assert len(actions) == 1
    assert any(key.startswith("cond-max1023:") for key in actions[0].scoped_css)

    payload = emit_element_style_payload(actions)
    template = _simple_template({"type": "heading", "tagName": "h2", "content": "Title", "attributes": {"id": "h1"}})
    rendered, owners = apply_overrides_with_owners(template, {"heading_1": "Title"})
    apply_element_styles(rendered, owners, payload, library_key="k")
    rule = rendered["styles"][0]
    assert rule.get("mediaText") == "(max-width: 1023px)"
    assert rule["style"]["font-size"] == "12px"


def test_no_section_responsive_evidence_is_invented_for_a_child() -> None:
    """A base (unconditioned) element observation must never gain a fabricated condition."""

    element = _styled_heading("el-1")
    binding = SemanticBinding(semantic_field="item.title", slot="heading_1", source_element_ids=("el-1",), value="v")
    actions, _warnings = translate_element_styles(
        [element], [binding], FEATURE_CARDS_ENTRY.capabilities, StyleTranslationConfig(),
        css_scope=".proj .sec",
    )
    assert len(actions) == 1
    assert list(actions[0].scoped_css) == ["font-size"]


# --------------------------------------------------------------------------
# Native utility/theme class path is preferred over scoped CSS.
# --------------------------------------------------------------------------


def test_element_style_prefers_native_utility_class_over_scoped_css() -> None:
    element = ContentElement(
        id="el-1",
        kind=ContentKind.TEXT,
        role="card_body",
        value="Body",
        order=0,
        provenance=[],
        confidence=1.0,
        style=StyleSet(observations=[StyleObservation(property=StyleProperty.TEXT_ALIGN, value="center")]),
    )
    binding = SemanticBinding(semantic_field="item.body", slot="text_1", source_element_ids=("el-1",), value="Body")
    actions, _warnings = translate_element_styles(
        [element], [binding], FEATURE_CARDS_ENTRY.capabilities, StyleTranslationConfig(),
        css_scope=".proj .sec",
    )
    assert len(actions) == 1
    assert not actions[0].scoped_css
    assert any(
        decision.layer.value == "platform_utility" and decision.target == "text-center"
        for decision in actions[0].style_decisions
    )

    payload = emit_element_style_payload(actions)
    assert payload and payload[0]["native_classes"][0]["target"] == "text-center"

    template = _simple_template({"type": "text", "content": "Body", "attributes": {"id": "t1"}})
    rendered, owners = apply_overrides_with_owners(template, {"text_1": "Body"})
    apply_element_styles(rendered, owners, payload, library_key="k")
    classes = [entry["name"] for entry in owners["text_1"].get("classes", [])]
    assert "text-center" in classes


# --------------------------------------------------------------------------
# Serialization roundtrip and backward compatibility.
# --------------------------------------------------------------------------


def test_element_styles_survive_serialization_roundtrip() -> None:
    section = _feature_section()
    target = next(item for item in section.content if item.role == "card_action" and item.value == "Learn 1")
    section = _with_element_style(
        section,
        target.id,
        StyleSet(observations=[StyleObservation(property=StyleProperty.BACKGROUND_COLOR, value="rgb(4, 5, 6)")]),
    )
    plan = plan_design_document(_document(section), catalog=CATALOG)
    assert plan.entries[0].element_styles
    restored = deserialize_composition_plan(serialize_composition_plan(plan))
    assert restored.entries[0].element_styles == plan.entries[0].element_styles


def test_old_plan_json_without_element_styles_field_still_loads() -> None:
    section = _feature_section()
    plan = plan_design_document(_document(section), catalog=CATALOG)
    payload = json.loads(serialize_composition_plan(plan))
    for entry in payload["entries"]:
        entry.pop("element_styles", None)
    restored = CompositionPlan.model_validate(payload)
    assert all(entry.element_styles == () for entry in restored.entries)


# --------------------------------------------------------------------------
# Untrusted/malformed element_styles payloads must be rejected outright.
# --------------------------------------------------------------------------


_VALID_ITEM = {
    "slot": "heading_1",
    "source_element_id": "el-1",
    "style_scope": ".proj .sec",
    "style_declarations": {"color": "red"},
}


@pytest.mark.parametrize(
    "payload",
    [
        "not-a-list",
        [123],
        [None],
        [{}],
        [{"slot": "HEADING_1", "source_element_id": "e"}],
        [{"slot": "heading_1"}],
        [{"slot": "heading_1", "source_element_id": ""}],
        [{"slot": "heading_1", "source_element_id": "e", "item_id": 5}],
        [{"slot": "heading_1", "source_element_id": "e"}],
        [{"slot": "unknown_9", "source_element_id": "e", "style_scope": ".p .s", "style_declarations": {"color": "red"}}],
        [{"slot": "heading_1", "source_element_id": "e", "style_scope": ".p .s", "style_declarations": {"color": "javascript:alert(1)"}}],
        [
            {
                "slot": "heading_1",
                "source_element_id": "e",
                "native_classes": [
                    {
                        "property": "text_align",
                        "source_value": "center",
                        "layer": "platform_utility",
                        "target": "not-a-real-class",
                        "family": ["not-a-real-class"],
                    }
                ],
            }
        ],
        [_VALID_ITEM, {**_VALID_ITEM, "source_element_id": "el-2"}],
    ],
)
def test_untrusted_element_styles_payload_is_rejected(payload) -> None:
    template = _two_heading_template()
    rendered, owners = apply_overrides_with_owners(template, {"heading_1": "Title A", "heading_2": "Title B"})
    with pytest.raises(ElementStyleTransportError):
        apply_element_styles(rendered, owners, payload, library_key="k")


def test_removed_owner_is_explicitly_reported_not_redirected_to_a_sibling() -> None:
    template = _two_heading_template()
    rendered, owners = apply_overrides_with_owners(template, {"heading_1": "", "heading_2": "Kept"})
    with pytest.raises(ElementStyleTransportError, match="removed or never resolved"):
        apply_element_styles(
            rendered,
            owners,
            [
                {
                    "slot": "heading_1",
                    "source_element_id": "el-1",
                    "style_scope": ".p .s",
                    "style_declarations": {"color": "red"},
                }
            ],
            library_key="k",
        )


# --------------------------------------------------------------------------
# No input mutation.
# --------------------------------------------------------------------------


def test_apply_element_styles_does_not_mutate_the_untrusted_payload() -> None:
    template = _two_heading_template()
    rendered, owners = apply_overrides_with_owners(template, {"heading_1": "Title A"})
    payload = [dict(_VALID_ITEM)]
    original = copy.deepcopy(payload)
    apply_element_styles(rendered, owners, payload, library_key="k")
    assert payload == original


def test_apply_overrides_with_owners_does_not_mutate_the_input_template() -> None:
    template = _two_heading_template()
    original = copy.deepcopy(template)
    apply_overrides_with_owners(template, {"heading_1": "Changed"})
    assert template == original


def test_translate_element_styles_does_not_mutate_section_content_or_bindings() -> None:
    section = _feature_section()
    bindings = bind_section(section, FEATURE_CARDS_ENTRY)
    original_section = section.model_copy(deep=True)
    original_bindings = copy.deepcopy(bindings)
    translate_element_styles(
        section.content, bindings, FEATURE_CARDS_ENTRY.capabilities, StyleTranslationConfig(),
        css_scope=".proj .sec",
    )
    assert section == original_section
    assert bindings == original_bindings
