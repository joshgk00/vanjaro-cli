"""Local state, locking, and recovery storage for project publication."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any

from vanjaro_cli.project import (
    ApprovalGate,
    ApprovalStatus,
    AuditEvent,
    ProjectManifest,
    ProjectStage,
    fingerprint_data,
    write_manifest,
)
from vanjaro_cli.project.publish_lock import (
    PublishLockError,
    clear_stale_publish_lock,
    publish_operation_lock,
)
from vanjaro_cli.project.publish_receipt import (
    PUBLISH_JOURNAL_ROOT,
    PUBLISH_REVIEW_PATH,
)
from vanjaro_cli.project.workspace import MANIFEST_FILENAME
from vanjaro_cli.reliability.contracts import PUBLISH_JOURNAL_SCHEMA
from vanjaro_cli.reliability.artifacts import ArtifactContractError, load_strict_json


class ProjectPublishError(ValueError):
    """Categorized publication workflow failure with safe recovery guidance."""

    def __init__(self, code: str, message: str, recommended_action: str) -> None:
        self.code = code
        self.message = message
        self.recommended_action = recommended_action
        super().__init__(
            f"[{code}] {message} Recommended action: {recommended_action}"
        )


def adopt_publish_receipt(
    root: Path,
    manifest: ProjectManifest,
    receipt: Mapping[str, Any],
    *,
    now: datetime,
) -> bool:
    """Atomically install a receipt, then adopt it into the project manifest."""

    path = root / PUBLISH_REVIEW_PATH
    text = publish_json_text(receipt)
    metadata = manifest.metadata.get("publish_review")
    if (
        isinstance(metadata, dict)
        and metadata.get("fingerprint") == receipt["fingerprint"]
        and path.is_file()
        and path.read_text(encoding="utf-8") == text
    ):
        return False
    previous = path.read_bytes() if path.is_file() else None
    manifest_path = root / MANIFEST_FILENAME
    previous_manifest = manifest_path.read_bytes()
    write_publish_text(path, text)
    try:
        working = manifest.model_copy(deep=True)
        working.metadata["publish_review"] = {
            "schema_version": "1.0",
            "path": PUBLISH_REVIEW_PATH.as_posix(),
            "fingerprint": receipt["fingerprint"],
            "verification_fingerprint": receipt["verification_fingerprint"],
            "prepared_at": receipt["prepared_at"],
        }
        for index, approval in enumerate(working.approvals):
            if approval.gate == ApprovalGate.PUBLISH and approval.status in {
                ApprovalStatus.PENDING,
                ApprovalStatus.APPROVED,
            }:
                working.approvals[index] = approval.model_copy(
                    update={
                        "status": ApprovalStatus.SUPERSEDED,
                        "resolved_at": now,
                        "resolved_by": "publish-prepare",
                        "note": "Superseded by a newly prepared publish receipt.",
                    }
                )
        working.audit.append(
            AuditEvent(
                id=f"event-{len(working.audit) + 1:05d}-publish-review-prepared",
                occurred_at=now,
                kind="publish_review_prepared",
                message="Prepared GET-only publish review receipt.",
                stage=ProjectStage.PUBLISH,
                fingerprint=str(receipt["fingerprint"]),
                artifacts=[PUBLISH_REVIEW_PATH.as_posix()],
            )
        )
        working.project = working.project.model_copy(update={"updated_at": now})
        write_manifest(root, ProjectManifest.model_validate(working.model_dump()))
    except Exception:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            write_publish_bytes(path, previous)
        write_publish_bytes(manifest_path, previous_manifest)
        raise
    return True


def load_or_create_publish_journal(
    path: Path,
    *,
    receipt: Mapping[str, Any],
    published_by: str,
    now: datetime,
) -> dict[str, Any]:
    """Load a matching recovery journal or durably create it before mutation."""

    if path.is_file():
        journal = read_publish_object(path)
        _validate_publish_journal(
            journal, receipt=receipt, published_by=published_by
        )
        return journal
    journal = {
        "schema_version": PUBLISH_JOURNAL_SCHEMA,
        "receipt_fingerprint": receipt["fingerprint"],
        "project_id": receipt["project_id"],
        "target": receipt["target"],
        "published_by": published_by,
        "started_at": _timestamp(now),
        "updated_at": _timestamp(now),
        "status": "applying",
        "error": None,
        "actions": [
            {
                "action": action,
                "status": (
                    "preexisting" if action.get("prepared_published") is True else "pending"
                ),
                "before": None,
                "after": None,
            }
            for action in receipt["actions"]
        ],
    }
    write_publish_json(path, journal)
    return journal


def write_publish_journal(
    path: Path, journal: dict[str, Any], *, now: datetime
) -> None:
    journal["updated_at"] = _timestamp(now)
    write_publish_json(path, journal)


def require_publish_approval(
    manifest: ProjectManifest, approval_id: str, fingerprint: str
) -> None:
    matching = next((item for item in manifest.approvals if item.id == approval_id), None)
    if matching is None:
        raise ProjectPublishError(
            "approval_missing",
            "publish approval ID was not found",
            "Request and approve this receipt.",
        )
    if (
        matching.gate != ApprovalGate.PUBLISH
        or matching.status != ApprovalStatus.APPROVED
        or matching.fingerprint != fingerprint
    ):
        raise ProjectPublishError(
            "approval_invalid",
            "approval is not an approved publish decision for this receipt",
            "Request and resolve a publish approval for the exact receipt fingerprint.",
        )


def _validate_publish_journal(
    journal: Mapping[str, Any],
    *,
    receipt: Mapping[str, Any],
    published_by: str,
) -> None:
    if journal.get("schema_version") != PUBLISH_JOURNAL_SCHEMA:
        _journal_tampered("publish journal schema is invalid")
    if journal.get("receipt_fingerprint") != receipt["fingerprint"]:
        raise ProjectPublishError(
            "journal_mismatch",
            "publish journal belongs to a different receipt",
            "Stop and review the existing recovery journal.",
        )
    if journal.get("project_id") != receipt["project_id"] or journal.get(
        "target"
    ) != receipt.get("target"):
        _journal_tampered("publish journal project or target does not match the receipt")
    if journal.get("published_by") != published_by:
        raise ProjectPublishError(
            "journal_publisher_mismatch",
            "publish recovery must use the same publisher identity as the transaction",
            f"Retry with --by {journal.get('published_by')!r} after reviewing the journal.",
        )
    status = journal.get("status")
    if status not in {"applying", "interrupted", "completed"}:
        _journal_tampered("publish journal transaction status is invalid")
    error = journal.get("error")
    if error is not None and not isinstance(error, str):
        _journal_tampered("publish journal error is invalid")
    entries = journal.get("actions")
    actions = receipt.get("actions")
    if not isinstance(entries, list) or not isinstance(actions, list):
        _journal_tampered("publish journal action records are invalid")
    if len(entries) != len(actions):
        _journal_tampered("publish journal action count does not match the receipt")
    for action, entry in zip(actions, entries, strict=True):
        if not isinstance(action, dict) or not isinstance(entry, dict):
            _journal_tampered("publish journal entry is invalid")
        if entry.get("action") != action:
            _journal_tampered("publish journal actions do not match the receipt")
        entry_status = entry.get("status")
        before = entry.get("before")
        after = entry.get("after")
        prepared_published = action.get("prepared_published") is True
        if entry_status == "pending":
            valid = not prepared_published and before is None and after is None
        elif entry_status == "preexisting":
            valid = prepared_published and before is None and after is None
        elif entry_status == "attempting":
            valid = (
                not prepared_published
                and _journal_observation_matches(action, before, published=False)
                and after is None
            )
        elif entry_status == "committed":
            valid_before = (
                before is None
                if prepared_published
                else _journal_observation_matches(action, before, published=False)
            )
            valid = valid_before and _journal_observation_matches(
                action, after, published=True
            )
        else:
            valid = False
        if not valid:
            _journal_tampered(
                f"publish journal has an impossible {entry_status!r} entry state"
            )
    if status == "completed" and any(
        entry.get("status") != "committed" for entry in entries
    ):
        _journal_tampered("completed publish journal contains uncommitted actions")


def _journal_observation_matches(
    action: Mapping[str, Any], value: object, *, published: bool
) -> bool:
    if not isinstance(value, dict) or value.get("published") is not published:
        return False
    keys = ("object_type", "object_id", "project_id", "version", "desired_hash")
    return all(value.get(key) == action.get(key) for key in keys)


def _journal_tampered(message: str) -> None:
    raise ProjectPublishError(
        "journal_tampered",
        message,
        "Stop and restore the journal from trusted recovery evidence.",
    )


def manifest_projection_fingerprint(manifest: ProjectManifest) -> str:
    """Hash authority-relevant manifest state without audit/approval cycles."""

    return fingerprint_data(
        {
            "schema_version": manifest.schema_version,
            "project": manifest.project.id,
            "target": manifest.target.model_dump(mode="json"),
            "agency_pack": manifest.agency_pack.model_dump(mode="json"),
            "sources": [source.model_dump(mode="json") for source in manifest.sources],
            "stages": {
                stage.value: {
                    "status": record.status.value,
                    "output_fingerprint": record.output_fingerprint,
                    "artifacts": record.artifacts,
                }
                for stage, record in manifest.stages.items()
                if stage != ProjectStage.PUBLISH
            },
        }
    )


def publish_journal_path(fingerprint: str) -> Path:
    return PUBLISH_JOURNAL_ROOT / fingerprint / "transaction.json"


def read_publish_object(path: Path) -> dict[str, Any]:
    try:
        value = load_strict_json(path)
    except ArtifactContractError as exc:
        raise ProjectPublishError(
            "evidence_invalid",
            f"cannot read {path}: {exc}",
            "Regenerate the owning project artifact.",
        ) from exc
    if not isinstance(value, dict):
        raise ProjectPublishError(
            "evidence_invalid",
            f"{path} must contain an object",
            "Regenerate the artifact.",
        )
    return value


def require_publish_records(
    value: Mapping[str, Any], key: str, label: str
) -> list[dict[str, Any]]:
    records = value.get(key)
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise ProjectPublishError(
            "evidence_invalid",
            f"{label} has invalid records",
            "Rerun the owning build stage.",
        )
    return records


def write_publish_json(path: Path, value: Mapping[str, Any]) -> None:
    write_publish_text(path, publish_json_text(value))


def publish_json_text(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
    ) + "\n"


def write_publish_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def write_publish_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.restore-tmp")
    with temporary.open("wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


@contextmanager
def publish_lock(
    root: Path,
    *,
    operation: str,
    receipt_fingerprint: str | None = None,
) -> Iterator[None]:
    """Refuse concurrent publication processes in one project workspace."""

    try:
        with publish_operation_lock(
            root,
            operation=operation,
            receipt_fingerprint=receipt_fingerprint,
        ):
            yield
    except PublishLockError as exc:
        raise ProjectPublishError(exc.code, exc.message, exc.recommended_action) from exc


def clear_publish_lock(
    root: Path, *, owner_token: str, confirmation: str
) -> dict[str, Any]:
    """Clear a proven-stale lock after exact operator confirmation."""

    try:
        return clear_stale_publish_lock(
            root, owner_token=owner_token, confirmation=confirmation
        )
    except PublishLockError as exc:
        raise ProjectPublishError(exc.code, exc.message, exc.recommended_action) from exc


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


__all__ = [
    "ProjectPublishError",
    "adopt_publish_receipt",
    "clear_publish_lock",
    "load_or_create_publish_journal",
    "manifest_projection_fingerprint",
    "publish_journal_path",
    "publish_lock",
    "read_publish_object",
    "require_publish_approval",
    "require_publish_records",
    "write_publish_journal",
    "write_publish_json",
]
