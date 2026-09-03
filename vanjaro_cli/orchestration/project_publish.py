"""Reviewed, resumable publication of project-owned hidden content."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

from vanjaro_cli.orchestration.portal_identity import verify_project_portal
from vanjaro_cli.orchestration.project_handoff_output import redact_handoff_text
from vanjaro_cli.orchestration.project_publish_state import (
    ProjectPublishError,
    adopt_publish_receipt,
    load_or_create_publish_journal,
    manifest_projection_fingerprint,
    publish_journal_path,
    publish_lock,
    read_publish_object,
    require_publish_approval,
    require_publish_records,
    write_publish_journal,
    write_publish_json,
)
from vanjaro_cli.portal.project_publication import (
    ProjectPublicationError,
    observe_publication_action,
    prepare_publication_actions,
    publication_state_matches,
    publish_publication_action,
)
from vanjaro_cli.project import (
    ProjectManifest,
    ProjectStage,
    StageContext,
    StageEngine,
    StageInputs,
    StageResult,
    StageStatus,
    fingerprint_files,
    load_manifest,
)
from vanjaro_cli.project.publish_receipt import (
    PUBLISH_RESULT_PATH,
    PUBLISH_REVIEW_PATH,
    PublishReceiptError,
    current_publish_review,
    finalize_publish_receipt,
    fingerprint_publish_payload,
)
from vanjaro_cli.reliability.contracts import (
    PUBLISH_RESULT_SCHEMA,
    PUBLISH_REVIEW_SCHEMA,
)


_EVIDENCE_PATHS = (
    Path("verify/draft-verification.json"),
    Path("build/global-page-manifest.json"),
    Path("build/global-block-manifest.json"),
    Path("qa/maintenance-scorecard.json"),
)
def prepare_project_publish(
    root: Path,
    *,
    dry_run: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """GET-only portal preflight and optional local receipt adoption."""

    workspace = root.expanduser().resolve()
    manifest = load_manifest(workspace)
    projection = manifest_projection_fingerprint(manifest)
    receipt = _build_review_receipt(workspace, manifest)
    if dry_run:
        return {
            "status": "ready_for_review",
            "dry_run": True,
            "portal_mutated": False,
            "workspace_mutated": False,
            "receipt": receipt,
        }
    with publish_lock(workspace, operation="prepare"):
        current = load_manifest(workspace)
        if manifest_projection_fingerprint(current) != projection:
            raise ProjectPublishError(
                "project_changed",
                "project inputs changed during publish preparation",
                "Rerun verification, handoff, and publish prepare.",
            )
        mutated = adopt_publish_receipt(
            workspace, current, receipt, now=(clock or _utc_now)()
        )
    return {
        "status": "ready_for_review",
        "dry_run": False,
        "portal_mutated": False,
        "workspace_mutated": mutated,
        "receipt": receipt,
    }


def apply_project_publish(
    root: Path,
    *,
    receipt_fingerprint: str,
    approval_id: str,
    confirmation: str,
    published_by: str,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Publish an approved receipt after exact action-time confirmation."""

    workspace = root.expanduser().resolve()
    if not published_by.strip():
        raise ProjectPublishError(
            "publisher_required", "publisher identity is empty", "Pass a nonempty --by value."
        )
    manifest, receipt, current_fingerprint = _authorized_publish_state(
        workspace,
        receipt_fingerprint=receipt_fingerprint,
        approval_id=approval_id,
        confirmation=confirmation,
    )
    with publish_lock(
        workspace,
        operation="apply",
        receipt_fingerprint=current_fingerprint,
    ):
        manifest, receipt, current_fingerprint = _authorized_publish_state(
            workspace,
            receipt_fingerprint=receipt_fingerprint,
            approval_id=approval_id,
            confirmation=confirmation,
        )
        journal_path = publish_journal_path(current_fingerprint)
        engine = StageEngine(workspace, clock=clock)
        execution = engine.execute(
            ProjectStage.PUBLISH,
            StageInputs(
                data={
                    "policy": "hidden-content-v1",
                    "receipt_fingerprint": current_fingerprint,
                },
                files=(PUBLISH_REVIEW_PATH,),
                approval_fingerprint=current_fingerprint,
            ),
            lambda context: _publish_stage(
                context,
                receipt=receipt,
                journal_path=journal_path,
                published_by=published_by.strip(),
                clock=clock or _utc_now,
            ),
        )
        if execution.status == "resumed":
            _reconcile_published_receipt(load_manifest(workspace), receipt)
        transaction_mutated = (
            _journal_recorded_mutation(workspace / journal_path)
            if execution.status == "completed"
            else False
        )
    return {
        "status": execution.status,
        "portal_mutated": transaction_mutated,
        "workspace_mutated": execution.status == "completed",
        "receipt_fingerprint": current_fingerprint,
        "execution": execution.as_dict(),
        "journal_path": str(workspace / journal_path),
        "result_path": str(workspace / PUBLISH_RESULT_PATH),
    }


