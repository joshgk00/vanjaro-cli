"""A source's own conditional/responsive override must not be silently
defeated by the translator's retained base utility class.

Root-confirmed failure (``artifacts/test_element_utility_precedence_independent.py``,
immutable): a base ``text-align: center`` observation resolves through the
translator's normal Bootstrap-utility path to a ``text-center`` class; a
sibling conditional observation (e.g. ``text-align: right`` at
``max-width: 480px``) has no native-class transport at all, so it can only
ever become a normal-priority scoped CSS rule. The installed target's
``text-center`` utility compiles with ``!important`` (root-inspected;
``style_translation.py``'s own Bootstrap 5.1 target note), so the normal
priority conditional rule can never win against it on any real target, no
matter how the class landed on the element -- one of this translator's own
actions, or a template's baked-in default class it was never asked to
remove.

``native_style_transport.build_native_style_report`` resolves this
deterministically: when a property has both a ``PLATFORM_UTILITY`` decision
and a ``SCOPED_CSS`` decision, ``NativeStyleReport.important_css_properties``
names the CSS property, and ``apply_important_css_properties`` promotes every
scoped declaration for that property to ``!important`` before it is
serialized. This is the translator's own generated priority fix -- distinct
from, and never touching, ``StyleTranslationConfig.important_allowlist``,
which continues to gate only a *source* value that already spells
``!important`` on its own.

Every scenario below that claims a final rendered rule or class runs the real
production pipeline (``plan_design_document`` -> ``emit_library_plan`` ->
``compose_project_library`` -> ``compose_project_pages``), the same one
``tests/test_element_style_transport.py`` and the immutable root test use --
not just the translator's own return values.
"""

from __future__ import annotations

import copy

import pytest
from bs4 import BeautifulSoup

from vanjaro_cli.design.element_style_transport import (
    ElementStyleTransportError,
    apply_element_styles,
    translate_element_styles,
)
from vanjaro_cli.design.models import (
    ConditionBound,
    ResponsiveCondition,
    ResponsiveConditionKind,
    ResponsiveConditionStatus,
    StyleObservation,
    StyleProperty,
    StyleSet,
)
from vanjaro_cli.design.native_style_transport import (
    NativeStyleTransportError,
    apply_important_css_properties,
    build_native_style_report,
    validate_native_class_actions,
)
from vanjaro_cli.design.planner import bind_section
from vanjaro_cli.design.style_translation import StyleTranslationConfig, translate_style_set
from vanjaro_cli.utils.block_compose import apply_overrides_with_owners

from tests.test_design_planner import _feature_section
from tests.test_element_style_transport import (
    FEATURE_CARDS_ENTRY,
    _build_page,
    _simple_template,
    _style_rule_matches,
    _with_element_style,
)


def _condition(threshold_px: int, *, rule_order: int = 1) -> ResponsiveCondition:
    return ResponsiveCondition(
        bounds=[ConditionBound(kind=ResponsiveConditionKind.MAX_WIDTH, threshold_px=threshold_px)],
        status=ResponsiveConditionStatus.OBSERVED,
        rule_order=rule_order,
    )


def _heading(soup: BeautifulSoup, text: str):
    return next(
        node for node in soup.find_all(["h1", "h2", "h3", "h4"])
        if node.get_text(" ", strip=True) == text
    )


# --------------------------------------------------------------------------
# Base plus conditional alignment on the same owner.
# --------------------------------------------------------------------------


def test_base_center_and_conditional_right_share_the_same_owner() -> None:
    section = _feature_section()
    title = next(item for item in section.content if item.role == "section_title")
    section = _with_element_style(
        section,
        title.id,
        StyleSet(observations=[
            StyleObservation(property=StyleProperty.TEXT_ALIGN, value="center"),
            StyleObservation(property=StyleProperty.TEXT_ALIGN, value="right", condition=_condition(480)),
        ]),
    )
    page = _build_page(section)
    soup = BeautifulSoup(page["content_html"], "html.parser")
    heading = _heading(soup, "Our Services")

    assert "text-center" in heading.get("class", [])
    matches = _style_rule_matches(page, soup, "text-align", "right !important")
    assert matches == [heading]
    mobile_rule = next(
        rule for rule in page["styles"] if rule.get("style", {}).get("text-align") == "right !important"
    )
    assert mobile_rule.get("mediaText") == "(max-width: 480px)"


