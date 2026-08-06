"""Tests for the shared CSS colour normalizer."""

from __future__ import annotations

import pytest

from vanjaro_cli.design.css_color import normalize_css_color


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("rgb(255, 255, 255)", "#ffffff"),
        ("rgb(11, 31, 58)", "#0b1f3a"),
        ("RGBA(11, 31, 58, 0.5)", "#0b1f3a"),
        ("#0b1f3a", "#0b1f3a"),
        ("#abc", "#abc"),
        ("  rgb(0, 0, 0)  ", "#000000"),
    ],
)
def test_recognized_colours_normalize_to_hex(value: str, expected: str) -> None:
    assert normalize_css_color(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "rgba(0, 0, 0, 0)",
        "transparent",
        "none",
        "hsl(210, 68%, 14%)",
        "rebeccapurple",
        "color-mix(in srgb, red, blue)",
        "rgb(300, 0, 0)",
        "",
        "   ",
        None,
        42,
    ],
)
def test_unusable_values_are_dropped_rather_than_guessed(value: object) -> None:
    """A fabricated colour in a score is worse than one fewer scored role."""

    assert normalize_css_color(value) is None


def test_partial_alpha_keeps_its_channels() -> None:
    """What it composites against is not knowable from the element alone."""

    assert normalize_css_color("rgba(11, 31, 58, 0.25)") == "#0b1f3a"


def test_both_fidelity_sides_use_the_same_normalizer() -> None:
    """A second copy would drift, and the two sides would stop agreeing."""

    from vanjaro_cli.design import fidelity_extraction, fidelity_measure

    assert fidelity_measure.normalize_css_color is normalize_css_color
    assert fidelity_extraction.normalize_css_color is normalize_css_color


def test_the_design_side_accepts_a_browser_computed_palette() -> None:
    """Rendered analysis puts rgb() on the design side, which used to raise."""

    from vanjaro_cli.design.fidelity_extraction import _palette
    from vanjaro_cli.design.models import (
        LayoutKind,
        LayoutObservation,
        Section,
        StyleObservation,
        StyleProperty,
        StyleSet,
    )

    section = Section(
        id="page.section.1",
        order=1,
        semantic_role="hero",
        role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.STACK, contained=True),
        content=[],
        groups=[],
        style=StyleSet(
            observations=[
                StyleObservation(
                    property=StyleProperty.BACKGROUND_COLOR, value="rgba(0, 0, 0, 0)"
                ),
                StyleObservation(
                    property=StyleProperty.TEXT_COLOR, value="rgb(0, 0, 0)"
                ),
            ]
        ),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )

    palette = _palette(section)

    assert list(palette.colors.values()) == ["#000000"]