def _build_review_receipt(
    root: Path, manifest: ProjectManifest
) -> dict[str, Any]:
    verify = manifest.stages[ProjectStage.VERIFY]
    if verify.status != StageStatus.COMPLETED or verify.output_fingerprint is None:
        raise ProjectPublishError(
            "verification_incomplete",
            "verify stage is not currently completed",
            "Run the project build through verify before preparing publication.",
        )
    try:
        observed_verify = fingerprint_files(
            root, tuple(Path(value) for value in verify.artifacts)
        )
    except Exception as exc:
        raise ProjectPublishError(
            "verification_stale",
            f"verify artifacts are unavailable: {exc}",
            "Rerun verify and the agency handoff.",
        ) from exc
    if observed_verify != verify.output_fingerprint:
        raise ProjectPublishError(
            "verification_stale",
            "verify artifacts changed after completion",
            "Rerun verify and the agency handoff.",
        )
    verification = read_publish_object(root / "verify/draft-verification.json")
    if verification.get("valid") is not True or verification.get("blocker_count") != 0:
        raise ProjectPublishError(
            "verification_blocked",
            "draft verification is not valid and blocker-free",
            "Resolve every verification blocker and rerun verify.",
        )
    scorecard = read_publish_object(root / "qa/maintenance-scorecard.json")
    if scorecard.get("status") != "publish_ready":
        raise ProjectPublishError(
            "handoff_not_ready",
            "maintenance scorecard is not publish-ready",
            "Run project handoff and resolve every failed or unavailable check.",
        )
    unsigned_scorecard = dict(scorecard)
    handoff_fingerprint = unsigned_scorecard.pop("fingerprint", None)
    if handoff_fingerprint != fingerprint_publish_payload(unsigned_scorecard):
        raise ProjectPublishError(
            "handoff_invalid",
            "maintenance scorecard fingerprint is invalid",
            "Regenerate the project handoff.",
        )
    page_manifest = read_publish_object(root / "build/global-page-manifest.json")
    global_manifest = read_publish_object(root / "build/global-block-manifest.json")
    pages = require_publish_records(page_manifest, "pages", "page manifest")
    globals_ = require_publish_records(global_manifest, "blocks", "global block manifest")
    client, verified = verify_project_portal(manifest)
    try:
        actions = prepare_publication_actions(
            client,
            project_id=manifest.project.id,
            page_records=pages,
            global_records=globals_,
        )
    except ProjectPublicationError as exc:
        raise ProjectPublishError(
            "portal_preflight_failed",
            str(exc),
            "Rerun verify and prepare after resolving the reported portal drift.",
        ) from exc
    evidence = [
        {
            "path": relative.as_posix(),
            "sha256": hashlib.sha256((root / relative).read_bytes()).hexdigest(),
        }
        for relative in _EVIDENCE_PATHS
    ]
    prepared_at = verify.completed_at.isoformat().replace("+00:00", "Z")
    return finalize_publish_receipt(
        {
            "schema_version": PUBLISH_REVIEW_SCHEMA,
            "prepared_at": prepared_at,
            "project_id": manifest.project.id,
            "mode": "hidden_content",
            "target": manifest.target.model_dump(mode="json"),
            "observed_portal": verified.as_dict(),
            "verification_fingerprint": verify.output_fingerprint,
            "handoff_fingerprint": handoff_fingerprint,
            "evidence": evidence,
            "actions": actions,
            "warnings": [
                "Pages remain hidden from navigation and retain agency draft names.",
                "Publication is externally observable and cannot be fully reversed.",
            ],
        }
    )


