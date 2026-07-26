"""Deterministic resumable stage execution for agency project workspaces."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from vanjaro_cli.project.models import (
    ApprovalGate,
    ApprovalStatus,
    AuditEvent,
    PROJECT_STAGE_ORDER,
    ProjectManifest,
    ProjectStage,
    StageRecord,
    StageStatus,
)
from vanjaro_cli.project.workspace import (
    ProjectWorkspaceError,
    artifact_path,
    fingerprint_data,
    fingerprint_files,
    load_manifest,
    write_manifest,
)


class ProjectStageError(ProjectWorkspaceError):
    """Base error for an unsafe or failed stage transition."""


class StageDependencyError(ProjectStageError):
    """Raised when prerequisite stages have not completed."""


class StageApprovalError(ProjectStageError):
    """Raised when a mutating stage lacks exact artifact approval."""


class StageOperationError(ProjectStageError):
    """Raised after an operation failure has been persisted."""


@dataclass(frozen=True, slots=True)
class StageDefinition:
    stage: ProjectStage
    dependencies: tuple[ProjectStage, ...] = ()
    approval_gate: ApprovalGate | None = None
    mutates_portal: bool = False
    contract_version: str = "1.0"


STAGE_DEFINITIONS: dict[ProjectStage, StageDefinition] = {
    ProjectStage.INTAKE: StageDefinition(ProjectStage.INTAKE),
    ProjectStage.ANALYZE: StageDefinition(
        ProjectStage.ANALYZE,
        (ProjectStage.INTAKE,),
        contract_version="1.1",
    ),
    ProjectStage.PLAN: StageDefinition(
        ProjectStage.PLAN,
        (ProjectStage.ANALYZE,),
        contract_version="1.6",
    ),
    ProjectStage.THEME: StageDefinition(
        ProjectStage.THEME,
        (ProjectStage.PLAN,),
        ApprovalGate.PORTAL_MUTATION,
        True,
        contract_version="1.1",
    ),
    ProjectStage.ASSETS: StageDefinition(
        ProjectStage.ASSETS,
        (ProjectStage.THEME,),
        ApprovalGate.PORTAL_MUTATION,
        True,
        contract_version="1.1",
    ),
    ProjectStage.LIBRARY: StageDefinition(
        ProjectStage.LIBRARY,
        (ProjectStage.ASSETS,),
        ApprovalGate.PORTAL_MUTATION,
        True,
        contract_version="1.2",
    ),
    ProjectStage.PAGES: StageDefinition(
        ProjectStage.PAGES,
        (ProjectStage.LIBRARY,),
        ApprovalGate.PORTAL_MUTATION,
        True,
        contract_version="1.2",
    ),
    ProjectStage.GLOBAL_BLOCKS: StageDefinition(
        ProjectStage.GLOBAL_BLOCKS,
        (ProjectStage.PAGES,),
        ApprovalGate.PORTAL_MUTATION,
        True,
        contract_version="1.2",
    ),
    ProjectStage.VERIFY: StageDefinition(
        ProjectStage.VERIFY,
        (ProjectStage.GLOBAL_BLOCKS,),
        contract_version="1.1",
    ),
    ProjectStage.PUBLISH: StageDefinition(
        ProjectStage.PUBLISH,
        (ProjectStage.VERIFY,),
        ApprovalGate.PUBLISH,
        True,
    ),
}


@dataclass(frozen=True, slots=True)
class StageInputs:
    data: Mapping[str, JsonValue] = field(default_factory=dict)
    files: tuple[Path, ...] = ()
    approval_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class StageResult:
    artifacts: tuple[str, ...] = ()
    message: str = "Stage completed."


@dataclass(frozen=True, slots=True)
class StageContext:
    root: Path
    stage: ProjectStage
    manifest: ProjectManifest
    input_fingerprint: str
    attempt: int


@dataclass(frozen=True, slots=True)
class StageExecution:
    stage: ProjectStage
    action: Literal["execute", "resume"]
    status: Literal["completed", "dry_run", "resumed"]
    input_fingerprint: str
    output_fingerprint: str | None
    attempt: int
    artifacts: tuple[str, ...]
    approval_gate: ApprovalGate | None = None
    approval_fingerprint: str | None = None

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "stage": self.stage.value,
            "action": self.action,
            "status": self.status,
            "input_fingerprint": self.input_fingerprint,
            "output_fingerprint": self.output_fingerprint,
            "attempt": self.attempt,
            "artifacts": list(self.artifacts),
            "approval_gate": self.approval_gate.value if self.approval_gate else None,
            "approval_fingerprint": self.approval_fingerprint,
        }


class StageEngine:
    """Run one stage with persistent transitions, resumption, and safety gates."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        allow_pack_upgrade_lock: bool = False,
    ) -> None:
        self.root = root.expanduser().resolve()
        self.clock = clock or _utc_now
        self.allow_pack_upgrade_lock = allow_pack_upgrade_lock

    def execute(
        self,
        stage: ProjectStage,
        inputs: StageInputs,
        operation: Callable[[StageContext], StageResult],
        *,
        dry_run: bool = False,
    ) -> StageExecution:
        """Execute, preview, or resume a stage without repeating valid work."""

        if (
            not self.allow_pack_upgrade_lock
            and (self.root / ".agency-pack-upgrade.lock").exists()
        ):
            raise ProjectStageError(
                "project is locked by an agency-pack upgrade transaction"
            )
        if stage == ProjectStage.INTAKE:
            raise ProjectStageError("intake is completed only by project initialization")
        manifest = load_manifest(self.root)
        definition = STAGE_DEFINITIONS[stage]
        self._require_dependencies(manifest, definition)
        approval_fingerprint = self._approval_fingerprint(
            manifest, definition, inputs.approval_fingerprint
        )
        self._require_approval(manifest, definition, approval_fingerprint)
        input_fingerprint = self._input_fingerprint(
            manifest, definition, inputs, approval_fingerprint
        )
        current = manifest.stages[stage]
        if self._can_resume(current, input_fingerprint):
            return StageExecution(
                stage=stage,
                action="resume",
                status="dry_run" if dry_run else "resumed",
                input_fingerprint=input_fingerprint,
                output_fingerprint=current.output_fingerprint,
                attempt=current.attempt,
                artifacts=tuple(current.artifacts),
                approval_gate=definition.approval_gate,
                approval_fingerprint=approval_fingerprint,
            )

        next_attempt = current.attempt + 1
        if dry_run:
            return StageExecution(
                stage=stage,
                action="execute",
                status="dry_run",
                input_fingerprint=input_fingerprint,
                output_fingerprint=None,
                attempt=next_attempt,
                artifacts=(),
                approval_gate=definition.approval_gate,
                approval_fingerprint=approval_fingerprint,
            )

        now = self.clock()
        working = manifest.model_copy(deep=True)
        self._invalidate_stale_state(working, stage, now)
        working.stages[stage] = StageRecord(
            stage=stage,
            status=StageStatus.RUNNING,
            attempt=next_attempt,
            input_fingerprint=input_fingerprint,
            started_at=now,
            message="Stage operation started.",
        )
        self._append_audit(
            working,
            now=now,
            kind="stage_started",
            message=f"Started {stage.value} attempt {next_attempt}.",
            stage=stage,
            fingerprint=input_fingerprint,
        )
        self._touch(working, now)
        write_manifest(self.root, _validated(working))

        context = StageContext(
            root=self.root,
            stage=stage,
            manifest=working.model_copy(deep=True),
            input_fingerprint=input_fingerprint,
            attempt=next_attempt,
        )
        try:
            result = operation(context)
            if not isinstance(result, StageResult):
                raise TypeError("stage operation must return StageResult")
            artifacts = self._validate_artifacts(result.artifacts)
            output_fingerprint = self._output_fingerprint(artifacts, result.message)
        except Exception as exc:
            failed_at = self.clock()
            working.stages[stage] = StageRecord(
                stage=stage,
                status=StageStatus.FAILED,
                attempt=next_attempt,
                input_fingerprint=input_fingerprint,
                started_at=now,
                completed_at=failed_at,
                message=str(exc) or exc.__class__.__name__,
            )
            self._append_audit(
                working,
                now=failed_at,
                kind="stage_failed",
                message=f"{stage.value} failed: {str(exc) or exc.__class__.__name__}",
                stage=stage,
                fingerprint=input_fingerprint,
            )
            self._touch(working, failed_at)
            write_manifest(self.root, _validated(working))
            raise StageOperationError(
                f"{stage.value} stage failed: {str(exc) or exc.__class__.__name__}"
            ) from exc

        completed_at = self.clock()
        working.stages[stage] = StageRecord(
            stage=stage,
            status=StageStatus.COMPLETED,
            attempt=next_attempt,
            input_fingerprint=input_fingerprint,
            output_fingerprint=output_fingerprint,
            started_at=now,
            completed_at=completed_at,
            artifacts=list(artifacts),
            message=result.message,
        )
        self._append_audit(
            working,
            now=completed_at,
            kind="stage_completed",
            message=result.message,
            stage=stage,
            fingerprint=output_fingerprint,
            artifacts=artifacts,
        )
        self._touch(working, completed_at)
        write_manifest(self.root, _validated(working))
        return StageExecution(
            stage=stage,
            action="execute",
            status="completed",
            input_fingerprint=input_fingerprint,
            output_fingerprint=output_fingerprint,
            attempt=next_attempt,
            artifacts=artifacts,
            approval_gate=definition.approval_gate,
            approval_fingerprint=approval_fingerprint,
        )

    def _require_dependencies(
        self, manifest: ProjectManifest, definition: StageDefinition
    ) -> None:
        incomplete = [
            dependency.value
            for dependency in definition.dependencies
            if manifest.stages[dependency].status not in {
                StageStatus.COMPLETED,
                StageStatus.SKIPPED,
            }
        ]
        if incomplete:
            raise StageDependencyError(
                f"{definition.stage.value} requires completed stage(s): {', '.join(incomplete)}"
            )

    def _approval_fingerprint(
        self,
        manifest: ProjectManifest,
        definition: StageDefinition,
        explicit: str | None,
    ) -> str | None:
        if definition.approval_gate is None:
            return None
        if explicit:
            return explicit
        owner = (
            ProjectStage.PLAN
            if definition.approval_gate == ApprovalGate.PORTAL_MUTATION
            else ProjectStage.VERIFY
        )
        return manifest.stages[owner].output_fingerprint

    def _require_approval(
        self,
        manifest: ProjectManifest,
        definition: StageDefinition,
        fingerprint: str | None,
    ) -> None:
        gate = definition.approval_gate
        if gate is None:
            return
        if fingerprint is None:
            raise StageApprovalError(
                f"{definition.stage.value} requires {gate.value} approval, but the approval artifact has no fingerprint"
            )
        owner = (
            ProjectStage.PLAN
            if gate == ApprovalGate.PORTAL_MUTATION
            else ProjectStage.VERIFY
        )
        owner_record = manifest.stages[owner]
        try:
            observed = self._output_fingerprint(
                tuple(owner_record.artifacts),
                owner_record.message or "Stage completed.",
            )
        except ProjectWorkspaceError as exc:
            raise StageApprovalError(
                f"{definition.stage.value} approval owner artifacts are missing; rerun {owner.value}"
            ) from exc
        if observed != fingerprint:
            raise StageApprovalError(
                f"{definition.stage.value} approval owner artifacts changed; rerun {owner.value}"
            )
        approved = any(
            approval.gate == gate
            and approval.status == ApprovalStatus.APPROVED
            and approval.fingerprint == fingerprint
            for approval in manifest.approvals
        )
        if not approved:
            raise StageApprovalError(
                f"{definition.stage.value} requires approved {gate.value} fingerprint {fingerprint}"
            )

    def _input_fingerprint(
        self,
        manifest: ProjectManifest,
        definition: StageDefinition,
        inputs: StageInputs,
        approval_fingerprint: str | None,
    ) -> str:
        file_fingerprint = (
            fingerprint_files(self.root, inputs.files)
            if inputs.files
            else fingerprint_data([])
        )
        dependencies = {
            dependency.value: manifest.stages[dependency].output_fingerprint
            for dependency in definition.dependencies
        }
        return fingerprint_data(
            {
                "schema_version": manifest.schema_version,
                "project_id": manifest.project.id,
                "target": manifest.target.model_dump(mode="json"),
                "agency_pack": manifest.agency_pack.model_dump(mode="json"),
                "sources": [source.model_dump(mode="json") for source in manifest.sources],
                "stage": definition.stage.value,
                "stage_contract_version": definition.contract_version,
                "dependencies": dependencies,
                "data": dict(inputs.data),
                "files": file_fingerprint,
                "approval": approval_fingerprint,
            }
        )

    def _can_resume(self, record: StageRecord, input_fingerprint: str) -> bool:
        if (
            record.status != StageStatus.COMPLETED
            or record.input_fingerprint != input_fingerprint
            or record.output_fingerprint is None
        ):
            return False
        try:
            current_output = self._output_fingerprint(
                tuple(record.artifacts), record.message or "Stage completed."
            )
        except ProjectWorkspaceError:
            return False
        return current_output == record.output_fingerprint

    def _validate_artifacts(self, values: tuple[str, ...]) -> tuple[str, ...]:
        artifacts = tuple(dict.fromkeys(values))
        for value in artifacts:
            path = artifact_path(self.root, value)
            if not path.is_file():
                raise ProjectWorkspaceError(
                    f"stage declared a missing artifact: {value}"
                )
        return artifacts

    def _output_fingerprint(self, artifacts: tuple[str, ...], message: str) -> str:
        if artifacts:
            return fingerprint_files(self.root, tuple(Path(value) for value in artifacts))
        return fingerprint_data({"artifacts": [], "message": message})

    def _invalidate_stale_state(
        self, manifest: ProjectManifest, stage: ProjectStage, now: datetime
    ) -> None:
        invalidated = invalidate_stage_state(
            manifest,
            stage,
            now=now,
            resolved_by="stage-engine",
            approval_note="Superseded because an upstream stage was rerun.",
        )
        if invalidated:
            self._append_audit(
                manifest,
                now=now,
                kind="stages_invalidated",
                message=f"Invalidated stage state from {stage.value}: {', '.join(invalidated)}.",
                stage=stage,
            )

    def _append_audit(
        self,
        manifest: ProjectManifest,
        *,
        now: datetime,
        kind: str,
        message: str,
        stage: ProjectStage | None = None,
        fingerprint: str | None = None,
        artifacts: tuple[str, ...] = (),
    ) -> None:
        manifest.audit.append(
            AuditEvent(
                id=f"event-{len(manifest.audit) + 1:05d}-{kind.replace('_', '-')}",
                occurred_at=now,
                kind=kind,
                message=message,
                stage=stage,
                fingerprint=fingerprint,
                artifacts=list(artifacts),
            )
        )

    @staticmethod
    def _touch(manifest: ProjectManifest, now: datetime) -> None:
        manifest.project = manifest.project.model_copy(update={"updated_at": now})


