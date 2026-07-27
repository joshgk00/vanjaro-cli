"""VF-003 — colour fidelity metric and CIEDE2000 implementation."""

from __future__ import annotations

import math

import pytest

from vanjaro_cli.design.fidelity import FidelityDimension
from vanjaro_cli.design.fidelity_color import (
    MAX_PERCEPTUAL_DISTANCE,
    ROLE_WEIGHTS,
    ColorRole,
    InvalidColorError,
    Lab,
    SectionPalette,
    delta_e_2000,
    distance_to_score,
    hex_to_lab,
    hex_to_rgb,
    role_distance,
    score_section_color,
)


def _palette(
    background: str | None = "#ffffff",
    text: str | None = "#222222",
    accent: str | None = "#c75b8e",
) -> SectionPalette:
    colors: dict[ColorRole, str] = {}
    if background is not None:
        colors[ColorRole.BACKGROUND] = background
    if text is not None:
        colors[ColorRole.TEXT] = text
    if accent is not None:
        colors[ColorRole.ACCENT] = accent
    return SectionPalette(colors=colors)


class TestHexParsing:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("#ffffff", (255, 255, 255)),
            ("#000000", (0, 0, 0)),
            ("ffffff", (255, 255, 255)),
            ("#FFF", (255, 255, 255)),
            ("#abc", (170, 187, 204)),
            ("  #c75b8e  ", (199, 91, 142)),
        ],
    )
    def test_parses_supported_forms(self, value: str, expected: tuple[int, int, int]) -> None:
        assert hex_to_rgb(value) == expected

    @pytest.mark.parametrize("value", ["", "#", "#12", "#12345", "#gggggg", "red", None])
    def test_rejects_malformed_values(self, value: object) -> None:
        with pytest.raises(InvalidColorError):
            hex_to_rgb(value)  # type: ignore[arg-type]


class TestLabConversion:
    def test_white_maps_to_maximum_lightness_and_neutral_axes(self) -> None:
        lab = hex_to_lab("#ffffff")

        assert lab.lightness == pytest.approx(100.0, abs=0.01)
        assert lab.a == pytest.approx(0.0, abs=0.01)
        assert lab.b == pytest.approx(0.0, abs=0.01)

    def test_black_maps_to_zero_lightness(self) -> None:
        lab = hex_to_lab("#000000")

        assert lab.lightness == pytest.approx(0.0, abs=0.01)

    def test_mid_grey_has_neutral_axes(self) -> None:
        lab = hex_to_lab("#808080")

        assert lab.a == pytest.approx(0.0, abs=0.05)
        assert lab.b == pytest.approx(0.0, abs=0.05)
        assert 50 < lab.lightness < 56

    def test_pure_red_is_positive_on_both_axes(self) -> None:
        lab = hex_to_lab("#ff0000")

        assert lab.lightness == pytest.approx(53.24, abs=0.1)
        assert lab.a == pytest.approx(80.09, abs=0.1)
        assert lab.b == pytest.approx(67.20, abs=0.1)


class TestDeltaE2000Reference:
    """Validate against published CIEDE2000 reference pairs (Sharma et al.).

    Without these the formula could be self-consistently wrong — a plausible
    curve that ranks colours in the wrong order.
    """

    @pytest.mark.parametrize(
        "first,second,expected",
        [
            ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
            ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
            ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
            ((50.0, -1.3802, -84.2814), (50.0, 0.0, -82.7485), 1.0000),
            ((50.0, -1.1848, -84.8006), (50.0, 0.0, -82.7485), 1.0000),
            ((50.0, -0.9009, -85.5211), (50.0, 0.0, -82.7485), 1.0000),
            ((50.0, 0.0, 0.0), (50.0, -1.0, 2.0), 2.3669),
            ((50.0, -1.0, 2.0), (50.0, 0.0, 0.0), 2.3669),
            ((50.0, 2.4900, -0.0010), (50.0, -2.4900, 0.0009), 7.1792),
            ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492),
            ((50.0, 2.5, 0.0), (50.0, 3.1736, 0.5854), 1.0000),
            ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
        ],
    )
    def test_matches_reference_values(
        self,
        first: tuple[float, float, float],
        second: tuple[float, float, float],
        expected: float,
    ) -> None:
        result = delta_e_2000(
            Lab(lightness=first[0], a=first[1], b=first[2]),
            Lab(lightness=second[0], a=second[1], b=second[2]),
        )

        assert result == pytest.approx(expected, abs=0.0002)

    def test_is_symmetric(self) -> None:
        first = Lab(lightness=50, a=2.5, b=0)
        second = Lab(lightness=73, a=25, b=-18)

        assert delta_e_2000(first, second) == delta_e_2000(second, first)

    def test_identical_colors_are_zero(self) -> None:
        assert delta_e_2000(hex_to_lab("#c75b8e"), hex_to_lab("#c75b8e")) == 0.0

    def test_is_not_euclidean_distance(self) -> None:
        # (50,2.5,0) vs (50,-2.5,0) is 5.0 in raw Lab but ~2.7 perceptually.
        first = Lab(lightness=50, a=2.5, b=0)
        second = Lab(lightness=50, a=-2.5, b=0)
        euclidean = math.dist(
            (first.lightness, first.a, first.b), (second.lightness, second.a, second.b)
        )

        assert delta_e_2000(first, second) != pytest.approx(euclidean, abs=0.5)


