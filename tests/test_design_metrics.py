"""Focused tests for offline extraction, matching, and regression metrics."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vanjaro_cli.design.matcher import ConfidenceLevel, match_section
from vanjaro_cli.design.metrics import (
    AggregateMetrics,
    BenchmarkCasePrediction,
    BenchmarkFixtureError,
    BenchmarkThresholds,
    ExtractionMetrics,
    MatcherMetrics,
    MetricScore,
    compare_with_baseline,
    evaluate_benchmark_case,
    evaluate_thresholds,
    render_benchmark_report,
    run_offline_benchmark,
)
from vanjaro_cli.design.models import (
    Alignment,
    AssetKind,
    AssetRecord,
    AssetRole,
    BreakpointName,
    ContentElement,
    ContentKind,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    EvidenceStatus,
    LayoutKind,
    LayoutObservation,
    NavigationVisibility,
    ObservationMethod,
    Page,
    Provenance,
    RepeatGroup,
    RepeatGroupItem,
    RepeatGroupKind,
    ResponsiveObservation,
    Section,
    SourceKind,
    StyleSet,
    Viewport,
)
from vanjaro_cli.design.template_catalog import load_template_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_template_catalog(PROJECT_ROOT / "artifacts" / "block-templates")


def _content(
    element_id: str,
    kind: ContentKind,
    role: str,
    value: str,
    order: int,
    *,
    group_id: str | None = None,
    asset_id: str | None = None,
) -> ContentElement:
    return ContentElement(
        id=element_id,
        kind=kind,
        role=role,
        value=value,
        group_id=group_id,
        asset_id=asset_id,
        order=order,
        provenance=[],
        confidence=1.0,
    )


def _section(*, perfect: bool, extra: bool = False) -> Section:
    if extra:
        return Section(
            id="actual-extra",
            order=2,
            semantic_role="content",
            role_confidence=1.0,
            candidate_roles=[],
            layout=LayoutObservation(kind=LayoutKind.STACK, contained=True, columns=1),
            content=[],
            groups=[],
            style=StyleSet(),
            responsive=[],
            decorative_layers=[],
            interactions=[],
            provenance=[],
        )
    content = [
        _content("section-title", ContentKind.HEADING, "section_title", "Services", 1),
        _content("item-title", ContentKind.HEADING, "card_title", "Strategy", 2, group_id="cards"),
        _content(
            "item-body",
            ContentKind.TEXT,
            "card_body",
            "Useful body" if perfect else "Changed body",
            3,
            group_id="cards",
        ),
        _content(
            "item-media",
            ContentKind.IMAGE,
            "card_media",
            "/images/service.svg",
            4,
            group_id="cards",
            asset_id="asset-service",
        ),
    ]
    group = RepeatGroup(
        id="cards",
        kind=RepeatGroupKind.CARD,
        items=[
            RepeatGroupItem(
                id="card-1",
                fields={
                    "title": "item-title",
                    "body": "item-body" if perfect else "item-title",
                    "media": "item-media",
                },
            )
        ],
    )
    changes = {"columns": 1, "direction": "vertical"} if perfect else {"columns": 1}
    return Section(
        id="expected-one",
        order=1,
        semantic_role="feature_cards",
        role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(
            kind=LayoutKind.GRID,
            contained=True,
            columns=3,
            alignment=Alignment.LEFT,
        ),
        content=content,
        groups=[group],
        style=StyleSet(),
        responsive=[
            ResponsiveObservation(
                breakpoint=BreakpointName.MOBILE,
                viewport=Viewport(width=390, height=844),
                status=EvidenceStatus.OBSERVED,
                layout_changes=changes,
            )
        ],
        decorative_layers=[],
        interactions=[],
        provenance=[
            Provenance(
                source_kind=SourceKind.LIVE_HTML,
                method=ObservationMethod.STATIC,
                css_selector="#services",
            )
        ],
    )


def _document(*, perfect: bool, include_extra: bool) -> DesignDocument:
    sections = [_section(perfect=perfect)]
    if include_extra:
        sections.append(_section(perfect=perfect, extra=True))
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.LIVE_HTML,
            identifier="synthetic://metrics",
            captured_at=datetime(2026, 7, 16, tzinfo=UTC),
            adapter_version="test-1",
        ),
        tokens=DesignTokens(),
        assets=[
            AssetRecord(
                id="asset-service",
                kind=AssetKind.IMAGE,
                role=AssetRole.EDITORIAL,
                source_url="/images/service.svg",
            )
        ],
        pages=[
            Page(
                id="page-one",
                source_reference="synthetic://metrics",
                title="Metrics Test",
                slug="metrics",
                sections=sections,
                breakpoints=[BreakpointName.DESKTOP, BreakpointName.MOBILE],
                navigation_visibility=NavigationVisibility.VISIBLE,
                provenance=[],
            )
        ],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1.0, unsupported_traits=[]),
    )


def _annotation(*, include_missing_section: bool) -> dict:
    sections = [
        {
            "id": "expected-one",
            "order": 1,
            "boundary": {"kind": "css_selector", "value": "#services"},
            "semantic_role": "feature_cards",
            "content": [
                {"id": "section-title", "kind": "heading", "role": "section_title", "order": 1, "value": "Services", "group_id": None},
                {"id": "item-title", "kind": "heading", "role": "card_title", "order": 2, "value": "Strategy", "group_id": "cards"},
                {"id": "item-body", "kind": "text", "role": "card_body", "order": 3, "value": "Useful body", "group_id": "cards"},
                {"id": "item-media", "kind": "image", "role": "card_media", "order": 4, "value": "/images/service.svg", "group_id": "cards"},
            ],
            "groups": [
                {
                    "id": "cards",
                    "kind": "card",
                    "items": [
                        {
                            "id": "card-1",
                            "fields": {"title": "item-title", "body": "item-body", "media": "item-media"},
                        }
                    ],
                }
            ],
            "assets": [
                {"element_id": "item-media", "role": "card_media", "source_ref": "/images/service.svg"}
            ],
            "responsive": [
                {"breakpoint": "mobile", "observations": {"columns": 1, "direction": "vertical"}}
            ],
            "acceptable_templates": [],
        }
    ]
    if include_missing_section:
        sections.append(
            {
                "id": "expected-two",
                "order": 2,
                "boundary": {"kind": "css_selector", "value": "#missing"},
                "semantic_role": "rich_text",
                "content": [
                    {"id": "missing-text", "kind": "text", "role": "body", "order": 1, "value": "Missing", "group_id": None}
                ],
                "groups": [],
                "assets": [],
                "responsive": [],
                "acceptable_templates": ["rich-text"],
            }
        )
    return {"schema_version": "1.0", "expected": {"sections": sections}}


def _prediction(*, perfect: bool, include_extra: bool) -> tuple[BenchmarkCasePrediction, str]:
    document = _document(perfect=perfect, include_extra=include_extra)
    section = document.pages[0].sections[0]
    match = match_section(section, CATALOG)
    selected = match.selected_candidate.model_copy(update={"confidence": ConfidenceLevel.HIGH})
    match = match.model_copy(update={"selected_candidate": selected})
    slug = Path(selected.template_id).name
    return BenchmarkCasePrediction(case_id="case-one", document=document, matches=(match,)), slug


def _set_acceptable(annotation: dict, slug: str) -> dict:
    annotation["expected"]["sections"][0]["acceptable_templates"] = [slug]
    return annotation


def test_known_metric_counts_and_per_case_failures() -> None:
    prediction, selected_slug = _prediction(perfect=False, include_extra=True)
    annotation = _set_acceptable(_annotation(include_missing_section=True), selected_slug)

    report = evaluate_benchmark_case("case-one", "live_html", annotation, prediction)

    assert report.extraction.section_boundary_precision.value == 0.5
    assert report.extraction.section_boundary_recall.value == 0.5
    assert report.extraction.semantic_role_accuracy.value == 1.0
    assert report.extraction.visitor_content_retention.value == 0.6
    assert report.extraction.group_field_association_accuracy.value == pytest.approx(2 / 3, abs=1e-6)
    assert report.extraction.asset_association_accuracy.value == 1.0
    assert report.extraction.responsive_observation_coverage.value == 0.5
    assert report.matcher.template_top1_accuracy.value == 0.5
    assert report.matcher.template_top3_accuracy.value == 0.5
    assert report.matcher.high_confidence_precision.value == 1.0
    assert any(failure.section_id == "expected-two" for failure in report.failures)
    binding_failure = next(
        failure for failure in report.failures if failure.metric == "group_field_association_accuracy"
    )
    assert binding_failure.expected == "item-body"
    assert binding_failure.actual == "item-title"


def test_zero_denominators_are_not_measurable_or_implicitly_passing() -> None:
    report = evaluate_benchmark_case(
        "empty",
        "live_html",
        {"expected": {"sections": []}},
        BenchmarkCasePrediction(case_id="empty"),
    )

    for score in report.extraction.model_dump().values():
        assert score["value"] is None
        assert score["status"] == "not_measurable"
    for score in report.matcher.model_dump().values():
        assert score["value"] is None
        assert score["status"] == "not_measurable"


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


def test_regression_must_exceed_tolerance_and_thresholds_fail_safely() -> None:
    aggregate = _aggregate_with_precision(0.80)
    exact_tolerance = {"aggregate": {"section_boundary_precision": {"value": 0.82}}}
    beyond_tolerance = {"aggregate": {"section_boundary_precision": {"value": 0.820001}}}

    exact = compare_with_baseline(aggregate, exact_tolerance, tolerance=0.02)
    beyond = compare_with_baseline(aggregate, beyond_tolerance, tolerance=0.02)

    assert not next(item for item in exact if item.metric == "section_boundary_precision").failed
    assert next(item for item in beyond if item.metric == "section_boundary_precision").failed
    failures = evaluate_thresholds(aggregate, BenchmarkThresholds(template_top1_accuracy=0.85))
    assert any(failure.metric == "template_top1_accuracy" for failure in failures)


def test_new_template_annotations_are_excluded_from_native_match_accuracy() -> None:
    annotations = {
        "expected": {
            "sections": [
                {
                    "id": "missing-native-navigation",
                    "semantic_role": "navigation",
                    "content": [],
                    "groups": [],
                    "assets": [],
                    "responsive": [],
                    "acceptable_templates": ["new:global-navbar"],
                }
            ]
        }
    }

    report = evaluate_benchmark_case(
        "new-template-gap", "image", annotations, prediction=None
    )

    assert report.matcher.template_top1_accuracy.status == "not_measurable"
    assert report.matcher.template_top3_accuracy.status == "not_measurable"
    assert not any(failure.metric.startswith("template_top") for failure in report.failures)


def _write_corpus(root: Path, *, two_cases: bool = False) -> None:
    cases = []
    case_ids = ("case-one", "case-two") if two_cases else ("case-one",)
    for case_id in case_ids:
        case_dir = root / "cases" / case_id
        case_dir.mkdir(parents=True)
        (case_dir / "source.html").write_text("<main></main>", encoding="utf-8")
        annotation = _annotation(include_missing_section=False)
        (case_dir / "annotations.json").write_text(json.dumps(annotation), encoding="utf-8")
        reference = root / "references" / f"{case_id}.svg"
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_text("<svg/>", encoding="utf-8")
        cases.append(
            {
                "id": case_id,
                "source_kind": "live_html",
                "source": {"path": f"cases/{case_id}/source.html"},
                "annotations": f"cases/{case_id}/annotations.json",
                "references": [{"path": f"references/{case_id}.svg"}],
            }
        )
    manifest = {
        "schema_version": "1.0",
        "corpus": {"name": "Test Corpus", "regression_tolerance": 0.02},
        "cases": cases,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_offline_runner_passes_writes_reports_and_filters(tmp_path: Path) -> None:
    _write_corpus(tmp_path, two_cases=True)
    prediction, selected_slug = _prediction(perfect=True, include_extra=False)
    for case_id in ("case-one", "case-two"):
        path = tmp_path / "cases" / case_id / "annotations.json"
        annotation = _set_acceptable(json.loads(path.read_text(encoding="utf-8")), selected_slug)
        path.write_text(json.dumps(annotation), encoding="utf-8")
    second_prediction = prediction.model_copy(update={"case_id": "case-two"})
    json_path = tmp_path / "reports" / "score.json"
    human_path = tmp_path / "reports" / "score.md"

    result = run_offline_benchmark(
        {"case-one": prediction, "case-two": second_prediction},
        corpus_root=tmp_path,
        case_ids=["case-two"],
        json_output=json_path,
        human_output=human_path,
    )

    assert result.passed
    assert result.exit_code == 0
    assert result.report.case_filter == ("case-two",)
    assert [case.case_id for case in result.report.cases] == ["case-two"]
    assert json.loads(json_path.read_text(encoding="utf-8"))["aggregate"]
    assert "Aggregate metrics" in human_path.read_text(encoding="utf-8")
    assert render_benchmark_report(result.report).endswith("\n")


def test_offline_runner_fails_thresholds_for_missing_prediction(tmp_path: Path) -> None:
    _write_corpus(tmp_path)

    result = run_offline_benchmark({}, corpus_root=tmp_path)

    assert not result.passed
    assert result.exit_code == 1
    assert result.report.threshold_failures
    assert result.report.cases[0].failures[0].metric == "prediction_missing"


def test_offline_runner_reports_unknown_and_missing_fixtures(tmp_path: Path) -> None:
    _write_corpus(tmp_path)

    with pytest.raises(BenchmarkFixtureError, match="unknown benchmark case"):
        run_offline_benchmark({}, corpus_root=tmp_path, case_ids=["missing-case"])

    (tmp_path / "cases" / "case-one" / "source.html").unlink()
    with pytest.raises(BenchmarkFixtureError, match="missing benchmark source fixture"):
        run_offline_benchmark({}, corpus_root=tmp_path)


def test_explicit_missing_baseline_is_an_error(tmp_path: Path) -> None:
    _write_corpus(tmp_path)

    with pytest.raises(BenchmarkFixtureError, match="missing benchmark baseline"):
        run_offline_benchmark(
            {},
            corpus_root=tmp_path,
            baseline_path=tmp_path / "missing-baseline.json",
        )
