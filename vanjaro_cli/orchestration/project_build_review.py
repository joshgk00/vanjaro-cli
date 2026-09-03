"""Fingerprint-bound review and one-stage execution for project builds."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from vanjaro_cli.orchestration.project_build import (
    preserve_project_theme,
    preview_preserve_project_theme,
    preview_project_asset_stage,
    preview_project_global_stage,
    preview_project_library_stage,
    preview_project_page_stage,
    reconcile_project_global_stage,
    reconcile_project_page_stage,
    register_project_library_stage,
    upload_project_asset_stage,
)
from vanjaro_cli.orchestration.project_theme import (
    plan_project_theme_stage,
    preview_project_theme_stage,
)
from vanjaro_cli.orchestration.project_verify import (
    preview_project_drafts,
    verify_project_drafts,
)
from vanjaro_cli.project.build_receipt import finalize_build_receipt, is_sha256
from vanjaro_cli.project.build_transaction import (
    BuildTransactionError,
    begin_build_transaction,
    build_transaction_path,
    complete_build_transaction,
    fail_build_transaction,
    load_build_transaction,
    mark_build_transaction_attempting,
    require_build_transaction_binding,
)
from vanjaro_cli.project.models import ApprovalStatus, ProjectManifest, ProjectStage
from vanjaro_cli.project.publish_lock import publish_operation_lock
from vanjaro_cli.project.stage_engine import (
    STAGE_DEFINITIONS,
    StageContext,
    StageEngine,
    StageExecution,
    StageInputs,
    StageResult,
)
from vanjaro_cli.project.workspace import artifact_path, fingerprint_data, load_manifest


BUILD_REVIEW_CONTRACT = "1.0"


class ProjectBuildReviewError(ValueError):
    """Raised when reviewed build authority is missing, stale, or mismatched."""


@dataclass(frozen=True, slots=True)
class BuildStageSpec:
    stage: ProjectStage
    inputs: StageInputs
    operation: Callable[[StageContext], StageResult]
    preview: Callable[[Path, ProjectManifest], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class PreparedBuildReview:
    receipt: dict[str, Any]
    execution: StageExecution
    spec: BuildStageSpec
    manifest: ProjectManifest | None = None


def prepare_next_build_review(
    root: Path,
    *,
    theme_mode: str,
    through: str,
    page_mode: str,
    operator: str,
) -> PreparedBuildReview:
    """Return a deterministic receipt for exactly the next executable stage."""

    operator = operator.strip()
    if not operator:
        raise ProjectBuildReviewError("build review requires a non-empty --by operator")
    _validate_modes(theme_mode=theme_mode, through=through, page_mode=page_mode)
    engine = StageEngine(root)
    resumed_probes: list[dict[str, Any]] = []
    selected: tuple[ProjectManifest, BuildStageSpec, StageExecution, dict[str, Any]] | None = None
    for stage in build_stage_sequence(through):
        manifest = load_manifest(engine.root)
        spec = build_stage_spec(
            engine.root,
            manifest,
            stage=stage,
            theme_mode=theme_mode,
            page_mode=page_mode,
        )
        execution = engine.execute(stage, spec.inputs, spec.operation, dry_run=True)
        raw_preview = spec.preview(engine.root, manifest)
        if execution.action == "execute":
            selected = (manifest, spec, execution, raw_preview)
            break
        resumed_probes.append(
            {
                "stage": stage.value,
                "preview_fingerprint": fingerprint_data(raw_preview),
            }
        )
    if selected is None:
        raise ProjectBuildReviewError(
            "no executable build stage exists at or below the requested ceiling"
        )
    manifest, spec, execution, raw_preview = selected
    receipt = _receipt(
        engine.root,
        manifest=manifest,
        spec=spec,
        execution=execution,
        raw_preview=raw_preview,
        requested={
            "theme_mode": theme_mode,
            "through": through,
            "page_mode": page_mode,
            "operator": operator,
        },
        resumed_probes=resumed_probes,
    )
    return PreparedBuildReview(
        receipt=receipt,
        execution=execution,
        spec=spec,
        manifest=manifest.model_copy(deep=True),
    )


def apply_build_review(
    root: Path,
    *,
    reviewed_receipt: dict[str, Any],
    confirmation: str,
    operator: str,
    theme_mode: str,
    through: str,
    page_mode: str,
) -> StageExecution:
    """Revalidate and execute exactly one reviewed stage under the authority lock."""

    fingerprint = reviewed_receipt.get("fingerprint")
    if not is_sha256(confirmation) or confirmation != fingerprint:
        raise ProjectBuildReviewError(
            "--confirm-build must equal the full fingerprint from the reviewed receipt"
        )
    requested = reviewed_receipt.get("requested")
    if not isinstance(requested, dict) or requested.get("operator") != operator.strip():
        raise ProjectBuildReviewError("--by must match the operator bound to the review")
    if (
        requested.get("theme_mode") != theme_mode
        or requested.get("through") != through
        or requested.get("page_mode") != page_mode
    ):
        raise ProjectBuildReviewError(
            "build modes and ceiling must match the reviewed receipt"
        )
    existing = load_build_transaction(root, str(fingerprint))
    if existing is not None:
        require_build_transaction_binding(
            existing, receipt=reviewed_receipt, operator=operator
        )
        if existing["status"] == "completed":
            return _resume_completed_transaction(
                root,
                receipt=reviewed_receipt,
                theme_mode=theme_mode,
                page_mode=page_mode,
            )
        if existing["status"] == "applying":
            try:
                resumed = _resume_completed_transaction(
                    root,
                    receipt=reviewed_receipt,
                    theme_mode=theme_mode,
                    page_mode=page_mode,
                )
            except (ProjectBuildReviewError, ProjectStageError):
                raise ProjectBuildReviewError(
                    "an interrupted build transaction requires supervised recovery; "
                    f"inspect {build_transaction_path(str(fingerprint)).as_posix()}"
                ) from None
            complete_build_transaction(
                root, existing, execution=resumed.as_dict()
            )
            return resumed
        raise ProjectBuildReviewError(
            "the reviewed build transaction is marked recovery_required; "
            f"inspect {build_transaction_path(str(fingerprint)).as_posix()} and do not replay portal mutations"
        )
    current = prepare_next_build_review(
        root,
        theme_mode=theme_mode,
        through=through,
        page_mode=page_mode,
        operator=operator,
    )
    _require_same_receipt(reviewed_receipt, current.receipt)
    with publish_operation_lock(
        root,
        operation=f"build-{current.spec.stage.value}",
        receipt_fingerprint=str(fingerprint),
    ):
        locked = prepare_next_build_review(
            root,
            theme_mode=theme_mode,
            through=through,
            page_mode=page_mode,
            operator=operator,
        )
        _require_same_receipt(reviewed_receipt, locked.receipt)
        engine = StageEngine(root)
        if locked.manifest is None:
            raise ProjectBuildReviewError(
                "locked build review did not retain its manifest snapshot"
            )
        locked_manifest_fingerprint = fingerprint_data(
            locked.manifest.model_dump(mode="json")
        )
        transaction: dict[str, Any] | None = None

        def revalidate_stage_preview(current_manifest: ProjectManifest) -> None:
            nonlocal transaction
            observed = locked.spec.preview(engine.root, current_manifest)
            expected = _raw_preview_from_receipt(locked.receipt)
            if observed != expected:
                raise ProjectBuildReviewError(
                    "build stage preview changed immediately before execution; run --dry-run again"
                )
            transaction = begin_build_transaction(
                engine.root,
                receipt=locked.receipt,
                operator=operator,
            )
            mark_build_transaction_attempting(engine.root, transaction)

        try:
            execution = engine.execute(
                locked.spec.stage,
                locked.spec.inputs,
                locked.spec.operation,
                dry_run=False,
                expected_manifest_fingerprint=str(
                    locked_manifest_fingerprint
                ),
                expected_input_fingerprint=str(locked.receipt["input_fingerprint"]),
                pre_operation=revalidate_stage_preview,
            )
        except Exception as exc:
            if transaction is not None:
                try:
                    fail_build_transaction(
                        engine.root, transaction, error=exc
                    )
                except Exception as journal_exc:
                    if hasattr(exc, "add_note"):
                        exc.add_note(
                            "build transaction failure update also failed: "
                            f"{type(journal_exc).__name__}"
                        )
            raise
        assert transaction is not None
        complete_build_transaction(
            engine.root, transaction, execution=execution.as_dict()
        )
        return execution


def build_stage_sequence(through: str) -> tuple[ProjectStage, ...]:
    order = (
        ProjectStage.THEME,
        ProjectStage.ASSETS,
        ProjectStage.LIBRARY,
        ProjectStage.PAGES,
        ProjectStage.GLOBAL_BLOCKS,
        ProjectStage.VERIFY,
    )
    ceiling = {
        "theme": ProjectStage.THEME,
        "assets": ProjectStage.ASSETS,
        "library": ProjectStage.LIBRARY,
        "pages": ProjectStage.PAGES,
        "globals": ProjectStage.GLOBAL_BLOCKS,
        "verify": ProjectStage.VERIFY,
    }.get(through)
    if ceiling is None:
        raise ProjectBuildReviewError("unsupported build ceiling")
    return order[: order.index(ceiling) + 1]


def build_stage_spec(
    root: Path,
    manifest: ProjectManifest,
    *,
    stage: ProjectStage,
    theme_mode: str,
    page_mode: str,
) -> BuildStageSpec:
    """Centralize each stage's exact inputs, operation, and zero-write preview."""

    del root
    if stage == ProjectStage.THEME:
        return BuildStageSpec(
            stage,
            StageInputs(
                data={"theme_mode": theme_mode},
                files=tuple(
                    Path(value)
                    for value in manifest.stages[ProjectStage.PLAN].artifacts
                ),
            ),
            preserve_project_theme if theme_mode == "preserve" else plan_project_theme_stage,
            preview_preserve_project_theme
            if theme_mode == "preserve"
            else _preview_theme_plan,
        )
    if stage == ProjectStage.ASSETS:
        return BuildStageSpec(
            stage,
            StageInputs(
                data={"folder": f"Images/agency/{manifest.project.id}/"},
                files=(
                    Path("plans/resolved-design-document.json"),
                    Path("plans/library-plan.json"),
                ),
            ),
            upload_project_asset_stage,
            preview_project_asset_stage,
        )
    if stage == ProjectStage.LIBRARY:
        return BuildStageSpec(
            stage,
            StageInputs(
                data={"registration_policy": "reconcile-no-update-v1"},
                files=(
                    Path("build/library-plan.json"),
                    Path("build/asset-manifest.json"),
                ),
            ),
            register_project_library_stage,
            preview_project_library_stage,
        )
    if stage == ProjectStage.PAGES:
        return BuildStageSpec(
            stage,
            StageInputs(
                data={"page_mode": page_mode},
                files=(
                    Path("build/design-document.json"),
                    Path("build/composed-blocks.json"),
                    Path("build/asset-manifest.json"),
                    Path("plans/global-block-plan.json"),
                ),
            ),
            lambda context: reconcile_project_page_stage(
                context, isolated=page_mode == "isolated"
            ),
            lambda workspace, project: preview_project_page_stage(
                workspace, project, isolated=page_mode == "isolated"
            ),
        )
    if stage == ProjectStage.GLOBAL_BLOCKS:
        return BuildStageSpec(
            stage,
            StageInputs(
                data={"global_policy": "unpublished-v2-with-draft-wrappers"},
                files=(
                    Path("build/design-document.json"),
                    Path("plans/global-block-plan.json"),
                    Path("build/pages-desired.json"),
                    Path("build/page-manifest.json"),
                ),
            ),
            reconcile_project_global_stage,
            preview_project_global_stage,
        )
    if stage == ProjectStage.VERIFY:
        from vanjaro_cli.orchestration.project_fidelity import FIDELITY_EVIDENCE_PATH

        return BuildStageSpec(
            stage,
            StageInputs(
                data={"verification_policy": "draft-publish-gate-v1"},
                files=(
                    Path("build/design-document.json"),
                    Path("build/global-block-manifest.json"),
                    Path("build/global-page-manifest.json"),
                    Path("build/pages-with-globals-desired.json"),
                    Path(FIDELITY_EVIDENCE_PATH),
                ),
            ),
            verify_project_drafts,
            _preview_verify,
        )
    raise ProjectBuildReviewError(f"unsupported build stage: {stage.value}")


