"""`vanjaro project capability-gaps` reads whatever plans a workspace has."""

from __future__ import annotations

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
    write_composition_plan,
)


def _write_plan(root: Path, project_id: str, *warnings: str) -> None:
    entry = CompositionPlanEntry(
        id="entry-1",
        source_section_id=f"{project_id}.section.1",
        template_id="Cards/testimonial-cards-3up",
        template="testimonial-cards-3up",
        match=PlanMatch(score=0.8, confidence="high"),
        block=PlanBlock(name=f"{project_id}-block", category="Cards"),
        warnings=tuple(warnings),
    )
    write_composition_plan(
        root / project_id / "plans" / "composition-plan.json",
        CompositionPlan(
            source_document_id=f"design:{project_id}",
            entries=(entry,),
            summary=PlanSummary(
                section_count=1,
                blocking_count=0,
                native_component_ratio=1.0,
                editable_content_coverage=1.0,
            ),
        ),
    )


def test_the_report_names_the_template_and_the_field(tmp_path: Path) -> None:
    _write_plan(tmp_path, "site-a", "source field 'section_title' is not editable by template")

    result = CliRunner().invoke(project, ["capability-gaps", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["projects"] == ["site-a"]
    assert payload["gaps"][0]["template_id"] == "Cards/testimonial-cards-3up"
    assert payload["gaps"][0]["field"] == "section_title"
    assert payload["dropped_field_count"] == 1


def test_a_project_that_has_not_planned_yet_is_skipped(tmp_path: Path) -> None:
    """A workspace mid-run is the normal state. Refusing to report until every
    project has planned would make the report unavailable exactly when wanted."""

    _write_plan(tmp_path, "planned", "source field 'section_title' is not editable by template")
    (tmp_path / "unplanned" / "sources").mkdir(parents=True)

    result = CliRunner().invoke(project, ["capability-gaps", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["projects"] == ["planned"]


def test_a_workspace_with_no_gaps_says_so(tmp_path: Path) -> None:
    _write_plan(tmp_path, "clean")

    result = CliRunner().invoke(project, ["capability-gaps", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "No template capability gaps" in result.output


def test_a_missing_root_is_an_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(project, ["capability-gaps", str(tmp_path / "absent"), "--json"])

    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "error"


def test_held_back_losses_are_listed_only_when_asked(tmp_path: Path) -> None:
    _write_plan(tmp_path, "site-a", "required interaction 'form' is unsupported")

    quiet = CliRunner().invoke(project, ["capability-gaps", str(tmp_path)])
    verbose = CliRunner().invoke(project, ["capability-gaps", str(tmp_path), "--held-back"])

    assert "held back" not in quiet.output
    assert "held back: 'form' is a missing behaviour" in verbose.output
