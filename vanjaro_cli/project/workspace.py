"""Filesystem services for deterministic, resumable agency project workspaces."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import shutil

from pydantic import JsonValue, ValidationError

from vanjaro_cli.project.models import (
    AgencyPack,
    ApprovalStatus,
    AuditEvent,
    PROJECT_STAGE_ORDER,
    ProjectIdentity,
    ProjectManifest,
    ProjectSource,
    ProjectStage,
    StageRecord,
    StageStatus,
    TargetPortal,
)
from vanjaro_cli.reliability.artifacts import (
    ArtifactContractError,
    atomic_write_json,
    canonical_json_sha256,
    load_strict_json,
)


MANIFEST_FILENAME = "project.json"
WORKSPACE_DIRECTORIES = (
    "sources",
    "analysis",
    "plans",
    "build",
    "qa",
    "history",
)


class ProjectWorkspaceError(ValueError):
    """Raised when a project workspace is missing, unsafe, or invalid."""


@dataclass(frozen=True, slots=True)
class WorkspaceStatus:
    root: Path
    project_id: str
    project_name: str
    target_profile: str
    source_count: int
    completed_stages: tuple[str, ...]
    failed_stages: tuple[str, ...]
    running_stages: tuple[str, ...]
    next_stage: str | None
    pending_approvals: int
    missing_directories: tuple[str, ...]

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "root": str(self.root),
            "project_id": self.project_id,
            "project_name": self.project_name,
            "target_profile": self.target_profile,
            "source_count": self.source_count,
            "completed_stages": list(self.completed_stages),
            "failed_stages": list(self.failed_stages),
            "running_stages": list(self.running_stages),
            "next_stage": self.next_stage,
            "pending_approvals": self.pending_approvals,
            "missing_directories": list(self.missing_directories),
        }


def create_manifest(
    *,
    name: str,
    target_profile: str,
    sources: Sequence[ProjectSource],
    agency_pack_name: str,
    agency_pack_version: str,
    expected_portal_id: int | None = None,
    expected_base_url: str | None = None,
    project_id: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ProjectManifest:
    """Create a complete initial manifest with an audited intake checkpoint."""

    now = (clock or _utc_now)()
    identity = ProjectIdentity(
        id=project_id or _slug(name),
        name=name,
        created_at=now,
        updated_at=now,
    )
    target = TargetPortal(
        profile=target_profile,
        expected_portal_id=expected_portal_id,
        expected_base_url=expected_base_url,
    )
    agency_pack = AgencyPack(name=agency_pack_name, version=agency_pack_version)
    source_list = list(sources)
    intake_fingerprint = fingerprint_data(
        {
            "project_id": identity.id,
            "target": target.model_dump(mode="json"),
            "agency_pack": agency_pack.model_dump(mode="json"),
            "sources": [source.model_dump(mode="json") for source in source_list],
        }
    )
    stages = {
        stage: StageRecord(stage=stage)
        for stage in ProjectStage
    }
    stages[ProjectStage.INTAKE] = StageRecord(
        stage=ProjectStage.INTAKE,
        status=StageStatus.COMPLETED,
        attempt=1,
        input_fingerprint=intake_fingerprint,
        output_fingerprint=intake_fingerprint,
        started_at=now,
        completed_at=now,
        artifacts=[MANIFEST_FILENAME],
        message="Project workspace initialized.",
    )
    return ProjectManifest(
        project=identity,
        target=target,
        agency_pack=agency_pack,
        sources=source_list,
        stages=stages,
        decisions=[],
        approvals=[],
        audit=[
            AuditEvent(
                id="project-initialized",
                occurred_at=now,
                kind="project_initialized",
                message="Created project workspace and completed intake.",
                stage=ProjectStage.INTAKE,
                fingerprint=intake_fingerprint,
                artifacts=[MANIFEST_FILENAME],
            )
        ],
        metadata={},
    )


def initialize_workspace(root: Path, manifest: ProjectManifest) -> Path:
    """Create a new workspace without overwriting any existing content."""

    root = root.expanduser().resolve()
    created_root = not root.exists()
    if root.exists() and any(root.iterdir()):
        raise ProjectWorkspaceError(
            f"project directory is not empty: {root}"
        )
    try:
        root.mkdir(parents=True, exist_ok=True)
        for directory in WORKSPACE_DIRECTORIES:
            (root / directory).mkdir()
        write_manifest(root, manifest)
    except Exception:
        if created_root and root.exists():
            shutil.rmtree(root)
        raise
    return root / MANIFEST_FILENAME


def write_manifest(root: Path, manifest: ProjectManifest) -> Path:
    """Atomically persist a validated manifest with deterministic formatting."""

    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ProjectWorkspaceError(f"project directory does not exist: {root}")
    path = root / MANIFEST_FILENAME
    try:
        atomic_write_json(path, manifest)
    except ArtifactContractError as exc:
        raise ProjectWorkspaceError(f"could not write project manifest: {exc}") from exc
    return path


def load_manifest(root: Path) -> ProjectManifest:
    """Read and validate a workspace manifest."""

    root = root.expanduser().resolve()
    path = root / MANIFEST_FILENAME
    try:
        payload = load_strict_json(path)
    except FileNotFoundError as exc:
        raise ProjectWorkspaceError(f"project manifest not found: {path}") from exc
    except (OSError, ArtifactContractError) as exc:
        raise ProjectWorkspaceError(f"could not read project manifest: {exc}") from exc
    try:
        if isinstance(payload, dict) and payload.get("schema_version") == "1.0":
            raise ProjectWorkspaceError(
                "project manifest schema 1.0 requires explicit migration; run "
                "`vanjaro project migrate-contract <directory>` to review it, then "
                "rerun with `--apply`"
            )
        return ProjectManifest.model_validate(payload)
    except ValidationError as exc:
        raise ProjectWorkspaceError(f"invalid project manifest {path}: {exc}") from exc


def workspace_status(root: Path, manifest: ProjectManifest | None = None) -> WorkspaceStatus:
    """Summarize resumable stage and approval state without mutating the project."""

    root = root.expanduser().resolve()
    current = manifest or load_manifest(root)
    completed = tuple(
        stage for stage in PROJECT_STAGE_ORDER
        if current.stages[ProjectStage(stage)].status in {
            StageStatus.COMPLETED,
            StageStatus.SKIPPED,
        }
    )
    failed = tuple(
        stage for stage in PROJECT_STAGE_ORDER
        if current.stages[ProjectStage(stage)].status == StageStatus.FAILED
    )
    running = tuple(
        stage for stage in PROJECT_STAGE_ORDER
        if current.stages[ProjectStage(stage)].status == StageStatus.RUNNING
    )
    next_stage = next(
        (
            stage for stage in PROJECT_STAGE_ORDER
            if current.stages[ProjectStage(stage)].status not in {
                StageStatus.COMPLETED,
                StageStatus.SKIPPED,
            }
        ),
        None,
    )
    missing = tuple(
        directory
        for directory in WORKSPACE_DIRECTORIES
        if not (root / directory).is_dir()
    )
    pending_approvals = sum(
        approval.status == ApprovalStatus.PENDING
        for approval in current.approvals
    )
    return WorkspaceStatus(
        root=root,
        project_id=current.project.id,
        project_name=current.project.name,
        target_profile=current.target.profile,
        source_count=len(current.sources),
        completed_stages=completed,
        failed_stages=failed,
        running_stages=running,
        next_stage=next_stage,
        pending_approvals=pending_approvals,
        missing_directories=missing,
    )


def fingerprint_data(value: object) -> str:
    """Return a stable SHA-256 fingerprint for JSON-compatible input."""

    try:
        return canonical_json_sha256(value)
    except ArtifactContractError as exc:
        raise ProjectWorkspaceError(f"could not fingerprint artifact data: {exc}") from exc


def fingerprint_files(root: Path, paths: Iterable[Path]) -> str:
    """Fingerprint workspace-relative files by normalized path and content."""

    root = root.expanduser().resolve()
    records: list[Mapping[str, str]] = []
    for requested in paths:
        absolute = (root / requested).resolve() if not requested.is_absolute() else requested.resolve()
        try:
            relative = absolute.relative_to(root)
        except ValueError as exc:
            raise ProjectWorkspaceError(
                f"fingerprint path escapes project workspace: {requested}"
            ) from exc
        if not absolute.is_file():
            raise ProjectWorkspaceError(f"fingerprint input is not a file: {relative}")
        records.append(
            {
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(absolute.read_bytes()).hexdigest(),
            }
        )
    return fingerprint_data(sorted(records, key=lambda record: record["path"]))


def artifact_path(root: Path, relative_path: str) -> Path:
    """Resolve a workspace-relative artifact path and reject traversal."""

    root = root.expanduser().resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ProjectWorkspaceError(
            f"artifact path escapes project workspace: {relative_path}"
        ) from exc
    return candidate


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized or "agency-project"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "MANIFEST_FILENAME",
    "ProjectWorkspaceError",
    "WORKSPACE_DIRECTORIES",
    "WorkspaceStatus",
    "artifact_path",
    "create_manifest",
    "fingerprint_data",
    "fingerprint_files",
    "initialize_workspace",
    "load_manifest",
    "workspace_status",
    "write_manifest",
]