def _preview_theme_plan(root: Path, manifest: ProjectManifest) -> dict[str, Any]:
    result = preview_project_theme_stage(root, manifest)
    return {
        **result,
        "portal_actions": [],
        "local_writes": [
            "build/theme-plan.json",
            "build/theme-palette.json",
            "build/theme-result.json",
        ],
    }


def _preview_verify(root: Path, manifest: ProjectManifest) -> dict[str, Any]:
    result = preview_project_drafts(root, manifest)
    return {
        **result,
        "portal_actions": [],
        "local_writes": ["verify/draft-verification.json"],
    }


def _receipt(
    root: Path,
    *,
    manifest: ProjectManifest,
    spec: BuildStageSpec,
    execution: StageExecution,
    raw_preview: dict[str, Any],
    requested: dict[str, str],
    resumed_probes: list[dict[str, Any]],
) -> dict[str, Any]:
    observed = raw_preview.get("target")
    if not isinstance(observed, dict):
        raise ProjectBuildReviewError("stage preview did not verify a portal target")
    files = []
    for relative in spec.inputs.files:
        path = artifact_path(root, relative)
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ProjectBuildReviewError(
                f"cannot fingerprint build input {relative.as_posix()}: {exc}"
            ) from exc
        files.append({"path": relative.as_posix(), "sha256": digest})
    definition = STAGE_DEFINITIONS[spec.stage]
    dependencies = [
        {
            "stage": dependency.value,
            "status": manifest.stages[dependency].status.value,
            "output_fingerprint": manifest.stages[dependency].output_fingerprint,
        }
        for dependency in definition.dependencies
    ]
    approval = None
    if execution.approval_gate is not None:
        matches = [
            item
            for item in manifest.approvals
            if item.gate == execution.approval_gate
            and item.status == ApprovalStatus.APPROVED
            and item.fingerprint == execution.approval_fingerprint
        ]
        if len(matches) != 1:
            raise ProjectBuildReviewError("stage approval is not unique and current")
        item = matches[0]
        approval = {
            "id": item.id,
            "gate": item.gate.value,
            "status": item.status.value,
            "fingerprint": item.fingerprint,
        }
    details = {
        key: value
        for key, value in raw_preview.items()
        if key not in {"target", "portal_actions", "local_writes"}
    }
    return finalize_build_receipt(
        {
            "schema_version": "agency-build-review-v1",
            "contract_version": BUILD_REVIEW_CONTRACT,
            "project_id": manifest.project.id,
            "target": manifest.target.model_dump(mode="json"),
            "stage": spec.stage.value,
            "stage_contract_version": definition.contract_version,
            "action": execution.action,
            "attempt": execution.attempt,
            "requested": requested,
            "manifest_fingerprint": fingerprint_data(
                _manifest_projection(manifest)
            ),
            "dependencies": dependencies,
            "inputs": {"data": dict(spec.inputs.data), "files": files},
            "input_fingerprint": execution.input_fingerprint,
            "approval": approval,
            "observed_portal": observed,
            "preview": {
                "schema_version": "agency-build-stage-plan-v1",
                "stage": spec.stage.value,
                "upstream_probes": resumed_probes,
                "portal_actions": list(raw_preview.get("portal_actions", [])),
                "local_writes": list(raw_preview.get("local_writes", [])),
                "details": details,
            },
        }
    )


