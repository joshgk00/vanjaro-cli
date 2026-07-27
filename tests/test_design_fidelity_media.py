"""VF-005 — media and integrity fidelity metrics."""

from __future__ import annotations

import pytest

from vanjaro_cli.design.fidelity import (
    CURRENT_REGIME_VERSION,
    FidelityDimension,
    SectionFidelityScore,
)
from vanjaro_cli.design.fidelity_media import (
    ASPECT_WEIGHT,
    CONSOLE_ERROR_PENALTY,
    CROP_WEIGHT,
    EMPTY_SLOT_PENALTY,
    FOCAL_WEIGHT,
    MAX_FOCAL_DISTANCE,
    OVERFLOW_PENALTY,
    OVERFLOW_TOLERANCE_PX,
    IntegrityObservation,
    MediaSample,
    SectionMedia,
    score_section_integrity,
    score_section_media,
)
from vanjaro_cli.design.models import BreakpointName


def _sample(
    aspect_ratio: float | None = 1.5,
    focal_x: float | None = 0.5,
    focal_y: float | None = 0.5,
    crop_coverage: float | None = 1.0,
) -> MediaSample:
    return MediaSample(
        aspect_ratio=aspect_ratio,
        focal_x=focal_x,
        focal_y=focal_y,
        crop_coverage=crop_coverage,
    )


def _media(**samples: MediaSample) -> SectionMedia:
    return SectionMedia(media=samples)


def _clean() -> IntegrityObservation:
    return IntegrityObservation(
        horizontal_overflow_px=0.0, empty_slot_count=0, console_error_count=0
    )


class TestCorrectCrop:
    def test_identical_media_scores_100(self) -> None:
        section = _media(hero=_sample())

        result = score_section_media(section, section)

        assert result.dimension is FidelityDimension.MEDIA
        assert result.score == 100.0
        assert result.detail is None

    def test_uncropped_matching_image_scores_full_crop(self) -> None:
        result = score_section_media(
            _media(hero=_sample(crop_coverage=1.0)),
            _media(hero=_sample(crop_coverage=1.0)),
        )

        assert result.score == 100.0

    def test_heavier_crop_scores_lower(self) -> None:
        expected = _media(hero=_sample(crop_coverage=1.0))
        light = score_section_media(
            expected, _media(hero=_sample(crop_coverage=0.9))
        ).score
        heavy = score_section_media(
            expected, _media(hero=_sample(crop_coverage=0.4))
        ).score

        assert light is not None and heavy is not None
        assert light > heavy


class TestAspectRatio:
    def test_aspect_change_reduces_the_score(self) -> None:
        result = score_section_media(
            _media(hero=_sample(aspect_ratio=1.5)),
            _media(hero=_sample(aspect_ratio=1.0)),
        )

        assert result.score == pytest.approx(
            ASPECT_WEIGHT * (100 * 1.0 / 1.5) + FOCAL_WEIGHT * 100 + CROP_WEIGHT * 100,
            abs=0.05,
        )

    def test_closer_aspect_scores_higher(self) -> None:
        expected = _media(hero=_sample(aspect_ratio=1.5))
        near = score_section_media(expected, _media(hero=_sample(aspect_ratio=1.4))).score
        far = score_section_media(expected, _media(hero=_sample(aspect_ratio=0.5))).score

        assert near is not None and far is not None
        assert near > far


class TestFocalPoint:
    def test_matching_focal_point_scores_full(self) -> None:
        result = score_section_media(
            _media(hero=_sample(focal_x=0.3, focal_y=0.7)),
            _media(hero=_sample(focal_x=0.3, focal_y=0.7)),
        )

        assert result.score == 100.0

    def test_wrong_focal_point_reduces_the_score(self) -> None:
        result = score_section_media(
            _media(hero=_sample(focal_x=0.5, focal_y=0.5)),
            _media(hero=_sample(focal_x=0.5, focal_y=0.8)),
        )

        expected_focal = 100 * (1 - 0.3 / MAX_FOCAL_DISTANCE)
        assert result.score == pytest.approx(
            ASPECT_WEIGHT * 100 + FOCAL_WEIGHT * expected_focal + CROP_WEIGHT * 100,
            abs=0.05,
        )

    def test_focal_point_beyond_the_cap_scores_zero(self) -> None:
        result = score_section_media(
            _media(hero=_sample(focal_x=0.0, focal_y=0.0)),
            _media(hero=_sample(focal_x=1.0, focal_y=1.0)),
        )

        assert result.score == pytest.approx(
            ASPECT_WEIGHT * 100 + CROP_WEIGHT * 100, abs=0.05
        )

    def test_sub_weights_sum_to_one(self) -> None:
        assert ASPECT_WEIGHT + FOCAL_WEIGHT + CROP_WEIGHT == pytest.approx(1.0)


class TestMissingMedia:
    def test_designed_image_absent_from_the_build_scores_zero(self) -> None:
        result = score_section_media(_media(hero=_sample()), _media())

        assert result.score == 0.0
        assert "media absent from the build: hero" in (result.detail or "")

    def test_one_missing_image_among_several_drags_the_mean(self) -> None:
        result = score_section_media(
            _media(hero=_sample(), inset=_sample()), _media(hero=_sample())
        )

        assert result.score == 50.0

    def test_unmeasurable_media_is_unavailable_not_zero(self) -> None:
        blank = MediaSample()

        result = score_section_media(_media(hero=blank), _media(hero=blank))

        assert result.score is None
        assert "no media evidence for hero" in (result.detail or "")

    def test_extra_built_media_is_ignored(self) -> None:
        result = score_section_media(
            _media(hero=_sample()), _media(hero=_sample(), bonus=_sample())
        )

        assert result.score == 100.0


