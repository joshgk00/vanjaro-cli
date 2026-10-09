"""RT-37 — card fills, photo darkening, and contrast in the colour dimension."""

from __future__ import annotations

import pytest

from vanjaro_cli.design.fidelity_color import (
    OVERLAY_WEIGHT,
    ROLE_WEIGHTS,
    SURFACE_WEIGHT,
    ColorRole,
    OverlaySample,
    SectionPalette,
    contrast_ratio,
    score_section_color,
)

PINK = "#f0709d"
YELLOW = "#fdbb2c"
TEAL = "#103030"
WHITE = "#ffffff"


def _palette(
    *surfaces: str,
    background: str | None = WHITE,
    text: str | None = None,
    overlay: OverlaySample | None = None,
    measured: bool = True,
) -> SectionPalette:
    colors = {}
    if background is not None:
        colors[ColorRole.BACKGROUND] = background
    if text is not None:
        colors[ColorRole.TEXT] = text
    return SectionPalette(
        colors=colors,
        surfaces=tuple(surfaces) if measured else None,
        overlay=overlay,
    )


def _overlay(color: str = "#000000", opacity: float = 0.4) -> OverlaySample:
    return OverlaySample(present=True, color=color, opacity=opacity)


class TestCardFills:
    def test_cards_painted_the_designed_colours_score_full_marks(self) -> None:
        result = score_section_color(
            _palette(PINK, YELLOW, TEAL), _palette(TEAL, PINK, YELLOW)
        )

        assert result.score == 100.0

    def test_cards_left_unpainted_show_the_band_and_score_by_how_far_that_is(self) -> None:
        designed = _palette(TEAL, "#1a1a1a", background=WHITE)
        flat = _palette(background=WHITE)

        result = score_section_color(designed, flat)

        # The white backdrop stands in for both dark cards and is nothing like
        # either, so only the matching background keeps any credit.
        background = ROLE_WEIGHTS[ColorRole.BACKGROUND]
        assert result.score == pytest.approx(100 * background / (background + SURFACE_WEIGHT), abs=0.01)
        assert "drift in surfaces" in (result.detail or "")

    def test_a_designed_white_card_on_a_white_band_matches_an_unpainted_card(self) -> None:
        result = score_section_color(_palette(WHITE, WHITE), _palette(background=WHITE))

        assert result.score == 100.0

    def test_one_painted_surface_cannot_stand_in_for_two_designed_cards(self) -> None:
        designed = _palette(PINK, PINK, background=None)
        one_pink = _palette(PINK, background=None)

        result = score_section_color(designed, one_pink)

        assert result.score == 50.0

    def test_a_card_painted_a_nearby_colour_loses_a_little(self) -> None:
        result = score_section_color(_palette(PINK), _palette("#f2759f"))

        assert result.score is not None and 90 < result.score < 100

    def test_a_build_that_did_not_report_surfaces_leaves_them_unmeasured(self) -> None:
        result = score_section_color(
            _palette(PINK, text="#111111"), _palette(text="#111111", measured=False)
        )

        assert result.score == 100.0
        assert "no colour evidence for" in (result.detail or "") and "surfaces" in (result.detail or "")

    def test_a_design_with_no_cards_does_not_score_the_build_surfaces(self) -> None:
        result = score_section_color(
            SectionPalette(colors={ColorRole.BACKGROUND: WHITE}),
            _palette(PINK, YELLOW, background=WHITE),
        )

        assert result.score == 100.0
        assert result.total_subscores == len(ColorRole)

    def test_designed_cards_add_one_subscore_to_the_split(self) -> None:
        result = score_section_color(_palette(PINK), _palette(PINK))

        assert result.total_subscores == len(ColorRole) + 1
        assert result.measured_subscores == 2

    def test_surfaces_weigh_against_the_roles_by_their_declared_weight(self) -> None:
        designed = _palette(PINK, text="#111111", background=None)
        built = _palette(WHITE, text="#111111", background=None)

        result = score_section_color(designed, built)

        surface_score = 100 * 0.0
        expected = (
            ROLE_WEIGHTS[ColorRole.TEXT] * 100.0 + SURFACE_WEIGHT * surface_score
        ) / (ROLE_WEIGHTS[ColorRole.TEXT] + SURFACE_WEIGHT)
        assert result.score == pytest.approx(expected, abs=0.5)


