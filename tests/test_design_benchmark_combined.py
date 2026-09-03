"""Tests for the cross-corpus combined offline benchmark report."""

from __future__ import annotations

from vanjaro_cli.design.benchmark_combined import build_combined_report, render_combined_markdown
from vanjaro_cli.design.metrics import (
    AggregateMetrics,
    BenchmarkReport,
    ExtractionMetrics,
    MatcherMetrics,
    MetricScore,
)


def _aggregate_with_precision(value: float) -> AggregateMetrics:
    measured = MetricScore(value=value, numerator=int(value * 100), denominator=100, status="measured")
    return AggregateMetrics(
        extraction=ExtractionMetrics(
            section_boundary_precision=measured,
            section_boundary_recall=measured,
            semantic_role_accuracy=measured,
            visitor_content_retention=measured,
            group_field_association_accuracy=measured,
            asset_association_accuracy=measured,
            responsive_observation_coverage=measured,
        ),
        matcher=MatcherMetrics(
            template_top1_accuracy=measured,
            template_top3_accuracy=measured,
            high_confidence_precision=measured,
        ),
    )


def _not_measurable_aggregate() -> AggregateMetrics:
    empty = MetricScore(value=None, numerator=0, denominator=0, status="not_measurable")
    return AggregateMetrics(
        extraction=ExtractionMetrics(
            section_boundary_precision=empty,
            section_boundary_recall=empty,
            semantic_role_accuracy=empty,
            visitor_content_retention=empty,
            group_field_association_accuracy=empty,
            asset_association_accuracy=empty,
            responsive_observation_coverage=empty,
        ),
        matcher=MatcherMetrics(
            template_top1_accuracy=empty,
            template_top3_accuracy=empty,
            high_confidence_precision=empty,
        ),
    )


def _report(name: str, aggregate: AggregateMetrics, threshold_failures=(), regressions=()) -> BenchmarkReport:
    return BenchmarkReport(
        corpus_name=name,
        case_filter=("case-1",),
        aggregate=aggregate,
        cases=(),
        regressions=regressions,
        threshold_failures=threshold_failures,
    )


def test_combined_report_has_one_row_per_metric_and_one_column_per_corpus() -> None:
    html_report = _report("design-benchmarks", _aggregate_with_precision(0.90))
    image_report = _report("design-image-benchmarks", _aggregate_with_precision(0.80))

    combined = build_combined_report(
        (
            ("design-benchmarks", html_report, True),
            ("design-image-benchmarks", image_report, True),
        )
    )

    expected_metric_names = tuple(ExtractionMetrics.model_fields) + tuple(MatcherMetrics.model_fields)
    assert tuple(row.metric for row in combined.rows) == expected_metric_names
    assert combined.corpora == ("design-benchmarks", "design-image-benchmarks")
    for row in combined.rows:
        assert tuple(cell.corpus for cell in row.cells) == combined.corpora
        assert row.cells[0].value == 0.90
        assert row.cells[1].value == 0.80


def test_overall_passed_is_false_when_any_single_corpus_fails() -> None:
    passing = _report("design-benchmarks", _aggregate_with_precision(0.95))
    failing = _report("design-image-benchmarks", _aggregate_with_precision(0.50))

    combined = build_combined_report(
        (
            ("design-benchmarks", passing, True),
            ("design-image-benchmarks", failing, False),
        )
    )

    assert combined.passed is False
    statuses = {status.corpus: status.passed for status in combined.statuses}
    assert statuses == {"design-benchmarks": True, "design-image-benchmarks": False}


def test_overall_passed_is_true_only_when_every_corpus_passed() -> None:
    both_passing = build_combined_report(
        (
            ("a", _report("a", _aggregate_with_precision(0.95)), True),
            ("b", _report("b", _aggregate_with_precision(0.95)), True),
        )
    )

    assert both_passing.passed is True


def test_threshold_and_regression_failure_counts_are_carried_per_corpus() -> None:
    from vanjaro_cli.design.metrics import RegressionComparison, ThresholdFailure

    failing_threshold = ThresholdFailure(
        metric="template_top1_accuracy", minimum=0.85, actual=0.5, reason="below minimum"
    )
    failing_regression = RegressionComparison(
        metric="section_boundary_precision",
        baseline=0.9,
        current=0.5,
        delta=-0.4,
        tolerance=0.02,
        comparable=True,
        failed=True,
    )
    report = _report(
        "design-benchmarks",
        _aggregate_with_precision(0.5),
        threshold_failures=(failing_threshold,),
        regressions=(failing_regression,),
    )

    combined = build_combined_report((("design-benchmarks", report, False),))

    status = combined.statuses[0]
    assert status.threshold_failure_count == 1
    assert status.regression_failure_count == 1


def test_non_measured_status_renders_as_status_text_not_a_number() -> None:
    report = _report("design-image-benchmarks", _not_measurable_aggregate())

    combined = build_combined_report((("design-image-benchmarks", report, True),))
    markdown = render_combined_markdown(combined)

    assert "not_measurable" in markdown
    for row in combined.rows:
        assert row.cells[0].value is None
        assert row.cells[0].status == "not_measurable"


def test_render_combined_markdown_is_deterministic_across_calls() -> None:
    html_report = _report("design-benchmarks", _aggregate_with_precision(0.9))
    image_report = _report("design-image-benchmarks", _aggregate_with_precision(0.8))
    combined = build_combined_report(
        (
            ("design-benchmarks", html_report, True),
            ("design-image-benchmarks", image_report, True),
        )
    )

    first = render_combined_markdown(combined)
    second = render_combined_markdown(combined)

    assert first == second
    assert "design-benchmarks" in first
    assert "design-image-benchmarks" in first
