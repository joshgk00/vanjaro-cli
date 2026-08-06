"""Tests for source-neutral Design Translation v2 style decisions."""

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
    _CSS_INITIAL_VALUES,
    _CSS_PROPERTY_NAMES,
    _RENDERED_REPRODUCIBLE_PROPERTIES,
    translate_responsive_observations,
    translate_style_set,
)
from vanjaro_cli.design.template_catalog import load_template_catalog


def _capabilities():
    return next(
        entry.capabilities
        for entry in load_template_catalog()
        if entry.name == "Centered Hero"
    )


def _observation(property_name: StyleProperty, value: str) -> StyleObservation:
    return StyleObservation(property=property_name, value=value)


def test_precedence_prefers_theme_then_platform_utility():
    style = StyleSet(
        observations=[
            _observation(StyleProperty.BACKGROUND_COLOR, "#ff0101"),
            _observation(StyleProperty.TEXT_ALIGN, "center"),
        ]
    )
    config = StyleTranslationConfig(palette={"primary": "#ff0000"})

    result = translate_style_set(style, _capabilities(), config)

    assert result.decisions[0].layer == TranslationLayer.THEME
    assert result.decisions[0].target == "bg-primary"
    assert result.decisions[0].distance is not None
    assert result.decisions[1].layer == TranslationLayer.PLATFORM_UTILITY
    assert result.decisions[1].target == "text-center"
    assert result.css_declarations == {}


def test_template_modifier_precedes_agency_and_css():
    capabilities = _capabilities()
    modifier = capabilities.supported_modifiers[0]
    property_name = StyleProperty.BORDER_RADIUS
    config = StyleTranslationConfig(
        modifier_properties={property_name: modifier},
        agency_utilities={f"{property_name.value}:24px": "agency-rounded"},
    )

    result = translate_style_set(
        StyleSet(observations=[_observation(property_name, "24px")]),
        capabilities,
        config,
    )

    assert result.decisions[0].layer == TranslationLayer.TEMPLATE_MODIFIER
    assert result.decisions[0].target == f"{modifier}=24px"


def test_agency_utility_precedes_scoped_css_when_no_modifier():
    property_name = StyleProperty.BORDER_RADIUS
    result = translate_style_set(
        StyleSet(observations=[_observation(property_name, "24px")]),
        _capabilities(),
        StyleTranslationConfig(
            agency_utilities={f"{property_name.value}:24px": "agency-rounded"}
        ),
    )

    assert result.decisions[0].layer == TranslationLayer.AGENCY_UTILITY
    assert result.decisions[0].target == "agency-rounded"


def test_safe_fallback_is_scoped_css_and_raw_css_is_not_copied():
    result = translate_style_set(
        StyleSet(
            observations=[_observation(StyleProperty.BOX_SHADOW, "0 2px 8px #000")],
            raw={"clip-path": "polygon(0 0, 100% 0, 90% 100%)"},
        ),
        _capabilities(),
        StyleTranslationConfig(),
    )

    assert result.decisions[0].layer == TranslationLayer.SCOPED_CSS
    assert result.css_declarations == {"box-shadow": "0 2px 8px #000"}
    assert any("not copied" in warning for warning in result.warnings)
    assert "clip-path" not in result.css_declarations


def test_unsafe_css_and_non_allowlisted_important_require_manual_review():
    style = StyleSet(
        observations=[
            _observation(StyleProperty.WIDTH, "100%; color:red"),
            _observation(StyleProperty.HEIGHT, "40px !important"),
        ]
    )

    result = translate_style_set(style, _capabilities(), StyleTranslationConfig())

    assert all(decision.layer == TranslationLayer.MANUAL for decision in result.decisions)
    assert result.css_declarations == {}
    assert len(result.warnings) == 2


def test_allowlisted_important_is_retained_with_reasoned_scoped_css():
    result = translate_style_set(
        StyleSet(observations=[_observation(StyleProperty.HEIGHT, "40px !important")]),
        _capabilities(),
        StyleTranslationConfig(important_allowlist=frozenset({StyleProperty.HEIGHT})),
    )

    assert result.decisions[0].layer == TranslationLayer.SCOPED_CSS
    assert result.css_declarations == {"height": "40px !important"}


def test_css_budget_warns_for_too_many_fallbacks():
    style = StyleSet(
        observations=[
            _observation(StyleProperty.WIDTH, "10px"),
            _observation(StyleProperty.HEIGHT, "20px"),
        ]
    )

    result = translate_style_set(
        style,
        _capabilities(),
        StyleTranslationConfig(max_scoped_rules_per_section=1),
    )

    assert any("budget exceeded" in warning for warning in result.warnings)


