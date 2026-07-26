"""VF-002 — layout and geometry fidelity metric."""

from __future__ import annotations

import pytest

from vanjaro_cli.design.fidelity import DimensionScore, FidelityDimension
from vanjaro_cli.design.fidelity_layout import (
    BOUNDS_WEIGHT,
    COLUMNS_WEIGHT,
    ORDER_WEIGHT,
    PageGeometry,
    SectionGeometry,
    normalized_iou,
    score_page_layout,
    score_section_layout,
)
from vanjaro_cli.design.models import BoundingBox


def _box(x: float = 0, y: float = 0, width: float = 1440, height: float = 600) -> BoundingBox:
    return BoundingBox(x=x, y=y, width=width, height=height)


_DEFAULT = object()


def _section(
    section_id: str = "hero",
    *,
    order: int = 0,
    bounds: BoundingBox | None | object = _DEFAULT,
    columns: int | None = 3,
) -> SectionGeometry:
    # A sentinel distinguishes "caller omitted bounds" from "caller explicitly
    # passed None", which is exactly the missing-geometry case under test.
    return SectionGeometry(
        section_id=section_id,
        order=order,
        bounds=_box() if bounds is _DEFAULT else bounds,
        columns=columns,
    )


def _score(
    expected: SectionGeometry,
    observed: SectionGeometry | None,
    *,
    section_count: int = 4,
    expected_width: float = 1440,
    observed_width: float = 1440,
) -> DimensionScore:
    return score_section_layout(
        expected,
        observed,
        expected_viewport_width=expected_width,
        observed_viewport_width=observed_width,
        section_count=section_count,
    )


class TestExactMatch:
    def test_identical_geometry_scores_100(self) -> None:
        result = _score(_section(), _section())

        assert result.dimension is FidelityDimension.LAYOUT
        assert result.score == 100.0
        assert result.detail is None

    def test_proportionally_identical_layout_at_another_width_scores_100(self) -> None:
        expected = _section(bounds=_box(0, 0, 1440, 600))
        observed = _section(bounds=_box(0, 0, 1280, 533.3333))

        result = _score(expected, observed, expected_width=1440, observed_width=1280)

        assert result.score == pytest.approx(100.0, abs=0.05)


class TestShiftedAndResized:
    def test_shifted_section_loses_points(self) -> None:
        expected = _section(bounds=_box(0, 0, 1440, 600))
        shifted = _section(bounds=_box(0, 300, 1440, 600))

        result = _score(expected, shifted)

        # Half the height overlaps, so IoU is 1/3.
        assert result.score is not None
        assert result.score < 100.0
        expected_bounds = 100.0 / 3
        assert result.score == pytest.approx(
            (BOUNDS_WEIGHT * expected_bounds + COLUMNS_WEIGHT * 100 + ORDER_WEIGHT * 100),
            abs=0.05,
        )

    def test_resized_section_loses_points(self) -> None:
        expected = _section(bounds=_box(0, 0, 1440, 600))
        resized = _section(bounds=_box(0, 0, 720, 600))

        result = _score(expected, resized)

        assert result.score is not None
        assert result.score < 100.0

    def test_disjoint_boxes_score_zero_bounds(self) -> None:
        expected = _section(bounds=_box(0, 0, 100, 100))
        elsewhere = _section(bounds=_box(500, 500, 100, 100))

        result = _score(expected, elsewhere)

        assert result.score == pytest.approx(
            COLUMNS_WEIGHT * 100 + ORDER_WEIGHT * 100, abs=0.05
        )


class TestColumns:
    def test_matching_column_count_scores_full(self) -> None:
        assert _score(_section(columns=3), _section(columns=3)).score == 100.0

    def test_column_mismatch_scores_by_ratio(self) -> None:
        result = _score(_section(columns=3), _section(columns=2))

        assert result.score == pytest.approx(
            BOUNDS_WEIGHT * 100 + COLUMNS_WEIGHT * (200 / 3) + ORDER_WEIGHT * 100,
            abs=0.05,
        )

    def test_closer_column_count_scores_higher(self) -> None:
        near = _score(_section(columns=3), _section(columns=2)).score
        far = _score(_section(columns=3), _section(columns=12)).score

        assert near is not None and far is not None
        assert near > far


class TestOrder:
    def test_reordered_section_loses_points(self) -> None:
        result = _score(_section(order=0), _section(order=3), section_count=4)

        assert result.score == pytest.approx(
            BOUNDS_WEIGHT * 100 + COLUMNS_WEIGHT * 100, abs=0.05
        )

    def test_small_displacement_scores_higher_than_large(self) -> None:
        near = _score(_section(order=0), _section(order=1), section_count=5).score
        far = _score(_section(order=0), _section(order=4), section_count=5).score

        assert near is not None and far is not None
        assert near > far


