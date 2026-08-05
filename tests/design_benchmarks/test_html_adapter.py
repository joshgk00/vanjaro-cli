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



def test_video_reclassified_as_media_does_not_leave_a_dangling_interaction():
    """A video the classifier reads as section media must not break the document.

    Interaction targets come from the raw crawl (`.video.N`) while element IDs
    are rebuilt from the classified role (`.section-media.N`). When those
    disagree the target cannot resolve, and the Design Document validator
    rejects the whole document. The interaction is still real, so only the
    unresolvable pointer is dropped.
    """

    html = """
    <html><body>
      <section id="promo">
        <h2>See how it works</h2>
        <video src="/promo.mp4"></video>
      </section>
    </body></html>
    """

    document = design_document_from_html(html, source_url="https://agency.example/")

    section = document.pages[0].sections[0]
    element_ids = {element.id for element in section.content}
    for interaction in section.interactions:
        assert set(interaction.target_element_ids) <= element_ids


def test_asset_urls_do_not_win_a_boundary_from_the_section_that_holds_the_copy():
    """Boundary matching compares visitor-facing words only.

    A text-free band still carries an image URL, and URL path tokens collide
    with real copy. Scoring those let an empty section outscore the pane that
    actually contained the page's text and take it, leaving the real content
    section bound to the wrong boundary with nothing to place.
    """

    from vanjaro_cli.design.html_boundaries import prepare_static_sections

    html = """
    <html><body>
      <div id="dnn_BannerPane" class="Pane">
        <img src="/Portals/0/adam/Content/banner.png" alt="">
      </div>
      <div id="dnn_TopPane" class="Pane">
        <h2>Who is Adam Consulting?</h2>
        <p>Adam Consulting brings organisations together for shared outcomes.</p>
      </div>
    </body></html>
    """
    raw = [
        {"type": "hero", "content": {"headings": [], "paragraphs": [],
         "images": [{"src": "/Portals/0/adam/Content/banner.png", "alt": ""}]}},
        {"type": "bio", "content": {"headings": ["Who is Adam Consulting?"],
         "paragraphs": ["Adam Consulting brings organisations together for shared outcomes."],
         "images": []}},
    ]

    prepared = prepare_static_sections(html, raw)

    assert prepared[0]["_static_selector"] == "#dnn_BannerPane"
    assert prepared[1]["_static_selector"] == "#dnn_TopPane"
