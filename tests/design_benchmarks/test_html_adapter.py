"""End-to-end acceptance tests for committed live-HTML benchmark fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from vanjaro_cli.design.html_adapter import design_document_from_html
from vanjaro_cli.design.metrics import BenchmarkCasePrediction, evaluate_benchmark_case
from vanjaro_cli.design.models import EvidenceStatus


CORPUS = Path(__file__).parents[1] / "fixtures" / "design-benchmarks"
CAPTURED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
HTML_CASES = (
    "html-bootstrap-agency",
    "html-elementor-studio",
    "html-dnn-services",
)


def _prediction(case_id: str) -> tuple[dict, BenchmarkCasePrediction]:
    case_root = CORPUS / "cases" / case_id
    annotation = json.loads((case_root / "annotations.json").read_text(encoding="utf-8"))
    document = design_document_from_html(
        (case_root / "source.html").read_text(encoding="utf-8"),
        f"https://benchmark.invalid/{case_id}",
        captured_at=CAPTURED_AT,
    )
    return annotation, BenchmarkCasePrediction(case_id=case_id, document=document)


@pytest.mark.parametrize("case_id", HTML_CASES)
def test_html_fixture_boundaries_roles_and_relationships_score_perfectly(case_id: str) -> None:
    annotation, prediction = _prediction(case_id)
    report = evaluate_benchmark_case(case_id, "live_html", annotation, prediction)
    extraction = report.extraction

    assert extraction.section_boundary_precision.value == 1.0
    assert extraction.section_boundary_recall.value == 1.0
    assert extraction.semantic_role_accuracy.value == 1.0
    assert extraction.visitor_content_retention.value == 1.0
    assert extraction.group_field_association_accuracy.value == 1.0
    assert extraction.asset_association_accuracy.value == 1.0


@pytest.mark.parametrize("case_id", HTML_CASES)
def test_html_fixture_uses_source_selectors_not_annotation_ids(case_id: str) -> None:
    annotation, prediction = _prediction(case_id)
    expected = annotation["expected"]["sections"]
    actual = prediction.document.pages[0].sections

    assert [section.semantic_role for section in actual] == [item["semantic_role"] for item in expected]
    assert [section.provenance[0].css_selector for section in actual] == [
        item["boundary"]["value"] for item in expected
    ]
    annotation_ids = {
        element["id"] for section in expected for element in section["content"]
    }
    actual_ids = {
        element.id for section in actual for element in section.content
    }
    assert annotation_ids.isdisjoint(actual_ids)


def test_static_responsive_evidence_is_conservative_and_explicitly_inferred() -> None:
    reports = []
    observations = []
    for case_id in HTML_CASES:
        annotation, prediction = _prediction(case_id)
        reports.append(evaluate_benchmark_case(case_id, "live_html", annotation, prediction))
        observations.extend(
            responsive
            for section in prediction.document.pages[0].sections
            for responsive in section.responsive
        )

    correct = sum(report.extraction.responsive_observation_coverage.numerator for report in reports)
    expected = sum(report.extraction.responsive_observation_coverage.denominator for report in reports)
    assert correct / expected >= 0.60
    assert observations
    assert all(item.status == EvidenceStatus.INFERRED for item in observations)
    # Unsupported visual details remain failures instead of being fabricated.
    assert any(
        failure.path.endswith(".min_height")
        for report in reports
        for failure in report.failures
    )