def _require_same_receipt(
    reviewed: dict[str, Any], current: dict[str, Any]
) -> None:
    if reviewed.get("fingerprint") != current.get("fingerprint") or reviewed != current:
        raise ProjectBuildReviewError(
            "build review is stale or belongs to a different project, target, stage, or action; run --dry-run again"
        )


def _raw_preview_from_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    preview = receipt.get("preview")
    if not isinstance(preview, dict) or not isinstance(preview.get("details"), dict):
        raise ProjectBuildReviewError("reviewed build receipt has no stage preview")
    return {
        **preview["details"],
        "target": receipt.get("observed_portal"),
        "portal_actions": list(preview.get("portal_actions", [])),
        "local_writes": list(preview.get("local_writes", [])),
    }


def _resume_completed_transaction(
    root: Path,
    *,
    receipt: dict[str, Any],
    theme_mode: str,
    page_mode: str,
) -> StageExecution:
    """Prove an exact completed transaction is still locally and live reusable."""

    try:
        stage = ProjectStage(str(receipt["stage"]))
    except ValueError as exc:
        raise ProjectBuildReviewError("build transaction stage is invalid") from exc
    manifest = load_manifest(root)
    spec = build_stage_spec(
        root,
        manifest,
        stage=stage,
        theme_mode=theme_mode,
        page_mode=page_mode,
    )
    execution = StageEngine(root).execute(
        stage, spec.inputs, spec.operation, dry_run=True
    )
    if (
        execution.action != "resume"
        or execution.input_fingerprint != receipt.get("input_fingerprint")
    ):
        raise ProjectBuildReviewError(
            "completed build transaction no longer matches local stage state"
        )
    preview = spec.preview(Path(root).expanduser().resolve(), manifest)
    if preview.get("target") != receipt.get("observed_portal"):
        raise ProjectBuildReviewError(
            "completed build transaction portal identity changed"
        )
    if _preview_mutates_portal(preview):
        raise ProjectBuildReviewError(
            "completed build transaction no longer matches live portal state"
        )
    if stage == ProjectStage.VERIFY:
        from vanjaro_cli.reliability import ArtifactContractError, load_strict_json

        try:
            recorded = load_strict_json(
                Path(root).expanduser().resolve()
                / "verify/draft-verification.json"
            )
        except ArtifactContractError as exc:
            raise ProjectBuildReviewError(
                "completed verification artifact is unreadable"
            ) from exc
        if recorded != preview:
            raise ProjectBuildReviewError(
                "completed verification evidence changed relative to live drafts"
            )
    return StageExecution(
        stage=execution.stage,
        action="resume",
        status="resumed",
        input_fingerprint=execution.input_fingerprint,
        output_fingerprint=execution.output_fingerprint,
        attempt=execution.attempt,
        artifacts=execution.artifacts,
        approval_gate=execution.approval_gate,
        approval_fingerprint=execution.approval_fingerprint,
    )


