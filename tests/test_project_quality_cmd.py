"""CliRunner coverage for `vanjaro project quality`."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from click.testing import CliRunner

from vanjaro_cli.commands.project_cmd import project
from vanjaro_cli.design.composition import (
    CompositionPlan,
    CompositionPlanEntry,
    PlanBlock,
    PlanMatch,
    PlanSummary,
    SemanticBinding,
    serialize_composition_plan,
)
from vanjaro_cli.design.models import SourceKind
from vanjaro_cli.design.template_catalog import load_template_catalog
from vanjaro_cli.project import ProjectSource, create_manifest, initialize_workspace
from vanjaro_cli.release.models import ProjectQualityEvidence

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_template_catalog(ROOT / "artifacts" / "block-templates")


def _template(filename: str):
    return next(entry for entry in CATALOG if Path(entry.relative_path).name == filename)


def _plan() -> CompositionPlan:
    hero = _template("centered-hero.json")
    rich_text = _template("rich-text.json")
    entries = (
        CompositionPlanEntry(
            id="home.section.1.plan",
            source_section_id="home.section.1",
            template_id=hero.template_id,
            template=hero.name,
            match=PlanMatch(score=0.95, confidence="high"),
            block=PlanBlock(name="Home Hero", category=hero.category),
            bindings=(
                SemanticBinding(
                    semantic_field="heading",
                    slot="heading",
                    source_element_ids=("el-1",),
                    value="Welcome",
                    editable=True,
                ),
            ),
        ),
        CompositionPlanEntry(
            id="home.section.2.plan",
            source_section_id="home.section.2",
            template_id=rich_text.template_id,
            template=rich_text.name,
            match=PlanMatch(score=0.8, confidence="medium"),
            block=PlanBlock(name="Home Body", category=rich_text.category),
            bindings=(
                SemanticBinding(
                    semantic_field="body",
                    slot="body",
                    source_element_ids=("el-2",),
                    value="More copy",
                    editable=True,
                ),
            ),
        ),
    )
    return CompositionPlan(
        source_document_id="quality-cmd-doc",
        entries=entries,
        summary=PlanSummary(
            section_count=len(entries),
            blocking_count=0,
            native_component_ratio=1.0,
            editable_content_coverage=1.0,
        ),
    )


def _workspace(tmp_path: Path, *, project_id: str = "quality-cmd") -> Path:
    root = tmp_path / project_id
    manifest = create_manifest(
        name="Quality Command",
        project_id=project_id,
        target_profile="client-one",
        sources=[
            ProjectSource(
                id="live-home",
                kind=SourceKind.LIVE_HTML,
                reference="https://source.example/",
            )
        ],
        agency_pack_name="clicks-and-mortars",
        agency_pack_version="2.0.0",
        clock=lambda: NOW,
    )
    initialize_workspace(root, manifest)
    plan_path = root / "plans/composition-plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(serialize_composition_plan(_plan()), encoding="utf-8")
    return root


def test_project_quality_reports_table_and_ratios(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    result = CliRunner().invoke(project, ["quality", str(root)])

    assert result.exit_code == 0, result.output
    assert "quality-cmd" in result.output
    assert "eligible_section_editable_coverage: 2/2" in result.output
    assert "body_without_generic_fallback: 1/2" in result.output
    assert "home.section.1.plan" in result.output
    assert "no resolved design document" in result.output


def test_project_quality_json_output(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    result = CliRunner().invoke(project, ["quality", str(root), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["project_id"] == "quality-cmd"
    assert payload["quality"]["eligible_section_editable_coverage"]["numerator"] == 2
    assert payload["quality"]["eligible_section_editable_coverage"]["denominator"] == 2
    assert payload["quality"]["body_without_generic_fallback"]["numerator"] == 1
    assert len(payload["rows"]) == 2
    assert any("no resolved design document" in warning for warning in payload["warnings"])
    assert payload["output"] is None


def test_project_quality_output_writes_valid_evidence_document(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    output_path = tmp_path / "quality-counts.json"

    result = CliRunner().invoke(
        project,
        [
            "quality",
            str(root),
            "--candidate-id",
            "candidate-1",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0, result.output
    document = json.loads(output_path.read_text(encoding="utf-8"))
    evidence = ProjectQualityEvidence.model_validate(document)
    assert evidence.candidate_id == "candidate-1"
    assert evidence.project_id == "quality-cmd"
    assert evidence.source_kind == "live_html"
    assert evidence.quality.eligible_section_editable_coverage.numerator == 2
    assert evidence.quality.eligible_section_editable_coverage.denominator == 2


def test_project_quality_requires_candidate_id_and_output_together(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    result = CliRunner().invoke(
        project, ["quality", str(root), "--candidate-id", "candidate-1"]
    )

    assert result.exit_code != 0
    assert "--candidate-id and --output must be used together" in result.output


def test_project_quality_reports_missing_plan(tmp_path: Path) -> None:
    root = tmp_path / "no-plan"
    manifest = create_manifest(
        name="No Plan",
        project_id="no-plan",
        target_profile="client-one",
        sources=[
            ProjectSource(
                id="live-home",
                kind=SourceKind.LIVE_HTML,
                reference="https://source.example/",
            )
        ],
        agency_pack_name="clicks-and-mortars",
        agency_pack_version="2.0.0",
        clock=lambda: NOW,
    )
    initialize_workspace(root, manifest)

    result = CliRunner().invoke(project, ["quality", str(root)])

    assert result.exit_code != 0
    assert "composition-plan.json" in result.output
