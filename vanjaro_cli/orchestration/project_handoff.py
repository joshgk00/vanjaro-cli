"""Deterministic editor handoff and maintenance scorecard generation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from vanjaro_cli.orchestration.project_handoff_output import (
    HandoffOutputError,
    commit_handoff_outputs,
    redact_handoff_text,
    redact_handoff_value,
    render_handoff,
)
from vanjaro_cli.project import (
    ProjectStage,
    ProjectWorkspaceError,
    StageStatus,
    fingerprint_files,
    load_manifest,
)


SCORECARD_PATH = Path("qa/maintenance-scorecard.json")
HANDOFF_PATH = Path("qa/agency-handoff.md")
VERIFY_REPORT_PATH = Path("verify/draft-verification.json")
EVIDENCE_PATHS = (
    Path("project.json"),
    Path("plans/validation.json"),
    VERIFY_REPORT_PATH,
    Path("build/asset-manifest.json"),
    Path("build/block-manifest.json"),
    Path("build/global-page-manifest.json"),
    Path("build/global-block-manifest.json"),
)
EVIDENCE_OWNERS = {
    Path("plans/validation.json"): ProjectStage.PLAN,
    VERIFY_REPORT_PATH: ProjectStage.VERIFY,
    Path("build/asset-manifest.json"): ProjectStage.ASSETS,
    Path("build/block-manifest.json"): ProjectStage.LIBRARY,
    Path("build/global-page-manifest.json"): ProjectStage.GLOBAL_BLOCKS,
    Path("build/global-block-manifest.json"): ProjectStage.GLOBAL_BLOCKS,
}

_CHECKS = (
    ("plan_valid", "Composition plan is valid", 10),
    ("content_loss", "No planned visitor content is lost", 10),
    ("editable_coverage", "Editable content coverage", 15),
    ("native_components", "Native or agency-standard component ratio", 15),
    ("source_text", "Built source-text coverage", 15),
    ("action_urls", "All source actions have destinations", 10),
    ("verification", "Draft verification has no blockers", 25),
)

class ProjectHandoffError(ValueError):
    """Categorized failure to build a safe handoff from workspace evidence."""

    def __init__(self, code: str, message: str, recommended_action: str) -> None:
        self.code = code
        self.message = message
        self.recommended_action = recommended_action
        super().__init__(
            f"[{code}] {message} Recommended action: {recommended_action}"
        )


@dataclass(frozen=True, slots=True)
class ProjectHandoffResult:
    status: str
    score: int
    fingerprint: str
    scorecard_path: Path
    handoff_path: Path

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "score": self.score,
            "fingerprint": self.fingerprint,
            "scorecard_path": str(self.scorecard_path),
            "handoff_path": str(self.handoff_path),
        }


def generate_project_handoff(root: Path) -> ProjectHandoffResult:
    """Generate agency handoff artifacts without network or manifest mutation."""

    workspace = root.expanduser().resolve()
    try:
        manifest = load_manifest(workspace)
    except ProjectWorkspaceError as exc:
        raise ProjectHandoffError(
            "workspace_invalid",
            str(exc),
            "Repair or reinitialize the project workspace, then rerun handoff.",
        ) from exc

    verify_stage = manifest.stages[ProjectStage.VERIFY]
    if verify_stage.status != StageStatus.COMPLETED or verify_stage.completed_at is None:
        raise ProjectHandoffError(
            "verification_incomplete",
            "the verify stage is not completed",
            "Run `vanjaro project build <directory> --through verify` first.",
        )
    if VERIFY_REPORT_PATH.as_posix() not in {
        value.replace("\\", "/") for value in verify_stage.artifacts
    }:
        raise ProjectHandoffError(
            "verification_artifact_undeclared",
            f"verify did not declare {VERIFY_REPORT_PATH.as_posix()}",
            "Rerun the verify stage so its current report is fingerprint-bound.",
        )
    for evidence_path, owner in EVIDENCE_OWNERS.items():
        _require_current_stage_evidence(workspace, manifest, owner, evidence_path)

    inputs = {path.as_posix(): _read_object(workspace / path, path) for path in EVIDENCE_PATHS[1:]}
    validation = inputs["plans/validation.json"]
    verification = inputs[VERIFY_REPORT_PATH.as_posix()]
    assets = _require_records(inputs["build/asset-manifest.json"], "assets", "asset manifest")
    blocks = _require_records(inputs["build/block-manifest.json"], "blocks", "block manifest")
    pages = _require_records(inputs["build/global-page-manifest.json"], "pages", "page manifest")
    globals_ = _require_records(inputs["build/global-block-manifest.json"], "blocks", "global block manifest")
    _validate_target(manifest, verification)

    evidence = [
        {
            "path": path.as_posix(),
            "sha256": hashlib.sha256((workspace / path).read_bytes()).hexdigest(),
        }
        for path in EVIDENCE_PATHS
    ]
    checks = _build_checks(validation, verification)
    score = sum(int(check["earned_points"]) for check in checks)
    status = "publish_ready" if all(check["status"] == "pass" for check in checks) else "review_required"
    open_items = _open_items(validation, verification)
    source_kinds = Counter(source.kind.value for source in manifest.sources)

    scorecard: dict[str, Any] = {
        "schema_version": "agency-maintenance-scorecard-v1",
        "generated_at": verify_stage.completed_at.isoformat().replace("+00:00", "Z"),
        "project": {
            "id": manifest.project.id,
            "name": manifest.project.name,
        },
        "target": manifest.target.model_dump(mode="json"),
        "agency_pack": manifest.agency_pack.model_dump(mode="json"),
        "sources": {
            "count": len(manifest.sources),
            "kinds": dict(sorted(source_kinds.items())),
        },
        "inventory": {
            "asset_count": len(assets),
            "assets": _inventory(assets, ("asset_id", "status")),
            "library_block_count": len(blocks),
            "library_blocks": _inventory(blocks, ("name", "category", "type", "status")),
            "page_count": len(pages),
            "pages": _inventory(pages, ("page_id", "title", "path", "published", "status")),
            "global_block_count": len(globals_),
            "global_blocks": _inventory(globals_, ("kind", "name", "published", "status")),
        },
        "score": score,
        "maximum_score": 100,
        "status": status,
        "checks": checks,
        "open_items": open_items,
        "evidence": evidence,
    }
    scorecard = redact_handoff_value(scorecard)
    scorecard["fingerprint"] = _fingerprint(scorecard)
    json_text = json.dumps(
        scorecard, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
    ) + "\n"
    markdown = render_handoff(scorecard)
    try:
        commit_handoff_outputs(
            workspace / SCORECARD_PATH,
            json_text,
            workspace / HANDOFF_PATH,
            markdown,
        )
    except HandoffOutputError as exc:
        raise ProjectHandoffError(
            exc.code,
            str(exc),
            exc.recommended_action,
        ) from exc
    return ProjectHandoffResult(
        status=status,
        score=score,
        fingerprint=str(scorecard["fingerprint"]),
        scorecard_path=workspace / SCORECARD_PATH,
        handoff_path=workspace / HANDOFF_PATH,
    )


def _require_current_stage_evidence(
    workspace: Path,
    manifest: Any,
    stage: ProjectStage,
    required_path: Path,
) -> None:
    record = manifest.stages[stage]
    if record.status != StageStatus.COMPLETED:
        raise ProjectHandoffError(
            "evidence_stage_incomplete",
            f"{stage.value} is not completed for {required_path.as_posix()}",
            f"Rerun the {stage.value} stage before generating a handoff.",
        )
    declared = {value.replace("\\", "/") for value in record.artifacts}
    if required_path.as_posix() not in declared:
        raise ProjectHandoffError(
            "evidence_artifact_undeclared",
            f"{stage.value} did not declare {required_path.as_posix()}",
            f"Rerun the {stage.value} stage to recreate current evidence.",
        )
    try:
        observed = fingerprint_files(
            workspace,
            tuple(Path(value) for value in record.artifacts),
        )
    except ProjectWorkspaceError as exc:
        raise ProjectHandoffError(
            "evidence_missing",
            str(exc),
            f"Rerun the {stage.value} stage to recreate its declared evidence.",
        ) from exc
    if observed != record.output_fingerprint:
        raise ProjectHandoffError(
            "evidence_stale",
            f"{stage.value} evidence no longer matches its completed fingerprint",
            f"Rerun the {stage.value} stage before generating a handoff.",
        )


def _read_object(path: Path, relative: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda constant: _reject_json_constant(constant),
        )
    except FileNotFoundError as exc:
        raise ProjectHandoffError(
            "evidence_missing",
            f"required handoff evidence is missing: {relative.as_posix()}",
            "Complete the plan/build/verify workflow and rerun handoff.",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProjectHandoffError(
            "evidence_invalid",
            f"cannot read {relative.as_posix()}: {exc}",
            "Regenerate the named artifact from its owning project stage.",
        ) from exc
    if not isinstance(value, dict):
        raise ProjectHandoffError(
            "evidence_invalid",
            f"{relative.as_posix()} must contain a JSON object",
            "Regenerate the named artifact from its owning project stage.",
        )
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")


def _require_records(value: Mapping[str, Any], key: str, label: str) -> list[dict[str, Any]]:
    records = value.get(key)
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise ProjectHandoffError(
            "evidence_invalid",
            f"{label} must contain a {key!r} array of objects",
            "Rerun the build stage that owns this manifest.",
        )
    return records


def _validate_target(manifest: Any, verification: Mapping[str, Any]) -> None:
    target = verification.get("target")
    if not isinstance(target, dict) or target.get("profile") != manifest.target.profile:
        raise ProjectHandoffError(
            "verification_target_mismatch",
            "verification target profile does not match project.json",
            "Verify the explicitly pinned project target again.",
        )
    expected_id = manifest.target.expected_portal_id
    if expected_id is not None and target.get("portal_id") != expected_id:
        raise ProjectHandoffError(
            "verification_target_mismatch",
            "verification portal ID does not match the pinned project target",
            "Correct the target pin and rerun verification.",
        )
    expected_url = manifest.target.expected_base_url
    observed_url = target.get("base_url")
    if expected_url is not None and (
        not isinstance(observed_url, str)
        or observed_url.rstrip("/") != expected_url.rstrip("/")
    ):
        raise ProjectHandoffError(
            "verification_target_mismatch",
            "verification base URL does not match the pinned project target",
            "Correct the target pin and rerun verification.",
        )


def _build_checks(
    validation: Mapping[str, Any], verification: Mapping[str, Any]
) -> list[dict[str, Any]]:
    values: dict[str, tuple[object, object, bool | None]] = {
        "plan_valid": (validation.get("valid"), True, _bool_pass(validation.get("valid"), True)),
        "content_loss": (validation.get("content_loss_count"), 0, _count_pass(validation.get("content_loss_count"), 0)),
        "editable_coverage": (validation.get("editable_content_coverage"), 0.85, _ratio_pass(validation.get("editable_content_coverage"), 0.85)),
        "native_components": (validation.get("native_component_ratio"), 0.90, _ratio_pass(validation.get("native_component_ratio"), 0.90)),
        "source_text": (verification.get("source_text_coverage"), 0.95, _ratio_pass(verification.get("source_text_coverage"), 0.95)),
        "action_urls": (verification.get("missing_action_url_count"), 0, _count_pass(verification.get("missing_action_url_count"), 0)),
        "verification": (
            {"valid": verification.get("valid"), "blocker_count": verification.get("blocker_count")},
            {"valid": True, "blocker_count": 0},
            _verification_pass(verification),
        ),
    }
    checks: list[dict[str, Any]] = []
    for identifier, label, weight in _CHECKS:
        actual, required, passed = values[identifier]
        status = "unavailable" if passed is None else ("pass" if passed else "fail")
        checks.append(
            {
                "id": identifier,
                "label": label,
                "weight": weight,
                "earned_points": weight if passed else 0,
                "status": status,
                "actual": actual,
                "required": required,
            }
        )
    return checks


def _bool_pass(value: object, required: bool) -> bool | None:
    return value == required if isinstance(value, bool) else None


def _ratio_pass(value: object, required: float) -> bool | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        return None
    return value >= required


def _count_pass(value: object, required: int) -> bool | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value == required


def _verification_pass(value: Mapping[str, Any]) -> bool | None:
    valid = value.get("valid")
    blockers = value.get("blocker_count")
    if (
        not isinstance(valid, bool)
        or isinstance(blockers, bool)
        or not isinstance(blockers, int)
        or blockers < 0
    ):
        return None
    return valid and blockers == 0


def _open_items(
    validation: Mapping[str, Any], verification: Mapping[str, Any]
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    _append_messages(items, "plan", validation.get("issues"))
    losses = validation.get("content_losses")
    if isinstance(losses, dict):
        for section, fields in sorted(losses.items(), key=lambda item: str(item[0])):
            if isinstance(fields, list):
                for field in fields:
                    items.append(
                        {
                            "category": "content_loss",
                            "message": redact_handoff_text(f"{section}: {field}"),
                        }
                    )
    _append_messages(items, "blocker", verification.get("blockers"))
    _append_messages(items, "warning", verification.get("warnings"))
    return items


def _append_messages(
    target: list[dict[str, str]], category: str, values: object
) -> None:
    if not isinstance(values, list):
        return
    for value in values:
        if isinstance(value, str) and value.strip():
            target.append(
                {"category": category, "message": redact_handoff_text(value.strip())}
            )


def _inventory(records: Iterable[Mapping[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    result = [
        {
            field: record[field]
            for field in fields
            if field in record and isinstance(record[field], (str, int, bool))
        }
        for record in records
    ]
    return sorted(result, key=lambda item: json.dumps(item, sort_keys=True))


def _fingerprint(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "HANDOFF_PATH",
    "SCORECARD_PATH",
    "ProjectHandoffError",
    "ProjectHandoffResult",
    "generate_project_handoff",
]
