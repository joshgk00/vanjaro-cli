"""Benchmark evidence verification and current-code benchmark execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from vanjaro_cli.design.metrics import (
    BenchmarkFixtureError,
    BenchmarkReport,
    BenchmarkThresholds,
    run_offline_benchmark,
)
from vanjaro_cli.release.gates import (
    EXTRACTION_THRESHOLDS as _EXTRACTION_THRESHOLDS,
    MATCHER_THRESHOLDS as _MATCHER_THRESHOLDS,
    GateLedger as _GateLedger,
    ReleaseVerificationError,
)
from vanjaro_cli.release.models import BenchmarkEvidence
from vanjaro_cli.release.paths import (
    _contains_link_or_reparse,
    _json_object,
    _verify_reference,
)
from vanjaro_cli.reliability.artifacts import ArtifactContractError, load_strict_json

BenchmarkRunner = Callable[[Path, Path, tuple[str, ...]], BenchmarkReport]


def _verify_benchmark(
    evidence: BenchmarkEvidence,
    *,
    root: Path,
    ledger: _GateLedger,
    benchmark_runner: BenchmarkRunner,
) -> dict[str, float]:
    source_kind = evidence.source_kind
    provenance_gate = f"benchmark-provenance-{source_kind}"
    references = (
        evidence.manifest,
        evidence.baseline,
        evidence.report,
        *evidence.inputs,
    )
    paths: dict[str, Path] = {}
    digests: list[str] = []
    reasons: list[str] = []
    for reference in references:
        ok, reason, path = _verify_reference(root, reference)
        if not ok or path is None:
            reasons.append(reason)
        else:
            paths[reference.path] = path
            digests.append(reference.sha256)
    if reasons:
        ledger.set(provenance_gate, "failed", *reasons)
        _mark_benchmark_metrics_upstream(source_kind, ledger)
        return {}
    try:
        manifest = _json_object(paths[evidence.manifest.path])
        _json_object(paths[evidence.baseline.path])
        report = BenchmarkReport.model_validate(
            load_strict_json(paths[evidence.report.path])
        )
    except (ArtifactContractError, ReleaseVerificationError, ValidationError):
        ledger.set(provenance_gate, "failed", "invalid-benchmark-json")
        _mark_benchmark_metrics_upstream(source_kind, ledger)
        return {}

    manifest_cases = manifest.get("cases")
    if not isinstance(manifest_cases, list):
        ledger.set(provenance_gate, "failed", "invalid-case-list")
        _mark_benchmark_metrics_upstream(source_kind, ledger)
        return {}
    all_manifest_ids = [
        item.get("id") for item in manifest_cases if isinstance(item, dict)
    ]
    if len(all_manifest_ids) != len(set(all_manifest_ids)):
        reasons.append("duplicate-manifest-case-id")
    selected_manifest = [
        item
        for item in manifest_cases
        if isinstance(item, dict) and item.get("id") in evidence.case_ids
    ]
    manifest_ids = tuple(item.get("id") for item in selected_manifest)
    report_ids = tuple(item.case_id for item in report.cases)
    filter_ids = report.case_filter
    if len(report_ids) != len(set(report_ids)) or len(filter_ids) != len(
        set(filter_ids)
    ):
        reasons.append("duplicate-report-case-id")
    expected_ids = set(evidence.case_ids)
    if (
        set(manifest_ids) != expected_ids
        or set(report_ids) != expected_ids
        or set(filter_ids) != expected_ids
    ):
        reasons.append("case-set-mismatch")
    if any(item.get("source_kind") != source_kind for item in selected_manifest):
        reasons.append("manifest-source-kind-mismatch")
    if any(item.source_kind != source_kind for item in report.cases):
        reasons.append("report-source-kind-mismatch")
    discovered = _manifest_input_paths(
        manifest_path=paths[evidence.manifest.path],
        selected_cases=selected_manifest,
        root=root,
    )
    declared = {item.path for item in evidence.inputs}
    if discovered != declared:
        reasons.append("fixture-inventory-mismatch")
    if report.threshold_failures or any(item.failed for item in report.regressions):
        reasons.append("benchmark-gate-failure")
    if evidence.measurement_mode != "autonomous":
        ledger.set(
            provenance_gate,
            "incomplete",
            "assisted-measurement-is-not-autonomous-evidence",
            evidence=tuple(digests),
        )
        _mark_benchmark_metrics_upstream(source_kind, ledger)
        return {}
    try:
        rerun = benchmark_runner(
            paths[evidence.manifest.path],
            paths[evidence.baseline.path],
            evidence.case_ids,
        )
    except (
        ArtifactContractError,
        BenchmarkFixtureError,
        OSError,
        ValidationError,
        ValueError,
    ):
        reasons.append("benchmark-rerun-failed")
    except Exception:
        # A malformed fixture must fail this gate, never crash the aggregate
        # release audit. The runner is local and read-only; no recovery action
        # is hidden by treating an unexpected adapter exception as bad evidence.
        reasons.append("benchmark-rerun-failed")
    else:
        if rerun != report:
            reasons.append("benchmark-report-not-reproducible")
    if reasons:
        ledger.set(provenance_gate, "failed", *reasons, evidence=tuple(digests))
        _mark_benchmark_metrics_upstream(source_kind, ledger)
        return {}
    ledger.set(provenance_gate, "passed", "evidence-bound", evidence=tuple(digests))

    metrics: dict[str, float] = {}
    for group, thresholds in (
        ("extraction", _EXTRACTION_THRESHOLDS),
        ("matcher", _MATCHER_THRESHOLDS),
    ):
        for metric, threshold in thresholds.items():
            value = _aggregate_metric(
                [item.model_dump(mode="json") for item in report.cases], group, metric
            )
            metrics[metric] = value if value is not None else -1.0
            gate_id = f"quality-{metric}-{source_kind}"
            if value is None:
                ledger.set(gate_id, "incomplete", "metric-not-measurable")
            elif value < threshold:
                ledger.set(
                    gate_id,
                    "failed",
                    "threshold-not-met",
                    evidence=tuple(digests),
                )
            else:
                ledger.set(gate_id, "passed", "threshold-met", evidence=tuple(digests))
    return metrics


def _mark_benchmark_metrics_upstream(source_kind: str, ledger: _GateLedger) -> None:
    for metric in (*_EXTRACTION_THRESHOLDS, *_MATCHER_THRESHOLDS):
        ledger.set(
            f"quality-{metric}-{source_kind}",
            "incomplete",
            "benchmark-evidence-invalid",
        )


def _aggregate_metric(cases: list[Any], group: str, metric: str) -> float | None:
    numerator = 0
    denominator = 0
    for case in cases:
        if not isinstance(case, dict):
            return None
        item = (
            case.get(group, {}).get(metric)
            if isinstance(case.get(group), dict)
            else None
        )
        if not isinstance(item, dict) or item.get("status") != "measured":
            return None
        current_numerator = item.get("numerator")
        current_denominator = item.get("denominator")
        if (
            not isinstance(current_numerator, int)
            or not isinstance(current_denominator, int)
            or current_denominator <= 0
        ):
            return None
        numerator += current_numerator
        denominator += current_denominator
    return numerator / denominator if denominator else None


def _manifest_input_paths(
    *,
    manifest_path: Path,
    selected_cases: list[dict[str, Any]],
    root: Path,
) -> set[str]:
    result: set[str] = set()
    for case in selected_cases:
        candidates: list[object] = []
        source = case.get("source")
        if isinstance(source, dict):
            candidates.append(source.get("path"))
        candidates.append(case.get("annotations"))
        references = case.get("references")
        if isinstance(references, list):
            candidates.extend(
                item.get("path") for item in references if isinstance(item, dict)
            )
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            unresolved = manifest_path.parent / candidate
            if _contains_link_or_reparse(unresolved):
                result.add("[symlink]")
                continue
            absolute = unresolved.resolve()
            try:
                result.add(absolute.relative_to(root).as_posix())
            except ValueError:
                result.add("[path-escape]")
    return result


def _run_current_benchmark(
    manifest_path: Path,
    baseline_path: Path,
    case_ids: tuple[str, ...],
) -> BenchmarkReport:
    # Deferred: importing this at module load time re-enters
    # vanjaro_cli.design.benchmark_corpus while it is still initializing
    # (benchmark_corpus -> orchestration.image_acquisition -> orchestration
    # package init -> release.paths -> release package init -> verifier ->
    # this module), which fails with a partial-init ImportError.
    from vanjaro_cli.design.benchmark_corpus import load_benchmark_predictions

    predictions = load_benchmark_predictions(manifest_path, case_ids)
    result = run_offline_benchmark(
        predictions,
        manifest_path=manifest_path,
        case_ids=case_ids,
        baseline_path=baseline_path,
        thresholds=BenchmarkThresholds(
            section_boundary_precision=_EXTRACTION_THRESHOLDS[
                "section_boundary_precision"
            ],
            section_boundary_recall=_EXTRACTION_THRESHOLDS[
                "section_boundary_recall"
            ],
            visitor_content_retention=_EXTRACTION_THRESHOLDS[
                "visitor_content_retention"
            ],
            group_field_association_accuracy=_EXTRACTION_THRESHOLDS[
                "group_field_association_accuracy"
            ],
            template_top1_accuracy=_MATCHER_THRESHOLDS["template_top1_accuracy"],
            template_top3_accuracy=_MATCHER_THRESHOLDS["template_top3_accuracy"],
            high_confidence_precision=_MATCHER_THRESHOLDS[
                "high_confidence_precision"
            ],
        ),
    )
    return result.report


__all__ = ["BenchmarkRunner", "_run_current_benchmark", "_verify_benchmark"]
