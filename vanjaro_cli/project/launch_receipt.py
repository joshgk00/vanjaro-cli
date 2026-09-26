"""Pure validation for adopted, fingerprint-bound launch review receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from vanjaro_cli.project.models import ProjectManifest, ProjectStage, StageStatus
from vanjaro_cli.project.publish_receipt import current_publish_review
from vanjaro_cli.project.workspace import artifact_path
from vanjaro_cli.reliability.contracts import LAUNCH_REVIEW_SCHEMA
from vanjaro_cli.reliability.artifacts import ArtifactContractError, load_strict_json


LAUNCH_PLAN_PATH = Path("plans/launch-plan.json")
LAUNCH_REVIEW_PATH = Path("qa/launch-review.json")
LAUNCH_RESULT_PATH = Path("qa/launch-result.json")
LAUNCH_JOURNAL_ROOT = Path("history/launch")
_DESIGN_DOCUMENT_PATH = Path("plans/resolved-design-document.json")
_PAGE_MANIFEST_PATH = Path("build/global-page-manifest.json")


class LaunchReceiptError(ValueError):
    """Raised when local launch authority is missing, stale, or malformed."""


def fingerprint_launch_payload(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def finalize_launch_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("fingerprint", None)
    result["fingerprint"] = fingerprint_launch_payload(result)
    return result


def load_launch_payload(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = load_strict_json(path)
    except ArtifactContractError as exc:
        if not path.exists():
            raise LaunchReceiptError(f"{label} is missing: {path}") from exc
        raise LaunchReceiptError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise LaunchReceiptError(f"{label} must contain a JSON object")
    supplied = value.get("fingerprint")
    unsigned = dict(value)
    unsigned.pop("fingerprint", None)
    if supplied != fingerprint_launch_payload(unsigned):
        raise LaunchReceiptError(f"{label} fingerprint does not match its payload")
    return value


def current_launch_review(root: Path, manifest: ProjectManifest) -> dict[str, Any]:
    metadata = manifest.metadata.get("launch_review")
    if not isinstance(metadata, dict):
        raise LaunchReceiptError(
            "no launch review is adopted; run `vanjaro project launch prepare`"
        )
    if metadata.get("path") != LAUNCH_REVIEW_PATH.as_posix():
        raise LaunchReceiptError("adopted launch review path is invalid")
    receipt = load_launch_payload(
        artifact_path(root, LAUNCH_REVIEW_PATH.as_posix()),
        label="launch review receipt",
    )
    if metadata.get("fingerprint") != receipt["fingerprint"]:
        raise LaunchReceiptError("adopted launch review fingerprint is stale")
    if receipt.get("schema_version") != LAUNCH_REVIEW_SCHEMA:
        raise LaunchReceiptError("unsupported launch review schema version")
    if receipt.get("project_id") != manifest.project.id:
        raise LaunchReceiptError("launch review belongs to a different project")
    if receipt.get("target") != manifest.target.model_dump(mode="json"):
        raise LaunchReceiptError("launch review target no longer matches project.json")

    publish = manifest.stages[ProjectStage.PUBLISH]
    if publish.status != StageStatus.COMPLETED or publish.output_fingerprint is None:
        raise LaunchReceiptError("publish stage is not currently completed")
    if receipt.get("publish_output_fingerprint") != publish.output_fingerprint:
        raise LaunchReceiptError("launch review references a different publish result")

    plan = load_launch_payload(
        artifact_path(root, LAUNCH_PLAN_PATH.as_posix()),
        label="launch plan",
    )
    if plan.get("project_id") != manifest.project.id:
        raise LaunchReceiptError("launch plan belongs to a different project")
    if receipt.get("launch_plan_fingerprint") != plan["fingerprint"]:
        raise LaunchReceiptError("launch plan changed after review preparation")
    for field, relative, label in (
        ("design_document_sha256", _DESIGN_DOCUMENT_PATH, "resolved design"),
        ("page_manifest_sha256", _PAGE_MANIFEST_PATH, "managed page manifest"),
    ):
        if plan.get(field) != _sha256_file(artifact_path(root, relative.as_posix()), label):
            raise LaunchReceiptError(f"{label} changed after launch planning")
    try:
        publish_review = current_publish_review(root, manifest)
    except ValueError as exc:
        raise LaunchReceiptError(f"publish review is no longer current: {exc}") from exc
    if receipt.get("publish_receipt_fingerprint") != publish_review.get("fingerprint"):
        raise LaunchReceiptError("launch review references a different publish receipt")
    publish_result = artifact_path(root, "qa/publish-result.json")
    try:
        observed_publish_result = hashlib.sha256(publish_result.read_bytes()).hexdigest()
    except OSError as exc:
        raise LaunchReceiptError(f"publish result is unavailable: {exc}") from exc
    if receipt.get("publish_result_sha256") != observed_publish_result:
        raise LaunchReceiptError("publish result changed after launch preparation")
    if not _sha256(receipt.get("visual_fidelity_fingerprint")):
        raise LaunchReceiptError("launch review has no visual fidelity fingerprint")
    _require_launch_actions(receipt)
    return receipt


def current_launch_review_fingerprint(root: Path, manifest: ProjectManifest) -> str:
    return str(current_launch_review(root, manifest)["fingerprint"])


def _require_launch_actions(receipt: Mapping[str, Any]) -> None:
    namespace = receipt.get("namespace_fingerprint")
    if not _sha256(namespace):
        raise LaunchReceiptError("launch namespace fingerprint is invalid")
    project_id = receipt.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise LaunchReceiptError("launch review project ID is invalid")
    actions = receipt.get("actions")
    if not isinstance(actions, list) or not actions:
        raise LaunchReceiptError("launch review contains no page actions")
    seen_keys: set[str] = set()
    seen_ids: set[int] = set()
    for action in actions:
        if not isinstance(action, dict):
            raise LaunchReceiptError("launch action must be a JSON object")
        page_key = action.get("page_key")
        page_id = action.get("page_id")
        before = action.get("before")
        after = action.get("after")
        if not isinstance(page_key, str) or not page_key:
            raise LaunchReceiptError("launch page key is invalid")
        if isinstance(page_id, bool) or not isinstance(page_id, int) or page_id < 0:
            raise LaunchReceiptError("launch page ID is invalid")
        if page_key in seen_keys or page_id in seen_ids:
            raise LaunchReceiptError("launch review contains duplicate page ownership")
        if action.get("project_id") != project_id:
            raise LaunchReceiptError("launch action project ownership is invalid")
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise LaunchReceiptError("launch action before/after state is invalid")
        _require_page_state(before, page_id=page_id, include_token=True)
        _require_page_state(after, page_id=page_id, include_token=False)
        seen_keys.add(page_key)
        seen_ids.add(page_id)
    home = receipt.get("home")
    if not isinstance(home, dict):
        raise LaunchReceiptError("launch review home state is invalid")
    for key in ("before_page_id", "after_page_id"):
        value = home.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise LaunchReceiptError(f"launch review {key} is invalid")
    warnings = receipt.get("warnings")
    if not isinstance(warnings, list) or any(
        not isinstance(item, str) or not item for item in warnings
    ):
        raise LaunchReceiptError("launch review warnings are invalid")


def _require_page_state(
    state: Mapping[str, Any], *, page_id: int, include_token: bool
) -> None:
    if state.get("page_id") != page_id:
        raise LaunchReceiptError("launch state page identity is invalid")
    if include_token:
        token = state.get("metadata_token")
        if not isinstance(token, str) or not token:
            raise LaunchReceiptError("launch action metadata token is invalid")
    elif state.get("metadata_token") is not None:
        raise LaunchReceiptError("intended launch state must not predict a metadata token")
    for field in ("name", "title", "path"):
        value = state.get(field)
        if not isinstance(value, str) or not value:
            raise LaunchReceiptError(f"launch state {field} is invalid")
    if not isinstance(state.get("is_visible"), bool):
        raise LaunchReceiptError("launch state visibility is invalid")
    parent = state.get("parent_id")
    if parent is not None and (
        isinstance(parent, bool) or not isinstance(parent, int) or parent < 0
    ):
        raise LaunchReceiptError("launch state parent ID is invalid")
    order = state.get("tab_order")
    if isinstance(order, bool) or not isinstance(order, int) or order < 0:
        raise LaunchReceiptError("launch state tab order is invalid")
    culture = state.get("culture_code")
    if culture is not None and not isinstance(culture, str):
        raise LaunchReceiptError("launch state culture is invalid")


def _sha256_file(path: Path, label: str) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise LaunchReceiptError(f"{label} is unavailable: {exc}") from exc


def _sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


__all__ = [
    "LAUNCH_JOURNAL_ROOT",
    "LAUNCH_PLAN_PATH",
    "LAUNCH_RESULT_PATH",
    "LAUNCH_REVIEW_PATH",
    "LaunchReceiptError",
    "current_launch_review",
    "current_launch_review_fingerprint",
    "finalize_launch_payload",
    "fingerprint_launch_payload",
    "load_launch_payload",
]
