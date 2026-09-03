"""Local launch-plan generation and adoption for agency projects."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from vanjaro_cli.design.serialization import read_design_document
from vanjaro_cli.project import (
    ApprovalGate,
    ApprovalStatus,
    AuditEvent,
    ProjectStage,
    StageRecord,
    StageStatus,
    fingerprint_files,
    load_manifest,
    write_manifest,
)
from vanjaro_cli.project.launch_plan import LaunchPlanError, build_launch_plan
from vanjaro_cli.project.launch_receipt import LAUNCH_PLAN_PATH
from vanjaro_cli.project.publish_lock import PublishLockError, publish_operation_lock
from vanjaro_cli.reliability.artifacts import ArtifactContractError, load_strict_json


_DESIGN_PATH = Path("plans/resolved-design-document.json")
_PAGE_MANIFEST_PATH = Path("build/global-page-manifest.json")


class ProjectLaunchPlanError(ValueError):
    """Raised when launch intent is incomplete, stale, or unsafe to adopt."""


def create_project_launch_plan(
    root: Path,
    *,
    home_page_key: str | None,
    preserve_current_home: bool,
    visibility_overrides: Mapping[str, bool] | None = None,
    name_overrides: Mapping[str, str] | None = None,
    title_overrides: Mapping[str, str] | None = None,
    dry_run: bool = False,
    clock=None,
) -> dict[str, Any]:
    workspace = root.expanduser().resolve()
    manifest = load_manifest(workspace)
    _require_current_stage_artifacts(workspace, manifest, ProjectStage.PLAN)
    _require_current_stage_artifacts(workspace, manifest, ProjectStage.GLOBAL_BLOCKS)
    try:
        document = read_design_document(workspace / _DESIGN_PATH)
        page_manifest = _read_object(workspace / _PAGE_MANIFEST_PATH)
        records = page_manifest.get("pages")
        if not isinstance(records, list):
            raise ProjectLaunchPlanError("managed page manifest has no pages list")
        plan = build_launch_plan(
            document,
            records,
            project_id=manifest.project.id,
            design_document_sha256=_sha256(workspace / _DESIGN_PATH),
            page_manifest_sha256=_sha256(workspace / _PAGE_MANIFEST_PATH),
            home_page_key=home_page_key,
            preserve_current_home=preserve_current_home,
            visibility_overrides=visibility_overrides,
            name_overrides=name_overrides,
            title_overrides=title_overrides,
        )
    except (OSError, ValueError, LaunchPlanError) as exc:
        if isinstance(exc, ProjectLaunchPlanError):
            raise
        raise ProjectLaunchPlanError(str(exc)) from exc
    payload = plan.model_dump(mode="json")
    if dry_run:
        return {
            "status": "ready_for_review",
            "dry_run": True,
            "workspace_mutated": False,
            "portal_mutated": False,
            "plan": payload,
        }
    try:
        with publish_operation_lock(workspace, operation="launch-plan"):
            current = load_manifest(workspace)
            _require_current_stage_artifacts(workspace, current, ProjectStage.PLAN)
            _require_current_stage_artifacts(
                workspace, current, ProjectStage.GLOBAL_BLOCKS
            )
            if _sha256(workspace / _DESIGN_PATH) != plan.design_document_sha256:
                raise ProjectLaunchPlanError("resolved design changed during launch planning")
            if _sha256(workspace / _PAGE_MANIFEST_PATH) != plan.page_manifest_sha256:
                raise ProjectLaunchPlanError("managed pages changed during launch planning")
            mutated = _adopt_plan(
                workspace,
                current,
                payload,
                now=(clock or _utc_now)(),
            )
    except PublishLockError as exc:
        raise ProjectLaunchPlanError(str(exc)) from exc
    return {
        "status": "ready_for_review",
        "dry_run": False,
        "workspace_mutated": mutated,
        "portal_mutated": False,
        "plan": payload,
    }


def _adopt_plan(root, manifest, plan: dict[str, Any], *, now: datetime) -> bool:
    path = root / LAUNCH_PLAN_PATH
    encoded = (json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    previous_plan = path.read_bytes() if path.is_file() else None
    previous_manifest = (root / "project.json").read_bytes()
    metadata = manifest.metadata.get("launch_plan")
    if (
        previous_plan == encoded
        and isinstance(metadata, dict)
        and metadata.get("fingerprint") == plan["fingerprint"]
    ):
        return False
    try:
        _write_bytes(path, encoded)
        working = manifest.model_copy(deep=True)
        working.metadata["launch_plan"] = {
            "path": LAUNCH_PLAN_PATH.as_posix(),
            "fingerprint": plan["fingerprint"],
        }
        working.metadata.pop("launch_review", None)
        working.stages[ProjectStage.LAUNCH] = StageRecord(stage=ProjectStage.LAUNCH)
        for index, approval in enumerate(working.approvals):
            if approval.gate == ApprovalGate.LAUNCH and approval.status in {
                ApprovalStatus.PENDING,
                ApprovalStatus.APPROVED,
            }:
                working.approvals[index] = approval.model_copy(
                    update={
                        "status": ApprovalStatus.SUPERSEDED,
                        "resolved_at": now,
                        "resolved_by": "launch-plan",
                        "note": "Superseded by a newer launch plan.",
                    }
                )
        working.project = working.project.model_copy(update={"updated_at": now})
        working.audit.append(
            AuditEvent(
                id=f"event-{len(working.audit) + 1:05d}-launch-plan-adopted",
                occurred_at=now,
                kind="launch_plan_adopted",
                message="Adopted explicit launch intent for review.",
                fingerprint=plan["fingerprint"],
                artifacts=[LAUNCH_PLAN_PATH.as_posix()],
            )
        )
        write_manifest(root, working)
    except Exception:
        _restore(path, previous_plan)
        _write_bytes(root / "project.json", previous_manifest)
        raise
    return True


def _require_current_stage_artifacts(root, manifest, stage: ProjectStage) -> None:
    record = manifest.stages[stage]
    if record.status != StageStatus.COMPLETED or record.output_fingerprint is None:
        raise ProjectLaunchPlanError(f"{stage.value} stage is not currently completed")
    if fingerprint_files(root, tuple(Path(value) for value in record.artifacts)) != record.output_fingerprint:
        raise ProjectLaunchPlanError(f"{stage.value} artifacts changed after completion")


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = load_strict_json(path)
    except ArtifactContractError as exc:
        raise ProjectLaunchPlanError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProjectLaunchPlanError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _restore(path: Path, value: bytes | None) -> None:
    if value is None:
        path.unlink(missing_ok=True)
    else:
        _write_bytes(path, value)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["ProjectLaunchPlanError", "create_project_launch_plan"]
