"""Pure validation for adopted, fingerprint-bound publish review receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from vanjaro_cli.project.models import ProjectManifest, ProjectStage, StageStatus
from vanjaro_cli.project.workspace import artifact_path, fingerprint_files
from vanjaro_cli.reliability.contracts import PUBLISH_REVIEW_SCHEMA
from vanjaro_cli.reliability.artifacts import ArtifactContractError, load_strict_json


PUBLISH_REVIEW_PATH = Path("qa/publish-review.json")
PUBLISH_RESULT_PATH = Path("qa/publish-result.json")
PUBLISH_JOURNAL_ROOT = Path("history/publish")


class PublishReceiptError(ValueError):
    """Raised when local publication authority is missing, stale, or malformed."""


def fingerprint_publish_payload(value: Mapping[str, Any]) -> str:
    """Fingerprint strict canonical JSON without accepting non-finite values."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def finalize_publish_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached receipt with a self-fingerprint."""

    result = dict(value)
    result.pop("fingerprint", None)
    result["fingerprint"] = fingerprint_publish_payload(result)
    return result


def load_publish_review(path: Path) -> dict[str, Any]:
    """Load one strict JSON-object receipt and verify its self-fingerprint."""

    try:
        value = load_strict_json(path)
    except ArtifactContractError as exc:
        if not path.exists():
            raise PublishReceiptError(f"publish review receipt is missing: {path}") from exc
        raise PublishReceiptError(f"publish review receipt is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise PublishReceiptError("publish review receipt must contain a JSON object")
    supplied = value.get("fingerprint")
    unsigned = dict(value)
    unsigned.pop("fingerprint", None)
    expected = fingerprint_publish_payload(unsigned)
    if supplied != expected:
        raise PublishReceiptError("publish review receipt fingerprint does not match its payload")
    return value


def current_publish_review(
    root: Path, manifest: ProjectManifest
) -> dict[str, Any]:
    """Validate the adopted receipt against current local publish evidence."""

    metadata = manifest.metadata.get("publish_review")
    if not isinstance(metadata, dict):
        raise PublishReceiptError(
            "no publish review is adopted; run `vanjaro project publish prepare`"
        )
    expected_path = PUBLISH_REVIEW_PATH.as_posix()
    if metadata.get("path") != expected_path:
        raise PublishReceiptError("adopted publish review path is invalid")
    receipt = load_publish_review(artifact_path(root, expected_path))
    fingerprint = receipt["fingerprint"]
    if metadata.get("fingerprint") != fingerprint:
        raise PublishReceiptError("adopted publish review fingerprint is stale")
    if receipt.get("schema_version") != PUBLISH_REVIEW_SCHEMA:
        raise PublishReceiptError("unsupported publish review schema version")
    if receipt.get("project_id") != manifest.project.id:
        raise PublishReceiptError("publish review belongs to a different project")
    if receipt.get("target") != manifest.target.model_dump(mode="json"):
        raise PublishReceiptError("publish review target no longer matches project.json")

    verify = manifest.stages[ProjectStage.VERIFY]
    if verify.status != StageStatus.COMPLETED or verify.output_fingerprint is None:
        raise PublishReceiptError("verify stage is not currently completed")
    if receipt.get("verification_fingerprint") != verify.output_fingerprint:
        raise PublishReceiptError("publish review verification fingerprint is stale")
    try:
        observed_verify = fingerprint_files(
            root, tuple(Path(value) for value in verify.artifacts)
        )
    except (OSError, ValueError) as exc:
        raise PublishReceiptError(f"verify evidence cannot be fingerprinted: {exc}") from exc
    if observed_verify != verify.output_fingerprint:
        raise PublishReceiptError("verify artifacts changed after completion")

    evidence = receipt.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise PublishReceiptError("publish review contains no evidence digests")
    for item in evidence:
        if not isinstance(item, dict):
            raise PublishReceiptError("publish review evidence entry is invalid")
        relative = item.get("path")
        digest = item.get("sha256")
        if not isinstance(relative, str) or not _is_sha256(digest):
            raise PublishReceiptError("publish review evidence digest is invalid")
        path = artifact_path(root, relative)
        try:
            observed = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise PublishReceiptError(
                f"publish review evidence is unavailable: {relative}: {exc}"
            ) from exc
        if observed != digest:
            raise PublishReceiptError(
                f"publish review evidence changed after preparation: {relative}"
            )
    _require_publish_ready_handoff(root, receipt)
    _require_action_contract(receipt)
    return receipt


def current_publish_review_fingerprint(
    root: Path, manifest: ProjectManifest
) -> str:
    return str(current_publish_review(root, manifest)["fingerprint"])


def _require_publish_ready_handoff(
    root: Path, receipt: Mapping[str, Any]
) -> None:
    handoff_path = artifact_path(root, "qa/maintenance-scorecard.json")
    try:
        scorecard = load_strict_json(handoff_path)
    except ArtifactContractError as exc:
        raise PublishReceiptError(f"maintenance scorecard is unreadable: {exc}") from exc
    if not isinstance(scorecard, dict) or scorecard.get("status") != "publish_ready":
        raise PublishReceiptError("maintenance scorecard is not publish-ready")
    supplied = scorecard.get("fingerprint")
    unsigned = dict(scorecard)
    unsigned.pop("fingerprint", None)
    if supplied != fingerprint_publish_payload(unsigned):
        raise PublishReceiptError("maintenance scorecard fingerprint is invalid")
    if receipt.get("handoff_fingerprint") != supplied:
        raise PublishReceiptError("publish review references a different handoff")


def _require_action_contract(receipt: Mapping[str, Any]) -> None:
    if receipt.get("mode") != "hidden_content":
        raise PublishReceiptError("unsupported publish review mode")
    actions = receipt.get("actions")
    if not isinstance(actions, list) or not actions:
        raise PublishReceiptError("publish review contains no actions")
    keys: set[tuple[str, str]] = set()
    seen_page = False
    project_id = receipt.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise PublishReceiptError("publish review project identity is invalid")
    for action in actions:
        if not isinstance(action, dict):
            raise PublishReceiptError("publish action must be a JSON object")
        kind = action.get("object_type")
        identity = action.get("object_id")
        version = action.get("version")
        digest = action.get("desired_hash")
        prepared_published = action.get("prepared_published")
        if kind not in {"global_block", "page"} or not isinstance(identity, str):
            raise PublishReceiptError("publish action identity is invalid")
        if action.get("project_id") != project_id:
            raise PublishReceiptError("publish action project ownership is invalid")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise PublishReceiptError("publish action version is invalid")
        if not _is_sha256(digest):
            raise PublishReceiptError("publish action desired hash is invalid")
        if not isinstance(prepared_published, bool):
            raise PublishReceiptError("publish action prepared state is invalid")
        key = (kind, identity)
        if key in keys:
            raise PublishReceiptError(f"duplicate publish action: {kind} {identity}")
        keys.add(key)
        if kind == "page":
            if not isinstance(action.get("page_key"), str) or not action["page_key"]:
                raise PublishReceiptError("publish page ownership key is invalid")
            seen_page = True
        else:
            if not isinstance(action.get("global_kind"), str) or not action["global_kind"]:
                raise PublishReceiptError("publish global kind is invalid")
            if seen_page:
                raise PublishReceiptError("global blocks must precede pages in publish order")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "PUBLISH_JOURNAL_ROOT",
    "PUBLISH_RESULT_PATH",
    "PUBLISH_REVIEW_PATH",
    "PublishReceiptError",
    "current_publish_review",
    "current_publish_review_fingerprint",
    "finalize_publish_receipt",
    "fingerprint_publish_payload",
    "load_publish_review",
]