def test_conditional_only_observation_still_collides_with_a_baked_in_template_default() -> None:
    """No base observation at all -- the collision comes purely from the
    matched template's own default ``text-center`` class
    (``artifacts/block-templates/Cards/feature-cards-3up.json``'s heading),
    which no ``StyleDecision`` ever describes. This is why the fix has to
    read the owner's actual rendered classes (``important_css_properties_for_component``)
    rather than only the translator's decisions."""

    section = _feature_section()
    title = next(item for item in section.content if item.role == "section_title")
    section = _with_element_style(
        section,
        title.id,
        StyleSet(observations=[
            StyleObservation(property=StyleProperty.TEXT_ALIGN, value="right", condition=_condition(480)),
        ]),
    )
    page = _build_page(section)
    soup = BeautifulSoup(page["content_html"], "html.parser")
    heading = _heading(soup, "Our Services")

    assert "text-center" in heading.get("class", [])
    matches = _style_rule_matches(page, soup, "text-align", "right !important")
    assert matches == [heading]


# --------------------------------------------------------------------------
# Section root vs. bound child: independent resolution, no leakage.
# --------------------------------------------------------------------------


def test_section_root_and_child_heading_resolve_the_collision_independently() -> None:
    section = _feature_section()
    section = section.model_copy(
        update={
            "style": StyleSet(observations=[
                StyleObservation(property=StyleProperty.TEXT_ALIGN, value="center"),
                StyleObservation(property=StyleProperty.TEXT_ALIGN, value="right", condition=_condition(480)),
            ]),
        }
    )
    card_title = next(item for item in section.content if item.role == "card_title" and item.value == "Service 1")
    section = _with_element_style(
        section, card_title.id, StyleSet(observations=[StyleObservation(property=StyleProperty.TEXT_ALIGN, value="left")])
    )

    page = _build_page(section)
    soup = BeautifulSoup(page["content_html"], "html.parser")
    section_node = soup.find("section")
    card_heading = _heading(soup, "Service 1")

    assert "text-center" in section_node.get("class", [])
    assert "text-start" in card_heading.get("class", [])

    section_matches = _style_rule_matches(page, soup, "text-align", "right !important")
    assert section_matches == [section_node]
    # The child's own plain (non-conditional, non-colliding) style never
    # gains a fabricated importance, and never lands on the section root.
    assert not _style_rule_matches(page, soup, "text-align", "left !important")
    assert not any(rule.get("style", {}).get("text-align") == "left" for rule in page["styles"])


# --------------------------------------------------------------------------
# Two differing sibling cards: each owner's collision resolves on its own.
# --------------------------------------------------------------------------


def test_two_sibling_cards_resolve_alignment_collisions_independently() -> None:
    section = _feature_section()
    title1 = next(item for item in section.content if item.role == "card_title" and item.value == "Service 1")
    title2 = next(item for item in section.content if item.role == "card_title" and item.value == "Service 2")

    def _styled(conditional_value: str, threshold: int) -> StyleSet:
        return StyleSet(observations=[
            StyleObservation(property=StyleProperty.TEXT_ALIGN, value="center"),
            StyleObservation(property=StyleProperty.TEXT_ALIGN, value=conditional_value, condition=_condition(threshold)),
        ])

    section = section.model_copy(
        update={
            "content": [
                item.model_copy(update={"style": _styled("right", 480)}) if item.id == title1.id
                else item.model_copy(update={"style": _styled("left", 600)}) if item.id == title2.id
                else item
                for item in section.content
            ]
        }
    )
    page = _build_page(section)
    soup = BeautifulSoup(page["content_html"], "html.parser")
    heading1 = _heading(soup, "Service 1")
    heading2 = _heading(soup, "Service 2")

    assert "text-center" in heading1.get("class", [])
    assert "text-center" in heading2.get("class", [])

    right_matches = _style_rule_matches(page, soup, "text-align", "right !important")
    left_matches = _style_rule_matches(page, soup, "text-align", "left !important")
    assert right_matches == [heading1]
    assert left_matches == [heading2]
    assert not set(id(node) for node in right_matches) & set(id(node) for node in left_matches)


