"""VF-001 — deterministic fidelity score contracts and regime versioning."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from vanjaro_cli.design.fidelity import (
    CURRENT_REGIME_VERSION,
    DIMENSION_WEIGHTS,
    BreakpointFidelityScore,
    DimensionScore,
    FidelityDimension,
    RegimeMismatchError,
    SectionFidelityScore,
    UnavailableScoreError,
    aggregate_breakpoint,
    build_fidelity_report,
    serialize_fidelity_report,
    to_viewport_visual_score,
)
from vanjaro_cli.design.models import BreakpointName


def _dimensions(value: float | None = 80.0) -> tuple[DimensionScore, ...]:
    return tuple(
        DimensionScore(dimension=dimension, score=value) for dimension in FidelityDimension
    )


def _section(
    section_id: str = "hero",
    *,
    breakpoint: BreakpointName = BreakpointName.DESKTOP,
    regime: int = CURRENT_REGIME_VERSION,
    dimensions: tuple[DimensionScore, ...] | None = None,
) -> SectionFidelityScore:
    return SectionFidelityScore(
        regime_version=regime,
        section_id=section_id,
        breakpoint=breakpoint,
        dimensions=dimensions if dimensions is not None else _dimensions(),
    )


class TestRegimeVersioning:
    def test_every_record_carries_a_regime_version(self) -> None:
        section = _section()
        breakpoint = aggregate_breakpoint(BreakpointName.DESKTOP, [section])
        report = build_fidelity_report("home", [breakpoint])

        assert section.regime_version == CURRENT_REGIME_VERSION
        assert breakpoint.regime_version == CURRENT_REGIME_VERSION
        assert report.regime_version == CURRENT_REGIME_VERSION

    def test_aggregating_across_regimes_raises(self) -> None:
        sections = [_section("hero", regime=1), _section("cta", regime=2)]

        with pytest.raises(RegimeMismatchError) as excinfo:
            aggregate_breakpoint(BreakpointName.DESKTOP, sections)

        assert excinfo.value.versions == (1, 2)
        assert "Re-score every baseline" in str(excinfo.value)

    def test_report_rejects_mixed_regime_breakpoints(self) -> None:
        desktop = aggregate_breakpoint(
            BreakpointName.DESKTOP, [_section("hero", regime=1)]
        )
        mobile = aggregate_breakpoint(
            BreakpointName.MOBILE,
            [_section("hero", breakpoint=BreakpointName.MOBILE, regime=2)],
        )

        with pytest.raises(RegimeMismatchError):
            build_fidelity_report("home", [desktop, mobile])

    def test_breakpoint_rejects_section_from_another_regime(self) -> None:
        # Direct construction surfaces the mismatch through pydantic's
        # ValidationError wrapper; the aggregate helpers raise
        # RegimeMismatchError directly. Both refuse to combine regimes.
        with pytest.raises(ValidationError, match="different regimes"):
            BreakpointFidelityScore(
                regime_version=1,
                breakpoint=BreakpointName.DESKTOP,
                sections=(_section(regime=2),),
            )


class TestScoreBoundaries:
    @pytest.mark.parametrize("value", [0.0, 100.0])
    def test_boundary_scores_are_preserved(self, value: float) -> None:
        section = _section(dimensions=_dimensions(value))

        assert section.score == value
        assert section.measured is True

    def test_score_outside_range_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            DimensionScore(dimension=FidelityDimension.LAYOUT, score=100.1)

        with pytest.raises(ValueError):
            DimensionScore(dimension=FidelityDimension.LAYOUT, score=-0.1)

    def test_weights_are_declared_once_and_cover_every_dimension(self) -> None:
        assert set(DIMENSION_WEIGHTS) == set(FidelityDimension)
        assert sum(DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)

    def test_weighted_mean_reflects_declared_weights(self) -> None:
        dimensions = (
            DimensionScore(dimension=FidelityDimension.LAYOUT, score=100.0),
            DimensionScore(dimension=FidelityDimension.COLOR, score=0.0),
        )
        section = _section(dimensions=dimensions)

        layout = DIMENSION_WEIGHTS[FidelityDimension.LAYOUT]
        color = DIMENSION_WEIGHTS[FidelityDimension.COLOR]
        assert section.score == pytest.approx(100 * layout / (layout + color))


class TestUnavailableEvidence:
    def test_unmeasured_dimension_is_excluded_not_counted_as_zero(self) -> None:
        dimensions = (
            DimensionScore(dimension=FidelityDimension.LAYOUT, score=90.0),
            DimensionScore(dimension=FidelityDimension.COLOR, score=None),
        )

        assert _section(dimensions=dimensions).score == 90.0

    def test_section_with_no_measurable_dimension_is_unmeasured(self) -> None:
        section = _section(dimensions=_dimensions(None))

        assert section.score is None
        assert section.measured is False
        with pytest.raises(UnavailableScoreError):
            section.require_score()

    def test_breakpoint_reports_unmeasured_sections(self) -> None:
        breakpoint = aggregate_breakpoint(
            BreakpointName.DESKTOP,
            [_section("hero"), _section("cta", dimensions=_dimensions(None))],
        )

        assert breakpoint.unmeasured_section_ids == ("cta",)
        # The measured section still scores; absence is reported, not averaged in.
        assert breakpoint.overall_score == 80.0


class TestIntegrityOverride:
    def test_forces_zero_overrides_every_other_dimension(self) -> None:
        dimensions = (
            DimensionScore(dimension=FidelityDimension.LAYOUT, score=100.0),
            DimensionScore(
                dimension=FidelityDimension.INTEGRITY,
                score=0.0,
                forces_zero=True,
                detail="placeholder text leaked into the published section",
            ),
        )

        assert _section(dimensions=dimensions).score == 0.0

    def test_forces_zero_requires_a_detail(self) -> None:
        with pytest.raises(ValueError, match="detail"):
            DimensionScore(
                dimension=FidelityDimension.INTEGRITY, score=0.0, forces_zero=True
            )


class TestDeterminism:
    def test_repeated_serialization_is_byte_identical(self) -> None:
        def build() -> str:
            desktop = aggregate_breakpoint(
                BreakpointName.DESKTOP, [_section("cta"), _section("hero")]
            )
            mobile = aggregate_breakpoint(
                BreakpointName.MOBILE,
                [
                    _section("hero", breakpoint=BreakpointName.MOBILE),
                    _section("cta", breakpoint=BreakpointName.MOBILE),
                ],
            )
            return serialize_fidelity_report(build_fidelity_report("home", [mobile, desktop]))

        assert build() == build()

    def test_serialization_ends_with_a_single_newline(self) -> None:
        report = build_fidelity_report(
            "home", [aggregate_breakpoint(BreakpointName.DESKTOP, [_section()])]
        )
        serialized = serialize_fidelity_report(report)

        assert serialized.endswith("}\n")
        assert not serialized.endswith("\n\n")

    def test_input_order_does_not_change_output(self) -> None:
        first = aggregate_breakpoint(
            BreakpointName.DESKTOP, [_section("alpha"), _section("beta")]
        )
        second = aggregate_breakpoint(
            BreakpointName.DESKTOP, [_section("beta"), _section("alpha")]
        )

        assert serialize_fidelity_report(
            build_fidelity_report("home", [first])
        ) == serialize_fidelity_report(build_fidelity_report("home", [second]))

    def test_breakpoints_serialize_in_canonical_order(self) -> None:
        report = build_fidelity_report(
            "home",
            [
                aggregate_breakpoint(
                    BreakpointName.MOBILE,
                    [_section(breakpoint=BreakpointName.MOBILE)],
                ),
                aggregate_breakpoint(BreakpointName.DESKTOP, [_section()]),
            ],
        )

        assert [entry.breakpoint for entry in report.breakpoints] == [
            BreakpointName.DESKTOP,
            BreakpointName.MOBILE,
        ]


class TestGateBridge:
    def test_adapts_to_the_gate_score_contract(self) -> None:
        breakpoint = aggregate_breakpoint(
            BreakpointName.DESKTOP, [_section("hero"), _section("cta")]
        )

        viewport_score = to_viewport_visual_score(breakpoint)

        assert viewport_score.breakpoint == BreakpointName.DESKTOP
        assert viewport_score.overall_score == 80.0
        assert {section.section_id for section in viewport_score.sections} == {
            "hero",
            "cta",
        }

    def test_unmeasured_section_cannot_reach_the_gate(self) -> None:
        breakpoint = aggregate_breakpoint(
            BreakpointName.DESKTOP,
            [_section("hero"), _section("cta", dimensions=_dimensions(None))],
        )

        with pytest.raises(UnavailableScoreError, match="cta"):
            to_viewport_visual_score(breakpoint)


class TestStructuralValidation:
    def test_duplicate_dimension_is_rejected(self) -> None:
        duplicate = (
            DimensionScore(dimension=FidelityDimension.LAYOUT, score=10.0),
            DimensionScore(dimension=FidelityDimension.LAYOUT, score=20.0),
        )

        with pytest.raises(ValueError, match="at most once"):
            _section(dimensions=duplicate)

    def test_section_breakpoint_must_match_its_group(self) -> None:
        with pytest.raises(ValueError, match="must share the breakpoint"):
            BreakpointFidelityScore(
                regime_version=CURRENT_REGIME_VERSION,
                breakpoint=BreakpointName.MOBILE,
                sections=(_section(breakpoint=BreakpointName.DESKTOP),),
            )

    def test_duplicate_section_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            BreakpointFidelityScore(
                regime_version=CURRENT_REGIME_VERSION,
                breakpoint=BreakpointName.DESKTOP,
                sections=(_section("hero"), _section("hero")),
            )

    def test_models_are_frozen_and_reject_unknown_fields(self) -> None:
        section = _section()

        with pytest.raises(ValueError):
            section.section_id = "other"  # type: ignore[misc]

        with pytest.raises(ValueError):
            DimensionScore(
                dimension=FidelityDimension.LAYOUT, score=1.0, unexpected=True
            )


def _dimension(dimension: FidelityDimension, score: float | None) -> DimensionScore:
    return DimensionScore(dimension=dimension, score=score)


def _section_with(scores: dict[FidelityDimension, float | None]) -> SectionFidelityScore:
    return SectionFidelityScore(
        regime_version=CURRENT_REGIME_VERSION,
        section_id="page.section.1",
        breakpoint=BreakpointName.DESKTOP,
        dimensions=tuple(
            _dimension(dimension, score) for dimension, score in scores.items()
        ),
    )


def test_coverage_counts_only_the_dimensions_that_contributed() -> None:
    section = _section_with(
        {
            FidelityDimension.LAYOUT: 80.0,
            FidelityDimension.COLOR: 60.0,
            FidelityDimension.TYPOGRAPHY: None,
            FidelityDimension.SPACING: None,
            FidelityDimension.MEDIA: None,
            FidelityDimension.INTEGRITY: 90.0,
        }
    )

    assert section.measured_dimensions == 3
    assert section.dimension_coverage == 0.5


def test_a_higher_score_on_less_evidence_is_distinguishable() -> None:
    """The reason this exists: renormalizing hides how much was measured.

    A viewport scoring 90 on two dimensions must not read as more trustworthy
    than one scoring 60 on five, which is what the score alone implies.
    """

    thin = _section_with(
        {FidelityDimension.LAYOUT: 90.0, FidelityDimension.INTEGRITY: 90.0}
    )
    thorough = _section_with(
        {
            FidelityDimension.LAYOUT: 60.0,
            FidelityDimension.COLOR: 60.0,
            FidelityDimension.TYPOGRAPHY: 60.0,
            FidelityDimension.SPACING: 60.0,
            FidelityDimension.INTEGRITY: 60.0,
        }
    )

    assert thin.score > thorough.score
    assert thin.dimension_coverage < thorough.dimension_coverage


def test_a_section_measuring_nothing_reports_zero_coverage() -> None:
    section = _section_with(
        {FidelityDimension.LAYOUT: None, FidelityDimension.COLOR: None}
    )

    assert section.score is None
    assert section.measured_dimensions == 0
    assert section.dimension_coverage == 0.0


def test_breakpoint_coverage_is_the_mean_of_its_sections() -> None:
    full = _section_with(
        {dimension: 70.0 for dimension in FidelityDimension}
    )
    half = _section_with(
        {
            FidelityDimension.LAYOUT: 70.0,
            FidelityDimension.COLOR: 70.0,
            FidelityDimension.TYPOGRAPHY: 70.0,
            FidelityDimension.SPACING: None,
            FidelityDimension.MEDIA: None,
            FidelityDimension.INTEGRITY: None,
        }
    )
    half = half.model_copy(update={"section_id": "page.section.2"})

    aggregated = aggregate_breakpoint(BreakpointName.DESKTOP, [full, half])

    assert aggregated.dimension_coverage == 0.75


def test_coverage_does_not_change_any_score() -> None:
    """Coverage reports the regime; it must never participate in it."""

    section = _section_with(
        {FidelityDimension.LAYOUT: 80.0, FidelityDimension.COLOR: 40.0}
    )

    assert section.score == pytest.approx(
        (80.0 * DIMENSION_WEIGHTS[FidelityDimension.LAYOUT]
         + 40.0 * DIMENSION_WEIGHTS[FidelityDimension.COLOR])
        / (DIMENSION_WEIGHTS[FidelityDimension.LAYOUT]
           + DIMENSION_WEIGHTS[FidelityDimension.COLOR]),
        abs=0.01,
    )
