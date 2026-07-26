"""Committed-source acceptance coverage for the complete offline design pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re

import pytest

from vanjaro_cli.cli import cli
from vanjaro_cli.design.composition import SimplificationKind
from vanjaro_cli.design.figma_adapter import analyze_figma_document
from vanjaro_cli.design.html_adapter import design_document_from_html
from vanjaro_cli.design.matcher import match_design_document
from vanjaro_cli.design.models import DesignDocument
from vanjaro_cli.design.planner import (
    emit_library_plan,
    plan_design_document,
    serialize_library_plan,
    validate_composition_plan,
)
from vanjaro_cli.design.serialization import (
    deserialize_design_document,
    serialize_design_document,
)
from vanjaro_cli.design.template_catalog import load_template_catalog
from vanjaro_cli.utils.block_compose import apply_overrides, check_overflow, find_template
from vanjaro_cli.utils.grapesjs import render_components, render_styles


CORPUS = Path(__file__).parents[1] / "fixtures" / "design-benchmarks"
MANIFEST = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
CASES = tuple(case["id"] for case in MANIFEST["cases"])
CAPTURED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
CATALOG = load_template_catalog()

# Exact committed coverage: every source has five annotated sections. Blocking
# entries remain in Composition Plan v2 but are deliberately absent from the
# backward-compatible library plan and dry-run payload.
EXPECTED_COVERAGE = {
    "html-bootstrap-agency": {"sections": 5, "blocking": 1, "composed": 4},
    "html-elementor-studio": {"sections": 5, "blocking": 0, "composed": 5},
    "html-dnn-services": {"sections": 5, "blocking": 0, "composed": 5},
    "figma-auto-layout-saas": {"sections": 5, "blocking": 1, "composed": 4},
    "figma-freeform-nonprofit": {"sections": 5, "blocking": 1, "composed": 4},
}

_PLACEHOLDER = re.compile(
    r"(?:placehold\.co|via\.placeholder|lorem\s+ipsum|your\s+headline\s+here)",
    re.IGNORECASE,
)
_REMOTE_SOURCE = re.compile(r"(?:https?://|figma://)", re.IGNORECASE)


def _case(case_id: str) -> tuple[dict, dict, Path]:
    manifest_case = next(case for case in MANIFEST["cases"] if case["id"] == case_id)
    annotation_path = CORPUS / manifest_case["annotations"]
    return (
        manifest_case,
        json.loads(annotation_path.read_text(encoding="utf-8")),
        CORPUS / manifest_case["source"]["path"],
    )


def _analyze(case_id: str) -> tuple[DesignDocument, dict]:
    manifest_case, annotation, source_path = _case(case_id)
    if manifest_case["source_kind"] == "live_html":
        document = design_document_from_html(
            source_path.read_text(encoding="utf-8"),
            f"https://benchmark.invalid/{case_id}",
            title=manifest_case["title"],
            captured_at=CAPTURED_AT,
        )
    else:
        document = analyze_figma_document(
            json.loads(source_path.read_text(encoding="utf-8")),
            file_key=case_id,
            captured_at=CAPTURED_AT,
        )
    return document, annotation


def _with_migrated_assets(document: DesignDocument, case_id: str) -> DesignDocument:
    """Model the asset phase that precedes block composition in a live run."""

    assets = [
        asset.model_copy(
            update={
                "local_path": f"/Portals/0/e2e/{case_id}/{asset.id}.bin",
                "missing_reason": None,
            }
        )
        for asset in document.assets
    ]
    return document.model_copy(update={"assets": assets})


def _assert_committed_schema(document: DesignDocument) -> DesignDocument:
    serialized = serialize_design_document(document)
    decoded = deserialize_design_document(serialized)
    assert decoded == document

    committed = json.loads(
        (Path(__file__).parents[2] / "schemas" / "design-document-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    generated = DesignDocument.model_json_schema()
    for key in {"$id", "$schema", "description", "title", "x-validation-notes"}:
        committed.pop(key, None)
        generated.pop(key, None)
    assert committed == generated
    return decoded


@pytest.mark.parametrize("case_id", CASES)
def test_committed_source_runs_through_full_offline_pipeline(
    case_id: str,
    runner,
    tmp_path: Path,
) -> None:
    document, annotation = _analyze(case_id)
    document = _with_migrated_assets(_assert_committed_schema(document), case_id)
    expected_sections = annotation["expected"]["sections"]
    coverage = EXPECTED_COVERAGE[case_id]

    assert len(document.pages) == 1
    assert len(document.pages[0].sections) == coverage["sections"]
    assert len(expected_sections) == coverage["sections"]
    matches = match_design_document(document, CATALOG)
    assert len(matches) == coverage["sections"]

    plan = plan_design_document(document, catalog=CATALOG)
    assert len(plan.entries) == coverage["sections"]
    assert plan.summary.blocking_count == coverage["blocking"]
    assert [entry.source_section_id for entry in plan.entries] == [
        section.id for section in document.pages[0].sections
    ]

    blocking = [entry for entry in plan.entries if entry.match.blocking]
    issues = validate_composition_plan(plan, catalog=CATALOG)
    assert len(issues) == len(blocking)
    assert all("unresolved blocking match or simplification" in issue for issue in issues)

    # An explicitly unavailable benchmark target must remain visible as a
    # blocker; the pipeline may not silently force its nearest native match.
    for expected, entry in zip(expected_sections, plan.entries, strict=True):
        if any(value.startswith("new:") for value in expected["acceptable_templates"]):
            assert entry.match.blocking is True
            assert any(
                decision.classification == SimplificationKind.NEW_TEMPLATE
                for decision in entry.simplifications
            )
            assert expected["semantic_role"] == "navigation"

    library_plan = emit_library_plan(plan)
    assert len(library_plan) == coverage["composed"]
    assert {entry["name"] for entry in library_plan}.isdisjoint(
        entry.block.name for entry in blocking
    )

    composed_payloads = []
    for entry in library_plan:
        template = find_template(entry["template"])
        assert check_overflow(template, entry["overrides"]) == []
        composed = apply_overrides(template, entry["overrides"])
        rendered = render_components([composed["template"]]) + render_styles(
            composed.get("styles", [])
        )
        payload = json.dumps(composed, ensure_ascii=False, sort_keys=True) + rendered
        assert _PLACEHOLDER.search(payload) is None
        assert _REMOTE_SOURCE.search(payload) is None
        composed_payloads.append(composed)
    assert len(composed_payloads) == coverage["composed"]

    library_path = tmp_path / f"{case_id}-library-plan.json"
    library_path.write_text(serialize_library_plan(plan), encoding="utf-8")
    dry_run = runner.invoke(
        cli,
        [
            "blocks",
            "build-library",
            "--plan",
            str(library_path),
            "--dry-run",
            "--json",
        ],
    )
    assert dry_run.exit_code == 0, dry_run.output
    dry_run_payload = json.loads(dry_run.output)
    assert dry_run_payload["status"] == "ok"
    assert dry_run_payload["summary"] == {
        "total": coverage["composed"],
        "created": 0,
        "failed": 0,
    }
    assert all(item["status"] == "dry_run" for item in dry_run_payload["results"])


def test_exact_corpus_coverage_and_remote_assets_block_instead_of_leaking() -> None:
    assert sum(item["sections"] for item in EXPECTED_COVERAGE.values()) == 25
    assert sum(item["blocking"] for item in EXPECTED_COVERAGE.values()) == 3
    assert sum(item["composed"] for item in EXPECTED_COVERAGE.values()) == 22

    document, _annotation = _analyze("html-dnn-services")
    plan = plan_design_document(document, catalog=CATALOG)
    blocked_roles = {
        section.semantic_role
        for section, entry in zip(document.pages[0].sections, plan.entries, strict=True)
        if entry.match.blocking
    }
    assert blocked_roles == {"hero", "split_feature"}
    assert all(
        any(decision.classification == SimplificationKind.NEW_TEMPLATE for decision in entry.simplifications)
        for entry in plan.entries
        if entry.match.blocking
    )
    emitted = serialize_library_plan(plan)
    assert "https://benchmark.invalid" not in emitted
    assert "figma://" not in emitted

