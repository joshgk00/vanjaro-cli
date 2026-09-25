"""Tests for the confirmed style translation correction: a rendered nondefault
``min-height`` is an authored sizing constraint, not a measured box HEIGHT, and
must be retained instead of being discarded as incidental measurement noise.

See docs/agency-minimum-height-intent-contract.md for the source contract.
"""

from __future__ import annotations

from vanjaro_cli.design.models import (
    BreakpointName,
    EvidenceStatus,
    ObservationMethod,
    Provenance,
    ResponsiveObservation,
    SourceKind,
    StyleObservation,
    StyleProperty,
    StyleSet,
    Viewport,
)
from vanjaro_cli.design.style_translation import (
    StyleTranslationConfig,
    TranslationLayer,
    translate_responsive_observations,
    translate_style_set,
)
from vanjaro_cli.design.template_catalog import load_template_catalog

import pytest


def _capabilities():
    return next(
        entry.capabilities
        for entry in load_template_catalog()
        if entry.name == "Centered Hero"
    )


def _rendered(value: str, breakpoint: BreakpointName | None = None) -> StyleObservation:
    return StyleObservation(
        property=StyleProperty.MIN_HEIGHT,
        value=value,
        provenance=[
            Provenance(
                source_kind=SourceKind.LIVE_HTML,
                source_url="https://northstar.test/",
                method=ObservationMethod.RENDERED,
            )
        ],
    )


def _layer_for(result, property_name: StyleProperty) -> TranslationLayer:
    return next(
        decision.layer
        for decision in result.decisions
        if decision.property is property_name
    )


# -- Defaults ----------------------------------------------------------------


@pytest.mark.parametrize("default_value", ["auto", "0", "0px"])
def test_default_rendered_min_height_is_filtered(default_value):
    style = StyleSet(observations=[_rendered(default_value)])

    result = translate_style_set(style, _capabilities(), StyleTranslationConfig())

    assert result.css_declarations == {}
    assert _layer_for(result, StyleProperty.MIN_HEIGHT) is TranslationLayer.MEASUREMENT_ONLY


# -- Positive constraints -----------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["720px", "620px", "520px", "560px", "40rem", "75vh", "50%"],
)
def test_nondefault_rendered_min_height_is_preserved_as_scoped_css(value):
    """Supports the CSS length/percentage units the hero probe actually observed,
    not just hardcoded pixels."""

    style = StyleSet(observations=[_rendered(value)])

    result = translate_style_set(style, _capabilities(), StyleTranslationConfig())

    assert result.css_declarations.get("min-height") == value
    assert _layer_for(result, StyleProperty.MIN_HEIGHT) is TranslationLayer.SCOPED_CSS
    assert result.scoped_rule_count == 1


def test_nondefault_rendered_min_height_reason_cites_a_constraint_not_a_measurement():
    style = StyleSet(observations=[_rendered("520px")])

    result = translate_style_set(style, _capabilities(), StyleTranslationConfig())

    decision = next(
        item for item in result.decisions if item.property is StyleProperty.MIN_HEIGHT
    )
    assert decision.layer is TranslationLayer.SCOPED_CSS
    assert decision.source_value == "520px"


# -- Viewport-specific CSS -----------------------------------------------------


def _responsive(breakpoint: BreakpointName, width: int, height: int, value: str):
    return ResponsiveObservation(
        breakpoint=breakpoint,
        viewport=Viewport(width=width, height=height),
        status=EvidenceStatus.OBSERVED,
        style=StyleSet(observations=[_rendered(value)]),
    )


def test_viewport_specific_min_height_changes_only_the_changed_breakpoint():
    """Real-browser evidence retains 720px desktop, 620px tablet, and a mobile
    value that must track the source: changing only the mobile source CSS from
    520px to 560px must change only the generated mobile declaration."""

    before = [
        _responsive(BreakpointName.DESKTOP, 1440, 900, "720px"),
        _responsive(BreakpointName.TABLET, 834, 1194, "620px"),
        _responsive(BreakpointName.MOBILE, 390, 844, "520px"),
    ]
    after = [
        _responsive(BreakpointName.DESKTOP, 1440, 900, "720px"),
        _responsive(BreakpointName.TABLET, 834, 1194, "620px"),
        _responsive(BreakpointName.MOBILE, 390, 844, "560px"),
    ]

    config = StyleTranslationConfig()
    capabilities = _capabilities()
    before_result = translate_responsive_observations(before, capabilities, config)
    after_result = translate_responsive_observations(after, capabilities, config)

    assert before_result.css_declarations["desktop:min-height"] == "720px"
    assert before_result.css_declarations["tablet:min-height"] == "620px"
    assert before_result.css_declarations["mobile:min-height"] == "520px"

    assert after_result.css_declarations["desktop:min-height"] == "720px"
    assert after_result.css_declarations["tablet:min-height"] == "620px"
    assert after_result.css_declarations["mobile:min-height"] == "560px"


# -- Safety --------------------------------------------------------------------


def test_unsafe_rendered_min_height_value_requires_manual_review():
    style = StyleSet(
        observations=[_rendered("520px; background:url(javascript:alert(1))")]
    )

    result = translate_style_set(style, _capabilities(), StyleTranslationConfig())

    assert result.css_declarations == {}
    assert _layer_for(result, StyleProperty.MIN_HEIGHT) is TranslationLayer.MANUAL


def test_important_rendered_min_height_requires_allowlisting():
    style = StyleSet(observations=[_rendered("520px !important")])

    blocked = translate_style_set(style, _capabilities(), StyleTranslationConfig())
    assert blocked.css_declarations == {}
    assert _layer_for(blocked, StyleProperty.MIN_HEIGHT) is TranslationLayer.MANUAL

    allowed = translate_style_set(
        style,
        _capabilities(),
        StyleTranslationConfig(important_allowlist=frozenset({StyleProperty.MIN_HEIGHT})),
    )
    assert allowed.css_declarations.get("min-height") == "520px !important"


# -- Native/utility precedence --------------------------------------------------


def test_template_modifier_still_precedes_scoped_css_for_min_height():
    capabilities = _capabilities()
    modifier = capabilities.supported_modifiers[0]
    config = StyleTranslationConfig(
        modifier_properties={StyleProperty.MIN_HEIGHT: modifier}
    )

    result = translate_style_set(
        StyleSet(observations=[_rendered("520px")]), capabilities, config
    )

    assert result.decisions[0].layer == TranslationLayer.TEMPLATE_MODIFIER
    assert result.decisions[0].target == f"{modifier}=520px"
    assert result.css_declarations == {}


def test_agency_utility_still_precedes_scoped_css_for_min_height():
    config = StyleTranslationConfig(
        agency_utilities={"min_height:520px": "agency-min-height-520"}
    )

    result = translate_style_set(
        StyleSet(observations=[_rendered("520px")]), _capabilities(), config
    )

    assert result.decisions[0].layer == TranslationLayer.AGENCY_UTILITY
    assert result.decisions[0].target == "agency-min-height-520"
    assert result.css_declarations == {}
