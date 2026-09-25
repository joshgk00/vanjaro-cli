"""Tests for the available-platform-utilities capability on StyleTranslationConfig.

The default set matches the root-inspected target (installed Basic Theme.css +
Bootstrap 5.1.0 source): 25 of 27 mapped utility classes exist there, and
object-fit-cover / object-fit-contain do not. This module only corrects which
utility class the translator *chooses*; applying object-fit to real image
components and transporting the choice into generated blocks remain separate,
unsolved tasks.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from vanjaro_cli.design.models import StyleObservation, StyleProperty, StyleSet
from vanjaro_cli.design.style_translation import (
    DEFAULT_AVAILABLE_PLATFORM_UTILITIES,
    StyleTranslationConfig,
    TranslationLayer,
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


def _translate(property_name, value, config):
    return translate_style_set(
        StyleSet(observations=[_observation(property_name, value)]),
        _capabilities(),
        config,
    )


# -- Default target compatibility --------------------------------------------


@pytest.mark.parametrize("value", ["cover", "contain"])
def test_default_object_fit_falls_back_to_scoped_css(value):
    """object-fit-cover/contain are absent from the inspected 5.1 target, so
    the default config must fall through to the existing scoped-CSS layer
    instead of emitting a class the target doesn't ship."""

    result = _translate(StyleProperty.OBJECT_FIT, value, StyleTranslationConfig())

    assert result.css_declarations.get("object-fit") == value
    decision = result.decisions[0]
    assert decision.layer == TranslationLayer.SCOPED_CSS
    assert all(item.layer != TranslationLayer.PLATFORM_UTILITY for item in result.decisions)


def test_default_available_alignment_utility_remains_preferred():
    """The 25 existing supported classes must stay preferred by default."""

    result = _translate(StyleProperty.TEXT_ALIGN, "right", StyleTranslationConfig())

    assert result.decisions[0].layer == TranslationLayer.PLATFORM_UTILITY
    assert result.decisions[0].target == "text-end"
    assert result.css_declarations == {}


def test_default_excludes_only_the_two_absent_object_fit_classes():
    assert "object-fit-cover" not in DEFAULT_AVAILABLE_PLATFORM_UTILITIES
    assert "object-fit-contain" not in DEFAULT_AVAILABLE_PLATFORM_UTILITIES
    assert "text-end" in DEFAULT_AVAILABLE_PLATFORM_UTILITIES


# -- Explicit enable / disable -------------------------------------------------


def test_explicit_support_for_a_known_mapping_enables_it():
    """A caller with a verified different target may explicitly opt an
    already-known mapping (here object-fit-cover) back in."""

    config = StyleTranslationConfig(
        available_platform_utilities=DEFAULT_AVAILABLE_PLATFORM_UTILITIES
        | {"object-fit-cover"}
    )

    result = _translate(StyleProperty.OBJECT_FIT, "cover", config)

    assert result.decisions[0].layer == TranslationLayer.PLATFORM_UTILITY
    assert result.decisions[0].target == "object-fit-cover"
    assert result.css_declarations == {}


def test_explicit_empty_support_disables_platform_utilities():
    config = StyleTranslationConfig(available_platform_utilities=frozenset())

    result = _translate(StyleProperty.TEXT_ALIGN, "right", config)

    assert result.decisions[0].layer != TranslationLayer.PLATFORM_UTILITY
    assert result.css_declarations.get("text-align") == "right"


def test_disabling_one_target_does_not_disable_unrelated_mappings():
    """Explicit support still applies template/agency/scoped-CSS precedence
    for properties it does not opt back in."""

    config = StyleTranslationConfig(
        available_platform_utilities=frozenset({"object-fit-cover"})
    )

    cover_result = _translate(StyleProperty.OBJECT_FIT, "cover", config)
    align_result = _translate(StyleProperty.TEXT_ALIGN, "right", config)

    assert cover_result.decisions[0].layer == TranslationLayer.PLATFORM_UTILITY
    assert align_result.decisions[0].layer != TranslationLayer.PLATFORM_UTILITY
    assert align_result.css_declarations.get("text-align") == "right"


# -- No mutation of shared defaults -------------------------------------------


def test_default_frozenset_is_not_mutated_by_other_configs():
    baseline = frozenset(DEFAULT_AVAILABLE_PLATFORM_UTILITIES)

    StyleTranslationConfig(available_platform_utilities=frozenset())
    StyleTranslationConfig(
        available_platform_utilities=DEFAULT_AVAILABLE_PLATFORM_UTILITIES
        | {"object-fit-cover"}
    )

    assert DEFAULT_AVAILABLE_PLATFORM_UTILITIES == baseline
    assert "object-fit-cover" not in DEFAULT_AVAILABLE_PLATFORM_UTILITIES

    default_config_result = _translate(
        StyleProperty.OBJECT_FIT, "cover", StyleTranslationConfig()
    )
    assert default_config_result.decisions[0].layer != TranslationLayer.PLATFORM_UTILITY


# -- Unsafe capability data ----------------------------------------------------


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "object-fit-cover; } body { display:none",
        "<script>alert(1)</script>",
        "not-a-real-utility",
    ],
)
def test_unknown_or_unsafe_capability_strings_are_rejected(unsafe_value):
    with pytest.raises(ValidationError):
        StyleTranslationConfig(
            available_platform_utilities=frozenset({unsafe_value})
        )


# -- Unchanged CSS safety ------------------------------------------------------


def test_unsafe_object_fit_value_still_requires_manual_review_when_enabled():
    """Enabling the mapping must not weaken the existing CSS-injection guard."""

    config = StyleTranslationConfig(
        available_platform_utilities=DEFAULT_AVAILABLE_PLATFORM_UTILITIES
        | {"object-fit-cover"}
    )

    result = _translate(StyleProperty.OBJECT_FIT, "cover; } body { color:red", config)

    assert result.css_declarations == {}
    assert result.decisions[0].layer == TranslationLayer.MANUAL


def test_object_fit_scoped_css_fallback_is_still_budget_counted():
    config = StyleTranslationConfig(max_scoped_rules_per_section=0)

    result = _translate(StyleProperty.OBJECT_FIT, "cover", config)

    assert result.css_declarations.get("object-fit") == "cover"
    assert any("budget exceeded" in warning for warning in result.warnings)
