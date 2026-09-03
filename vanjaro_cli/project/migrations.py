"""Explicit, reviewable migrations for persisted agency project contracts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from vanjaro_cli.project.models import ProjectManifest, ProjectStage, StageRecord
from vanjaro_cli.project.workspace import MANIFEST_FILENAME
from vanjaro_cli.reliability.artifacts import (
    ArtifactContractError,
    atomic_write_json,
    canonical_json_bytes,
    load_strict_json,
)
from vanjaro_cli.reliability.contracts import (
    PROJECT_MIGRATION_REPORT_SCHEMA,
    PROJECT_MIGRATION_TRANSACTION_SCHEMA,
)


PROJECT_MIGRATION_ID = "project-1.0-to-1.1"
PROJECT_MIGRATION_RECEIPT = Path(
    "history/contract-migrations/project-1.0-to-1.1.json"
)
PROJECT_MIGRATION_BACKUP = Path(
    "history/contract-migrations/project-v1.0.json"
)
PROJECT_MIGRATION_JOURNAL = Path(
    "history/contract-migrations/project-1.0-to-1.1.pending.json"
)


class ProjectMigrationError(ValueError):
    """Raised when a project contract cannot be migrated safely."""


class ProjectMigrationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["project-migration-report-v1"] = PROJECT_MIGRATION_REPORT_SCHEMA
    migration_id: Literal["project-1.0-to-1.1"] = PROJECT_MIGRATION_ID
    status: Literal["current", "review_required", "recovery_required", "applied"]
    source_version: Literal["1.0", "1.1"]
    target_version: Literal["1.1"] = "1.1"
    manifest_path: Literal["project.json"] = "project.json"
    backup_path: str | None = None
    receipt_path: str | None = None
    input_sha256: str
    output_sha256: str
    changes: tuple[str, ...]

    @model_validator(mode="after")
    def _require_consistent_state(self) -> "ProjectMigrationReport":
        historical = (self.backup_path, self.receipt_path)
        canonical = (
            PROJECT_MIGRATION_BACKUP.as_posix(),
            PROJECT_MIGRATION_RECEIPT.as_posix(),
        )
        if self.status == "current":
            valid = self.source_version == "1.1" and historical == (None, None)
        elif self.status == "review_required":
            valid = self.source_version == "1.0" and historical == (None, None)
        else:
            valid = self.source_version == "1.0" and historical == canonical
        if not valid:
            raise ValueError(
                "migration status, source version, and artifact paths are inconsistent"
            )
        return self


def migrate_project_manifest(root: Path, *, apply: bool = False) -> ProjectMigrationReport:
    """Review or apply the only supported project v1.0 to v1.1 migration."""

    root = root.expanduser().resolve()
    path = root / MANIFEST_FILENAME
    try:
        original = path.read_bytes()
        payload = load_strict_json(path)
    except (OSError, ArtifactContractError) as exc:
        raise ProjectMigrationError(f"cannot read project manifest for migration: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProjectMigrationError("project manifest must contain a JSON object")
    source_version = payload.get("schema_version")
    input_sha256 = hashlib.sha256(original).hexdigest()
    interrupted = _recover_interrupted_migration(
        root,
        current_bytes=original,
        current_payload=payload,
        apply=apply,
    )
    if interrupted is not None:
        return interrupted
    if source_version == "1.1":
        try:
            current = ProjectManifest.model_validate(payload)
        except ValidationError as exc:
            raise ProjectMigrationError(f"current project manifest is invalid: {exc}") from exc
        output = canonical_json_bytes(current)
        current_report = ProjectMigrationReport(
            status="current",
            source_version="1.1",
            input_sha256=input_sha256,
            output_sha256=hashlib.sha256(output).hexdigest(),
            changes=(),
        )
        return _require_complete_migration_artifacts(
            root,
            current_bytes=original,
            current_report=current_report,
            apply=apply,
        )
    if source_version != "1.0":
        raise ProjectMigrationError(
            f"unsupported project schema version {source_version!r}; only 1.0 can migrate to 1.1"
        )

    migrated = dict(payload)
    stages = migrated.get("stages")
    if not isinstance(stages, dict):
        raise ProjectMigrationError("project 1.0 stages must be a JSON object")
    required_old = {
        stage.value for stage in ProjectStage
    } - {ProjectStage.ASSETS.value, ProjectStage.LAUNCH.value}
    allowed_old = required_old | {ProjectStage.ASSETS.value}
    if not required_old.issubset(stages) or not set(stages).issubset(allowed_old):
        missing = sorted(required_old - set(stages))
        extra = sorted(set(stages) - allowed_old)
        raise ProjectMigrationError(
            f"project 1.0 stage shape is unsupported; missing={missing}, extra={extra}"
        )
    migrated["schema_version"] = "1.1"
    migrated["stages"] = dict(stages)
    changes = ["schema_version:1.0->1.1"]
    if ProjectStage.ASSETS.value not in migrated["stages"]:
        migrated["stages"][ProjectStage.ASSETS.value] = StageRecord(
            stage=ProjectStage.ASSETS
        ).model_dump(mode="json")
        changes.append("stages.assets:added-pending")
    migrated["stages"][ProjectStage.LAUNCH.value] = StageRecord(
        stage=ProjectStage.LAUNCH
    ).model_dump(mode="json")
    changes.append("stages.launch:added-pending")
    try:
        validated = ProjectManifest.model_validate(migrated)
    except ValidationError as exc:
        raise ProjectMigrationError(f"project 1.0 cannot migrate safely: {exc}") from exc
    output = canonical_json_bytes(validated)
    output_sha256 = hashlib.sha256(output).hexdigest()
    report = ProjectMigrationReport(
        status="applied" if apply else "review_required",
        source_version="1.0",
        backup_path=PROJECT_MIGRATION_BACKUP.as_posix() if apply else None,
        receipt_path=PROJECT_MIGRATION_RECEIPT.as_posix() if apply else None,
        input_sha256=input_sha256,
        output_sha256=output_sha256,
        changes=tuple(changes),
    )
    if not apply:
        return report

    backup = root / PROJECT_MIGRATION_BACKUP
    receipt = root / PROJECT_MIGRATION_RECEIPT
    journal = root / PROJECT_MIGRATION_JOURNAL
    try:
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists() and backup.read_bytes() != original:
            raise ProjectMigrationError(
                "migration backup already exists with different bytes: "
                f"{PROJECT_MIGRATION_BACKUP.as_posix()}"
            )
        if not backup.exists():
            _atomic_write_bytes(backup, original)
        atomic_write_json(
            journal,
            {
                "schema_version": PROJECT_MIGRATION_TRANSACTION_SCHEMA,
                "migration_id": PROJECT_MIGRATION_ID,
                "input_sha256": input_sha256,
                "output_sha256": output_sha256,
                "report": report.model_dump(mode="json"),
            },
        )
        _atomic_write_bytes(path, output)
        atomic_write_json(receipt, report)
        journal.unlink(missing_ok=True)
    except (OSError, ArtifactContractError, ProjectMigrationError) as exc:
        raise ProjectMigrationError(f"could not apply project migration: {exc}") from exc
    return report


def _recover_interrupted_migration(
    root: Path,
    *,
    current_bytes: bytes,
    current_payload: object,
    apply: bool,
) -> ProjectMigrationReport | None:
    journal_path = root / PROJECT_MIGRATION_JOURNAL
    if not journal_path.is_file():
        return None
    try:
        journal = load_strict_json(journal_path)
    except ArtifactContractError as exc:
        raise ProjectMigrationError(f"migration recovery journal is invalid: {exc}") from exc
    if not isinstance(journal, dict) or set(journal) != {
        "schema_version",
        "migration_id",
        "input_sha256",
        "output_sha256",
        "report",
    }:
        raise ProjectMigrationError("migration recovery journal shape is invalid")
    if (
        journal.get("schema_version") != PROJECT_MIGRATION_TRANSACTION_SCHEMA
        or journal.get("migration_id") != PROJECT_MIGRATION_ID
    ):
        raise ProjectMigrationError("migration recovery journal version is unsupported")
    try:
        report = ProjectMigrationReport.model_validate(journal.get("report"))
    except ValidationError as exc:
        raise ProjectMigrationError(f"migration recovery report is invalid: {exc}") from exc
    input_sha = journal.get("input_sha256")
    output_sha = journal.get("output_sha256")
    if report.input_sha256 != input_sha or report.output_sha256 != output_sha:
        raise ProjectMigrationError("migration recovery journal fingerprints disagree")
    backup = root / PROJECT_MIGRATION_BACKUP
    try:
        backup_bytes = backup.read_bytes()
        backup_payload = load_strict_json(backup)
        if backup.read_bytes() != backup_bytes:
            raise ProjectMigrationError("migration recovery backup changed while being read")
    except (OSError, ArtifactContractError) as exc:
        raise ProjectMigrationError(f"migration recovery backup is unavailable: {exc}") from exc
    backup_sha = hashlib.sha256(backup_bytes).hexdigest()
    if backup_sha != input_sha:
        raise ProjectMigrationError("migration recovery backup fingerprint does not match")
    expected = _plan_v1_migration(backup_payload, backup_bytes, apply=True)
    if report != expected:
        raise ProjectMigrationError(
            "migration recovery report does not match the reconstructed migration report"
        )
    current_sha = hashlib.sha256(current_bytes).hexdigest()
    if current_sha == input_sha and isinstance(current_payload, dict) and current_payload.get("schema_version") == "1.0":
        if apply:
            journal_path.unlink(missing_ok=True)
            return None
        return ProjectMigrationReport.model_validate(
            {**report.model_dump(mode="json"), "status": "recovery_required"}
        )
    if current_sha != output_sha or not isinstance(current_payload, dict) or current_payload.get("schema_version") != "1.1":
        raise ProjectMigrationError("migration recovery found an unknown manifest state")
    if not apply:
        return ProjectMigrationReport.model_validate(
            {**report.model_dump(mode="json"), "status": "recovery_required"}
        )
    try:
        atomic_write_json(root / PROJECT_MIGRATION_RECEIPT, report)
        journal_path.unlink(missing_ok=True)
    except (OSError, ArtifactContractError) as exc:
        raise ProjectMigrationError(f"could not complete interrupted migration: {exc}") from exc
    return report


def _require_complete_migration_artifacts(
    root: Path,
    *,
    current_bytes: bytes,
    current_report: ProjectMigrationReport,
    apply: bool,
) -> ProjectMigrationReport:
    backup = root / PROJECT_MIGRATION_BACKUP
    receipt = root / PROJECT_MIGRATION_RECEIPT
    if not backup.exists() and not receipt.exists():
        return current_report
    if backup.exists() != receipt.exists():
        if not backup.exists():
            raise ProjectMigrationError("project migration receipt exists without its exact backup")
        try:
            backup_bytes = backup.read_bytes()
            backup_payload = load_strict_json(backup)
            if backup.read_bytes() != backup_bytes:
                raise ProjectMigrationError("project migration backup changed while being read")
        except (OSError, ArtifactContractError) as exc:
            raise ProjectMigrationError(f"project migration backup is invalid: {exc}") from exc
        repair = _plan_v1_migration(backup_payload, backup_bytes, apply=True)
        if repair.output_sha256 != hashlib.sha256(current_bytes).hexdigest():
            raise ProjectMigrationError("project migration backup does not produce the current manifest")
        if not apply:
            return ProjectMigrationReport.model_validate(
                {**repair.model_dump(mode="json"), "status": "recovery_required"}
            )
        try:
            atomic_write_json(receipt, repair)
        except ArtifactContractError as exc:
            raise ProjectMigrationError(f"could not repair project migration receipt: {exc}") from exc
        return repair
    try:
        backup_bytes = backup.read_bytes()
        backup_payload = load_strict_json(backup)
        if backup.read_bytes() != backup_bytes:
            raise ProjectMigrationError("project migration backup changed while being read")
        expected = _plan_v1_migration(backup_payload, backup_bytes, apply=True)
        if expected.output_sha256 != hashlib.sha256(current_bytes).hexdigest():
            raise ProjectMigrationError(
                "project migration backup does not produce the current manifest"
            )
        value = ProjectMigrationReport.model_validate(load_strict_json(receipt))
    except (OSError, ArtifactContractError, ValidationError) as exc:
        raise ProjectMigrationError(f"project migration receipt is invalid: {exc}") from exc
    if value != expected:
        raise ProjectMigrationError(
            "project migration receipt does not match the reconstructed migration report"
        )
    return current_report


def _plan_v1_migration(
    payload: object,
    original: bytes,
    *,
    apply: bool,
) -> ProjectMigrationReport:
    """Plan a historical v1 migration for interrupted-receipt recovery."""

    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ProjectMigrationError("migration backup is not a project schema 1.0 manifest")
    migrated = dict(payload)
    stages = migrated.get("stages")
    if not isinstance(stages, dict):
        raise ProjectMigrationError("migration backup stages are invalid")
    required_old = {stage.value for stage in ProjectStage} - {
        ProjectStage.ASSETS.value,
        ProjectStage.LAUNCH.value,
    }
    allowed_old = required_old | {ProjectStage.ASSETS.value}
    if not required_old.issubset(stages) or not set(stages).issubset(allowed_old):
        raise ProjectMigrationError("migration backup stage shape is unsupported")
    migrated["schema_version"] = "1.1"
    migrated["stages"] = dict(stages)
    changes = ["schema_version:1.0->1.1"]
    if ProjectStage.ASSETS.value not in migrated["stages"]:
        migrated["stages"][ProjectStage.ASSETS.value] = StageRecord(
            stage=ProjectStage.ASSETS
        ).model_dump(mode="json")
        changes.append("stages.assets:added-pending")
    migrated["stages"][ProjectStage.LAUNCH.value] = StageRecord(
        stage=ProjectStage.LAUNCH
    ).model_dump(mode="json")
    changes.append("stages.launch:added-pending")
    try:
        validated = ProjectManifest.model_validate(migrated)
    except ValidationError as exc:
        raise ProjectMigrationError(f"migration backup cannot be upgraded: {exc}") from exc
    output = canonical_json_bytes(validated)
    return ProjectMigrationReport(
        status="applied" if apply else "review_required",
        source_version="1.0",
        backup_path=PROJECT_MIGRATION_BACKUP.as_posix() if apply else None,
        receipt_path=PROJECT_MIGRATION_RECEIPT.as_posix() if apply else None,
        input_sha256=hashlib.sha256(original).hexdigest(),
        output_sha256=hashlib.sha256(output).hexdigest(),
        changes=tuple(changes),
    )


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise ProjectMigrationError(f"cannot write migration artifact {path.name}: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


__all__ = [
    "PROJECT_MIGRATION_BACKUP",
    "PROJECT_MIGRATION_ID",
    "PROJECT_MIGRATION_JOURNAL",
    "PROJECT_MIGRATION_RECEIPT",
    "ProjectMigrationError",
    "ProjectMigrationReport",
    "migrate_project_manifest",
]