def _preview_mutates_portal(preview: dict[str, Any]) -> bool:
    for action in preview.get("portal_actions", []):
        if not isinstance(action, dict):
            continue
        operations = action.get("operations", [])
        if isinstance(operations, list) and any(
            isinstance(operation, dict)
            and operation.get("kind") == "portal_request"
            and str(operation.get("method", "")).upper()
            in {"POST", "POST_FORM", "PUT", "PATCH", "DELETE"}
            for operation in operations
        ):
            return True
        if str(action.get("method", "")).upper() in {
            "POST",
            "POST_FORM",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            return True
    return False


def _validate_modes(*, theme_mode: str, through: str, page_mode: str) -> None:
    if theme_mode not in {"preserve", "plan"}:
        raise ProjectBuildReviewError("unsupported theme mode")
    if page_mode != "isolated":
        raise ProjectBuildReviewError("unsupported page mode")
    build_stage_sequence(through)
    if theme_mode == "plan" and through != "theme":
        raise ProjectBuildReviewError(
            "theme-mode plan is artifact-only and can run only through theme"
        )


def _manifest_projection(manifest: ProjectManifest) -> dict[str, Any]:
    """Bind semantic build authority without timestamps or audit-history noise."""

    return {
        "schema_version": manifest.schema_version,
        "project_id": manifest.project.id,
        "target": manifest.target.model_dump(mode="json"),
        "agency_pack": manifest.agency_pack.model_dump(mode="json"),
        "sources": [source.model_dump(mode="json") for source in manifest.sources],
        "stages": {
            stage.value: {
                "status": record.status.value,
                "attempt": record.attempt,
                "input_fingerprint": record.input_fingerprint,
                "output_fingerprint": record.output_fingerprint,
                "artifacts": list(record.artifacts),
            }
            for stage, record in manifest.stages.items()
        },
    }


__all__ = [
    "BUILD_REVIEW_CONTRACT",
    "BuildStageSpec",
    "PreparedBuildReview",
    "ProjectBuildReviewError",
    "apply_build_review",
    "build_stage_sequence",
    "build_stage_spec",
    "prepare_next_build_review",
]
