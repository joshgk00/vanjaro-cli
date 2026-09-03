"""Durable, receipt-keyed intent journals for one-stage agency builds."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from vanjaro_cli.project.build_receipt import is_sha256
from vanjaro_cli.reliability import (
    ArtifactContractError,
    atomic_write_json,
    load_strict_json,
    redact_diagnostic_text,
)


BUILD_TRANSACTION_SCHEMA = "agency-build-transaction-v1"
BUILD_TRANSACTION_ROOT = Path("history/build")
_FIELDS = {
    "schema_version",
    "receipt_fingerprint",
    "project_id",
    "stage",
    "attempt",
    "operator",
    "status",
    "started_at",
    "updated_at",
    "error",
    "actions",
    "local_writes",
    "execution",
}


class BuildTransactionError(ValueError):
    """A malformed, mismatched, or recovery-required build transaction."""


def build_transaction_path(fingerprint: str) -> Path:
    if not is_sha256(fingerprint):
        raise BuildTransactionError("build transaction fingerprint is invalid")
    return BUILD_TRANSACTION_ROOT / fingerprint / "transaction.json"


def load_build_transaction(root: Path, fingerprint: str) -> dict[str, Any] | None:
    path = root.expanduser().resolve() / build_transaction_path(fingerprint)
    if not path.is_file():
        return None
    try:
        value = load_strict_json(path)
    except ArtifactContractError as exc:
        raise BuildTransactionError(f"build transaction is unreadable: {exc}") from exc
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise BuildTransactionError("build transaction has an invalid field contract")
    if value.get("schema_version") != BUILD_TRANSACTION_SCHEMA:
        raise BuildTransactionError("build transaction schema is unsupported")
    if value.get("receipt_fingerprint") != fingerprint:
        raise BuildTransactionError("build transaction fingerprint is mismatched")
    if value.get("status") not in {"applying", "completed", "recovery_required"}:
        raise BuildTransactionError("build transaction status is invalid")
    actions = value.get("actions")
    if not isinstance(actions, list) or any(not isinstance(item, dict) for item in actions):
        raise BuildTransactionError("build transaction actions are invalid")
    for action in actions:
        if set(action) != {"sequence", "plan", "status"}:
            raise BuildTransactionError("build transaction action contract is invalid")
        if action["status"] not in {"pending", "attempting", "committed", "preexisting"}:
            raise BuildTransactionError("build transaction action status is invalid")
    return value


def begin_build_transaction(
    root: Path,
    *,
    receipt: Mapping[str, Any],
    operator: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    fingerprint = str(receipt.get("fingerprint", ""))
    existing = load_build_transaction(root, fingerprint)
    if existing is not None:
        _require_binding(existing, receipt=receipt, operator=operator)
        raise BuildTransactionError(
            f"build transaction already exists with status {existing['status']}"
        )
    preview = receipt.get("preview")
    if not isinstance(preview, Mapping):
        raise BuildTransactionError("build receipt has no transaction preview")
    actions = preview.get("portal_actions")
    local_writes = preview.get("local_writes")
    if not isinstance(actions, list) or not isinstance(local_writes, list):
        raise BuildTransactionError("build receipt transaction plan is invalid")
    timestamp = _timestamp(now or datetime.now(timezone.utc))
    journal = {
        "schema_version": BUILD_TRANSACTION_SCHEMA,
        "receipt_fingerprint": fingerprint,
        "project_id": receipt.get("project_id"),
        "stage": receipt.get("stage"),
        "attempt": receipt.get("attempt"),
        "operator": operator.strip(),
        "status": "applying",
        "started_at": timestamp,
        "updated_at": timestamp,
        "error": None,
        "actions": [
            {
                "sequence": index,
                "plan": action,
                "status": "pending" if _mutates_portal(action) else "preexisting",
            }
            for index, action in enumerate(actions, 1)
        ],
        "local_writes": list(local_writes),
        "execution": None,
    }
    _write(root, fingerprint, journal)
    return journal


def mark_build_transaction_attempting(
    root: Path,
    journal: dict[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    for action in journal["actions"]:
        if action["status"] == "pending":
            action["status"] = "attempting"
    journal["updated_at"] = _timestamp(now or datetime.now(timezone.utc))
    _write(root, str(journal["receipt_fingerprint"]), journal)


def complete_build_transaction(
    root: Path,
    journal: dict[str, Any],
    *,
    execution: Mapping[str, Any],
    now: datetime | None = None,
) -> None:
    for action in journal["actions"]:
        if action["status"] in {"pending", "attempting"}:
            action["status"] = "committed"
    journal["status"] = "completed"
    journal["execution"] = dict(execution)
    journal["error"] = None
    journal["updated_at"] = _timestamp(now or datetime.now(timezone.utc))
    _write(root, str(journal["receipt_fingerprint"]), journal)


def fail_build_transaction(
    root: Path,
    journal: dict[str, Any],
    *,
    error: BaseException,
    now: datetime | None = None,
) -> None:
    journal["status"] = "recovery_required"
    journal["error"] = {
        "type": type(error).__name__,
        "message": redact_diagnostic_text(str(error) or type(error).__name__),
    }
    journal["updated_at"] = _timestamp(now or datetime.now(timezone.utc))
    _write(root, str(journal["receipt_fingerprint"]), journal)


def require_build_transaction_binding(
    journal: Mapping[str, Any],
    *,
    receipt: Mapping[str, Any],
    operator: str,
) -> None:
    _require_binding(journal, receipt=receipt, operator=operator)


def _require_binding(
    journal: Mapping[str, Any],
    *,
    receipt: Mapping[str, Any],
    operator: str,
) -> None:
    expected = {
        "receipt_fingerprint": receipt.get("fingerprint"),
        "project_id": receipt.get("project_id"),
        "stage": receipt.get("stage"),
        "attempt": receipt.get("attempt"),
        "operator": operator.strip(),
    }
    if any(journal.get(key) != value for key, value in expected.items()):
        raise BuildTransactionError(
            "build transaction belongs to a different receipt, stage, attempt, or operator"
        )


def _mutates_portal(action: object) -> bool:
    if not isinstance(action, Mapping):
        return False
    operations = action.get("operations")
    if isinstance(operations, list):
        return any(
            isinstance(item, Mapping)
            and item.get("kind") == "portal_request"
            and str(item.get("method", "")).upper() in {"POST", "POST_FORM", "PUT", "PATCH", "DELETE"}
            for item in operations
        )
    return str(action.get("method", "")).upper() in {
        "POST",
        "POST_FORM",
        "PUT",
        "PATCH",
        "DELETE",
    }


def _write(root: Path, fingerprint: str, journal: Mapping[str, Any]) -> None:
    try:
        atomic_write_json(
            root.expanduser().resolve() / build_transaction_path(fingerprint), journal
        )
    except ArtifactContractError as exc:
        raise BuildTransactionError(f"cannot persist build transaction: {exc}") from exc


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "BUILD_TRANSACTION_ROOT",
    "BUILD_TRANSACTION_SCHEMA",
    "BuildTransactionError",
    "begin_build_transaction",
    "build_transaction_path",
    "complete_build_transaction",
    "fail_build_transaction",
    "load_build_transaction",
    "mark_build_transaction_attempting",
    "require_build_transaction_binding",
]
