"""CliRunner coverage for offline Composition Plan commands."""

from __future__ import annotations

import json

from vanjaro_cli.cli import cli
from vanjaro_cli.design.serialization import write_design_document
from tests.test_design_planner import _document, _feature_section


def test_blocks_plan_writes_v2_and_backward_compatible_library_plan(runner, tmp_path) -> None:
    design_path = tmp_path / "design-document.json"
    plan_path = tmp_path / "composition-plan.json"
    library_path = tmp_path / "library-plan.json"
    write_design_document(design_path, _document(_feature_section()))

    result = runner.invoke(
        cli,
        [
            "blocks",
            "plan",
            "--design",
            str(design_path),
            "--output",
            str(plan_path),
            "--library-plan",
            str(library_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["sections"] == 1
    assert plan_path.exists()
    assert library_path.exists()
    assert json.loads(plan_path.read_text(encoding="utf-8"))["schema_version"] == "2.0"
    library = json.loads(library_path.read_text(encoding="utf-8"))
    assert library[0]["template"] == "Feature Cards (3-up)"
    # Pack 1.6.0 gave the card templates a section title, so heading_1 is the
    # section's own heading and the card titles follow it.
    assert library[0]["overrides"]["heading_1"] == "Our Services"
    assert library[0]["overrides"]["heading_2"] == "Service 1"
    assert library[0]["overrides"]["heading_4"] == ""

    compatibility = runner.invoke(
        cli,
        ["blocks", "build-library", "--plan", str(library_path), "--dry-run", "--json"],
    )
    assert compatibility.exit_code == 0, compatibility.output
    assert json.loads(compatibility.output)["summary"]["total"] == 1


def test_blocks_plan_dry_run_and_explain_do_not_write(runner, tmp_path) -> None:
    design_path = tmp_path / "design-document.json"
    plan_path = tmp_path / "composition-plan.json"
    write_design_document(design_path, _document(_feature_section()))

    result = runner.invoke(
        cli,
        [
            "blocks",
            "plan",
            "--design",
            str(design_path),
            "--output",
            str(plan_path),
            "--dry-run",
            "--explain",
            "home.services",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["explanation"]["source_section_id"] == "home.services"
    assert not plan_path.exists()


def test_blocks_plan_returns_structured_error_for_bad_override(runner, tmp_path) -> None:
    design_path = tmp_path / "design-document.json"
    write_design_document(design_path, _document(_feature_section()))

    result = runner.invoke(
        cli,
        [
            "blocks",
            "plan",
            "--design",
            str(design_path),
            "--output",
            str(tmp_path / "plan.json"),
            "--template-override",
            "bad-format",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["category"] == "invalid_option"
    assert "SECTION_ID=TEMPLATE_NAME" in payload["error"]["recommended_action"]


def test_blocks_plan_validate_accepts_generated_plan(runner, tmp_path) -> None:
    design_path = tmp_path / "design-document.json"
    plan_path = tmp_path / "composition-plan.json"
    write_design_document(design_path, _document(_feature_section()))
    planned = runner.invoke(
        cli,
        ["blocks", "plan", "--design", str(design_path), "--output", str(plan_path)],
    )
    assert planned.exit_code == 0, planned.output

    result = runner.invoke(cli, ["blocks", "plan-validate", str(plan_path), "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"status": "ok", "entries": 1, "issues": []}


def test_blocks_plan_validate_reports_malformed_artifact(runner, tmp_path) -> None:
    plan_path = tmp_path / "composition-plan.json"
    plan_path.write_text('{"schema_version": "2.0", "entries": [}', encoding="utf-8")

    result = runner.invoke(cli, ["blocks", "plan-validate", str(plan_path), "--json"])

    assert result.exit_code == 1
    assert json.loads(result.output)["error"]["category"] == "invalid_composition_plan"
