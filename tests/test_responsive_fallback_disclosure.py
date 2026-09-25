"""Disclosure warnings for unproven responsive breakpoint fallback thresholds.

``translate_responsive_observations`` emits scoped CSS keyed to the agency's
fixed mobile/tablet policy widths whenever a source condition is absent or
``UNRESOLVED`` (see ``_scoped_css_key``). That fallback threshold is a policy
approximation, not evidence read from the source's own CSS -- these tests
require the translator to say so, without touching the CSS values or the
transported keys themselves. This is transparency for an existing
approximation, not a new agency policy mechanism or full responsive fidelity.
"""

from __future__ import annotations

from vanjaro_cli.design.models import (
    BreakpointName,
    ConditionBound,
    EvidenceStatus,
    ResponsiveCondition,
    ResponsiveConditionKind,
    ResponsiveConditionStatus,
    ResponsiveObservation,
    StyleObservation,
    StyleProperty,
    StyleSet,
    Viewport,
)
from vanjaro_cli.design.style_translation import (
    StyleTranslationConfig,
    translate_responsive_observations,
)
from vanjaro_cli.design.template_catalog import load_template_catalog
from tests.test_design_planner import _entry


def _capabilities():
    return next(
        entry.capabilities
        for entry in load_template_catalog()
        if entry.name == "Centered Hero"
    )


def _fallback_terms(message: str) -> bool:
    return any(
        term in message.lower()
        for term in ("condition", "threshold", "fallback", "approximate", "policy")
    )


def _responsive(
    breakpoint: BreakpointName,
    property_name: StyleProperty,
    value: str,
    *,
    condition: ResponsiveCondition | None = None,
) -> ResponsiveObservation:
    return ResponsiveObservation(
        breakpoint=breakpoint,
        viewport=Viewport(width=390, height=844),
        status=EvidenceStatus.OBSERVED,
        style=StyleSet(
            observations=[
                StyleObservation(property=property_name, value=value, condition=condition)
            ]
        ),
    )


def test_absent_condition_gets_an_actionable_fallback_warning():
    """No condition was ever gathered: same legacy scoped CSS, plus disclosure."""

    observation = _responsive(BreakpointName.MOBILE, StyleProperty.MIN_HEIGHT, "520px")

    result = translate_responsive_observations(
        [observation], _capabilities(), StyleTranslationConfig()
    )

    assert result.css_declarations == {"mobile:min-height": "520px"}
    matches = [message for message in result.warnings if _fallback_terms(message)]
    assert matches, "expected an actionable fallback threshold warning"
    assert "mobile" in matches[0]
    assert "min-height" in matches[0]


def test_unresolved_condition_gets_a_fallback_warning_preserving_the_reason():
    """Evidence was gathered but attribution failed: reason must survive."""

    condition = ResponsiveCondition(
        bounds=[],
        status=ResponsiveConditionStatus.UNRESOLVED,
        rule_order=1,
        reason="an unsupported media/container expression may win the cascade",
    )
    observation = _responsive(
        BreakpointName.TABLET, StyleProperty.MIN_HEIGHT, "620px", condition=condition
    )

    result = translate_responsive_observations(
        [observation], _capabilities(), StyleTranslationConfig()
    )

    assert result.css_declarations == {"tablet:min-height": "620px"}
    matches = [message for message in result.warnings if _fallback_terms(message)]
    assert matches
    assert any(condition.reason in message for message in matches)


def test_observed_condition_is_transported_without_a_false_fallback_warning():
    """A genuinely proven source condition must not be flagged as approximate."""

    condition = ResponsiveCondition(
        bounds=[ConditionBound(kind=ResponsiveConditionKind.MAX_WIDTH, threshold_px=480)],
        status=ResponsiveConditionStatus.OBSERVED,
        rule_order=1,
        selector="#hero",
    )
    observation = _responsive(
        BreakpointName.MOBILE, StyleProperty.MIN_HEIGHT, "520px", condition=condition
    )

    result = translate_responsive_observations(
        [observation], _capabilities(), StyleTranslationConfig()
    )

    assert result.css_declarations == {"cond-max480:min-height": "520px"}
    assert not any(_fallback_terms(message) for message in result.warnings)


def test_multiple_fallback_properties_each_identified_and_deduplicated():
    """Each affected property is named, and exact-duplicate warnings collapse."""

    section_a = _responsive(BreakpointName.MOBILE, StyleProperty.MIN_HEIGHT, "520px")
    section_b = _responsive(BreakpointName.MOBILE, StyleProperty.PADDING, "24px")
    repeat_of_a = _responsive(BreakpointName.MOBILE, StyleProperty.MIN_HEIGHT, "520px")

    result = translate_responsive_observations(
        [section_a, section_b, repeat_of_a], _capabilities(), StyleTranslationConfig()
    )

    fallback_messages = [message for message in result.warnings if _fallback_terms(message)]
    assert len(fallback_messages) == len(set(fallback_messages)), "duplicate warnings must collapse"
    assert any("min-height" in message for message in fallback_messages)
    assert any("padding" in message for message in fallback_messages)


def test_native_utility_responsive_translation_still_has_no_declarations_or_fallback_warning():
    """A property served by an existing platform utility (no scoped CSS,
    no approximated threshold) must keep its prior unsupported/no-op shape:
    no declarations and no fallback disclosure noise."""

    observation = _responsive(BreakpointName.MOBILE, StyleProperty.TEXT_ALIGN, "center")

    result = translate_responsive_observations(
        [observation], _capabilities(), StyleTranslationConfig()
    )

    assert result.css_declarations == {}
    assert not any(_fallback_terms(message) for message in result.warnings)