class TestMissingEvidence:
    def test_absent_section_scores_zero_not_unavailable(self) -> None:
        result = _score(_section(), None)

        assert result.score == 0.0
        assert "absent from the build" in (result.detail or "")

    def test_missing_geometry_is_unavailable_not_zero(self) -> None:
        expected = _section(bounds=None, columns=None)
        observed = _section(bounds=None, columns=None)

        result = _score(expected, observed)

        # Only order remains measurable, so the section still scores on order
        # alone rather than being penalised for absent evidence.
        assert result.score == 100.0
        assert "no geometry evidence for bounds, columns" == result.detail

    def test_partial_geometry_uses_only_available_subscores(self) -> None:
        expected = _section(bounds=_box(), columns=None)
        observed = _section(bounds=_box(0, 300, 1440, 600), columns=None)

        result = _score(expected, observed)

        assert result.score == pytest.approx(
            (BOUNDS_WEIGHT * (100 / 3) + ORDER_WEIGHT * 100)
            / (BOUNDS_WEIGHT + ORDER_WEIGHT),
            abs=0.05,
        )
        assert result.detail == "no geometry evidence for columns"

    def test_one_sided_geometry_is_unavailable(self) -> None:
        result = _score(_section(bounds=_box()), _section(bounds=None))

        assert "bounds" in (result.detail or "")


class TestNormalizedIou:
    def test_identical_boxes(self) -> None:
        value = normalized_iou(
            _box(), _box(), expected_viewport_width=1440, observed_viewport_width=1440
        )
        assert value == 1.0

    def test_disjoint_boxes(self) -> None:
        value = normalized_iou(
            _box(0, 0, 10, 10),
            _box(100, 100, 10, 10),
            expected_viewport_width=1440,
            observed_viewport_width=1440,
        )
        assert value == 0.0

    def test_degenerate_boxes_match_only_at_the_same_origin(self) -> None:
        same = normalized_iou(
            _box(5, 5, 0, 0),
            _box(5, 5, 0, 0),
            expected_viewport_width=1440,
            observed_viewport_width=1440,
        )
        different = normalized_iou(
            _box(5, 5, 0, 0),
            _box(6, 6, 0, 0),
            expected_viewport_width=1440,
            observed_viewport_width=1440,
        )

        assert same == 1.0
        assert different == 0.0

    def test_is_symmetric(self) -> None:
        first = normalized_iou(
            _box(0, 0, 100, 100),
            _box(50, 0, 100, 100),
            expected_viewport_width=1000,
            observed_viewport_width=1000,
        )
        second = normalized_iou(
            _box(50, 0, 100, 100),
            _box(0, 0, 100, 100),
            expected_viewport_width=1000,
            observed_viewport_width=1000,
        )

        assert first == second


class TestPageScoring:
    def test_scores_every_designed_section(self) -> None:
        expected = PageGeometry(
            viewport_width=1440,
            sections=(_section("hero", order=0), _section("cta", order=1)),
        )
        observed = PageGeometry(
            viewport_width=1440,
            sections=(_section("hero", order=0), _section("cta", order=1)),
        )

        results = score_page_layout(expected, observed)

        assert set(results) == {"hero", "cta"}
        assert all(entry.score == 100.0 for entry in results.values())

    def test_missing_section_in_build_scores_zero(self) -> None:
        expected = PageGeometry(
            viewport_width=1440,
            sections=(_section("hero", order=0), _section("cta", order=1)),
        )
        observed = PageGeometry(viewport_width=1440, sections=(_section("hero", order=0),))

        results = score_page_layout(expected, observed)

        assert results["hero"].score == 100.0
        assert results["cta"].score == 0.0

    def test_extra_built_section_is_ignored(self) -> None:
        expected = PageGeometry(viewport_width=1440, sections=(_section("hero", order=0),))
        observed = PageGeometry(
            viewport_width=1440,
            sections=(_section("hero", order=0), _section("bonus", order=1)),
        )

        assert set(score_page_layout(expected, observed)) == {"hero"}

    def test_duplicate_section_ids_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            PageGeometry(
                viewport_width=1440, sections=(_section("hero"), _section("hero"))
            )


class TestDeterminism:
    def test_repeated_scoring_is_identical(self) -> None:
        expected = PageGeometry(
            viewport_width=1440,
            sections=(_section("hero", order=0), _section("cta", order=1)),
        )
        observed = PageGeometry(
            viewport_width=1440,
            sections=(_section("cta", order=1), _section("hero", order=2)),
        )

        first = score_page_layout(expected, observed)
        second = score_page_layout(expected, observed)

        assert {k: v.score for k, v in first.items()} == {
            k: v.score for k, v in second.items()
        }

    def test_sub_weights_sum_to_one(self) -> None:
        assert BOUNDS_WEIGHT + COLUMNS_WEIGHT + ORDER_WEIGHT == pytest.approx(1.0)
