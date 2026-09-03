"""Explicit project-contract migration and CLI tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vanjaro_cli.commands.project_cmd import project
from vanjaro_cli.design.models import SourceKind
from vanjaro_cli.project import (
    PROJECT_MIGRATION_BACKUP,
    PROJECT_MIGRATION_JOURNAL,
    PROJECT_MIGRATION_RECEIPT,
    ProjectMigrationError,
    ProjectMigrationReport,
    ProjectSource,
    create_manifest,
    initialize_workspace,
    load_manifest,
    migrate_project_manifest,
)


def _legacy_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "legacy"
    manifest = create_manifest(
        name="Legacy Project",
        target_profile="legacy",
        sources=[
            ProjectSource(
                id="html",
                kind=SourceKind.LIVE_HTML,
                reference="https://example.test/",
            )
        ],
        agency_pack_name="agency",
        agency_pack_version="1.0.0",
    )
    initialize_workspace(root, manifest)
    payload = manifest.model_dump(mode="json")
    payload["schema_version"] = "1.0"
    payload["stages"].pop("launch")
    (root / "project.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root


def test_v1_manifest_requires_explicit_migration_and_dry_run_changes_nothing(
    tmp_path: Path,
) -> None:
    root = _legacy_workspace(tmp_path)
    before = (root / "project.json").read_bytes()

    with pytest.raises(ValueError, match="explicit migration"):
        load_manifest(root)
    report = migrate_project_manifest(root)

    assert report.status == "review_required"
    assert report.changes == (
        "schema_version:1.0->1.1",
        "stages.launch:added-pending",
    )
    assert (root / "project.json").read_bytes() == before
    assert not (root / PROJECT_MIGRATION_BACKUP).exists()


def test_apply_preserves_exact_backup_writes_receipt_and_is_idempotent(tmp_path: Path) -> None:
    root = _legacy_workspace(tmp_path)
    before = (root / "project.json").read_bytes()

    applied = migrate_project_manifest(root, apply=True)
    current = migrate_project_manifest(root, apply=True)

    assert applied.status == "applied"
    assert current.status == "current"
    assert (root / PROJECT_MIGRATION_BACKUP).read_bytes() == before
    assert not (root / PROJECT_MIGRATION_JOURNAL).exists()
    receipt = json.loads((root / PROJECT_MIGRATION_RECEIPT).read_text(encoding="utf-8"))
    assert receipt["migration_id"] == "project-1.0-to-1.1"
    assert load_manifest(root).schema_version == "1.1"
    assert load_manifest(root).stages["launch"].status.value == "pending"


def test_receipt_write_failure_leaves_recoverable_journal_and_retry_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import vanjaro_cli.project.migrations as migrations

    root = _legacy_workspace(tmp_path)
    real_write = migrations.atomic_write_json

    def fail_receipt(path: Path, value: object, *, pretty: bool = True):
        if path == root / PROJECT_MIGRATION_RECEIPT:
            raise migrations.ArtifactContractError("synthetic receipt failure")
        return real_write(path, value, pretty=pretty)

    monkeypatch.setattr(migrations, "atomic_write_json", fail_receipt)
    with pytest.raises(ProjectMigrationError, match="could not apply"):
        migrate_project_manifest(root, apply=True)

    assert (root / PROJECT_MIGRATION_JOURNAL).is_file()
    assert not (root / PROJECT_MIGRATION_RECEIPT).exists()
    assert json.loads((root / "project.json").read_text(encoding="utf-8"))["schema_version"] == "1.1"
    assert migrate_project_manifest(root).status == "recovery_required"

    monkeypatch.setattr(migrations, "atomic_write_json", real_write)
    recovered = migrate_project_manifest(root, apply=True)

    assert recovered.status == "applied"
    assert (root / PROJECT_MIGRATION_RECEIPT).is_file()
    assert not (root / PROJECT_MIGRATION_JOURNAL).exists()


def test_shape_drift_and_future_versions_are_rejected(tmp_path: Path) -> None:
    root = _legacy_workspace(tmp_path)
    payload = json.loads((root / "project.json").read_text(encoding="utf-8"))
    payload["stages"].pop("theme")
    (root / "project.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProjectMigrationError, match="shape is unsupported"):
        migrate_project_manifest(root)

    payload["schema_version"] = "9.0"
    (root / "project.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProjectMigrationError, match="unsupported"):
        migrate_project_manifest(root)


def test_migration_cli_is_review_first(runner, tmp_path: Path) -> None:
    root = _legacy_workspace(tmp_path)
    preview = runner.invoke(project, ["migrate-contract", str(root), "--json"])
    applied = runner.invoke(
        project, ["migrate-contract", str(root), "--apply", "--json"]
    )

    assert preview.exit_code == 0
    assert json.loads(preview.output)["status"] == "review_required"
    assert applied.exit_code == 0
    assert json.loads(applied.output)["status"] == "applied"


@pytest.mark.parametrize(
    "updates",
    [
        {"status": "current", "source_version": "1.0"},
        {"status": "current", "backup_path": PROJECT_MIGRATION_BACKUP.as_posix()},
        {"status": "review_required", "source_version": "1.1"},
        {"status": "review_required", "receipt_path": PROJECT_MIGRATION_RECEIPT.as_posix()},
        {"status": "applied", "backup_path": None},
        {"status": "recovery_required", "receipt_path": "history/wrong.json"},
    ],
)
def test_migration_report_rejects_impossible_status_source_path_combinations(
    updates: dict[str, object],
) -> None:
    payload = {
        "status": "current",
        "source_version": "1.1",
        "input_sha256": "a" * 64,
        "output_sha256": "a" * 64,
        "changes": [],
        **updates,
    }
    with pytest.raises(ValueError, match="inconsistent"):
        ProjectMigrationReport.model_validate(payload)


def test_complete_migration_receipt_must_match_reconstructed_report(tmp_path: Path) -> None:
    root = _legacy_workspace(tmp_path)
    migrate_project_manifest(root, apply=True)
    receipt_path = root / PROJECT_MIGRATION_RECEIPT
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["changes"] = ["schema_version:1.0->1.1"]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ProjectMigrationError, match="reconstructed migration report"):
        migrate_project_manifest(root)


def test_complete_migration_backup_transform_must_produce_current_manifest(
    tmp_path: Path,
) -> None:
    root = _legacy_workspace(tmp_path)
    migrate_project_manifest(root, apply=True)
    backup_path = root / PROJECT_MIGRATION_BACKUP
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    backup["project"]["name"] = "Altered Historical Project"
    backup_path.write_text(json.dumps(backup), encoding="utf-8")

    with pytest.raises(ProjectMigrationError, match="does not produce the current manifest"):
        migrate_project_manifest(root)