# --------------------------------------------------------------------------
# Recognized template alignment default: no observation, no conflict, no
# change from the ordinary (pre-fix) behavior.
# --------------------------------------------------------------------------


def test_recognized_template_alignment_default_stays_ordinary_without_conflict() -> None:
    section = _feature_section()
    page = _build_page(section)
    soup = BeautifulSoup(page["content_html"], "html.parser")
    heading = _heading(soup, "Our Services")

    assert "text-center" in heading.get("class", [])
    assert not any(rule.get("style", {}).get("text-align") for rule in page["styles"])


def test_no_collision_native_action_is_not_flagged_important() -> None:
    decisions = translate_style_set(
        StyleSet(observations=[StyleObservation(property=StyleProperty.TEXT_ALIGN, value="center")]),
        FEATURE_CARDS_ENTRY.capabilities,
        StyleTranslationConfig(),
    ).decisions
    report = build_native_style_report(decisions)

    assert report.important_css_properties == frozenset()
    assert len(report.actions) == 1
    assert report.actions[0].target == "text-center"
    assert not any("important" in diagnostic for diagnostic in report.diagnostics)


# --------------------------------------------------------------------------
# Another supported important utility property: display.
# --------------------------------------------------------------------------


def test_display_utility_and_conditional_override_share_priority() -> None:
    section = _feature_section()
    title = next(item for item in section.content if item.role == "section_title")
    section = _with_element_style(
        section,
        title.id,
        StyleSet(observations=[
            StyleObservation(property=StyleProperty.DISPLAY, value="block"),
            StyleObservation(property=StyleProperty.DISPLAY, value="none", condition=_condition(480)),
        ]),
    )
    page = _build_page(section)
    soup = BeautifulSoup(page["content_html"], "html.parser")
    heading = _heading(soup, "Our Services")

    assert "d-block" in heading.get("class", [])
    matches = _style_rule_matches(page, soup, "display", "none !important")
    assert matches == [heading]


# --------------------------------------------------------------------------
# Multiple conditional widths for the same colliding property.
# --------------------------------------------------------------------------


def test_multiple_conditional_widths_all_gain_matching_priority() -> None:
    section = _feature_section()
    title = next(item for item in section.content if item.role == "section_title")
    section = _with_element_style(
        section,
        title.id,
        StyleSet(observations=[
            StyleObservation(property=StyleProperty.TEXT_ALIGN, value="center"),
            StyleObservation(property=StyleProperty.TEXT_ALIGN, value="left", condition=_condition(900, rule_order=1)),
            StyleObservation(property=StyleProperty.TEXT_ALIGN, value="right", condition=_condition(480, rule_order=2)),
        ]),
    )
    page = _build_page(section)
    soup = BeautifulSoup(page["content_html"], "html.parser")
    heading = _heading(soup, "Our Services")

    assert "text-center" in heading.get("class", [])
    left_matches = _style_rule_matches(page, soup, "text-align", "left !important")
    right_matches = _style_rule_matches(page, soup, "text-align", "right !important")
    assert left_matches == [heading]
    assert right_matches == [heading]

    left_index = next(
        index for index, rule in enumerate(page["styles"])
        if rule.get("style", {}).get("text-align") == "left !important"
    )
    right_index = next(
        index for index, rule in enumerate(page["styles"])
        if rule.get("style", {}).get("text-align") == "right !important"
    )
    # The narrower max-480 override must be ordered after the wider max-900
    # one so a real browser's last-wins cascade still resolves mobile to
    # "right", exactly as style_transport.build_style_rules already orders
    # any other pair of conditional rules.
    assert left_index < right_index