class TestIntegrityClean:
    def test_clean_section_scores_100(self) -> None:
        result = score_section_integrity(_clean())

        assert result.dimension is FidelityDimension.INTEGRITY
        assert result.score == 100.0
        assert result.forces_zero is False
        assert result.detail is None


class TestOverflow:
    def test_horizontal_overflow_is_penalised(self) -> None:
        result = score_section_integrity(
            IntegrityObservation(
                horizontal_overflow_px=24.0, empty_slot_count=0, console_error_count=0
            )
        )

        assert result.score == pytest.approx(100 - OVERFLOW_PENALTY)
        assert "horizontal overflow of 24px" in (result.detail or "")

    def test_sub_pixel_overflow_is_tolerated(self) -> None:
        result = score_section_integrity(
            IntegrityObservation(
                horizontal_overflow_px=OVERFLOW_TOLERANCE_PX,
                empty_slot_count=0,
                console_error_count=0,
            )
        )

        assert result.score == 100.0


class TestEmptySlotsAndConsoleErrors:
    def test_empty_slots_are_penalised_per_slot(self) -> None:
        result = score_section_integrity(
            IntegrityObservation(
                horizontal_overflow_px=0, empty_slot_count=2, console_error_count=0
            )
        )

        assert result.score == pytest.approx(100 - 2 * EMPTY_SLOT_PENALTY)

    def test_console_errors_are_penalised_per_error(self) -> None:
        result = score_section_integrity(
            IntegrityObservation(
                horizontal_overflow_px=0, empty_slot_count=0, console_error_count=3
            )
        )

        assert result.score == pytest.approx(100 - 3 * CONSOLE_ERROR_PENALTY)

    def test_penalties_accumulate_and_floor_at_zero(self) -> None:
        result = score_section_integrity(
            IntegrityObservation(
                horizontal_overflow_px=50, empty_slot_count=4, console_error_count=5
            )
        )

        assert result.score == 0.0
        assert result.forces_zero is False


class TestPlaceholderLeakage:
    def test_leakage_forces_zero(self) -> None:
        result = score_section_integrity(
            IntegrityObservation(
                horizontal_overflow_px=0,
                empty_slot_count=0,
                console_error_count=0,
                placeholder_leaks=("Lorem ipsum dolor",),
            )
        )

        assert result.score == 0.0
        assert result.forces_zero is True
        assert "placeholder content leaked" in (result.detail or "")

    def test_leakage_overrides_an_otherwise_clean_section(self) -> None:
        # Every other signal is perfect; the section must still score zero.
        section = SectionFidelityScore(
            regime_version=CURRENT_REGIME_VERSION,
            section_id="hero",
            breakpoint=BreakpointName.DESKTOP,
            dimensions=(
                score_section_media(_media(hero=_sample()), _media(hero=_sample())),
                score_section_integrity(
                    IntegrityObservation(
                        horizontal_overflow_px=0,
                        empty_slot_count=0,
                        console_error_count=0,
                        placeholder_leaks=("[placeholder image]",),
                    )
                ),
            ),
        )

        assert section.score == 0.0

    def test_multiple_leaks_are_reported_in_stable_order(self) -> None:
        first = score_section_integrity(
            IntegrityObservation(placeholder_leaks=("zebra", "alpha"))
        )
        second = score_section_integrity(
            IntegrityObservation(placeholder_leaks=("alpha", "zebra"))
        )

        assert first.detail == second.detail
        assert "alpha, zebra" in (first.detail or "")


class TestIntegrityMissingEvidence:
    def test_no_observations_yields_unavailable_not_clean(self) -> None:
        result = score_section_integrity(IntegrityObservation())

        assert result.score is None
        assert "no integrity evidence for" in (result.detail or "")

    def test_partial_observations_score_what_was_seen(self) -> None:
        result = score_section_integrity(
            IntegrityObservation(horizontal_overflow_px=0.0)
        )

        assert result.score == 100.0
        assert "empty-slots" in (result.detail or "")
        assert "console-errors" in (result.detail or "")

    def test_leakage_reports_zero_even_without_other_evidence(self) -> None:
        result = score_section_integrity(
            IntegrityObservation(placeholder_leaks=("Lorem ipsum",))
        )

        assert result.score == 0.0
        assert result.forces_zero is True


class TestDeterminism:
    def test_repeated_media_scoring_is_identical(self) -> None:
        expected = _media(hero=_sample(), inset=_sample(aspect_ratio=1.0))
        observed = _media(hero=_sample(focal_y=0.6), inset=_sample(aspect_ratio=1.2))

        first = score_section_media(expected, observed)
        second = score_section_media(expected, observed)

        assert (first.score, first.detail) == (second.score, second.detail)

    def test_repeated_integrity_scoring_is_identical(self) -> None:
        observation = IntegrityObservation(
            horizontal_overflow_px=12, empty_slot_count=1, console_error_count=2
        )

        first = score_section_integrity(observation)
        second = score_section_integrity(observation)

        assert (first.score, first.detail) == (second.score, second.detail)