def _publish_stage(
    context: StageContext,
    *,
    receipt: Mapping[str, Any],
    journal_path: Path,
    published_by: str,
    clock: Callable[[], datetime],
) -> StageResult:
    try:
        current = current_publish_review(context.root, context.manifest)
    except PublishReceiptError as exc:
        raise _receipt_error(exc) from exc
    if current["fingerprint"] != receipt["fingerprint"]:
        raise ProjectPublishError(
            "receipt_changed",
            "publish review changed after stage authorization",
            "Stop and prepare a new reviewed receipt.",
        )
    client, verified = verify_project_portal(context.manifest)
    if verified.as_dict() != receipt.get("observed_portal"):
        raise ProjectPublishError(
            "portal_identity_changed",
            "live portal identity/version evidence changed after preparation",
            "Prepare and approve a new publish review.",
        )
    journal = load_or_create_publish_journal(
        context.root / journal_path,
        receipt=receipt,
        published_by=published_by,
        now=clock(),
    )
    try:
        _preflight_journal_actions(client, receipt, journal)
        for index, action in enumerate(receipt["actions"]):
            entry = journal["actions"][index]
            observed = observe_publication_action(client, action)
            if publication_state_matches(action, observed, published=True):
                entry.update({"status": "committed", "after": observed})
                write_publish_journal(context.root / journal_path, journal, now=clock())
                continue
            if not publication_state_matches(action, observed, published=False):
                raise ProjectPublicationError(
                    f"{action['object_type']} {action['object_id']} is neither the "
                    "receipted draft nor its exact published result"
                )
            entry.update({"status": "attempting", "before": observed})
            write_publish_journal(context.root / journal_path, journal, now=clock())
            after = publish_publication_action(client, action)
            entry.update({"status": "committed", "after": after})
            write_publish_journal(context.root / journal_path, journal, now=clock())
        final_observations = _require_all_published(client, receipt)
        for entry, observed in zip(
            journal["actions"], final_observations, strict=True
        ):
            entry.update({"status": "committed", "after": observed})
            write_publish_journal(context.root / journal_path, journal, now=clock())
    except ProjectPublishError as exc:
        journal["status"] = "interrupted"
        journal["error"] = redact_handoff_text(str(exc))
        write_publish_journal(context.root / journal_path, journal, now=clock())
        raise
    except Exception as exc:
        journal["status"] = "interrupted"
        journal["error"] = redact_handoff_text(str(exc))
        write_publish_journal(context.root / journal_path, journal, now=clock())
        raise ProjectPublishError(
            "portal_publish_interrupted",
            "portal publication was interrupted before whole-set verification completed",
            f"Review {journal_path.as_posix()} and retry the exact approved receipt.",
        ) from exc
    journal["status"] = "completed"
    journal["error"] = None
    write_publish_journal(context.root / journal_path, journal, now=clock())
    result = {
        "schema_version": PUBLISH_RESULT_SCHEMA,
        "status": "published_hidden_content",
        "receipt_fingerprint": receipt["fingerprint"],
        "project_id": receipt["project_id"],
        "target": receipt["target"],
        "published_by": published_by,
        "actions": [entry["after"] for entry in journal["actions"]],
        "warnings": receipt["warnings"],
    }
    write_publish_json(context.root / PUBLISH_RESULT_PATH, result)
    return StageResult(
        artifacts=(journal_path.as_posix(), PUBLISH_RESULT_PATH.as_posix()),
        message=(
            f"Published {len(result['actions'])} project-owned hidden content object(s) "
            f"for receipt {str(receipt['fingerprint'])[:12]}."
        ),
    )


