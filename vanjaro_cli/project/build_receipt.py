"""Strict, detached receipts for agency build review results."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping


SCHEMA_VERSION = "agency-build-review-v1"
CONTRACT_VERSION = "1.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+$")
_STAGES = frozenset({"theme", "assets", "library", "pages", "global_blocks", "verify"})
_OBSERVED_PORTAL_FIELDS = {
    "profile",
    "base_url",
    "portal_id",
    "health_status",
    "dnn_version",
    "vanjaro_version",
    "user_name",
}
_FIELDS = frozenset(
    {
        "schema_version",
        "contract_version",
        "project_id",
        "target",
        "stage",
        "stage_contract_version",
        "action",
        "attempt",
        "requested",
        "manifest_fingerprint",
        "dependencies",
        "inputs",
        "input_fingerprint",
        "approval",
        "observed_portal",
        "preview",
        "fingerprint",
    }
)


class BuildReceiptError(ValueError):
    """Raised when a build receipt is unsafe or violates its contract."""


def is_sha256(value: object) -> bool:
    """Return whether *value* is a lowercase SHA-256 hexadecimal digest."""

    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _reject_constant(_: str) -> None:
    raise BuildReceiptError("receipt contains a non-finite number")


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BuildReceiptError("receipt contains a duplicate key")
        result[key] = value
    return result


def _canonical(payload: Mapping[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError):
        raise BuildReceiptError("receipt payload is not canonical JSON") from None
    return encoded.encode("utf-8", errors="strict")


def fingerprint_build_payload(payload: Mapping[str, Any]) -> str:
    """Fingerprint a receipt payload, excluding its detached fingerprint."""

    if not isinstance(payload, Mapping):
        raise BuildReceiptError("receipt payload must be an object")
    unsigned = {key: value for key, value in payload.items() if key != "fingerprint"}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def finalize_build_receipt(unsigned: Mapping[str, Any]) -> dict[str, Any]:
    """Return a validated copy of *unsigned* with its detached fingerprint."""

    if not isinstance(unsigned, Mapping):
        raise BuildReceiptError("receipt payload must be an object")
    if "fingerprint" in unsigned:
        raise BuildReceiptError("unsigned receipt must not contain a fingerprint")
    receipt = dict(unsigned)
    receipt["fingerprint"] = fingerprint_build_payload(receipt)
    _validate(receipt)
    return receipt


def _identity(value: object) -> bool:
    return isinstance(value, str) and _IDENTITY.fullmatch(value) is not None


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BuildReceiptError(f"receipt {label} must be an object")
    return value


def _exact_fields(value: dict[str, Any], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise BuildReceiptError(f"receipt {label} has missing or unknown fields")


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BuildReceiptError(f"receipt {label} is invalid")
    return value.strip()


def _validate_json_values(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise BuildReceiptError("receipt contains a non-finite number")
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise BuildReceiptError("receipt object keys must be strings")
        for child in value.values():
            _validate_json_values(child)
    elif isinstance(value, list):
        for child in value:
            _validate_json_values(child)


def _validate_file_path(value: object) -> None:
    if not isinstance(value, str) or not value:
        raise BuildReceiptError("inputs.files contains an invalid path")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or ".." in posix.parts or ".." in windows.parts:
        raise BuildReceiptError("inputs.files contains an unsafe path")


def _validate(receipt: dict[str, Any]) -> None:
    keys = set(receipt)
    if keys != _FIELDS:
        raise BuildReceiptError("receipt has missing or unknown top-level fields")
    if receipt["schema_version"] != SCHEMA_VERSION:
        raise BuildReceiptError("receipt has an unsupported schema version")
    if receipt["contract_version"] != CONTRACT_VERSION:
        raise BuildReceiptError("receipt has an unsupported contract version")
    if not _identity(receipt["project_id"]):
        raise BuildReceiptError("receipt contains an invalid project identity")
    if receipt["stage"] not in _STAGES:
        raise BuildReceiptError("receipt contains an invalid stage")
    if not isinstance(receipt["stage_contract_version"], str) or not _VERSION.fullmatch(
        receipt["stage_contract_version"]
    ):
        raise BuildReceiptError("receipt contains an invalid stage contract version")
    if receipt["action"] not in {"execute", "resume"}:
        raise BuildReceiptError("receipt has an invalid action")
    attempt = receipt["attempt"]
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
        raise BuildReceiptError("receipt has an invalid attempt")
    for field in ("manifest_fingerprint", "input_fingerprint", "fingerprint"):
        if not is_sha256(receipt[field]):
            raise BuildReceiptError("receipt contains an invalid fingerprint")
    target = _object(receipt["target"], "target")
    _exact_fields(
        target,
        {"profile", "expected_base_url", "expected_portal_id"},
        "target",
    )
    _nonempty_text(target["profile"], "target profile")
    _nonempty_text(target["expected_base_url"], "target base URL")
    portal_id = target["expected_portal_id"]
    if isinstance(portal_id, bool) or not isinstance(portal_id, int) or portal_id < 0:
        raise BuildReceiptError("receipt target portal ID is invalid")

    requested = _object(receipt["requested"], "requested")
    _exact_fields(
        requested,
        {"theme_mode", "through", "page_mode", "operator"},
        "requested",
    )
    if requested["theme_mode"] not in {"preserve", "plan"}:
        raise BuildReceiptError("receipt requested theme mode is invalid")
    if requested["through"] not in {
        "theme",
        "assets",
        "library",
        "pages",
        "globals",
        "verify",
    }:
        raise BuildReceiptError("receipt requested build ceiling is invalid")
    if requested["page_mode"] != "isolated":
        raise BuildReceiptError("receipt requested page mode is invalid")
    _nonempty_text(requested["operator"], "operator")

    if not isinstance(receipt["dependencies"], list):
        raise BuildReceiptError("receipt dependencies must be a list")
    for dependency in receipt["dependencies"]:
        entry = _object(dependency, "dependency")
        _exact_fields(entry, {"stage", "status", "output_fingerprint"}, "dependency")
        if entry["stage"] not in _STAGES | {"plan"}:
            raise BuildReceiptError("receipt dependency stage is invalid")
        _nonempty_text(entry["status"], "dependency status")
        output = entry["output_fingerprint"]
        if output is not None and not is_sha256(output):
            raise BuildReceiptError("receipt dependency fingerprint is invalid")

    inputs = _object(receipt["inputs"], "inputs")
    _exact_fields(inputs, {"data", "files"}, "inputs")
    _object(inputs["data"], "input data")
    if not isinstance(receipt["preview"], dict):
        raise BuildReceiptError("receipt preview must be an object")
    for field in ("approval", "observed_portal"):
        if receipt[field] is not None and not isinstance(receipt[field], dict):
            raise BuildReceiptError("receipt nullable object field is invalid")
    files = inputs["files"]
    if not isinstance(files, list):
        raise BuildReceiptError("inputs.files must be a list")
    for file_record in files:
        record = _object(file_record, "input file")
        _exact_fields(record, {"path", "sha256"}, "input file")
        _validate_file_path(record["path"])
        if not is_sha256(record["sha256"]):
            raise BuildReceiptError("receipt input file digest is invalid")

    approval = receipt["approval"]
    if approval is not None:
        approval_record = _object(approval, "approval")
        _exact_fields(
            approval_record,
            {"id", "gate", "status", "fingerprint"},
            "approval",
        )
        _nonempty_text(approval_record["id"], "approval ID")
        _nonempty_text(approval_record["gate"], "approval gate")
        if approval_record["status"] != "approved":
            raise BuildReceiptError("receipt approval is not approved")
        if not is_sha256(approval_record["fingerprint"]):
            raise BuildReceiptError("receipt approval fingerprint is invalid")

    observed = receipt["observed_portal"]
    if observed is not None:
        observed_record = _object(observed, "observed portal")
        _exact_fields(observed_record, _OBSERVED_PORTAL_FIELDS, "observed portal")
        for key in ("profile", "base_url", "health_status", "user_name"):
            _nonempty_text(observed_record.get(key), f"observed portal {key}")
        for key in ("dnn_version", "vanjaro_version"):
            if not isinstance(observed_record[key], str):
                raise BuildReceiptError(
                    f"receipt observed portal {key.replace('_', ' ')} is invalid"
                )
        observed_id = observed_record.get("portal_id")
        if isinstance(observed_id, bool) or not isinstance(observed_id, int) or observed_id < 0:
            raise BuildReceiptError("receipt observed portal ID is invalid")
    _validate_json_values(receipt)


def load_build_receipt(path: str | Path) -> dict[str, Any]:
    """Load and strictly verify a receipt from a caller-selected path."""

    try:
        raw = Path(path).read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError):
        raise BuildReceiptError("unable to read build receipt") from None
    try:
        receipt = json.loads(
            raw,
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except BuildReceiptError:
        raise
    except (json.JSONDecodeError, UnicodeError):
        raise BuildReceiptError("build receipt is not valid JSON") from None
    if not isinstance(receipt, dict):
        raise BuildReceiptError("build receipt must be an object")
    _validate(receipt)
    if fingerprint_build_payload(receipt) != receipt["fingerprint"]:
        raise BuildReceiptError("build receipt fingerprint does not match")
    return receipt


__all__ = [
    "BuildReceiptError",
    "finalize_build_receipt",
    "fingerprint_build_payload",
    "is_sha256",
    "load_build_receipt",
]
