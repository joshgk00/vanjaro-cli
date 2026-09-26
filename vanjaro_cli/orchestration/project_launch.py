"""Reviewed, resumable promotion of published managed pages into live site state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from vanjaro_cli.orchestration.portal_identity import verify_project_portal
from vanjaro_cli.orchestration.project_handoff_output import redact_handoff_text
from vanjaro_cli.orchestration.project_fidelity import (
    ProjectFidelityError,
    evaluate_project_fidelity,
)
from vanjaro_cli.orchestration.project_launch_state import (
    ProjectLaunchStateError,
    adopt_launch_receipt,
    launch_journal_path,
    launch_lock,
    load_or_create_launch_journal,
    read_launch_journal,
    require_launch_approval,
    write_launch_journal,
    write_launch_json,
)
from vanjaro_cli.portal.project_launch import (
    ProjectLaunchError,
    apply_launch_preview,
    launch_state_matches,
    observe_launch_action,
    prepare_launch_preview,
)
from vanjaro_cli.project import (
    ProjectStage,
    StageContext,
    StageEngine,
    StageInputs,
    StageOperationError,
    StageResult,
    StageStatus,
    fingerprint_data,
    fingerprint_files,
    load_manifest,
)
from vanjaro_cli.project.launch_plan import LaunchPlan
from vanjaro_cli.project.launch_receipt import (
    LAUNCH_PLAN_PATH,
    LAUNCH_RESULT_PATH,
    LAUNCH_REVIEW_PATH,
    LaunchReceiptError,
    current_launch_review,
    finalize_launch_payload,
    load_launch_payload,
)
from vanjaro_cli.project.publish_receipt import (
    PUBLISH_RESULT_PATH,
    current_publish_review,
)
from vanjaro_cli.reliability.contracts import (
    LAUNCH_RESULT_SCHEMA,
    LAUNCH_REVIEW_SCHEMA,
)


class ProjectLaunchWorkflowError(ValueError):
    """Categorized launch workflow failure with safe operator recovery guidance."""

    def __init__(self, code: str, detail: str, recovery: str) -> None:
        self.code = code
        self.detail = detail
        self.recovery = recovery
        super().__init__(f"{code}: {detail}. Recovery: {recovery}")


def prepare_project_launch(
    root: Path,
    *,
    dry_run: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    workspace = root.expanduser().resolve()
    manifest = load_manifest(workspace)
    projection = _local_projection(manifest)
    receipt = _build_launch_receipt(workspace, manifest)
    if dry_run:
        return {
            "status": "ready_for_review",
            "dry_run": True,
            "portal_mutated": False,
            "workspace_mutated": False,
            "receipt": receipt,
        }
    with launch_lock(workspace, operation="prepare"):
        current = load_manifest(workspace)
        if _local_projection(current) != projection:
            raise ProjectLaunchWorkflowError(
                "project_changed",
                "project authority changed during launch preparation",
                "Rerun launch plan and prepare.",
            )
        mutated = adopt_launch_receipt(
            workspace, current, receipt, now=(clock or _utc_now)()
        )
    return {
        "status": "ready_for_review",
        "dry_run": False,
        "portal_mutated": False,
        "workspace_mutated": mutated,
        "receipt": receipt,
    }


def apply_project_launch(
    root: Path,
    *,
    receipt_fingerprint: str,
    approval_id: str,
    confirmation: str,
    home_confirmation: int | None,
    launched_by: str,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    workspace = root.expanduser().resolve()
    if not launched_by.strip():
        raise ProjectLaunchWorkflowError(
            "launcher_required", "launcher identity is empty", "Pass a nonempty --by value."
        )
    manifest, receipt, fingerprint = _authorized_launch_state(
        workspace,
        receipt_fingerprint=receipt_fingerprint,
        approval_id=approval_id,
        confirmation=confirmation,
        home_confirmation=home_confirmation,
    )
    with launch_lock(
        workspace, operation="apply", receipt_fingerprint=fingerprint
    ):
        manifest, receipt, fingerprint = _authorized_launch_state(
            workspace,
            receipt_fingerprint=receipt_fingerprint,
            approval_id=approval_id,
            confirmation=confirmation,
            home_confirmation=home_confirmation,
        )
        journal_path = launch_journal_path(fingerprint)
        try:
            execution = StageEngine(workspace, clock=clock).execute(
                ProjectStage.LAUNCH,
                StageInputs(
                    data={
                        "policy": "managed-launch-v1",
                        "receipt_fingerprint": fingerprint,
                    },
                    files=(LAUNCH_REVIEW_PATH,),
                    approval_fingerprint=fingerprint,
                ),
                lambda context: _launch_stage(
                    context,
                    receipt=receipt,
                    journal_path=journal_path,
                    launched_by=launched_by.strip(),
                    clock=clock or _utc_now,
                ),
            )
        except StageOperationError as exc:
            cause = exc.__cause__
            if isinstance(cause, ProjectLaunchWorkflowError):
                raise cause
            if isinstance(cause, ProjectLaunchStateError):
                raise ProjectLaunchWorkflowError(
                    "launch_journal_invalid",
                    str(cause),
                    f"Review {journal_path.as_posix()} before retrying.",
                ) from exc
            raise ProjectLaunchWorkflowError(
                "launch_stage_failed",
                redact_handoff_text(str(exc)),
                f"Review {journal_path.as_posix()} and the launch audit event.",
            ) from exc
        if execution.status == "resumed":
            _reconcile_launched_receipt(workspace, load_manifest(workspace), receipt)
        mutated = False
        path = workspace / journal_path
        if path.is_file():
            journal = json.loads(path.read_text(encoding="utf-8"))
            mutated = journal.get("batch_attempted") is True
    return {
        "status": execution.status,
        "portal_mutated": mutated,
        "workspace_mutated": execution.status == "completed",
        "receipt_fingerprint": fingerprint,
        "execution": execution.as_dict(),
        "journal_path": str(workspace / journal_path),
        "result_path": str(workspace / LAUNCH_RESULT_PATH),
    }


def _build_launch_receipt(root, manifest) -> dict[str, Any]:
    publish = manifest.stages[ProjectStage.PUBLISH]
    if publish.status != StageStatus.COMPLETED or publish.output_fingerprint is None:
        raise ProjectLaunchWorkflowError(
            "publication_incomplete",
            "hidden-content publication is not currently completed",
            "Complete and reconcile project publish before launch preparation.",
        )
    if (
        fingerprint_files(root, tuple(Path(item) for item in publish.artifacts))
        != publish.output_fingerprint
    ):
        raise ProjectLaunchWorkflowError(
            "publication_stale", "publish artifacts changed after completion", "Reconcile publication."
        )
    try:
        plan = LaunchPlan.model_validate(
            load_launch_payload(root / LAUNCH_PLAN_PATH, label="launch plan")
        )
        publish_review = current_publish_review(root, manifest)
        publish_result = _read_object(root / PUBLISH_RESULT_PATH)
    except (LaunchReceiptError, ValueError) as exc:
        raise ProjectLaunchWorkflowError(
            "launch_evidence_invalid", str(exc), "Regenerate the launch plan and reconcile publication."
        ) from exc
    if plan.project_id != manifest.project.id:
        raise ProjectLaunchWorkflowError(
            "launch_plan_project_mismatch",
            "launch plan belongs to a different project",
            "Regenerate the launch plan.",
        )
    for expected, relative, label in (
        (
            plan.design_document_sha256,
            Path("plans/resolved-design-document.json"),
            "resolved design",
        ),
        (
            plan.page_manifest_sha256,
            Path("build/global-page-manifest.json"),
            "managed page manifest",
        ),
    ):
        try:
            observed = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        except OSError as exc:
            raise ProjectLaunchWorkflowError(
                "launch_plan_source_missing",
                f"{label} is unavailable",
                "Regenerate the launch plan.",
            ) from exc
        if expected != observed:
            raise ProjectLaunchWorkflowError(
                "launch_plan_stale",
                f"{label} changed after launch planning",
                "Regenerate the launch plan.",
            )
    if publish_result.get("receipt_fingerprint") != publish_review.get("fingerprint"):
        raise ProjectLaunchWorkflowError(
            "publication_result_mismatch",
            "publish result is not for the adopted publish receipt",
            "Reconcile project publish before launch preparation.",
        )
    visual_fidelity_fingerprint = _require_passing_fidelity(root, manifest)
    try:
        client, verified = verify_project_portal(manifest)
    except Exception as exc:
        raise ProjectLaunchWorkflowError(
            "portal_launch_preflight_failed",
            redact_handoff_text(str(exc)),
            "Resolve portal identity/authentication and prepare a new launch review.",
        ) from exc
    try:
        preview = prepare_launch_preview(
            client,
            project_id=manifest.project.id,
            plan=plan,
            publish_actions=publish_review["actions"],
        )
    except ProjectLaunchError as exc:
        raise ProjectLaunchWorkflowError(
            "portal_launch_preflight_failed",
            str(exc),
            "Resolve portal drift/collisions and prepare a new launch review.",
        ) from exc
    except Exception as exc:
        raise ProjectLaunchWorkflowError(
            "portal_launch_preflight_failed",
            "launch preview request did not complete",
            "Check the local server logs, resolve transport/authentication, and prepare again.",
        ) from exc
    if preview["portal_id"] != verified.portal_id:
        raise ProjectLaunchWorkflowError(
            "portal_identity_changed",
            "launch preview returned a different portal ID",
            "Verify the target profile and prepare again.",
        )
    return finalize_launch_payload(
        {
            "schema_version": LAUNCH_REVIEW_SCHEMA,
            "prepared_at": publish.completed_at.isoformat().replace("+00:00", "Z"),
            "project_id": manifest.project.id,
            "target": manifest.target.model_dump(mode="json"),
            "observed_portal": verified.as_dict(),
            "launch_plan_fingerprint": plan.fingerprint,
            "publish_output_fingerprint": publish.output_fingerprint,
            "publish_receipt_fingerprint": publish_review["fingerprint"],
            "publish_result_sha256": hashlib.sha256((root / PUBLISH_RESULT_PATH).read_bytes()).hexdigest(),
            "visual_fidelity_fingerprint": visual_fidelity_fingerprint,
            "namespace_fingerprint": preview["namespace_fingerprint"],
            "actions": preview["actions"],
            "home": preview["home"],
            "warnings": preview["warnings"] + [
                "Launch changes public routes, navigation visibility, and optionally the portal home page.",
                "DNN tab-order values are preserved; managed sibling order was verified against the launch plan.",
                "Recovery reconciles the atomic batch as all-before or all-after; any mixed state stops for supervised recovery.",
            ],
        }
    )


def _launch_stage(
    context: StageContext,
    *,
    receipt: Mapping[str, Any],
    journal_path: Path,
    launched_by: str,
    clock: Callable[[], datetime],
) -> StageResult:
    client, verified = verify_project_portal(context.manifest)
    if verified.as_dict() != receipt.get("observed_portal"):
        raise ProjectLaunchWorkflowError(
            "portal_identity_changed", "portal identity changed after review", "Prepare a new launch review."
        )
    journal = load_or_create_launch_journal(
        context.root / journal_path,
        receipt=receipt,
        launched_by=launched_by,
        now=clock(),
    )
    try:
        observations = [observe_launch_action(client, action) for action in receipt["actions"]]
        before = _whole_state(receipt, observations, after=False)
        after = _whole_state(receipt, observations, after=True)
        if not before and not after:
            raise ProjectLaunchError(
                "live launch state is neither the exact reviewed before-state nor the intended result"
            )
        if before:
            for entry in journal["actions"]:
                entry.update({"status": "attempting", "after": None})
            journal["status"] = "applying"
            journal["batch_attempted"] = True
            write_launch_journal(context.root / journal_path, journal, now=clock())
            applied = apply_launch_preview(client, receipt)
            observations = applied["observations"]
            journal["apply_warnings"] = applied["warnings"]
        if not _whole_state(receipt, observations, after=True):
            raise ProjectLaunchError("launch batch did not produce the exact intended state")
        for entry, observed in zip(journal["actions"], observations, strict=True):
            entry.update({"status": "committed", "after": observed})
        final = [observe_launch_action(client, action) for action in receipt["actions"]]
        if not _whole_state(receipt, final, after=True, journal=journal):
            raise ProjectLaunchError("final whole-set launch readback drifted")
        for entry, observed in zip(journal["actions"], final, strict=True):
            entry["after"] = observed
    except Exception as exc:
        journal["status"] = "interrupted"
        journal["error"] = redact_handoff_text(str(exc))
        write_launch_journal(context.root / journal_path, journal, now=clock())
        raise ProjectLaunchWorkflowError(
            "portal_launch_interrupted",
            "portal launch was interrupted before whole-set verification completed",
            f"Review {journal_path.as_posix()} and retry the exact approved receipt.",
        ) from exc
    journal["status"] = "completed"
    journal["error"] = None
    write_launch_journal(context.root / journal_path, journal, now=clock())
    result = {
        "schema_version": LAUNCH_RESULT_SCHEMA,
        "status": "launched",
        "receipt_fingerprint": receipt["fingerprint"],
        "project_id": receipt["project_id"],
        "target": receipt["target"],
        "launched_by": launched_by,
        "actions": [entry["after"] for entry in journal["actions"]],
        "home": receipt["home"],
        "warnings": list(
            dict.fromkeys(receipt["warnings"] + journal.get("apply_warnings", []))
        ),
    }
    write_launch_json(context.root / LAUNCH_RESULT_PATH, result)
    return StageResult(
        artifacts=(journal_path.as_posix(), LAUNCH_RESULT_PATH.as_posix()),
        message=f"Launched {len(result['actions'])} managed page(s).",
    )


def _whole_state(receipt, observations, *, after: bool, journal=None) -> bool:
    if len(observations) != len(receipt["actions"]):
        return False
    expected_home = receipt["home"]["after_page_id" if after else "before_page_id"]
    for index, (action, observed) in enumerate(zip(receipt["actions"], observations, strict=True)):
        token = None
        if journal is not None and after:
            recorded = journal["actions"][index].get("after")
            token = recorded.get("metadata_token") if isinstance(recorded, Mapping) else None
        if not launch_state_matches(action, observed, after=after, exact_after_token=token):
            return False
        if observed.get("home_page_id") != expected_home:
            return False
    return True


def _reconcile_launched_receipt(root: Path, manifest, receipt) -> None:
    client, verified = verify_project_portal(manifest)
    if verified.as_dict() != receipt.get("observed_portal"):
        raise ProjectLaunchWorkflowError(
            "launched_state_drifted", "portal identity changed after launch", "Prepare a new review."
        )
    observations = [observe_launch_action(client, action) for action in receipt["actions"]]
    try:
        journal = read_launch_journal(
            root / launch_journal_path(receipt["fingerprint"]), receipt=receipt
        )
    except (OSError, ProjectLaunchStateError) as exc:
        raise ProjectLaunchWorkflowError(
            "launch_journal_invalid",
            str(exc),
            "Review the launch journal and prepare a new review if it cannot be recovered.",
        ) from exc
    if journal.get("status") != "completed" or not _whole_state(
        receipt, observations, after=True, journal=journal
    ):
        raise ProjectLaunchWorkflowError(
            "launched_state_drifted", "live launch state no longer matches the receipt", "Prepare a new review."
        )


def _authorized_launch_state(
    root,
    *,
    receipt_fingerprint,
    approval_id,
    confirmation,
    home_confirmation,
):
    manifest = load_manifest(root)
    try:
        receipt = current_launch_review(root, manifest)
    except LaunchReceiptError as exc:
        raise ProjectLaunchWorkflowError(
            "launch_receipt_invalid", str(exc), "Prepare and adopt a new launch review."
        ) from exc
    fingerprint = receipt["fingerprint"]
    if receipt_fingerprint != fingerprint or confirmation != fingerprint:
        raise ProjectLaunchWorkflowError(
            "confirmation_mismatch", "receipt or action-time confirmation does not match", "Use the full adopted launch fingerprint."
        )
    try:
        require_launch_approval(manifest, approval_id=approval_id, fingerprint=fingerprint)
    except ProjectLaunchStateError as exc:
        raise ProjectLaunchWorkflowError(
            "launch_approval_invalid", str(exc), "Approve the exact adopted launch review."
        ) from exc
    if not _launch_completed_for(root, manifest, fingerprint) and (
        _require_passing_fidelity(root, manifest) != receipt.get("visual_fidelity_fingerprint")
    ):
        raise ProjectLaunchWorkflowError(
            "visual_fidelity_stale",
            "capture evidence changed after launch preparation",
            "Prepare, review, and approve a new launch receipt.",
        )
    home = receipt["home"]
    changes_home = home["before_page_id"] != home["after_page_id"]
    if changes_home and home_confirmation != home["after_page_id"]:
        raise ProjectLaunchWorkflowError(
            "home_confirmation_mismatch", "home-page acknowledgement does not match", "Pass --confirm-home with the receipted page ID."
        )
    if not changes_home and home_confirmation is not None:
        raise ProjectLaunchWorkflowError(
            "unexpected_home_confirmation", "receipt does not change the home page", "Remove --confirm-home."
        )
    return manifest, receipt, fingerprint


def _require_passing_fidelity(root: Path, manifest) -> str:
    # Rendered fidelity can only be captured after hidden publication, so the
    # draft verify gate cannot require it; launch is the first visitor-facing step.
    try:
        report, blockers = evaluate_project_fidelity(root, manifest)
    except ProjectFidelityError as exc:
        report, blockers = {}, [str(exc)]
    if not blockers and report.get("legacy") is not False:
        blockers = ["launch requires per-page capture evidence from `vanjaro project capture`"]
    if blockers:
        raise ProjectLaunchWorkflowError(
            "visual_fidelity_failed",
            redact_handoff_text("; ".join(blockers)),
            "Run `vanjaro project capture` for every page and fix fidelity before launch.",
        )
    return fingerprint_data(report)


def _launch_completed_for(root: Path, manifest, fingerprint: str) -> bool:
    # Completed re-entry only reconciles; evidence recaptured after launch must
    # not turn that GET-only path into a stale-fidelity refusal.
    if manifest.stages[ProjectStage.LAUNCH].status != StageStatus.COMPLETED:
        return False
    result_path = root / LAUNCH_RESULT_PATH
    if not result_path.is_file():
        return False
    return _read_object(result_path).get("receipt_fingerprint") == fingerprint


def _local_projection(manifest) -> str:
    value = {
        "project_id": manifest.project.id,
        "target": manifest.target.model_dump(mode="json"),
        "publish": manifest.stages[ProjectStage.PUBLISH].model_dump(mode="json"),
        "launch_plan": manifest.metadata.get("launch_plan"),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "ProjectLaunchWorkflowError",
    "apply_project_launch",
    "prepare_project_launch",
]
