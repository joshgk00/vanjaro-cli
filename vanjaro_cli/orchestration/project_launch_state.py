"""Local receipt, journal, approval, and lock state for project launch."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping

from vanjaro_cli.project import (
    ApprovalGate,
    ApprovalStatus,
    AuditEvent,
    ProjectManifest,
    ProjectStage,
    StageRecord,
    write_manifest,
)
from vanjaro_cli.project.launch_receipt import (
    LAUNCH_JOURNAL_ROOT,
    LAUNCH_REVIEW_PATH,
)
from vanjaro_cli.project.publish_lock import publish_operation_lock
from vanjaro_cli.reliability.contracts import LAUNCH_TRANSACTION_SCHEMA
from vanjaro_cli.reliability.artifacts import ArtifactContractError, load_strict_json


class ProjectLaunchStateError(ValueError):
    """Raised when local launch transaction state is invalid or tampered."""


def launch_lock(root: Path, *, operation: str, receipt_fingerprint: str | None = None):
    return publish_operation_lock(
        root,
        operation=f"launch-{operation}",
        receipt_fingerprint=receipt_fingerprint,
    )


def launch_journal_path(fingerprint: str) -> Path:
    return LAUNCH_JOURNAL_ROOT / fingerprint / "transaction.json"


def adopt_launch_receipt(
    root: Path,
    manifest: ProjectManifest,
    receipt: Mapping[str, Any],
    *,
    now: datetime,
) -> bool:
    path = root / LAUNCH_REVIEW_PATH
    encoded = _encoded(receipt)
    previous_receipt = path.read_bytes() if path.is_file() else None
    previous_manifest = (root / "project.json").read_bytes()
    metadata = manifest.metadata.get("launch_review")
    fingerprint = receipt.get("fingerprint")
    if (
        previous_receipt == encoded
        and isinstance(metadata, dict)
        and metadata.get("fingerprint") == fingerprint
    ):
        return False
    try:
        _write_bytes(path, encoded)
        working = manifest.model_copy(deep=True)
        working.metadata["launch_review"] = {
            "path": LAUNCH_REVIEW_PATH.as_posix(),
            "fingerprint": fingerprint,
        }
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
                        "resolved_by": "launch-review",
                        "note": "Superseded by a newer launch review receipt.",
                    }
                )
        working.project = working.project.model_copy(update={"updated_at": now})
        working.audit.append(
            AuditEvent(
                id=f"event-{len(working.audit) + 1:05d}-launch-review-adopted",
                occurred_at=now,
                kind="launch_review_adopted",
                message="Adopted exact live launch review receipt.",
                fingerprint=str(fingerprint),
                artifacts=[LAUNCH_REVIEW_PATH.as_posix()],
            )
        )
        write_manifest(root, working)
    except Exception:
        _restore(path, previous_receipt)
        _write_bytes(root / "project.json", previous_manifest)
        raise
    return True


def require_launch_approval(
    manifest: ProjectManifest, *, approval_id: str, fingerprint: str
) -> None:
    matches = [item for item in manifest.approvals if item.id == approval_id]
    if len(matches) != 1:
        raise ProjectLaunchStateError("launch approval ID is missing or ambiguous")
    approval = matches[0]
    if (
        approval.gate != ApprovalGate.LAUNCH
        or approval.status != ApprovalStatus.APPROVED
        or approval.fingerprint != fingerprint
    ):
        raise ProjectLaunchStateError(
            "launch approval is not approved for the exact receipt fingerprint"
        )


def load_or_create_launch_journal(
    path: Path,
    *,
    receipt: Mapping[str, Any],
    launched_by: str,
    now: datetime,
) -> dict[str, Any]:
    if path.is_file():
        journal = _read_object(path)
        _validate_journal(journal, receipt=receipt, launched_by=launched_by)
        return journal
    actions = receipt.get("actions")
    if not isinstance(actions, list):
        raise ProjectLaunchStateError("launch receipt actions are invalid")
    return {
        "schema_version": LAUNCH_TRANSACTION_SCHEMA,
        "status": "applying",
        "receipt_fingerprint": receipt.get("fingerprint"),
        "project_id": receipt.get("project_id"),
        "launched_by": launched_by,
        "started_at": _timestamp(now),
        "updated_at": _timestamp(now),
        "batch_attempted": False,
        "error": None,
        "apply_warnings": [],
        "actions": [
            {
                "page_key": action.get("page_key"),
                "page_id": action.get("page_id"),
                "status": "pending",
                "before": action.get("before"),
                "after": None,
            }
            for action in actions
        ],
        "home": receipt.get("home"),
    }


def read_launch_journal(
    path: Path, *, receipt: Mapping[str, Any]
) -> dict[str, Any]:
    """Read and authenticate an existing journal without changing it."""

    journal = _read_object(path)
    launched_by = journal.get("launched_by")
    if not isinstance(launched_by, str) or not launched_by:
        raise ProjectLaunchStateError("launch journal publisher identity is invalid")
    _validate_journal(journal, receipt=receipt, launched_by=launched_by)
    return journal


def write_launch_journal(path: Path, value: dict[str, Any], *, now: datetime) -> None:
    value["updated_at"] = _timestamp(now)
    _write_bytes(path, _encoded(value))


def write_launch_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_bytes(path, _encoded(value))


def _validate_journal(
    journal: Mapping[str, Any], *, receipt: Mapping[str, Any], launched_by: str
) -> None:
    if journal.get("schema_version") != LAUNCH_TRANSACTION_SCHEMA:
        raise ProjectLaunchStateError("launch journal schema is invalid")
    if journal.get("receipt_fingerprint") != receipt.get("fingerprint"):
        raise ProjectLaunchStateError("launch journal belongs to a different receipt")
    if journal.get("project_id") != receipt.get("project_id"):
        raise ProjectLaunchStateError("launch journal belongs to a different project")
    if journal.get("launched_by") != launched_by:
        raise ProjectLaunchStateError("launch retry requires the original publisher identity")
    if journal.get("status") not in {"applying", "interrupted", "completed"}:
        raise ProjectLaunchStateError("launch journal status is invalid")
    if not isinstance(journal.get("batch_attempted"), bool):
        raise ProjectLaunchStateError("launch journal batch state is invalid")
    error = journal.get("error")
    if error is not None and not isinstance(error, str):
        raise ProjectLaunchStateError("launch journal error evidence is invalid")
    warnings = journal.get("apply_warnings")
    if not isinstance(warnings, list) or any(
        not isinstance(item, str) for item in warnings
    ):
        raise ProjectLaunchStateError("launch journal apply warnings are invalid")
    entries = journal.get("actions")
    actions = receipt.get("actions")
    if not isinstance(entries, list) or not isinstance(actions, list) or len(entries) != len(actions):
        raise ProjectLaunchStateError("launch journal action set is invalid")
    for entry, action in zip(entries, actions, strict=True):
        if not isinstance(entry, Mapping):
            raise ProjectLaunchStateError("launch journal entry is invalid")
        if entry.get("page_key") != action.get("page_key") or entry.get("page_id") != action.get("page_id"):
            raise ProjectLaunchStateError("launch journal action identity was modified")
        if entry.get("before") != action.get("before"):
            raise ProjectLaunchStateError("launch journal before-state was modified")
        status = entry.get("status")
        if status not in {"pending", "attempting", "committed"}:
            raise ProjectLaunchStateError("launch journal action status is invalid")
        after = entry.get("after")
        if status == "committed" and not isinstance(after, Mapping):
            raise ProjectLaunchStateError("committed launch journal action has no after-state")
        if status != "committed" and after is not None:
            raise ProjectLaunchStateError("uncommitted launch journal action has after-state")
        if status == "committed" and not _committed_after_matches(after, action):
            raise ProjectLaunchStateError("committed launch after-state was modified")
    if journal.get("home") != receipt.get("home"):
        raise ProjectLaunchStateError("launch journal home state was modified")
    statuses = [entry.get("status") for entry in entries]
    batch_attempted = journal.get("batch_attempted") is True
    journal_status = journal.get("status")
    if journal_status == "completed":
        if any(status != "committed" for status in statuses) or error is not None:
            raise ProjectLaunchStateError("completed launch journal is internally inconsistent")
    elif journal_status == "applying":
        if not batch_attempted or any(status != "attempting" for status in statuses):
            raise ProjectLaunchStateError("applying launch journal is internally inconsistent")
    elif not batch_attempted and any(status != "pending" for status in statuses):
        raise ProjectLaunchStateError("unattempted launch journal is internally inconsistent")
    if any(status == "attempting" for status in statuses) and not batch_attempted:
        raise ProjectLaunchStateError("attempting launch journal has no batch evidence")


def _committed_after_matches(
    observed: Mapping[str, Any], action: Mapping[str, Any]
) -> bool:
    expected = action.get("after")
    if not isinstance(expected, Mapping):
        return False
    fields = (
        "page_id",
        "name",
        "title",
        "path",
        "is_visible",
        "parent_id",
        "tab_order",
        "culture_code",
    )
    token = observed.get("metadata_token")
    return (
        isinstance(token, str)
        and bool(token)
        and all(observed.get(field) == expected.get(field) for field in fields)
    )


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = load_strict_json(path)
    except ArtifactContractError as exc:
        raise ProjectLaunchStateError(f"launch journal is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise ProjectLaunchStateError("launch journal must contain a JSON object")
    return value


def _encoded(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


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


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


__all__ = [
    "ProjectLaunchStateError",
    "adopt_launch_receipt",
    "launch_journal_path",
    "launch_lock",
    "load_or_create_launch_journal",
    "read_launch_journal",
    "require_launch_approval",
    "write_launch_journal",
    "write_launch_json",
]
