"""Fingerprint-bound approval services for mutation and publish gates."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
from pathlib import Path

from vanjaro_cli.project.models import (
    ApprovalGate,
    ApprovalRecord,
    ApprovalStatus,
    AuditEvent,
    ProjectManifest,
    ProjectStage,
)
from vanjaro_cli.project.workspace import (
    ProjectWorkspaceError,
    fingerprint_files,
    load_manifest,
    write_manifest,
)
from vanjaro_cli.project.publish_receipt import (
    PublishReceiptError,
    current_publish_review_fingerprint,
)
from vanjaro_cli.project.launch_receipt import (
    LaunchReceiptError,
    current_launch_review_fingerprint,
)
from vanjaro_cli.project.publish_lock import PublishLockError, publish_operation_lock


class ProjectApprovalError(ProjectWorkspaceError):
    """Raised when an approval request or transition is invalid."""


def approval_artifact_fingerprint(
    root: Path, manifest: ProjectManifest, gate: ApprovalGate
) -> str:
    """Return the exact stage output that owns an approval gate."""

    if gate == ApprovalGate.PUBLISH:
        try:
            return current_publish_review_fingerprint(root, manifest)
        except PublishReceiptError as exc:
            raise ProjectApprovalError(str(exc)) from exc
    if gate == ApprovalGate.LAUNCH:
        try:
            return current_launch_review_fingerprint(root, manifest)
        except LaunchReceiptError as exc:
            raise ProjectApprovalError(str(exc)) from exc

    owner = {
        ApprovalGate.PLAN: ProjectStage.PLAN,
        ApprovalGate.PORTAL_MUTATION: ProjectStage.PLAN,
        ApprovalGate.LAUNCH: ProjectStage.LAUNCH,
    }[gate]
    fingerprint = manifest.stages[owner].output_fingerprint
    if fingerprint is None:
        raise ProjectApprovalError(
            f"cannot request {gate.value} approval before {owner.value} completes"
        )
    return fingerprint


def _request_approval_unlocked(
    root: Path,
    *,
    gate: ApprovalGate,
    requested_by: str,
    fingerprint: str | None = None,
    note: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ApprovalRecord:
    """Create an idempotent pending approval for an exact artifact fingerprint."""

    now = (clock or _utc_now)()
    manifest = load_manifest(root).model_copy(deep=True)
    current_fingerprint = approval_artifact_fingerprint(root, manifest, gate)
    owner = {
        ApprovalGate.PLAN: ProjectStage.PLAN,
        ApprovalGate.PORTAL_MUTATION: ProjectStage.PLAN,
        ApprovalGate.PUBLISH: ProjectStage.PUBLISH,
        ApprovalGate.LAUNCH: ProjectStage.LAUNCH,
    }[gate]
    owner_record = manifest.stages[owner]
    if gate not in {ApprovalGate.PUBLISH, ApprovalGate.LAUNCH} and owner_record.artifacts:
        observed = fingerprint_files(
            root, tuple(Path(value) for value in owner_record.artifacts)
        )
        if observed != current_fingerprint:
            raise ProjectApprovalError(
                f"cannot request {gate.value} approval because {owner.value} "
                "artifacts changed after completion; rerun the stage"
            )
    if fingerprint is not None and fingerprint != current_fingerprint:
        raise ProjectApprovalError(
            f"requested fingerprint is not the current {owner.value} output"
        )
    if gate in {ApprovalGate.PLAN, ApprovalGate.PORTAL_MUTATION}:
        _require_valid_plan_report(root, owner_record.artifacts)
    approved_fingerprint = current_fingerprint
    for approval in manifest.approvals:
        if (
            approval.gate == gate
            and approval.fingerprint == approved_fingerprint
            and approval.status in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED}
        ):
            return approval

    for index, approval in enumerate(manifest.approvals):
        if approval.gate == gate and approval.status in {
            ApprovalStatus.PENDING,
            ApprovalStatus.APPROVED,
        }:
            manifest.approvals[index] = approval.model_copy(
                update={
                    "status": ApprovalStatus.SUPERSEDED,
                    "resolved_at": now,
                    "resolved_by": requested_by,
                    "note": "Superseded by a newer artifact fingerprint.",
                }
            )

    approval = ApprovalRecord(
        id=f"approval-{len(manifest.approvals) + 1:04d}-{gate.value.replace('_', '-')}",
        gate=gate,
        fingerprint=approved_fingerprint,
        requested_by=requested_by,
        requested_at=now,
        note=note,
    )
    manifest.approvals.append(approval)
    _append_audit(
        manifest,
        now=now,
        kind="approval_requested",
        message=f"{requested_by} requested {gate.value} approval.",
        fingerprint=approved_fingerprint,
    )
    _touch(manifest, now)
    write_manifest(root, _validated(manifest))
    return approval


def request_approval(
    root: Path,
    *,
    gate: ApprovalGate,
    requested_by: str,
    fingerprint: str | None = None,
    note: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ApprovalRecord:
    """Create an approval while serializing publish authority transitions."""

    if gate not in {ApprovalGate.PUBLISH, ApprovalGate.LAUNCH}:
        return _request_approval_unlocked(
            root,
            gate=gate,
            requested_by=requested_by,
            fingerprint=fingerprint,
            note=note,
            clock=clock,
        )
    try:
        with publish_operation_lock(root, operation="approval-request"):
            return _request_approval_unlocked(
                root,
                gate=gate,
                requested_by=requested_by,
                fingerprint=fingerprint,
                note=note,
                clock=clock,
            )
    except PublishLockError as exc:
        raise ProjectApprovalError(str(exc)) from exc


def _resolve_approval_unlocked(
    root: Path,
    approval_id: str,
    *,
    approved: bool,
    resolved_by: str,
    note: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ApprovalRecord:
    """Approve or reject one pending request and persist the audit transition."""

    now = (clock or _utc_now)()
    manifest = load_manifest(root).model_copy(deep=True)
    index = next(
        (index for index, item in enumerate(manifest.approvals) if item.id == approval_id),
        None,
    )
    if index is None:
        raise ProjectApprovalError(f"approval not found: {approval_id}")
    current = manifest.approvals[index]
    if current.gate in {ApprovalGate.PUBLISH, ApprovalGate.LAUNCH}:
        expected = approval_artifact_fingerprint(root, manifest, current.gate)
        if current.fingerprint != expected:
            raise ProjectApprovalError(
                f"{current.gate.value} approval receipt changed after the request; prepare a new review"
            )
    target = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    if current.status == target:
        return current
    if current.status != ApprovalStatus.PENDING:
        raise ProjectApprovalError(
            f"approval {approval_id} is {current.status.value}, not pending"
        )
    resolved = current.model_copy(
        update={
            "status": target,
            "resolved_at": now,
            "resolved_by": resolved_by,
            "note": note if note is not None else current.note,
        }
    )
    manifest.approvals[index] = resolved
    _append_audit(
        manifest,
        now=now,
        kind=f"approval_{target.value}",
        message=f"{resolved_by} {target.value} {current.gate.value} approval.",
        fingerprint=current.fingerprint,
    )
    _touch(manifest, now)
    write_manifest(root, _validated(manifest))
    return resolved


def resolve_approval(
    root: Path,
    approval_id: str,
    *,
    approved: bool,
    resolved_by: str,
    note: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ApprovalRecord:
    """Resolve an approval while serializing publish authority transitions."""

    manifest = load_manifest(root)
    current = next((item for item in manifest.approvals if item.id == approval_id), None)
    if current is None or current.gate not in {
        ApprovalGate.PUBLISH,
        ApprovalGate.LAUNCH,
    }:
        return _resolve_approval_unlocked(
            root,
            approval_id,
            approved=approved,
            resolved_by=resolved_by,
            note=note,
            clock=clock,
        )
    try:
        with publish_operation_lock(root, operation="approval-resolve"):
            return _resolve_approval_unlocked(
                root,
                approval_id,
                approved=approved,
                resolved_by=resolved_by,
                note=note,
                clock=clock,
            )
    except PublishLockError as exc:
        raise ProjectApprovalError(str(exc)) from exc


def _append_audit(
    manifest: ProjectManifest,
    *,
    now: datetime,
    kind: str,
    message: str,
    fingerprint: str,
) -> None:
    manifest.audit.append(
        AuditEvent(
            id=f"event-{len(manifest.audit) + 1:05d}-{kind.replace('_', '-')}",
            occurred_at=now,
            kind=kind,
            message=message,
            fingerprint=fingerprint,
        )
    )


def _touch(manifest: ProjectManifest, now: datetime) -> None:
    manifest.project = manifest.project.model_copy(update={"updated_at": now})


def _validated(manifest: ProjectManifest) -> ProjectManifest:
    return ProjectManifest.model_validate(manifest.model_dump())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_valid_plan_report(root: Path, artifacts: list[str]) -> None:
    relative = "plans/validation.json"
    if relative not in artifacts:
        return
    path = root.expanduser().resolve() / relative
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectApprovalError(
            f"cannot approve plan because its validation report is unreadable: {exc}"
        ) from exc
    if not isinstance(report, dict) or report.get("valid") is not True:
        issue_count = report.get("issue_count", "unknown") if isinstance(report, dict) else "unknown"
        raise ProjectApprovalError(
            f"cannot approve plan with {issue_count} unresolved validation issue(s)"
        )


__all__ = [
    "ProjectApprovalError",
    "approval_artifact_fingerprint",
    "request_approval",
    "resolve_approval",
]
