"""Deterministic performance-budget contract tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from vanjaro_cli.reliability.performance import PerformanceEvidence, evaluate_performance


def _evidence(samples: list[float], **budget_overrides: float) -> PerformanceEvidence:
    budget = {
        "max_median_ms": 20,
        "max_p95_ms": 30,
        "baseline_p95_ms": 20,
        "max_regression_ratio": 1.5,
        **budget_overrides,
    }
    return PerformanceEvidence.model_validate(
        {
            "schema_version": "performance-evidence-v1",
            "policy_version": "agency-performance-v1",
            "environment": {
                "python_version": "3.11",
                "implementation": "CPython",
                "operating_system": "Windows",
                "architecture": "AMD64",
                "corpus_sha256": "a" * 64,
            },
            "warmups": 1,
            "cases": {"analyze": {"samples_ms": samples}},
            "budgets": {"analyze": budget},
        }
    )


def test_performance_report_recomputes_median_p95_and_passes_boundaries() -> None:
    report = evaluate_performance(_evidence([10, 20, 15, 25, 30]))

    assert report.status == "passed"
    assert report.cases["analyze"].median_ms == 20
    assert report.cases["analyze"].p95_ms == 30
    assert report.cases["analyze"].regression_ratio == 1.5


def test_performance_report_names_absolute_and_relative_failures() -> None:
    report = evaluate_performance(
        _evidence(
            [10, 20, 15, 25, 31],
            max_median_ms=19,
            max_p95_ms=30,
            max_regression_ratio=1.5,
        )
    )

    assert report.status == "failed"
    assert set(report.cases["analyze"].failures) == {
        "median-budget-exceeded",
        "p95-budget-exceeded",
        "relative-regression-exceeded",
    }


def test_rounding_never_hides_a_just_over_budget_measurement() -> None:
    report = evaluate_performance(
        _evidence(
            [20.0000004] * 5,
            max_median_ms=20,
            max_p95_ms=20,
            baseline_p95_ms=20,
            max_regression_ratio=1,
        )
    )

    assert report.cases["analyze"].median_ms == 20
    assert report.status == "failed"
    assert set(report.cases["analyze"].failures) == {
        "median-budget-exceeded",
        "p95-budget-exceeded",
        "relative-regression-exceeded",
    }


@pytest.mark.parametrize("sample", [0, -1, float("nan"), float("inf")])
def test_performance_samples_must_be_positive_and_finite(sample: float) -> None:
    with pytest.raises(ValidationError, match="positive finite"):
        _evidence([1, 2, 3, 4, sample])


@pytest.mark.parametrize("budget", [float("nan"), float("inf")])
def test_performance_budgets_must_be_finite(budget: float) -> None:
    with pytest.raises(ValidationError, match="budgets must be finite|greater than 0"):
        _evidence([1, 2, 3, 4, 5], max_p95_ms=budget)