class TestPhotoDarkening:
    def test_a_matching_layer_scores_full_marks(self) -> None:
        result = score_section_color(
            _palette(background=None, overlay=_overlay()),
            _palette(background=None, overlay=_overlay()),
        )

        assert result.score == 100.0

    def test_a_build_with_no_layer_scores_zero_for_it(self) -> None:
        result = score_section_color(
            _palette(background=None, overlay=_overlay()),
            _palette(background=None, overlay=OverlaySample(present=False)),
        )

        assert result.score == 0.0
        assert "overlay" in (result.detail or "")

    def test_a_lighter_layer_of_the_right_colour_loses_by_how_much_lighter(self) -> None:
        result = score_section_color(
            _palette(background=None, overlay=_overlay(opacity=0.4)),
            _palette(background=None, overlay=_overlay(opacity=0.2)),
        )

        # Colour is exact (100); an opacity swing of 0.2 of the 0.5 tolerance scores 60.
        assert result.score == pytest.approx(80.0, abs=0.01)

    def test_a_layer_of_the_wrong_colour_loses_on_colour(self) -> None:
        result = score_section_color(
            _palette(background=None, overlay=_overlay("#000000")),
            _palette(background=None, overlay=_overlay(YELLOW)),
        )

        assert result.score is not None and result.score < 55

    def test_a_build_that_did_not_report_a_layer_leaves_it_unmeasured(self) -> None:
        result = score_section_color(
            _palette(WHITE, background=WHITE, overlay=_overlay()),
            _palette(WHITE, background=WHITE),
        )

        assert result.score == 100.0
        assert "no colour evidence for" in (result.detail or "")
        assert "overlay" in (result.detail or "")

    def test_a_design_with_no_layer_does_not_score_the_build_one(self) -> None:
        result = score_section_color(
            _palette(background=WHITE),
            _palette(background=WHITE, overlay=_overlay()),
        )

        assert result.score == 100.0

    def test_overlay_weight_is_declared_beside_the_role_weights(self) -> None:
        assert 0 < OVERLAY_WEIGHT < SURFACE_WEIGHT <= 1


class TestPaletteContract:
    def test_a_present_overlay_must_state_its_colour_and_opacity(self) -> None:
        with pytest.raises(ValueError):
            OverlaySample(present=True, color=None, opacity=0.4)
        with pytest.raises(ValueError):
            OverlaySample(present=True, color="#000000", opacity=None)

    def test_an_absent_overlay_carries_no_paint(self) -> None:
        with pytest.raises(ValueError):
            OverlaySample(present=False, color="#000000", opacity=0.4)

    def test_a_malformed_surface_colour_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            SectionPalette(surfaces=("not-a-colour",))

    def test_a_palette_recorded_before_surfaces_existed_still_loads(self) -> None:
        palette = SectionPalette.model_validate({"colors": {"background": WHITE}})

        assert palette.surfaces is None
        assert palette.overlay is None


class TestContrast:
    def test_identical_colours_have_a_ratio_of_one(self) -> None:
        assert contrast_ratio(WHITE, WHITE) == pytest.approx(1.0)

    def test_black_on_white_is_the_maximum(self) -> None:
        assert contrast_ratio("#000000", WHITE) == pytest.approx(21.0)
        assert contrast_ratio(WHITE, "#000000") == pytest.approx(21.0)

    def test_white_on_pale_yellow_is_poor_but_not_invisible(self) -> None:
        assert 1.5 < contrast_ratio(WHITE, YELLOW) < 2.0

    def test_near_white_on_white_is_below_the_visibility_floor(self) -> None:
        assert contrast_ratio("#fefefe", WHITE) < 1.05
