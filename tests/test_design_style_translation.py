"""Tests for source-neutral Design Translation v2 style decisions."""

from __future__ import annotations

from vanjaro_cli.design.models import (
    BreakpointName,
    EvidenceStatus,
    ResponsiveObservation,
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