class TestDistanceToScore:
    def test_zero_distance_scores_100(self) -> None:
        assert distance_to_score(0.0) == 100.0

    def test_distance_at_or_beyond_the_cap_scores_zero(self) -> None:
        assert distance_to_score(MAX_PERCEPTUAL_DISTANCE) == 0.0
        assert distance_to_score(MAX_PERCEPTUAL_DISTANCE * 3) == 0.0

    def test_falloff_is_monotonic(self) -> None:
        scores = [distance_to_score(value) for value in (0, 1, 5, 10, 20, 25)]

        assert scores == sorted(scores, reverse=True)

    def test_imperceptible_drift_stays_high(self) -> None:
        assert distance_to_score(1.0) > 95.0


class TestSectionColorScoring:
    def test_identical_palette_scores_100(self) -> None:
        result = score_section_color(_palette(), _palette())

        assert result.dimension is FidelityDimension.COLOR
        assert result.score == 100.0
        assert result.detail is None

    def test_single_slot_drift_names_the_role(self) -> None:
        result = score_section_color(_palette(), _palette(accent="#8e5bc7"))

        assert result.score is not None
        assert result.score < 100.0
        assert "drift in accent" in (result.detail or "")

    def test_single_slot_drift_scores_higher_than_full_drift(self) -> None:
        single = score_section_color(_palette(), _palette(accent="#8e5bc7")).score
        full = score_section_color(
            _palette(), _palette(background="#101010", text="#f0d0a0", accent="#00ff00")
        ).score

        assert single is not None and full is not None
        assert single > full

    def test_full_palette_drift_scores_low(self) -> None:
        result = score_section_color(
            _palette(background="#ffffff", text="#000000", accent="#c75b8e"),
            _palette(background="#000000", text="#ffffff", accent="#00ff00"),
        )

        assert result.score is not None
        assert result.score < 25.0

    def test_background_outweighs_accent(self) -> None:
        background_drift = score_section_color(
            _palette(), _palette(background="#e8e8e8")
        ).score
        accent_drift = score_section_color(_palette(), _palette(accent="#d16a99")).score

        assert background_drift is not None and accent_drift is not None
        assert ROLE_WEIGHTS[ColorRole.BACKGROUND] > ROLE_WEIGHTS[ColorRole.ACCENT]

    def test_role_weights_cover_every_role_and_sum_to_one(self) -> None:
        assert set(ROLE_WEIGHTS) == set(ColorRole)
        assert sum(ROLE_WEIGHTS.values()) == pytest.approx(1.0)


class TestGreyscale:
    def test_identical_greys_score_100(self) -> None:
        grey = _palette(background="#808080", text="#404040", accent="#c0c0c0")

        assert score_section_color(grey, grey).score == 100.0

    def test_greyscale_drift_is_detected_by_lightness_alone(self) -> None:
        # Neutrals have near-zero a/b, so only the lightness term can move.
        distance = role_distance("#808080", "#909090")

        assert distance > 0
        assert score_section_color(
            _palette(background="#808080", text=None, accent=None),
            _palette(background="#909090", text=None, accent=None),
        ).score == pytest.approx(distance_to_score(distance))

    def test_black_to_white_is_maximally_distant(self) -> None:
        assert distance_to_score(role_distance("#000000", "#ffffff")) == 0.0

    def test_a_colour_swapped_for_grey_is_penalised(self) -> None:
        result = score_section_color(
            _palette(background=None, text=None, accent="#c75b8e"),
            _palette(background=None, text=None, accent="#808080"),
        )

        assert result.score is not None
        assert result.score < 80.0


class TestMissingEvidence:
    def test_role_missing_on_either_side_is_unmeasured(self) -> None:
        result = score_section_color(_palette(), _palette(accent=None))

        assert "no colour evidence for accent" in (result.detail or "")
        # The measured roles still score, rather than the section being penalised.
        assert result.score == 100.0

    def test_no_shared_role_yields_unavailable(self) -> None:
        result = score_section_color(
            _palette(background="#ffffff", text=None, accent=None),
            _palette(background=None, text="#000000", accent=None),
        )

        assert result.score is None

    def test_empty_palettes_yield_unavailable(self) -> None:
        result = score_section_color(SectionPalette(), SectionPalette())

        assert result.score is None

    def test_malformed_palette_colour_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            SectionPalette(colors={ColorRole.BACKGROUND: "not-a-colour"})


class TestDeterminism:
    def test_repeated_scoring_is_identical(self) -> None:
        expected = _palette()
        observed = _palette(accent="#8e5bc7")

        first = score_section_color(expected, observed)
        second = score_section_color(expected, observed)

        assert first.score == second.score
        assert first.detail == second.detail

    def test_conversion_is_stable(self) -> None:
        assert hex_to_lab("#c75b8e") == hex_to_lab("#c75b8e")
