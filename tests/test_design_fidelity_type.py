"""VF-004 — typography and spacing fidelity metrics."""

from __future__ import annotations

import pytest

from vanjaro_cli.design.fidelity import FidelityDimension
from vanjaro_cli.design.fidelity_type import (
    FAMILY_WEIGHT,
    PADDING_WEIGHT,
    RHYTHM_WEIGHT,
    SIZE_WEIGHT,
    WEIGHT_WEIGHT,
    SectionSpacing,
    SectionTypography,
    SpacingSample,
    TypeSample,
    normalize_family,
    score_section_spacing,
    score_section_typography,
    type_scale_ratio,
)

DESIGN_SCALE = {
    "display": TypeSample(family="Playfair Display", size_px=64, weight=700),
    "heading": TypeSample(family="Playfair Display", size_px=32, weight=600),
    "body": TypeSample(family="Inter", size_px=16, weight=400),
}


def _typography(**samples: TypeSample) -> SectionTypography:
    return SectionTypography(samples=samples)


def _spacing(
    padding_top: float | None = 96,
    padding_bottom: float | None = 96,
    element_gap: float | None = 24,
) -> SectionSpacing:
    return SectionSpacing(
        spacing=SpacingSample(
            padding_top=padding_top,
            padding_bottom=padding_bottom,
            element_gap=element_gap,
        )
    )


class TestFamilyNormalization:
    @pytest.mark.parametrize(
        "value",
        [
            "Playfair Display",
            "playfair display",
            '"Playfair Display", Georgia, serif',
            "  'Playfair Display' , serif ",
        ],
    )
    def test_equivalent_stacks_normalize_together(self, value: str) -> None:
        assert normalize_family(value) == "playfair display"

    def test_different_families_stay_distinct(self) -> None:
        assert normalize_family("Inter") != normalize_family("Lato")


class TestExactScale:
    def test_identical_typography_scores_100(self) -> None:
        design = _typography(**DESIGN_SCALE)

        result = score_section_typography(design, design)

        assert result.dimension is FidelityDimension.TYPOGRAPHY
        assert result.score == 100.0
        assert result.detail is None

    def test_scale_ratio_reports_the_designed_scale(self) -> None:
        design = _typography(**DESIGN_SCALE)

        assert type_scale_ratio(design, "display") == 4.0
        assert type_scale_ratio(design, "heading") == 2.0
        assert type_scale_ratio(design, "body") == 1.0


class TestCompressedScale:
    def test_compressed_scale_scores_below_exact(self) -> None:
        design = _typography(**DESIGN_SCALE)
        compressed = _typography(
            display=TypeSample(family="Playfair Display", size_px=28, weight=700),
            heading=TypeSample(family="Playfair Display", size_px=22, weight=600),
            body=TypeSample(family="Inter", size_px=16, weight=400),
        )

        result = score_section_typography(design, compressed)

        assert result.score is not None
        assert result.score < 100.0

    def test_compression_is_visible_in_the_scale_ratio(self) -> None:
        compressed = _typography(
            display=TypeSample(family="Playfair Display", size_px=28, weight=700),
            body=TypeSample(family="Inter", size_px=16, weight=400),
        )

        assert type_scale_ratio(compressed, "display") == 1.75

    def test_larger_roles_drift_more_under_compression(self) -> None:
        design = _typography(**DESIGN_SCALE)
        compressed = _typography(
            display=TypeSample(family="Playfair Display", size_px=28, weight=700),
            heading=TypeSample(family="Playfair Display", size_px=22, weight=600),
            body=TypeSample(family="Inter", size_px=16, weight=400),
        )

        display_only = score_section_typography(
            _typography(display=DESIGN_SCALE["display"]),
            _typography(display=compressed.samples["display"]),
        ).score
        body_only = score_section_typography(
            _typography(body=DESIGN_SCALE["body"]),
            _typography(body=compressed.samples["body"]),
        ).score

        assert display_only is not None and body_only is not None
        assert display_only < body_only
        assert body_only == 100.0
        # The whole-section score sits between the two extremes.
        overall = score_section_typography(design, compressed).score
        assert overall is not None
        assert display_only < overall < body_only


class TestSubstitutedFamily:
    def test_substituted_family_scores_zero_for_family(self) -> None:
        expected = _typography(body=TypeSample(family="Inter", size_px=16, weight=400))
        substituted = _typography(
            body=TypeSample(family="Arial", size_px=16, weight=400)
        )

        result = score_section_typography(expected, substituted)

        assert result.score == pytest.approx(
            SIZE_WEIGHT * 100 + WEIGHT_WEIGHT * 100, abs=0.05
        )
        assert "family mismatch in body" in (result.detail or "")

    def test_refused_substitution_is_unavailable_not_a_failure(self) -> None:
        expected = _typography(body=TypeSample(family="Genova", size_px=16, weight=400))
        refused = _typography(
            body=TypeSample(size_px=16, weight=400, substitution_refused=True)
        )

        result = score_section_typography(expected, refused)

        # Size and weight are correct, so the section scores 100 rather than
        # being penalised for the pipeline correctly declining to guess.
        assert result.score == 100.0
        assert "font substitution refused for body" in (result.detail or "")
        assert "family mismatch" not in (result.detail or "")

    def test_refusal_scores_higher_than_a_wrong_substitute(self) -> None:
        expected = _typography(body=TypeSample(family="Genova", size_px=16, weight=400))
        refused = score_section_typography(
            expected,
            _typography(body=TypeSample(size_px=16, weight=400, substitution_refused=True)),
        ).score
        wrong = score_section_typography(
            expected, _typography(body=TypeSample(family="Arial", size_px=16, weight=400))
        ).score

        assert refused is not None and wrong is not None
        assert refused > wrong


