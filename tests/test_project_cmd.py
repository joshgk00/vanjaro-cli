"""CLI tests for agency project initialization and status."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.cli import cli
from vanjaro_cli.project import (
    MANIFEST_FILENAME,
    WORKSPACE_DIRECTORIES,
    ProjectStage,
    StageEngine,
    StageInputs,
    StageResult,
)


def test_project_init_and_status_support_combined_sources(runner, tmp_path: Path) -> None:
    root = tmp_path / "agency-project"
    result = runner.invoke(
        cli,
        [
            "project",
            "init",
            str(root),
            "--name",
            "Agency Project",
            "--target-profile",
            "agency-project",
            "--expected-portal-id",
            "7",
            "--source",
            "live_html=https://agency.example/",
            "--source",
            "figma=https://figma.example/design/file?node-id=1-2",
            "--source-page",
            "live-html-1=home",
            "--source-page",
            "figma-1=home",
            "--source-page",
            "image-1=home",
            "--source",
            "image=references/mobile.png",
            "--image-viewport",
            "390x844",
            "--image-breakpoint",
            "image-1=mobile",
            "--image-evidence",
            "image-1=sources/mobile.evidence.json",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "status": "ok",
        "manifest": str(root / MANIFEST_FILENAME),
        "project_id": "agency-project",
        "target_profile": "agency-project",
        "sources": 3,
        "next_stage": "analyze",
    }
    assert all((root / directory).is_dir() for directory in WORKSPACE_DIRECTORIES)
    manifest = json.loads((root / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert [source["page_reference"] for source in manifest["sources"][:2]] == [
        "home",
        "home",
    ]
    assert manifest["sources"][2]["evidence_reference"] == (
        "sources/mobile.evidence.json"
    )

    status = runner.invoke(cli, ["project", "status", str(root), "--json"])
    assert status.exit_code == 0, status.output
    status_payload = json.loads(status.output)
    assert status_payload["status"] == "ok"
    assert status_payload["completed_stages"] == ["intake"]
    assert status_payload["next_stage"] == "analyze"
    assert status_payload["missing_directories"] == []


def test_project_init_requires_viewport_for_each_image(runner, tmp_path: Path) -> None:
    root = tmp_path / "invalid"
    result = runner.invoke(
        cli,
        [
            "project",
            "init",
            str(root),
            "--name",
            "Invalid",
            "--target-profile",
            "invalid",
            "--source",
            "image=desktop.png",
            "--json",
        ],
    )

    assert result.exit_code == 1
    assert "one --image-viewport each" in json.loads(result.output)["message"]
    assert not root.exists()


def test_project_init_requires_explicit_image_page_and_breakpoint(
    runner, tmp_path: Path
) -> None:
    root = tmp_path / "invalid-image-metadata"
    missing_page = runner.invoke(
        cli,
        [
            "project",
            "init",
            str(root),
            "--name",
            "Invalid",
            "--target-profile",
            "invalid",
            "--source",
            "image=sources/desktop.png",
            "--image-viewport",
            "1440x900",
            "--image-breakpoint",
            "image-1=desktop",
            "--json",
        ],
    )
    assert missing_page.exit_code == 1
    assert "requires --source-page" in json.loads(missing_page.output)["message"]
    assert not root.exists()

    missing_breakpoint = runner.invoke(
        cli,
        [
            "project",
            "init",
            str(root),
            "--name",
            "Invalid",
            "--target-profile",
            "invalid",
            "--source",
            "image=sources/desktop.png",
            "--image-viewport",
            "1440x900",
            "--source-page",
            "image-1=home",
            "--json",
        ],
    )
    assert missing_breakpoint.exit_code == 1
    assert "requires --image-breakpoint" in json.loads(missing_breakpoint.output)[
        "message"
    ]
    assert not root.exists()


def test_project_init_rejects_image_evidence_for_non_image_source(
    runner, tmp_path: Path
) -> None:
    root = tmp_path / "invalid-evidence"
    result = runner.invoke(
        cli,
        [
            "project",
            "init",
            str(root),
            "--name",
            "Invalid",
            "--target-profile",
            "invalid",
            "--source",
            "html=https://agency.example/",
            "--image-evidence",
            "live-html-1=sources/evidence.json",
            "--json",
        ],
    )
    assert result.exit_code == 1
    assert "non-image source" in json.loads(result.output)["message"]
    assert not root.exists()


def test_project_init_rejects_secret_urls_without_writing(runner, tmp_path: Path) -> None:
    root = tmp_path / "secret"
    result = runner.invoke(
        cli,
        [
            "project",
            "init",
            str(root),
            "--name",
            "Secret",
            "--target-profile",
            "secret",
            "--source",
            "figma=https://figma.example/file?access_token=secret",
            "--json",
        ],
    )

    assert result.exit_code == 1
    assert "secret query parameter" in json.loads(result.output)["message"]
    assert not root.exists()


def test_project_init_refuses_existing_content(runner, tmp_path: Path) -> None:
    root = tmp_path / "existing"
    root.mkdir()
    existing = root / "keep.txt"
    existing.write_text("keep", encoding="utf-8")

    result = runner.invoke(
        cli,
        [
            "project",
            "init",
            str(root),
            "--name",
            "Existing",
            "--target-profile",
            "existing",
            "--source",
            "html=https://agency.example/",
            "--json",
        ],
    )

    assert result.exit_code == 1
    assert "not empty" in json.loads(result.output)["message"]
    assert existing.read_text(encoding="utf-8") == "keep"


def test_project_approval_request_and_resolution_are_explicit(runner, tmp_path: Path) -> None:
    root = tmp_path / "approval"
    initialized = runner.invoke(
        cli,
        [
            "project",
            "init",
            str(root),
            "--name",
            "Approval",
            "--target-profile",
            "approval",
            "--source",
            "html=https://agency.example/",
        ],
    )
    assert initialized.exit_code == 0, initialized.output

    def write(relative: str, value: str):
        def operation(context):
            path = context.root / relative
            path.write_text(value, encoding="utf-8")
            return StageResult(artifacts=(relative,), message="complete")
        return operation

    engine = StageEngine(root)
    engine.execute(
        ProjectStage.ANALYZE,
        StageInputs(),
        write("analysis/design-document.json", "analysis"),
    )
    engine.execute(
        ProjectStage.PLAN,
        StageInputs(files=(Path("analysis/design-document.json"),)),
        write("plans/composition-plan.json", "plan"),
    )

    requested = runner.invoke(
        cli,
        [
            "project",
            "approval",
            "request",
            str(root),
            "--gate",
            "portal_mutation",
            "--by",
            "Josh",
            "--json",
        ],
    )
    assert requested.exit_code == 0, requested.output
    request_payload = json.loads(requested.output)["approval"]
    assert request_payload["status"] == "pending"
    assert request_payload["requested_by"] == "Josh"

    resolved = runner.invoke(
        cli,
        [
            "project",
            "approval",
            "resolve",
            str(root),
            request_payload["id"],
            "--decision",
            "approve",
            "--by",
            "Josh",
            "--json",
        ],
    )
    assert resolved.exit_code == 0, resolved.output
    resolved_payload = json.loads(resolved.output)["approval"]
    assert resolved_payload["status"] == "approved"
    assert resolved_payload["fingerprint"] == request_payload["fingerprint"]