def test_responsive_translation_preserves_breakpoint_and_inferred_status():
    responsive = ResponsiveObservation(
        breakpoint=BreakpointName.MOBILE,
        viewport=Viewport(width=390, height=844),
        status=EvidenceStatus.INFERRED,
        layout_changes={"columns": 1},
        style=StyleSet(
            observations=[
                StyleObservation(
                    property=StyleProperty.FLEX_DIRECTION,
                    value="column",
                    status=EvidenceStatus.INFERRED,
                )
            ]
        ),
    )

    result = translate_responsive_observations(
        [responsive], _capabilities(), StyleTranslationConfig()
    )

    assert result.decisions[0].target == "flex-column"
    assert result.decisions[0].breakpoint == BreakpointName.MOBILE
    assert result.decisions[0].evidence_status == EvidenceStatus.INFERRED
    assert any("inferred rather than observed" in warning for warning in result.warnings)


def test_invalid_project_prefix_is_rejected():
    try:
        translate_style_set(
            StyleSet(observations=[]),
            _capabilities(),
            StyleTranslationConfig(project_prefix="Bad Prefix"),
        )
    except ValueError as exc:
        assert "project_prefix" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("invalid prefix should fail")


def _rendered_observation(
    property_name: StyleProperty, value: str
) -> StyleObservation:
    return StyleObservation(
        property=property_name,
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


def test_incidental_computed_state_never_becomes_scoped_css():
    """A browser reports every computed property. Most of it is not intent.

    A native platform utility is still allowed to claim one, because a utility
    class costs no scoped rule and leaves the block editable. The budget this
    protects counts scoped CSS, and that must stay at zero here.
    """

    style = StyleSet(
        observations=[
            _rendered_observation(StyleProperty.DISPLAY, "block"),
            _rendered_observation(StyleProperty.POSITION, "static"),
            _rendered_observation(StyleProperty.OPACITY, "1"),
            _rendered_observation(StyleProperty.TRANSFORM, "none"),
            _rendered_observation(StyleProperty.ORDER, "0"),
        ]
    )

    result = translate_style_set(style, _capabilities(), StyleTranslationConfig())

    assert result.scoped_rule_count == 0
    assert result.css_declarations == {}
    for observed in (
        StyleProperty.POSITION,
        StyleProperty.OPACITY,
        StyleProperty.TRANSFORM,
        StyleProperty.ORDER,
    ):
        assert _layer_for(result, observed) is TranslationLayer.MEASUREMENT_ONLY


def test_design_intent_measured_by_the_browser_is_still_reproduced():
    style = StyleSet(
        observations=[
            _rendered_observation(StyleProperty.BACKGROUND_COLOR, "#0b1f3a"),
            _rendered_observation(StyleProperty.PADDING, "96px"),
        ]
    )

    result = translate_style_set(style, _capabilities(), StyleTranslationConfig())

    assert result.scoped_rule_count == 2
    assert "background-color" in result.css_declarations
    assert "padding" in result.css_declarations


def test_a_measured_css_initial_value_states_no_intent():
    """`box-shadow: none` is the absence of a decision, not a decision."""

    style = StyleSet(
        observations=[
            _rendered_observation(StyleProperty.BOX_SHADOW, "none"),
            _rendered_observation(StyleProperty.LETTER_SPACING, "normal"),
            _rendered_observation(StyleProperty.BORDER_RADIUS, "0px"),
            _rendered_observation(StyleProperty.BOX_SHADOW, "0 2px 8px #0003"),
        ]
    )

    result = translate_style_set(style, _capabilities(), StyleTranslationConfig())

    assert result.css_declarations.get("box-shadow") == "0 2px 8px #0003"
    assert "letter-spacing" not in result.css_declarations
    assert "border-radius" not in result.css_declarations


def test_a_declared_value_from_a_non_rendered_source_is_unaffected():
    """Figma declaring min-height states intent. A browser reporting it does not."""

    declared = StyleSet(observations=[_observation(StyleProperty.MIN_HEIGHT, "520px")])
    measured = StyleSet(
        observations=[_rendered_observation(StyleProperty.MIN_HEIGHT, "520px")]
    )
    config = StyleTranslationConfig()

    declared_result = translate_style_set(declared, _capabilities(), config)
    measured_result = translate_style_set(measured, _capabilities(), config)

    assert declared_result.css_declarations.get("min-height") == "520px"
    assert "min-height" not in measured_result.css_declarations


def test_every_reproducible_property_has_a_css_name():
    """A property declared translatable but absent from the CSS map is dead."""

    assert _RENDERED_REPRODUCIBLE_PROPERTIES <= set(_CSS_PROPERTY_NAMES)


def test_every_initial_value_key_is_a_real_css_property_name():
    assert set(_CSS_INITIAL_VALUES) <= set(_CSS_PROPERTY_NAMES.values())
