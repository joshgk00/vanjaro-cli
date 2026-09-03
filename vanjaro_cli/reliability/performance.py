"""Deterministic validation of separately measured performance samples."""

from __future__ import annotations

import math
import statistics
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from vanjaro_cli.reliability.contracts import (
    PERFORMANCE_EVIDENCE_SCHEMA,
    PERFORMANCE_REPORT_SCHEMA,
)


class _PerformanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PerformanceEnvironment(_PerformanceModel):
    python_version: str = Field(pattern=r"^\d+\.\d+$")
    implementation: str = Field(min_length=1)
    operating_system: str = Field(min_length=1)
    architecture: str = Field(min_length=1)
    corpus_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CasePerformanceEvidence(_PerformanceModel):
    samples_ms: tuple[float, ...] = Field(min_length=5)

    @field_validator("samples_ms")
    @classmethod
    def require_positive_finite_samples(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("performance samples must be positive finite milliseconds")
        return values


class CasePerformanceBudget(_PerformanceModel):
    max_median_ms: float = Field(gt=0)
    max_p95_ms: float = Field(gt=0)
    baseline_p95_ms: float = Field(gt=0)
    max_regression_ratio: float = Field(ge=1)

    @field_validator(
        "max_median_ms",
        "max_p95_ms",
        "baseline_p95_ms",
        "max_regression_ratio",
    )
    @classmethod
    def require_finite_budgets(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("performance budgets must be finite")
        return value


class PerformanceEvidence(_PerformanceModel):
    schema_version: Literal["performance-evidence-v1"] = PERFORMANCE_EVIDENCE_SCHEMA
    policy_version: Literal["agency-performance-v1"] = "agency-performance-v1"
    environment: PerformanceEnvironment
    warmups: int = Field(ge=1)
    cases: dict[str, CasePerformanceEvidence] = Field(min_length=1)
    budgets: dict[str, CasePerformanceBudget] = Field(min_length=1)

    @model_validator(mode="after")
    def require_exact_budget_set(self) -> "PerformanceEvidence":
        if set(self.cases) != set(self.budgets):
            raise ValueError("performance cases and budgets must have identical IDs")
        return self


class CasePerformanceResult(_PerformanceModel):
    median_ms: float
    p95_ms: float
    max_median_ms: float
    max_p95_ms: float
    regression_ratio: float
    max_regression_ratio: float
    failures: tuple[str, ...]


class PerformanceReport(_PerformanceModel):
    schema_version: Literal["performance-report-v1"] = PERFORMANCE_REPORT_SCHEMA
    status: Literal["passed", "failed"]
    policy_version: str
    environment: PerformanceEnvironment
    sample_count: int
    warmups: int
    cases: dict[str, CasePerformanceResult]
    failures: tuple[str, ...]


def evaluate_performance(evidence: PerformanceEvidence) -> PerformanceReport:
    """Recompute medians, nearest-rank p95 values, and every declared budget."""

    results: dict[str, CasePerformanceResult] = {}
    global_failures: list[str] = []
    sample_counts: set[int] = set()
    for case_id in sorted(evidence.cases):
        samples = evidence.cases[case_id].samples_ms
        budget = evidence.budgets[case_id]
        sample_counts.add(len(samples))
        raw_median = float(statistics.median(samples))
        raw_p95 = _nearest_rank(samples, 0.95)
        raw_ratio = raw_p95 / budget.baseline_p95_ms
        failures: list[str] = []
        if raw_median > budget.max_median_ms:
            failures.append("median-budget-exceeded")
        if raw_p95 > budget.max_p95_ms:
            failures.append("p95-budget-exceeded")
        if raw_ratio > budget.max_regression_ratio:
            failures.append("relative-regression-exceeded")
        results[case_id] = CasePerformanceResult(
            median_ms=_round_metric(raw_median),
            p95_ms=_round_metric(raw_p95),
            max_median_ms=budget.max_median_ms,
            max_p95_ms=budget.max_p95_ms,
            regression_ratio=_round_metric(raw_ratio),
            max_regression_ratio=budget.max_regression_ratio,
            failures=tuple(failures),
        )
        global_failures.extend(f"{case_id}:{failure}" for failure in failures)
    if len(sample_counts) != 1:
        global_failures.append("inconsistent-sample-count")
    return PerformanceReport(
        status="failed" if global_failures else "passed",
        policy_version=evidence.policy_version,
        environment=evidence.environment,
        sample_count=min(sample_counts) if sample_counts else 0,
        warmups=evidence.warmups,
        cases=results,
        failures=tuple(global_failures),
    )


def _nearest_rank(values: tuple[float, ...], quantile: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return float(ordered[rank - 1])


def _round_metric(value: float) -> float:
    return round(value, 6)


__all__ = [
    "CasePerformanceBudget",
    "CasePerformanceEvidence",
    "CasePerformanceResult",
    "PerformanceEnvironment",
    "PerformanceEvidence",
    "PerformanceReport",
    "evaluate_performance",
]
