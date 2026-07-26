"""Persist audited design corrections and invalidate stale project plans."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from vanjaro_cli.design.overlays import (
    DesignOverlay,
    DesignOverlaySet,
    read_design_overlays,
    serialize_design_overlays,
)
from vanjaro_cli.project.models import (
    AuditEvent,
    DecisionRecord,
    ProjectManifest,
    ProjectStage,
)
from vanjaro_cli.project.stage_engine import invalidate_stage_state
from vanjaro_cli.project.workspace import load_manifest, write_manifest


OVERLAY_ARTIFACT = "analysis/design-overlays.json"


class ProjectOverlayError(ValueError):
    """Raised when an audited project overlay cannot be persisted."""


def add_project_overlay(root: Path, overlay: DesignOverlay) -> DesignOverlay:
    """Append one immutable correction, audit it, and invalidate stale plans."""

    root = root.expanduser().resolve()
    path = root / OVERLAY_ARTIFACT
    if path.exists():
        overlay_set = read_design_overlays(path)
    else:
        overlay_set = DesignOverlaySet(overlays=[])
    existing = next((item for item in overlay_set.overlays if item.id == overlay.id), None)
    if existing is not None and existing != overlay:
        raise ProjectOverlayError(
            f"overlay ID {overlay.id!r} already exists with different content"
        )
    if existing is None:
        overlay_set = overlay_set.model_copy(
            update={"overlays": [*overlay_set.overlays, overlay]}
        )
        _atomic_write_text(path, serialize_design_overlays(overlay_set))

    manifest = load_manifest(root).model_copy(deep=True)
    decision_id = f"decision-overlay-{overlay.id}"
    if not any(decision.id == decision_id for decision in manifest.decisions):
        invalidated = invalidate_stage_state(
            manifest,
            ProjectStage.PLAN,
            now=overlay.created_at,
            resolved_by=overlay.author,
            approval_note="Superseded because an audited design overlay changed planning input.",
        )
        manifest.decisions.append(
            DecisionRecord(
                id=decision_id,
                topic="design_overlay",
                selection=json.dumps(overlay.value, ensure_ascii=False),
                rationale=overlay.reason,
                decided_by=overlay.author,
                decided_at=overlay.created_at,
                stage=ProjectStage.PLAN,
                metadata={
                    "overlay_id": overlay.id,
                    "operation": overlay.operation.value,
                    "target_id": overlay.target_id,
                    "field": overlay.field,
                    "content_kind": (
                        overlay.content_kind.value if overlay.content_kind else None
                    ),
                    "artifact": OVERLAY_ARTIFACT,
                },
            )
        )
        manifest.audit.append(
            AuditEvent(
                id=f"event-{len(manifest.audit) + 1:05d}-design-overlay-added",
                occurred_at=overlay.created_at,
                kind="design_overlay_added",
                message=(
                    f"{overlay.author} added design overlay {overlay.id}; "
                    f"invalidated: {', '.join(invalidated) or 'no completed stages'}."
                ),
                stage=ProjectStage.PLAN,
                artifacts=[OVERLAY_ARTIFACT],
            )
        )
        manifest.project = manifest.project.model_copy(
            update={
                "updated_at": max(manifest.project.updated_at, overlay.created_at)
            }
        )
        write_manifest(root, ProjectManifest.model_validate(manifest.model_dump()))
    return existing or overlay


def load_project_overlays(root: Path) -> DesignOverlaySet:
    path = root.expanduser().resolve() / OVERLAY_ARTIFACT
    return read_design_overlays(path) if path.exists() else DesignOverlaySet(overlays=[])


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "OVERLAY_ARTIFACT",
    "ProjectOverlayError",
    "add_project_overlay",
    "load_project_overlays",
    "utc_now",
]