def _validated(manifest: ProjectManifest) -> ProjectManifest:
    return ProjectManifest.model_validate(manifest.model_dump())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def invalidate_stage_state(
    manifest: ProjectManifest,
    stage: ProjectStage,
    *,
    now: datetime,
    resolved_by: str,
    approval_note: str,
) -> tuple[str, ...]:
    """Reset one stage and its dependents and supersede affected approvals."""

    start = PROJECT_STAGE_ORDER.index(stage.value)
    invalidated: list[str] = []
    for value in PROJECT_STAGE_ORDER[start:]:
        candidate = ProjectStage(value)
        if manifest.stages[candidate].status != StageStatus.PENDING:
            invalidated.append(value)
        manifest.stages[candidate] = StageRecord(stage=candidate)
    gates: set[ApprovalGate] = set()
    if start <= PROJECT_STAGE_ORDER.index(ProjectStage.PLAN.value):
        gates.update(
            {
                ApprovalGate.PLAN,
                ApprovalGate.PORTAL_MUTATION,
                ApprovalGate.PUBLISH,
            }
        )
    elif start <= PROJECT_STAGE_ORDER.index(ProjectStage.VERIFY.value):
        gates.add(ApprovalGate.PUBLISH)
    for index, approval in enumerate(manifest.approvals):
        if approval.gate in gates and approval.status in {
            ApprovalStatus.PENDING,
            ApprovalStatus.APPROVED,
        }:
            manifest.approvals[index] = approval.model_copy(
                update={
                    "status": ApprovalStatus.SUPERSEDED,
                    "resolved_at": now,
                    "resolved_by": resolved_by,
                    "note": approval_note,
                }
            )
    return tuple(invalidated)


__all__ = [
    "ProjectStageError",
    "STAGE_DEFINITIONS",
    "StageApprovalError",
    "StageContext",
    "StageDefinition",
    "StageDependencyError",
    "StageEngine",
    "StageExecution",
    "StageInputs",
    "StageOperationError",
    "StageResult",
    "invalidate_stage_state",
]
