"""Offline extraction and matcher metrics for Design Translation benchmarks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from vanjaro_cli.design.matcher import ConfidenceLevel, TemplateMatchResult
from vanjaro_cli.design.models import ContentElement, DesignDocument, RepeatGroup, Section

__all__ = [
    "AggregateMetrics",
    "BenchmarkCasePrediction",
    "BenchmarkFixtureError",
    "BenchmarkReport",
    "BenchmarkRunResult",
    "BenchmarkThresholds",
    "CaseMetricReport",
    "ExtractionMetrics",
    "MatcherMetrics",
    "MetricFailure",
    "MetricScore",
    "RegressionComparison",
    "ThresholdFailure",
    "compare_with_baseline",
    "evaluate_benchmark_case",
    "evaluate_thresholds",
    "render_benchmark_report",
    "run_offline_benchmark",
    "serialize_benchmark_report",
    "write_benchmark_reports",
]


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CORPUS_ROOT = _PROJECT_ROOT / "tests" / "fixtures" / "design-benchmarks"


class _MetricModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricScore(_MetricModel):
    """A count-derived metric that never treats an empty denominator as success."""

    value: float | None = Field(default=None, ge=0, le=1)
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    status: str


class ExtractionMetrics(_MetricModel):
    section_boundary_precision: MetricScore
    section_boundary_recall: MetricScore
    semantic_role_accuracy: MetricScore
    visitor_content_retention: MetricScore
    group_field_association_accuracy: MetricScore
    asset_association_accuracy: MetricScore
    responsive_observation_coverage: MetricScore


class MatcherMetrics(_MetricModel):
    template_top1_accuracy: MetricScore
    template_top3_accuracy: MetricScore
    high_confidence_precision: MetricScore


class AggregateMetrics(_MetricModel):
    extraction: ExtractionMetrics
    matcher: MatcherMetrics


class MetricFailure(_MetricModel):
    case_id: str
    metric: str
    message: str
    section_id: str | None = None
    path: str | None = None
    expected: JsonValue | None = None
    actual: JsonValue | None = None


class BenchmarkCasePrediction(_MetricModel):
    """Offline adapter output and corresponding matcher results for one case."""

    case_id: str
    document: DesignDocument | None = None
    matches: tuple[TemplateMatchResult, ...] = ()


class CaseMetricReport(_MetricModel):
    case_id: str
    source_kind: str
    extraction: ExtractionMetrics
    matcher: MatcherMetrics
    failures: tuple[MetricFailure, ...]


class RegressionComparison(_MetricModel):
    metric: str
    baseline: float | None = Field(default=None, ge=0, le=1)
    current: float | None = Field(default=None, ge=0, le=1)
    delta: float | None = None
    tolerance: float = Field(ge=0, le=1)
    comparable: bool
    failed: bool
    reason: str | None = None


class ThresholdFailure(_MetricModel):
    metric: str
    minimum: float = Field(ge=0, le=1)
    actual: float | None = Field(default=None, ge=0, le=1)
    reason: str


class BenchmarkThresholds(_MetricModel):
    """Quality gates with requirement-backed defaults and optional extra gates."""

    section_boundary_precision: float | None = Field(default=0.90, ge=0, le=1)
    section_boundary_recall: float | None = Field(default=0.90, ge=0, le=1)
    semantic_role_accuracy: float | None = Field(default=None, ge=0, le=1)
    visitor_content_retention: float | None = Field(default=None, ge=0, le=1)
    group_field_association_accuracy: float | None = Field(default=0.95, ge=0, le=1)
    asset_association_accuracy: float | None = Field(default=None, ge=0, le=1)
    responsive_observation_coverage: float | None = Field(default=None, ge=0, le=1)
    template_top1_accuracy: float | None = Field(default=0.85, ge=0, le=1)
    template_top3_accuracy: float | None = Field(default=0.95, ge=0, le=1)
    high_confidence_precision: float | None = Field(default=0.90, ge=0, le=1)


class BenchmarkReport(_MetricModel):
    schema_version: str = "1.0"
    corpus_name: str
    case_filter: tuple[str, ...]
    aggregate: AggregateMetrics
    cases: tuple[CaseMetricReport, ...]
    regressions: tuple[RegressionComparison, ...]
    threshold_failures: tuple[ThresholdFailure, ...]


class BenchmarkRunResult(_MetricModel):
    report: BenchmarkReport
    passed: bool
    exit_code: int


class BenchmarkFixtureError(ValueError):
    """Raised for an absent or malformed committed benchmark fixture."""

    def __init__(self, message: str, path: Path) -> None:
        self.path = path
        super().__init__(f"{message}: {path}")


def _ratio(numerator: int, denominator: int) -> MetricScore:
    if denominator == 0:
        return MetricScore(
            value=None,
            numerator=numerator,
            denominator=denominator,
            status="not_measurable",
        )
    return MetricScore(
        value=round(numerator / denominator, 6),
        numerator=numerator,
        denominator=denominator,
        status="measured",
    )


def _template_slug(template_id: str) -> str:
    return Path(template_id).name.removesuffix(".json")


def _section_boundary_values(section: Section) -> set[str]:
    values: set[str] = set()
    for provenance in section.provenance:
        values.update(
            value
            for value in (
                provenance.css_selector,
                provenance.page_node_id,
                provenance.frame_node_id,
                provenance.element_node_id,
            )
            if value
        )
        image_evidence_id = provenance.metadata.get("image_evidence_id")
        if isinstance(image_evidence_id, str) and image_evidence_id:
            values.add(image_evidence_id)
    return values


def _match_sections(
    expected_sections: list[dict],
    actual_sections: list[Section],
) -> tuple[dict[str, Section], list[Section]]:
    actual_by_id = {section.id: section for section in actual_sections}
    matched: dict[str, Section] = {}
    used_ids: set[str] = set()
    for expected in expected_sections:
        expected_id = expected["id"]
        actual = actual_by_id.get(expected_id)
        if actual is not None and actual.id not in used_ids:
            matched[expected_id] = actual
            used_ids.add(actual.id)
            continue
        boundary_value = expected.get("boundary", {}).get("value")
        if not boundary_value:
            continue
        for candidate in actual_sections:
            if candidate.id not in used_ids and boundary_value in _section_boundary_values(candidate):
                matched[expected_id] = candidate
                used_ids.add(candidate.id)
                break
    return matched, [section for section in actual_sections if section.id not in used_ids]


def _responsive_value(section: Section, breakpoint: str, property_name: str) -> JsonValue | None:
    for observation in section.responsive:
        if observation.breakpoint.value != breakpoint:
            continue
        if property_name in observation.layout_changes:
            value = observation.layout_changes[property_name]
            if isinstance(value, dict) and "to" in value:
                value = value["to"]
            if property_name == "direction" and value in {"row", "column"}:
                return "horizontal" if value == "row" else "vertical"
            return value
        if property_name == "hidden" and observation.hidden is not None:
            return observation.hidden
        for style in observation.style.observations:
            if style.property.value == property_name:
                return style.value
    return None


def _comparison_value(value: JsonValue) -> JsonValue:
    """Normalize semantically equal benchmark values without rewriting output."""

    if not isinstance(value, str):
        return value
    normalized = " ".join(value.split())
    parsed = urlsplit(normalized)
    if parsed.scheme and parsed.netloc:
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return normalized


def _content_correspondence(
    expected_content: list[dict], actual: Section | None
) -> dict[str, ContentElement]:
    """Match visitor content semantically; annotation IDs are not source IDs."""

    if actual is None:
        return {}
    available = list(actual.content)
    result: dict[str, ContentElement] = {}
    for expected in expected_content:
        expected_value = _comparison_value(expected.get("value"))
        candidates = [
            element for element in available
            if _comparison_value(element.value) == expected_value
        ]
        if not candidates:
            continue
        candidates.sort(
            key=lambda element: (
                element.role != expected.get("role"),
                element.kind.value != expected.get("kind"),
                bool(element.group_id) != bool(expected.get("group_id")),
                abs(element.order - int(expected.get("order", 0))),
                element.id,
            )
        )
        selected = candidates[0]
        result[expected["id"]] = selected
        available.remove(selected)
    return result


def _group_correspondence(expected_groups: list[dict], actual: Section | None) -> dict[str, RepeatGroup]:
    if actual is None:
        return {}
    available = list(actual.groups)
    result: dict[str, RepeatGroup] = {}
    for expected in expected_groups:
        candidates = sorted(
            available,
            key=lambda group: (
                group.kind.value != expected.get("kind"),
                abs(len(group.items) - len(expected.get("items", []))),
                group.id,
            ),
        )
        if candidates:
            result[expected["id"]] = candidates[0]
            available.remove(candidates[0])
    return result


def evaluate_benchmark_case(
    case_id: str,
    source_kind: str,
    annotations: Mapping[str, object],
    prediction: BenchmarkCasePrediction | None,
) -> CaseMetricReport:
    """Compare one Design Document and its matcher results with annotations."""

    expected_sections = list(annotations.get("expected", {}).get("sections", []))  # type: ignore[union-attr]
    document = prediction.document if prediction else None
    actual_sections = (
        [section for page in document.pages for section in page.sections]
        if document is not None
        else []
    )
    matches = {match.section_id: match for match in prediction.matches} if prediction else {}
    matched, unexpected = _match_sections(expected_sections, actual_sections)
    failures: list[MetricFailure] = []

    for expected in expected_sections:
        if expected["id"] not in matched:
            failures.append(
                MetricFailure(
                    case_id=case_id,
                    section_id=expected["id"],
                    metric="section_boundary_recall",
                    path=f"sections[{expected['id']}]",
                    message="expected section was not predicted",
                    expected=expected.get("boundary"),
                    actual=None,
                )
            )
    for actual in unexpected:
        failures.append(
            MetricFailure(
                case_id=case_id,
                section_id=actual.id,
                metric="section_boundary_precision",
                path=f"sections[{actual.id}]",
                message="predicted section has no expected correspondence",
                expected=None,
                actual={"id": actual.id, "semantic_role": actual.semantic_role},
            )
        )

    role_correct = 0
    content_retained = 0
    content_expected = 0
    binding_correct = 0
    binding_expected = 0
    asset_correct = 0
    asset_expected = 0
    responsive_correct = 0
    responsive_expected = 0
    assets_by_id = {asset.id: asset for asset in document.assets} if document else {}

    for expected in expected_sections:
        expected_id = expected["id"]
        actual = matched.get(expected_id)
        if actual is not None:
            if actual.semantic_role == expected["semantic_role"]:
                role_correct += 1
            else:
                failures.append(
                    MetricFailure(
                        case_id=case_id,
                        section_id=expected_id,
                        metric="semantic_role_accuracy",
                        path=f"sections[{expected_id}].semantic_role",
                        message="semantic role differs",
                        expected=expected["semantic_role"],
                        actual=actual.semantic_role,
                    )
                )

        content_map = _content_correspondence(expected.get("content", []), actual)
        for expected_element in expected.get("content", []):
            content_expected += 1
            actual_element = content_map.get(expected_element["id"])
            if actual_element is not None:
                content_retained += 1
            else:
                failures.append(
                    MetricFailure(
                        case_id=case_id,
                        section_id=expected_id,
                        metric="visitor_content_retention",
                        path=f"sections[{expected_id}].content[{expected_element['id']}]",
                        message="visitor-facing content is missing or changed",
                        expected=expected_element.get("value"),
                        actual=actual_element.value if actual_element else None,
                    )
                )

        group_map = _group_correspondence(expected.get("groups", []), actual)
        for expected_group in expected.get("groups", []):
            actual_group = group_map.get(expected_group["id"])
            actual_items = actual_group.items if actual_group else []
            for item_index, expected_item in enumerate(expected_group.get("items", [])):
                actual_item = actual_items[item_index] if item_index < len(actual_items) else None
                for field_name, expected_reference in expected_item.get("fields", {}).items():
                    binding_expected += 1
                    actual_reference = actual_item.fields.get(field_name) if actual_item else None
                    corresponding = content_map.get(expected_reference)
                    if corresponding is not None and actual_reference == corresponding.id:
                        binding_correct += 1
                    else:
                        failures.append(
                            MetricFailure(
                                case_id=case_id,
                                section_id=expected_id,
                                metric="group_field_association_accuracy",
                                path=(
                                    f"sections[{expected_id}].groups[{expected_group['id']}]"
                                    f".items[{expected_item['id']}].fields[{field_name}]"
                                ),
                                message="group field points to a different content element",
                                expected=expected_reference,
                                actual=actual_reference,
                            )
                        )

        for expected_asset in expected.get("assets", []):
            asset_expected += 1
            actual_element = content_map.get(expected_asset["element_id"])
            actual_asset = assets_by_id.get(actual_element.asset_id) if actual_element else None
            source_candidates = (
                [
                    actual_asset.local_path,
                    actual_asset.source_url,
                    actual_asset.metadata.get("figma_image_ref"),
                    actual_asset.metadata.get("figma_node_id"),
                ]
                if actual_asset is not None
                else []
            )
            expected_source = _comparison_value(expected_asset["source_ref"])
            actual_source = next(
                (
                    source
                    for source in source_candidates
                    if isinstance(source, str) and _comparison_value(source) == expected_source
                ),
                next((source for source in source_candidates if isinstance(source, str)), None),
            )
            association_matches = (
                actual_element is not None
                and actual_element.role == expected_asset["role"]
                and _comparison_value(actual_source) == expected_source
            )
            if association_matches:
                asset_correct += 1
            else:
                failures.append(
                    MetricFailure(
                        case_id=case_id,
                        section_id=expected_id,
                        metric="asset_association_accuracy",
                        path=f"sections[{expected_id}].assets[{expected_asset['element_id']}]",
                        message="editorial asset is missing or associated with the wrong element",
                        expected={"role": expected_asset["role"], "source_ref": expected_asset["source_ref"]},
                        actual=(
                            {"role": actual_element.role, "source_ref": actual_source}
                            if actual_element
                            else None
                        ),
                    )
                )

        for expected_observation in expected.get("responsive", []):
            breakpoint = expected_observation["breakpoint"]
            for property_name, expected_value in expected_observation.get("observations", {}).items():
                responsive_expected += 1
                actual_value = _responsive_value(actual, breakpoint, property_name) if actual else None
                if actual_value == expected_value:
                    responsive_correct += 1
                else:
                    failures.append(
                        MetricFailure(
                            case_id=case_id,
                            section_id=expected_id,
                            metric="responsive_observation_coverage",
                            path=f"sections[{expected_id}].responsive[{breakpoint}].{property_name}",
                            message="responsive observation is missing or differs",
                            expected=expected_value,
                            actual=actual_value,
                        )
                    )

    top1_correct = 0
    top3_correct = 0
    template_expected = 0
    high_correct = 0
    high_total = 0
    for expected in expected_sections:
        expected_id = expected["id"]
        acceptable = set(expected.get("acceptable_templates", []))
        native_acceptable = {item for item in acceptable if not item.startswith("new:")}
        if not native_acceptable:
            # A deliberately annotated library gap is a planning outcome, not
            # an incorrect choice among the templates that currently exist.
            continue
        acceptable = native_acceptable
        template_expected += 1
        actual_section = matched.get(expected_id)
        match = matches.get(actual_section.id) if actual_section is not None else None
        if match is None:
            failures.append(
                MetricFailure(
                    case_id=case_id,
                    section_id=expected_id,
                    metric="template_top1_accuracy",
                    path=f"sections[{expected_id}].template_match",
                    message="matcher result is missing",
                    expected=sorted(acceptable),
                    actual=None,
                )
            )
            continue
        selected = _template_slug(match.selected_candidate.template_id)
        candidates = [_template_slug(candidate.template_id) for candidate in match.candidates[:3]]
        if selected in acceptable:
            top1_correct += 1
        else:
            failures.append(
                MetricFailure(
                    case_id=case_id,
                    section_id=expected_id,
                    metric="template_top1_accuracy",
                    path=f"sections[{expected_id}].template_match.selected",
                    message="selected template is not an acceptable annotated match",
                    expected=sorted(acceptable),
                    actual=selected,
                )
            )
        if acceptable.intersection(candidates):
            top3_correct += 1
        else:
            failures.append(
                MetricFailure(
                    case_id=case_id,
                    section_id=expected_id,
                    metric="template_top3_accuracy",
                    path=f"sections[{expected_id}].template_match.candidates",
                    message="top three omit every acceptable annotated match",
                    expected=sorted(acceptable),
                    actual=candidates,
                )
            )
        if match.selected_candidate.confidence == ConfidenceLevel.HIGH:
            high_total += 1
            if selected in acceptable:
                high_correct += 1
            else:
                failures.append(
                    MetricFailure(
                        case_id=case_id,
                        section_id=expected_id,
                        metric="high_confidence_precision",
                        path=f"sections[{expected_id}].template_match.confidence",
                        message="high-confidence selection is incorrect",
                        expected=sorted(acceptable),
                        actual=selected,
                    )
                )

    extraction = ExtractionMetrics(
        section_boundary_precision=_ratio(len(matched), len(actual_sections)),
        section_boundary_recall=_ratio(len(matched), len(expected_sections)),
        semantic_role_accuracy=_ratio(role_correct, len(matched)),
        visitor_content_retention=_ratio(content_retained, content_expected),
        group_field_association_accuracy=_ratio(binding_correct, binding_expected),
        asset_association_accuracy=_ratio(asset_correct, asset_expected),
        responsive_observation_coverage=_ratio(responsive_correct, responsive_expected),
    )
    matcher = MatcherMetrics(
        template_top1_accuracy=_ratio(top1_correct, template_expected),
        template_top3_accuracy=_ratio(top3_correct, template_expected),
        high_confidence_precision=_ratio(high_correct, high_total),
    )
    return CaseMetricReport(
        case_id=case_id,
        source_kind=source_kind,
        extraction=extraction,
        matcher=matcher,
        failures=tuple(failures),
    )


_EXTRACTION_FIELDS = tuple(ExtractionMetrics.model_fields)
_MATCHER_FIELDS = tuple(MatcherMetrics.model_fields)


def _aggregate_scores(reports: Iterable[CaseMetricReport], group: str, fields: tuple[str, ...]):
    reports = tuple(reports)
    values: dict[str, MetricScore] = {}
    for field_name in fields:
        scores = [getattr(getattr(report, group), field_name) for report in reports]
        values[field_name] = _ratio(
            sum(score.numerator for score in scores),
            sum(score.denominator for score in scores),
        )
    return values


def _aggregate(reports: Iterable[CaseMetricReport]) -> AggregateMetrics:
    reports = tuple(reports)
    return AggregateMetrics(
        extraction=ExtractionMetrics(**_aggregate_scores(reports, "extraction", _EXTRACTION_FIELDS)),
        matcher=MatcherMetrics(**_aggregate_scores(reports, "matcher", _MATCHER_FIELDS)),
    )


_BASELINE_NAMES = {
    "section_boundary_precision": "section_boundary_precision",
    "section_boundary_recall": "section_boundary_recall",
    "semantic_role_accuracy": "semantic_role_accuracy",
    "visitor_content_retention": "visitor_content_retention",
    "group_field_association_accuracy": "group_field_association_accuracy",
    "asset_association_accuracy": "asset_association_accuracy",
    "responsive_observation_coverage": "responsive_observation_coverage",
}


def _all_metric_scores(aggregate: AggregateMetrics) -> dict[str, MetricScore]:
    return {
        **{name: getattr(aggregate.extraction, name) for name in _EXTRACTION_FIELDS},
        **{name: getattr(aggregate.matcher, name) for name in _MATCHER_FIELDS},
    }


def compare_with_baseline(
    aggregate: AggregateMetrics,
    baseline: Mapping[str, object],
    *,
    tolerance: float = 0.02,
) -> tuple[RegressionComparison, ...]:
    """Compare measurable current metrics with a frozen baseline."""

    baseline_aggregate = baseline.get("aggregate", {})
    current_scores = _all_metric_scores(aggregate)
    comparisons: list[RegressionComparison] = []
    for metric_name, baseline_name in _BASELINE_NAMES.items():
        baseline_record = baseline_aggregate.get(baseline_name, {})  # type: ignore[union-attr]
        baseline_value = baseline_record.get("value") if isinstance(baseline_record, dict) else None
        current_value = current_scores[metric_name].value
        if not isinstance(baseline_value, (int, float)) or current_value is None:
            comparisons.append(
                RegressionComparison(
                    metric=metric_name,
                    baseline=float(baseline_value) if isinstance(baseline_value, (int, float)) else None,
                    current=current_value,
                    tolerance=tolerance,
                    comparable=False,
                    failed=False,
                    reason="baseline or current metric is not measurable",
                )
            )
            continue
        delta = round(current_value - float(baseline_value), 6)
        comparisons.append(
            RegressionComparison(
                metric=metric_name,
                baseline=float(baseline_value),
                current=current_value,
                delta=delta,
                tolerance=tolerance,
                comparable=True,
                failed=delta < -tolerance - 1e-12,
            )
        )
    return tuple(comparisons)


def evaluate_thresholds(
    aggregate: AggregateMetrics,
    thresholds: BenchmarkThresholds,
) -> tuple[ThresholdFailure, ...]:
    """Return every configured minimum that is missing or not met."""

    scores = _all_metric_scores(aggregate)
    failures: list[ThresholdFailure] = []
    for metric_name, minimum in thresholds.model_dump().items():
        if minimum is None:
            continue
        actual = scores[metric_name].value
        if actual is None or actual < minimum:
            failures.append(
                ThresholdFailure(
                    metric=metric_name,
                    minimum=minimum,
                    actual=actual,
                    reason=(
                        "metric is not measurable"
                        if actual is None
                        else f"metric is below the required minimum by {minimum - actual:.6f}"
                    ),
                )
            )
    return tuple(failures)


def _read_json(path: Path, label: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BenchmarkFixtureError(f"missing {label}", path) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkFixtureError(f"invalid {label}: {exc}", path) from exc
    if not isinstance(data, dict):
        raise BenchmarkFixtureError(f"{label} must contain a JSON object", path)
    return data


def run_offline_benchmark(
    predictions: Mapping[str, BenchmarkCasePrediction],
    *,
    corpus_root: Path = _DEFAULT_CORPUS_ROOT,
    manifest_path: Path | None = None,
    case_ids: Iterable[str] | None = None,
    thresholds: BenchmarkThresholds | None = None,
    baseline_path: Path | None = None,
    json_output: Path | None = None,
    human_output: Path | None = None,
) -> BenchmarkRunResult:
    """Evaluate predictions using committed fixtures only and write optional reports."""

    resolved_manifest = manifest_path or corpus_root / "manifest.json"
    corpus_root = resolved_manifest.parent
    manifest = _read_json(resolved_manifest, "benchmark manifest")
    available_cases = {case["id"]: case for case in manifest.get("cases", [])}
    selected_ids = tuple(sorted(set(case_ids))) if case_ids is not None else tuple(available_cases)
    unknown = sorted(set(selected_ids) - set(available_cases))
    if unknown:
        raise BenchmarkFixtureError(f"unknown benchmark case {', '.join(unknown)}", resolved_manifest)
    if not selected_ids:
        raise BenchmarkFixtureError("benchmark case filter selected no cases", resolved_manifest)

    reports: list[CaseMetricReport] = []
    for case_id in selected_ids:
        case = available_cases[case_id]
        for relative_path, label in (
            (case["source"]["path"], "benchmark source fixture"),
            (case["annotations"], "benchmark annotations"),
        ):
            path = corpus_root / relative_path
            if not path.is_file():
                raise BenchmarkFixtureError(f"missing {label}", path)
        for reference in case.get("references", []):
            path = corpus_root / reference["path"]
            if not path.is_file():
                raise BenchmarkFixtureError("missing benchmark reference", path)
        annotations = _read_json(corpus_root / case["annotations"], "benchmark annotations")
        prediction = predictions.get(case_id)
        if prediction is not None and prediction.case_id != case_id:
            raise ValueError(
                f"prediction key {case_id!r} does not match prediction case_id {prediction.case_id!r}"
            )
        report = evaluate_benchmark_case(case_id, case["source_kind"], annotations, prediction)
        if prediction is None:
            missing = MetricFailure(
                case_id=case_id,
                metric="prediction_missing",
                message="no offline prediction was supplied for the selected benchmark case",
                path=case["source"]["path"],
                expected="DesignDocument and matcher outputs",
                actual=None,
            )
            report = report.model_copy(update={"failures": (missing,) + report.failures})
        reports.append(report)

    aggregate = _aggregate(reports)
    corpus = manifest.get("corpus", {})
    tolerance = float(corpus.get("regression_tolerance", 0.02))
    resolved_baseline = baseline_path or corpus_root / "baseline-score-report.json"
    if baseline_path is not None:
        baseline = _read_json(resolved_baseline, "benchmark baseline")
    else:
        baseline = (
            _read_json(resolved_baseline, "benchmark baseline")
            if resolved_baseline.is_file()
            else {}
        )
    baseline_case_ids = {
        item["case_id"]
        for item in baseline.get("cases", [])
        if item.get("status") == "measured"
    }
    baseline_reports = [report for report in reports if report.case_id in baseline_case_ids]
    baseline_aggregate = _aggregate(baseline_reports)
    regressions = (
        compare_with_baseline(baseline_aggregate, baseline, tolerance=tolerance)
        if baseline
        else ()
    )
    threshold_failures = evaluate_thresholds(aggregate, thresholds or BenchmarkThresholds())
    report = BenchmarkReport(
        corpus_name=str(corpus.get("name", "Offline benchmark")),
        case_filter=selected_ids,
        aggregate=aggregate,
        cases=tuple(reports),
        regressions=regressions,
        threshold_failures=threshold_failures,
    )
    regression_failed = any(comparison.failed for comparison in regressions)
    result = BenchmarkRunResult(
        report=report,
        passed=not threshold_failures and not regression_failed,
        exit_code=0 if not threshold_failures and not regression_failed else 1,
    )
    if json_output is not None or human_output is not None:
        write_benchmark_reports(result.report, json_path=json_output, human_path=human_output)
    return result


def serialize_benchmark_report(report: BenchmarkReport) -> str:
    """Return stable machine-readable JSON with a trailing newline."""

    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def _format_score(score: MetricScore) -> str:
    return "n/a" if score.value is None else f"{score.value:.4f} ({score.numerator}/{score.denominator})"


def render_benchmark_report(report: BenchmarkReport) -> str:
    """Render a deterministic human-readable Markdown quality report."""

    scores = _all_metric_scores(report.aggregate)
    lines = [
        "# Design Translation Offline Benchmark",
        "",
        f"Corpus: **{report.corpus_name}**",
        "",
        "## Aggregate metrics",
        "",
        "| Metric | Result |",
        "|---|---:|",
    ]
    lines.extend(f"| `{name}` | {_format_score(score)} |" for name, score in scores.items())
    lines.extend(["", "## Cases", "", "| Case | Failures |", "|---|---:|"])
    lines.extend(f"| `{case.case_id}` | {len(case.failures)} |" for case in report.cases)
    failures = [failure for case in report.cases for failure in case.failures]
    if failures:
        lines.extend(
            [
                "",
                "## Per-case failures",
                "",
                "| Case | Metric | Section | Expected | Actual | Message |",
                "|---|---|---|---|---|---|",
            ]
        )
        for failure in failures:
            expected = json.dumps(failure.expected, sort_keys=True) if failure.expected is not None else "null"
            actual = json.dumps(failure.actual, sort_keys=True) if failure.actual is not None else "null"
            message = failure.message.replace("|", "\\|")
            lines.append(
                f"| `{failure.case_id}` | `{failure.metric}` | `{failure.section_id or ''}` | "
                f"`{expected}` | `{actual}` | {message} |"
            )
    if report.threshold_failures:
        lines.extend(["", "## Threshold failures", ""])
        lines.extend(
            f"- `{failure.metric}`: {failure.reason} (required {failure.minimum:.4f})"
            for failure in report.threshold_failures
        )
    failed_regressions = [comparison for comparison in report.regressions if comparison.failed]
    if failed_regressions:
        lines.extend(["", "## Baseline regressions", ""])
        lines.extend(
            f"- `{item.metric}`: {item.current:.4f} vs {item.baseline:.4f} "
            f"(tolerance {item.tolerance:.4f})"
            for item in failed_regressions
            if item.current is not None and item.baseline is not None
        )
    lines.append("")
    return "\n".join(lines)


def write_benchmark_reports(
    report: BenchmarkReport,
    *,
    json_path: Path | None,
    human_path: Path | None,
) -> tuple[Path, ...]:
    """Write requested reports and return their paths."""

    written: list[Path] = []
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(serialize_benchmark_report(report), encoding="utf-8")
        written.append(json_path)
    if human_path is not None:
        human_path.parent.mkdir(parents=True, exist_ok=True)
        human_path.write_text(render_benchmark_report(report), encoding="utf-8")
        written.append(human_path)
    return tuple(written)
