"""Combine per-corpus offline benchmark reports into one cross-corpus view.

The offline benchmark command scores one manifest per invocation, so every
run only ever reports on live_html/figma or assisted-image cases, never both.
This module reads the resulting BenchmarkReport objects and lays them out as
one metric-by-corpus table, so a single score can be read across every
committed source kind. It performs no I/O and makes no network calls.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from vanjaro_cli.design.metrics import BenchmarkReport, ExtractionMetrics, MatcherMetrics, MetricScore

__all__ = [
    "CombinedBenchmarkReport",
    "CombinedCorpusStatus",
    "CombinedMetricCell",
    "CombinedMetricRow",
    "build_combined_report",
    "render_combined_markdown",
]


_EXTRACTION_METRIC_NAMES = tuple(ExtractionMetrics.model_fields)
_MATCHER_METRIC_NAMES = tuple(MatcherMetrics.model_fields)
_METRIC_NAMES = _EXTRACTION_METRIC_NAMES + _MATCHER_METRIC_NAMES


class _CombinedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CombinedMetricCell(_CombinedModel):
    """One metric's score for one corpus."""

    corpus: str
    value: float | None
    numerator: int
    denominator: int
    status: str


class CombinedMetricRow(_CombinedModel):
    """One metric, one cell per corpus, in the order corpora were supplied."""

    metric: str
    cells: tuple[CombinedMetricCell, ...]


class CombinedCorpusStatus(_CombinedModel):
    corpus: str
    passed: bool
    threshold_failure_count: int
    regression_failure_count: int


class CombinedBenchmarkReport(_CombinedModel):
    """Cross-corpus benchmark score table plus per-corpus pass/fail."""

    schema_version: str = "1.0"
    corpora: tuple[str, ...]
    rows: tuple[CombinedMetricRow, ...]
    statuses: tuple[CombinedCorpusStatus, ...]
    passed: bool


def _metric_score(report: BenchmarkReport, metric: str) -> MetricScore:
    if metric in _EXTRACTION_METRIC_NAMES:
        return getattr(report.aggregate.extraction, metric)
    return getattr(report.aggregate.matcher, metric)


def build_combined_report(
    entries: tuple[tuple[str, BenchmarkReport, bool], ...],
) -> CombinedBenchmarkReport:
    """Build one combined report from (corpus label, report, passed) entries.

    Corpus columns keep the order the caller supplied — the command passes
    manifests in a fixed, documented order, so that order is already
    deterministic without an extra alphabetical re-sort that would separate
    it from the per-corpus report files it was built from.
    """

    corpora = tuple(label for label, _report, _passed in entries)
    rows = tuple(
        CombinedMetricRow(
            metric=metric,
            cells=tuple(
                CombinedMetricCell(
                    corpus=label,
                    value=(score := _metric_score(report, metric)).value,
                    numerator=score.numerator,
                    denominator=score.denominator,
                    status=score.status,
                )
                for label, report, _passed in entries
            ),
        )
        for metric in _METRIC_NAMES
    )
    statuses = tuple(
        CombinedCorpusStatus(
            corpus=label,
            passed=passed,
            threshold_failure_count=len(report.threshold_failures),
            regression_failure_count=sum(1 for item in report.regressions if item.failed),
        )
        for label, report, passed in entries
    )
    return CombinedBenchmarkReport(
        corpora=corpora,
        rows=rows,
        statuses=statuses,
        passed=all(passed for _label, _report, passed in entries),
    )


def _format_cell(cell: CombinedMetricCell) -> str:
    if cell.status != "measured":
        return cell.status
    return f"{cell.value:.4f} ({cell.numerator}/{cell.denominator})"


def render_combined_markdown(report: CombinedBenchmarkReport) -> str:
    """Render a deterministic Markdown table: metric rows, corpus columns."""

    header = "| Metric | " + " | ".join(report.corpora) + " |"
    divider = "|---|" + "---:|" * len(report.corpora)
    lines = [
        "# Combined Design Translation Offline Benchmark",
        "",
        header,
        divider,
    ]
    for row in report.rows:
        cells = " | ".join(_format_cell(cell) for cell in row.cells)
        lines.append(f"| `{row.metric}` | {cells} |")

    lines.extend(["", "## Corpus status", ""])
    for status in report.statuses:
        lines.append(
            f"- `{status.corpus}`: {'passed' if status.passed else 'failed'} "
            f"(threshold failures: {status.threshold_failure_count}, "
            f"regression failures: {status.regression_failure_count})"
        )
    lines.append("")
    return "\n".join(lines)