def _preflight_journal_actions(
    client: object,
    receipt: Mapping[str, Any],
    journal: Mapping[str, Any],
) -> None:
    """Prove the complete transaction set before allowing its first POST."""

    entries = journal.get("actions")
    if not isinstance(entries, list) or len(entries) != len(receipt["actions"]):
        raise ProjectPublishError(
            "journal_invalid",
            "publish journal does not cover every receipted action",
            "Stop and restore the journal from trusted recovery evidence.",
        )
    for action, entry in zip(receipt["actions"], entries, strict=True):
        if not isinstance(entry, dict):
            raise ProjectPublishError(
                "journal_invalid", "publish journal entry is invalid", "Stop and review recovery evidence."
            )
        observed = observe_publication_action(client, action)
        prepared_published = action.get("prepared_published") is True
        if publication_state_matches(action, observed, published=False):
            if prepared_published:
                raise ProjectPublicationError(
                    f"pre-published {action['object_type']} {action['object_id']} is no longer published"
                )
            if entry.get("status") == "committed":
                raise ProjectPublicationError(
                    f"committed {action['object_type']} {action['object_id']} is no longer published"
                )
            continue
        allowed_published = {"attempting", "committed"}
        if prepared_published:
            allowed_published.add("preexisting")
        if publication_state_matches(action, observed, published=True) and entry.get(
            "status"
        ) in allowed_published:
            continue
        raise ProjectPublicationError(
            f"{action['object_type']} {action['object_id']} changed outside the receipted transaction"
        )


def _authorized_publish_state(
    workspace: Path,
    *,
    receipt_fingerprint: str,
    approval_id: str,
    confirmation: str,
) -> tuple[ProjectManifest, dict[str, Any], str]:
    """Perform every local authority check without writing to the workspace."""

    manifest = load_manifest(workspace)
    try:
        receipt = current_publish_review(workspace, manifest)
    except PublishReceiptError as exc:
        raise _receipt_error(exc) from exc
    current_fingerprint = str(receipt["fingerprint"])
    if receipt_fingerprint != current_fingerprint:
        raise ProjectPublishError(
            "receipt_mismatch",
            "accepted receipt fingerprint is not the currently adopted review",
            "Rerun prepare and accept the exact returned fingerprint.",
        )
    if confirmation != current_fingerprint:
        raise ProjectPublishError(
            "confirmation_mismatch",
            "action-time confirmation must equal the full receipt fingerprint",
            "Review the receipt and pass its exact fingerprint to --confirm-publish.",
        )
    require_publish_approval(manifest, approval_id, current_fingerprint)
    return manifest, receipt, current_fingerprint


def _reconcile_published_receipt(
    manifest: ProjectManifest, receipt: Mapping[str, Any]
) -> list[dict[str, Any]]:
    client, verified = verify_project_portal(manifest)
    if verified.as_dict() != receipt.get("observed_portal"):
        raise ProjectPublishError(
            "portal_identity_changed",
            "live portal identity/version evidence changed after preparation",
            "Prepare and approve a new publish review.",
        )
    try:
        return _require_all_published(client, receipt)
    except ProjectPublicationError as exc:
        raise ProjectPublishError(
            "published_state_drifted",
            str(exc),
            "Inspect the live object and prepare a new verified publish review.",
        ) from exc


def _require_all_published(
    client: object, receipt: Mapping[str, Any]
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for action in receipt["actions"]:
        observed = observe_publication_action(client, action)
        if not publication_state_matches(action, observed, published=True):
            raise ProjectPublicationError(
                f"{action['object_type']} {action['object_id']} is not the exact published result"
            )
        observations.append(observed)
    return observations


def _journal_recorded_mutation(path: Path) -> bool:
    journal = read_publish_object(path)
    entries = journal.get("actions")
    if not isinstance(entries, list):
        return False
    return any(
        isinstance(entry, dict)
        and isinstance(entry.get("before"), dict)
        and entry["before"].get("published") is False
        for entry in entries
    )


def _receipt_error(error: PublishReceiptError) -> ProjectPublishError:
    return ProjectPublishError(
        "receipt_invalid", str(error), "Prepare and approve a fresh publish review."
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "ProjectPublishError",
    "apply_project_publish",
    "prepare_project_publish",
]
