"""Preview-first worksheets for operator-supplied project release evidence."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
from typing import Literal

from vanjaro_cli.reliability.artifacts import (
    ArtifactContractError,
    canonical_json_bytes,
)
from vanjaro_cli.release.test_evidence import repository_path


SourceKind = Literal["live_html", "figma", "image"]


@dataclass(frozen=True)
class ScaffoldWriteResult:
    destinations: tuple[Path, ...]
    cleanup_warning: str | None = None


def project_evidence_templates(
    *, candidate_id: str, project_id: str, source_kind: SourceKind, workspace: str
) -> dict[str, dict[str, object]]:
    common = {
        "candidate_id": candidate_id,
        "project_id": project_id,
        "source_kind": source_kind,
    }
    missing = (
        "Replace every null/empty observation with independently measured evidence; "
        "this worksheet intentionally does not validate as release evidence."
    )
    empty_portal = {
        "portal_id": None,
        "base_url": "",
        "dnn_version": "",
        "vanjaro_version": "",
        "vanjaro_ai_version": "",
    }
    return {
        "quality-counts.template.json": {
            "instructions": missing,
            "schema_version": "project-quality-evidence-v1",
            **common,
            "quality": {
                name: {"numerator": None, "denominator": None}
                for name in (
                    "eligible_section_editable_coverage",
                    "native_agency_component_ratio",
                    "body_without_generic_fallback",
                    "desktop_tablet_mobile_evidence",
                )
            },
        },
        "effort-sessions.template.json": {
            "instructions": (
                missing
                + " Record real operator IDs, session IDs, timings, and hash-bound policies."
            ),
            "schema_version": "project-effort-evidence-v1",
            **common,
            "measurement_protocol": {"path": "", "sha256": None},
            "quality_policy": {"path": "", "sha256": None},
            "baseline_sessions": [],
            "current_sessions": [],
        },
        "project-receipt-bindings.template.json": {
            "instructions": (
                missing
                + " Compute digests only after the project and evidence files are final."
            ),
            "schema_version": "project-release-evidence-v1",
            **common,
            "workspace": workspace,
            "project_manifest_sha256": None,
            "maintenance_scorecard_sha256": None,
            "quality_evidence_sha256": None,
            "effort_evidence_sha256": None,
        },
        "live-receipt.template.json": {
            "instructions": (
                missing
                + " Populate only from an explicitly authorized real-portal observation; "
                "this command never contacts a portal."
            ),
            "schema_version": "agency-live-evidence-v1",
            "provenance": "real-vanjaro-portal",
            **common,
            "portal": {**empty_portal},
            "project_manifest_sha256": None,
            "publish_fingerprint": None,
            "launch_fingerprint": None,
            "observed_at": None,
            "valid_through": None,
            "captures": {},
            "smoke_checks": [],
            "cleanup_restored": None,
            "attestation": {"path": "", "sha256": None},
        },
        "live-attestation.template.json": {
            "instructions": (
                missing
                + " The observing operator must supply identity, routes, time, portal "
                "versions, and capture digests."
            ),
            "schema_version": "agency-live-attestation-v1",
            **common,
            "operator_id": None,
            "observed_at": None,
            "portal": {**empty_portal},
            "capture_sha256": {},
            "capture_routes": {},
            "smoke_routes": {},
            "statement": None,
        },
    }


def validate_scaffold_paths(
    root: Path, workspace: Path, output_dir: Path
) -> tuple[Path, Path]:
    safe_workspace = repository_path(root, workspace, label="workspace")
    safe_output = repository_path(root, output_dir, label="output directory")
    return safe_workspace, safe_output


def write_scaffold_transaction(
    output_dir: Path,
    templates: dict[str, dict[str, object]],
    *,
    overwrite: bool,
) -> ScaffoldWriteResult:
    """Replace a worksheet set together, restoring the prior set on failure."""

    payloads: dict[str, bytes] = {}
    for name, worksheet in templates.items():
        if not name or Path(name).name != name:
            raise ArtifactContractError(f"invalid worksheet filename: {name!r}")
        payloads[name] = canonical_json_bytes(worksheet)

    destinations = tuple(output_dir / name for name in payloads)
    existing = tuple(path for path in destinations if path.exists())
    if existing and not overwrite:
        names = ", ".join(path.name for path in existing)
        raise ArtifactContractError(
            f"worksheet outputs already exist: {names}; use --overwrite"
        )

    try:
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output_dir.name}.scaffold-",
                dir=output_dir.parent,
            )
        )
    except OSError as exc:
        raise ArtifactContractError(f"cannot stage worksheet outputs: {exc}") from exc

    output_preexisted = output_dir.exists()
    committed: list[Path] = []
    backups: dict[Path, Path] = {}
    preserve_staging = False
    transaction_error: ArtifactContractError | None = None
    transaction_cause: Exception | None = None
    try:
        staged_files = staging / "new"
        backup_files = staging / "backups"
        for name, payload in payloads.items():
            _write_staged_file(staged_files / name, payload)
        if existing:
            _create_backup_directory(backup_files)
            for destination in existing:
                backup = backup_files / destination.name
                _copy_backup(destination, backup)
                backups[destination] = backup

        _create_output_directory(output_dir)
        for destination in destinations:
            _replace_path(staged_files / destination.name, destination)
            committed.append(destination)
    except (ArtifactContractError, OSError) as exc:
        rollback_errors: list[str] = []
        for destination in reversed(committed):
            try:
                backup = backups.get(destination)
                if backup is None:
                    _remove_destination(destination)
                else:
                    _replace_path(backup, destination)
            except OSError as rollback_error:
                rollback_errors.append(f"{destination}: {rollback_error}")
        if not output_preexisted and output_dir.exists():
            try:
                _remove_output_directory(output_dir)
            except OSError as rollback_error:
                rollback_errors.append(f"{output_dir}: {rollback_error}")
        if rollback_errors:
            preserve_staging = True
            detail = "; ".join(rollback_errors)
            transaction_error = ArtifactContractError(
                f"worksheet transaction failed and rollback was incomplete; "
                f"recovery files remain at {staging}: {detail}"
            )
        else:
            transaction_error = ArtifactContractError(
                f"worksheet transaction failed; prior worksheet set was restored: {exc}"
            )
        transaction_cause = exc

    cleanup_warning = None
    if not preserve_staging:
        try:
            _remove_staging(staging)
        except OSError as cleanup_error:
            residual = f"temporary recovery files remain at {staging}: {cleanup_error}"
            if transaction_error is None:
                cleanup_warning = (
                    "worksheets were committed, but temporary cleanup failed; " + residual
                )
            else:
                transaction_error = ArtifactContractError(
                    f"{transaction_error}; {residual}"
                )
                transaction_cause = cleanup_error
    if transaction_error is not None:
        raise transaction_error from transaction_cause
    return ScaffoldWriteResult(destinations, cleanup_warning)


def _replace_path(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _write_staged_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _copy_backup(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination)


def _create_backup_directory(path: Path) -> None:
    path.mkdir()


def _create_output_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _remove_destination(path: Path) -> None:
    path.unlink(missing_ok=True)


def _remove_output_directory(path: Path) -> None:
    path.rmdir()


def _remove_staging(path: Path) -> None:
    shutil.rmtree(path)


__all__ = [
    "SourceKind",
    "ScaffoldWriteResult",
    "project_evidence_templates",
    "validate_scaffold_paths",
    "write_scaffold_transaction",
]