# --------------------------------------------------------------------------
# No source/plan mutation.
# --------------------------------------------------------------------------


def test_translate_element_styles_does_not_mutate_inputs_when_resolving_a_collision() -> None:
    section = _feature_section()
    title = next(item for item in section.content if item.role == "section_title")
    section = _with_element_style(
        section,
        title.id,
        StyleSet(observations=[
            StyleObservation(property=StyleProperty.TEXT_ALIGN, value="center"),
            StyleObservation(property=StyleProperty.TEXT_ALIGN, value="right", condition=_condition(480)),
        ]),
    )
    bindings = bind_section(section, FEATURE_CARDS_ENTRY)
    original_section = section.model_copy(deep=True)
    original_bindings = copy.deepcopy(bindings)

    translate_element_styles(
        section.content, bindings, FEATURE_CARDS_ENTRY.capabilities, StyleTranslationConfig(),
        css_scope=".proj .sec",
    )

    assert section == original_section
    assert bindings == original_bindings


def test_important_promotion_never_mutates_the_translator_result_in_place() -> None:
    style = StyleSet(observations=[
        StyleObservation(property=StyleProperty.TEXT_ALIGN, value="center"),
        StyleObservation(property=StyleProperty.TEXT_ALIGN, value="right", condition=_condition(480)),
    ])
    original_style = style.model_copy(deep=True)

    result = translate_style_set(style, FEATURE_CARDS_ENTRY.capabilities, StyleTranslationConfig())
    original_declarations = dict(result.css_declarations)
    report = build_native_style_report(result.decisions)
    promoted = apply_important_css_properties(result.css_declarations, report.important_css_properties)

    assert style == original_style
    assert result.css_declarations == original_declarations
    assert promoted is not result.css_declarations
    assert all(value.endswith("!important") for value in promoted.values())
    assert all(not value.endswith("!important") for value in original_declarations.values())


# --------------------------------------------------------------------------
# Hostile payload / important rejection: the fix must not weaken any
# existing safety gate.
# --------------------------------------------------------------------------


def test_source_important_syntax_stays_rejected_without_allowlist() -> None:
    """The translator's own generated !important is separate from the source
    allowlist gate in style_translation._css_decision -- a source value that
    spells !important on its own is still rejected exactly as before."""

    style = StyleSet(observations=[
        StyleObservation(property=StyleProperty.TEXT_ALIGN, value="center"),
        StyleObservation(
            property=StyleProperty.TEXT_ALIGN, value="right !important", condition=_condition(480)
        ),
    ])
    result = translate_style_set(style, FEATURE_CARDS_ENTRY.capabilities, StyleTranslationConfig())

    manual = [decision for decision in result.decisions if decision.layer.value == "manual"]
    assert manual and "not allowlisted" in manual[0].reason
    assert not result.css_declarations


def test_hostile_html_breakout_payload_is_rejected_even_with_important() -> None:
    template = _simple_template(
        {"type": "heading", "tagName": "h2", "content": "Title", "attributes": {"id": "h1"}}
    )
    rendered, owners = apply_overrides_with_owners(template, {"heading_1": "Title"})
    with pytest.raises(ElementStyleTransportError):
        apply_element_styles(
            rendered,
            owners,
            [
                {
                    "slot": "heading_1",
                    "source_element_id": "el-1",
                    "style_scope": ".proj .sec",
                    "style_declarations": {
                        "text-align": "right !important</style><script>alert(1)</script>"
                    },
                }
            ],
            library_key="k",
        )


def test_native_class_target_mismatch_still_rejected_for_important_utility_properties() -> None:
    """Promoting a scoped rule to !important never relaxes the exact
    source-value -> target check for the class itself."""

    with pytest.raises(NativeStyleTransportError):
        validate_native_class_actions([
            {
                "property": "display",
                "source_value": "block",
                "layer": "platform_utility",
                "target": "d-none",
                "family": ["d-none", "d-block", "d-inline", "d-inline-block", "d-flex", "d-grid"],
            }
        ])