class TestWeightAndSize:
    def test_weight_mismatch_reduces_the_score(self) -> None:
        expected = _typography(body=TypeSample(family="Inter", size_px=16, weight=400))
        heavier = _typography(body=TypeSample(family="Inter", size_px=16, weight=700))

        result = score_section_typography(expected, heavier)

        assert result.score == pytest.approx(
            FAMILY_WEIGHT * 100 + SIZE_WEIGHT * 100 + WEIGHT_WEIGHT * (400 / 7),
            abs=0.05,
        )

    def test_closer_size_scores_higher(self) -> None:
        expected = _typography(body=TypeSample(family="Inter", size_px=16))
        near = score_section_typography(
            expected, _typography(body=TypeSample(family="Inter", size_px=15))
        ).score
        far = score_section_typography(
            expected, _typography(body=TypeSample(family="Inter", size_px=8))
        ).score

        assert near is not None and far is not None
        assert near > far

    def test_sub_weights_sum_to_one(self) -> None:
        assert FAMILY_WEIGHT + SIZE_WEIGHT + WEIGHT_WEIGHT == pytest.approx(1.0)


class TestTypographyMissingEvidence:
    def test_role_absent_from_the_build_is_unmeasured(self) -> None:
        expected = _typography(**DESIGN_SCALE)
        partial = _typography(body=DESIGN_SCALE["body"])

        result = score_section_typography(expected, partial)

        assert result.score == 100.0
        assert "no type evidence for display, heading" in (result.detail or "")

    def test_no_shared_role_yields_unavailable(self) -> None:
        result = score_section_typography(
            _typography(display=DESIGN_SCALE["display"]),
            _typography(body=DESIGN_SCALE["body"]),
        )

        assert result.score is None

    def test_empty_typography_yields_unavailable(self) -> None:
        assert score_section_typography(SectionTypography(), SectionTypography()).score is None

    def test_scale_ratio_is_none_without_evidence(self) -> None:
        assert type_scale_ratio(_typography(body=TypeSample()), "display") is None
        assert type_scale_ratio(_typography(display=TypeSample(size_px=48)), "display") is None


class TestSpacing:
    def test_identical_spacing_scores_100(self) -> None:
        result = score_section_spacing(_spacing(), _spacing())

        assert result.dimension is FidelityDimension.SPACING
        assert result.score == 100.0
        assert result.detail is None

    def test_halved_padding_reduces_the_score(self) -> None:
        result = score_section_spacing(_spacing(), _spacing(padding_top=48, padding_bottom=48))

        assert result.score == pytest.approx(
            PADDING_WEIGHT * 50 + RHYTHM_WEIGHT * 100, abs=0.05
        )

    def test_rhythm_drift_reduces_the_score(self) -> None:
        result = score_section_spacing(_spacing(), _spacing(element_gap=12))

        assert result.score == pytest.approx(
            PADDING_WEIGHT * 100 + RHYTHM_WEIGHT * 50, abs=0.05
        )

    def test_padding_outweighs_rhythm(self) -> None:
        assert PADDING_WEIGHT > RHYTHM_WEIGHT
        assert PADDING_WEIGHT + RHYTHM_WEIGHT == pytest.approx(1.0)

    def test_zero_padding_on_both_sides_is_a_match(self) -> None:
        flush = _spacing(padding_top=0, padding_bottom=0)

        assert score_section_spacing(flush, flush).score == 100.0

    def test_padding_removed_entirely_scores_zero_padding_not_unavailable(self) -> None:
        # Zero is a measurement. Treating it as missing evidence would drop a
        # section whose spacing was stripped out of the score entirely.
        result = score_section_spacing(_spacing(), _spacing(padding_top=0, padding_bottom=0))

        assert result.score == pytest.approx(RHYTHM_WEIGHT * 100, abs=0.05)
        assert "no spacing evidence" not in (result.detail or "")

    def test_missing_spacing_evidence_is_unavailable(self) -> None:
        result = score_section_spacing(
            _spacing(), _spacing(padding_top=None, padding_bottom=None, element_gap=None)
        )

        assert result.score is None
        assert "no spacing evidence for" in (result.detail or "")

    def test_partial_spacing_evidence_uses_what_is_available(self) -> None:
        result = score_section_spacing(_spacing(), _spacing(element_gap=None))

        assert result.score == 100.0
        assert result.detail == "no spacing evidence for element-gap"


class TestDeterminism:
    def test_repeated_typography_scoring_is_identical(self) -> None:
        expected = _typography(**DESIGN_SCALE)
        observed = _typography(
            display=TypeSample(family="Arial", size_px=60, weight=700),
            heading=TypeSample(family="Playfair Display", size_px=32, weight=600),
            body=TypeSample(family="Inter", size_px=16, weight=400),
        )

        first = score_section_typography(expected, observed)
        second = score_section_typography(expected, observed)

        assert (first.score, first.detail) == (second.score, second.detail)

    def test_repeated_spacing_scoring_is_identical(self) -> None:
        first = score_section_spacing(_spacing(), _spacing(element_gap=18))
        second = score_section_spacing(_spacing(), _spacing(element_gap=18))

        assert (first.score, first.detail) == (second.score, second.detail)
