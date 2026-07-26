"""Target-portal identity pinning for safe multi-client project operations."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from vanjaro_cli.project.models import (
    AuditEvent,
    DecisionRecord,
    ProjectManifest,
    ProjectStage,
    TargetPortal,
)
from vanjaro_cli.project.stage_engine import invalidate_stage_state
from vanjaro_cli.project.workspace import load_manifest, write_manifest


class ProjectTargetError(ValueError):
    """Raised when a target cannot be pinned without cross-client risk."""


def pin_project_target(
    root: Path,
    *,
    expected_base_url: str,
    expected_portal_id: int,
    pinned_by: str,
    clock=None,
) -> TargetPortal:
    """Bind a project to one URL/portal pair before any mutation attempt."""

    now: datetime = (clock or _utc_now)()
    root = root.expanduser().resolve()
    manifest = load_manifest(root).model_copy(deep=True)
    attempted = [
        stage.value
        for stage in (
            ProjectStage.THEME,
            ProjectStage.LIBRARY,
            ProjectStage.PAGES,
            ProjectStage.GLOBAL_BLOCKS,
            ProjectStage.PUBLISH,
        )
        if manifest.stages[stage].attempt > 0
    ]
    if attempted:
        raise ProjectTargetError(
            "cannot repin a target after portal mutation was attempted: "
            + ", ".join(attempted)
        )
    target = TargetPortal(
        profile=manifest.target.profile,
        expected_portal_id=expected_portal_id,
        expected_base_url=expected_base_url,
    )
    if target == manifest.target:
        return target
    invalidated = invalidate_stage_state(
        manifest,
        ProjectStage.PLAN,
        now=now,
        resolved_by=pinned_by,
        approval_note="Superseded because the pinned target identity changed.",
    )
    manifest.target = target
    manifest.decisions.append(
        DecisionRecord(
            id=f"decision-{len(manifest.decisions) + 1:04d}-target-pin",
            topic="target_identity",
            selection=f"{target.expected_base_url}|portal:{target.expected_portal_id}",
            rationale="Pinned before portal mutation to prevent cross-client writes.",
            decided_by=pinned_by,
            decided_at=now,
            stage=ProjectStage.PLAN,
            metadata={
                "profile": target.profile,
                "expected_base_url": target.expected_base_url,
                "expected_portal_id": target.expected_portal_id,
            },
        )
    )
    manifest.audit.append(
        AuditEvent(
            id=f"event-{len(manifest.audit) + 1:05d}-target-pinned",
            occurred_at=now,
            kind="target_pinned",
            message=(
                f"{pinned_by} pinned {target.profile} to "
                f"{target.expected_base_url} portal {target.expected_portal_id}; "
                f"invalidated: {', '.join(invalidated) or 'no completed stages'}."
            ),
            stage=ProjectStage.PLAN,
        )
    )
    manifest.project = manifest.project.model_copy(
        update={"updated_at": max(manifest.project.updated_at, now)}
    )
    write_manifest(root, ProjectManifest.model_validate(manifest.model_dump()))
    return target


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["ProjectTargetError", "pin_project_target"]
