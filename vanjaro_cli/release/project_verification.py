"""Project readiness, quality, effort, and trusted live evidence verification."""

from __future__ import annotations

import hashlib
import math
from datetime import date
from pathlib import Path
from typing import Callable

from pydantic import ValidationError

from vanjaro_cli.project import (
    ApprovalStatus,
    ProjectManifest,
    ProjectStage,
    StageStatus,
    fingerprint_files,
    load_manifest,
)
from vanjaro_cli.project.publish_receipt import fingerprint_publish_payload
from vanjaro_cli.release.gates import (
    CAPTURE_DIMENSIONS as _CAPTURE_DIMENSIONS,
    PROJECT_QUALITY_THRESHOLDS as _PROJECT_QUALITY_THRESHOLDS,
    SOURCE_KINDS as _SOURCE_KINDS,
    GateLedger as _GateLedger,
    ReleaseVerificationError,
)
from vanjaro_cli.release.models import (
    LiveAttestationReceipt,
    LiveEvidenceReceipt,
    ProjectEffortEvidence,
    ProjectEvidence,
    ProjectQualityEvidence,
    ProjectReleaseReceipt,
)
from vanjaro_cli.release.paths import (
    _json_object,
    _read_png_dimensions,
    _resolve_repository_path,
    _verify_reference,
)
from vanjaro_cli.reliability.artifacts import ArtifactContractError, load_strict_json

TrustedLiveVerifier = Callable[[LiveEvidenceReceipt], bool | str | tuple[str, ...]]


def _verify_project(
    evidence: ProjectEvidence,
    *,
    candidate_id: str,
    evaluation_date: date,
    root: Path,
    ledger: _GateLedger,
    trusted_live_verifier: TrustedLiveVerifier | None,
) -> dict[str, float] | None:
    source_kind = evidence.source_kind
    ready_gate = f"project-ready-{source_kind}"
    effort_gate = f"effort-reduction-{source_kind}"
    live_gate = f"live-smoke-{source_kind}"
    reference_paths: dict[str, Path] = {}
    reference_reasons: list[str] = []
    for label, reference in (
        ("receipt", evidence.receipt),
        ("quality", evidence.quality_evidence),
        ("effort", evidence.effort_evidence),
    ):
        ok, reason, path = _verify_reference(root, reference)
        if not ok or path is None:
            reference_reasons.append(f"{label}-{reason}")
        else:
            reference_paths[label] = path
    if reference_reasons:
        ledger.set(ready_gate, "failed", *reference_reasons)
        ledger.set(effort_gate, "incomplete", "project-receipt-unavailable")
        ledger.set(live_gate, "incomplete", "project-receipt-unavailable")
        return None
    try:
        receipt = ProjectReleaseReceipt.model_validate(
            load_strict_json(reference_paths["receipt"])
        )
        quality_evidence = ProjectQualityEvidence.model_validate(
            load_strict_json(reference_paths["quality"])
        )
        effort_evidence = ProjectEffortEvidence.model_validate(
            load_strict_json(reference_paths["effort"])
        )
    except (ArtifactContractError, ValidationError):
        ledger.set(ready_gate, "failed", "invalid-project-receipt")
        ledger.set(effort_gate, "incomplete", "project-receipt-unavailable")
        ledger.set(live_gate, "incomplete", "project-receipt-unavailable")
        return None
    if (
        receipt.source_kind != source_kind
        or quality_evidence.source_kind != source_kind
        or effort_evidence.source_kind != source_kind
    ):
        ledger.set(ready_gate, "failed", "project-source-kind-mismatch")
        ledger.set(effort_gate, "incomplete", "project-receipt-mismatch")
        ledger.set(live_gate, "incomplete", "project-receipt-mismatch")
        return None
    workspace = _resolve_repository_path(
        root, evidence.workspace, expected_type="directory"
    )
    if workspace is None:
        ledger.set(ready_gate, "failed", "workspace-unavailable")
        ledger.set(effort_gate, "incomplete", "workspace-unavailable")
        ledger.set(live_gate, "incomplete", "workspace-unavailable")
        return None
    manifest_path = _resolve_repository_path(
        root, f"{evidence.workspace}/project.json", expected_type="file"
    )
    if manifest_path is None:
        ledger.set(ready_gate, "failed", "project-manifest-invalid")
        ledger.set(effort_gate, "incomplete", "project-manifest-invalid")
        ledger.set(live_gate, "incomplete", "project-manifest-invalid")
        return None
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = load_manifest(workspace)
    except (OSError, ValueError):
        ledger.set(ready_gate, "failed", "project-manifest-invalid")
        ledger.set(effort_gate, "incomplete", "project-manifest-invalid")
        ledger.set(live_gate, "incomplete", "project-manifest-invalid")
        return None
    ready_reasons: list[str] = []
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if (
        receipt.candidate_id != candidate_id
        or quality_evidence.candidate_id != candidate_id
        or effort_evidence.candidate_id != candidate_id
    ):
        ready_reasons.append("release-candidate-mismatch")
    if (
        receipt.project_id != manifest.project.id
        or quality_evidence.project_id != manifest.project.id
        or effort_evidence.project_id != manifest.project.id
        or receipt.project_manifest_sha256 != manifest_digest
    ):
        ready_reasons.append("project-manifest-mismatch")
    if receipt.quality_evidence_sha256 != evidence.quality_evidence.sha256:
        ready_reasons.append("quality-evidence-mismatch")
    if receipt.effort_evidence_sha256 != evidence.effort_evidence.sha256:
        ready_reasons.append("effort-evidence-mismatch")
    if not any(source.kind.value == source_kind for source in manifest.sources):
        ready_reasons.append("project-source-kind-absent")
    if any(
        record.status not in {StageStatus.COMPLETED, StageStatus.SKIPPED}
        for record in manifest.stages.values()
    ):
        ready_reasons.append("project-stages-incomplete")
    for required_stage in (
        ProjectStage.VERIFY,
        ProjectStage.PUBLISH,
        ProjectStage.LAUNCH,
    ):
        if manifest.stages[required_stage].status != StageStatus.COMPLETED:
            ready_reasons.append(f"required-stage-not-completed-{required_stage.value}")
    if any(item.status == ApprovalStatus.PENDING for item in manifest.approvals):
        ready_reasons.append("project-approval-pending")
    for stage, record in manifest.stages.items():
        if (
            stage == ProjectStage.INTAKE
            or record.status != StageStatus.COMPLETED
            or not record.artifacts
        ):
            continue
        artifact_paths: list[Path] = []
        for item in record.artifacts:
            artifact = _resolve_repository_path(
                root, f"{evidence.workspace}/{item}", expected_type="file"
            )
            if artifact is None:
                ready_reasons.append(f"stage-artifacts-unavailable-{stage.value}")
                break
            artifact_paths.append(artifact.relative_to(workspace))
        else:
            try:
                observed = fingerprint_files(workspace, tuple(artifact_paths))
            except (OSError, ValueError):
                ready_reasons.append(f"stage-artifacts-unavailable-{stage.value}")
                continue
            if observed != record.output_fingerprint:
                ready_reasons.append(f"stage-artifacts-stale-{stage.value}")
        if len(artifact_paths) != len(record.artifacts):
            continue
    scorecard_path = _resolve_repository_path(
        root,
        f"{evidence.workspace}/qa/maintenance-scorecard.json",
        expected_type="file",
    )
    try:
        if scorecard_path is None:
            raise OSError("unsafe maintenance scorecard path")
        scorecard_bytes = scorecard_path.read_bytes()
        scorecard = _json_object(scorecard_path)
    except (OSError, ArtifactContractError, ReleaseVerificationError):
        ready_reasons.append("maintenance-scorecard-unavailable")
        scorecard = {}
        scorecard_bytes = b""
    if hashlib.sha256(scorecard_bytes).hexdigest() != receipt.maintenance_scorecard_sha256:
        ready_reasons.append("maintenance-scorecard-mismatch")
    if scorecard.get("status") != "publish_ready":
        ready_reasons.append("maintenance-scorecard-not-ready")
    supplied = scorecard.get("fingerprint")
    unsigned = dict(scorecard)
    unsigned.pop("fingerprint", None)
    if supplied != fingerprint_publish_payload(unsigned):
        ready_reasons.append("maintenance-scorecard-fingerprint-invalid")
    ledger.set(
        ready_gate,
        "failed" if ready_reasons else "passed",
        *(ready_reasons or ("project-evidence-current",)),
        evidence=(
            evidence.receipt.sha256,
            evidence.quality_evidence.sha256,
            evidence.effort_evidence.sha256,
            manifest_digest,
        ),
    )

    effort_reasons: list[str] = []
    if receipt.effort_evidence_sha256 != evidence.effort_evidence.sha256:
        effort_reasons.append("effort-evidence-mismatch")
    if (
        receipt.candidate_id != candidate_id
        or effort_evidence.candidate_id != candidate_id
        or effort_evidence.project_id != manifest.project.id
    ):
        effort_reasons.append("effort-project-mismatch")
    effort_digests = [evidence.effort_evidence.sha256]
    for label, reference in (
        ("measurement-protocol", effort_evidence.measurement_protocol),
        ("quality-policy", effort_evidence.quality_policy),
    ):
        reference_ok, reference_reason, _ = _verify_reference(root, reference)
        if not reference_ok:
            effort_reasons.append(f"{label}-{reference_reason}")
        else:
            effort_digests.append(reference.sha256)
    baseline_minutes = sum(item.minutes for item in effort_evidence.baseline_sessions)
    current_minutes = sum(item.minutes for item in effort_evidence.current_sessions)
    if not math.isfinite(baseline_minutes) or not math.isfinite(current_minutes):
        effort_reasons.append("effort-aggregate-non-finite")
        reduction = float("-inf")
    else:
        reduction = (baseline_minutes - current_minutes) / baseline_minutes
        if not math.isfinite(reduction):
            effort_reasons.append("effort-reduction-non-finite")
    if effort_reasons:
        ledger.set(effort_gate, "failed", *effort_reasons)
    elif reduction < 0.60:
        ledger.set(effort_gate, "failed", "reduction-below-60-percent")
    else:
        ledger.set(
            effort_gate,
            "passed",
            "reduction-threshold-met",
            evidence=tuple(effort_digests),
        )

    _verify_live_receipt(
        evidence,
        candidate_id=candidate_id,
        receipt=receipt,
        manifest=manifest,
        manifest_digest=manifest_digest,
        evaluation_date=evaluation_date,
        root=root,
        ledger=ledger,
        trusted_live_verifier=trusted_live_verifier,
    )
    quality = {
        name: item.numerator / item.denominator
        for name, item in quality_evidence.quality
    }
    if any(
        reason in ready_reasons
        for reason in (
            "release-candidate-mismatch",
            "project-manifest-mismatch",
            "quality-evidence-mismatch",
        )
    ):
        return None
    return quality


def _verify_live_receipt(
    evidence: ProjectEvidence,
    *,
    candidate_id: str,
    receipt: ProjectReleaseReceipt,
    manifest: ProjectManifest,
    manifest_digest: str,
    evaluation_date: date,
    root: Path,
    ledger: _GateLedger,
    trusted_live_verifier: TrustedLiveVerifier | None,
) -> None:
    gate_id = f"live-smoke-{evidence.source_kind}"
    ok, reason, path = _verify_reference(root, evidence.live_receipt)
    if not ok or path is None:
        ledger.set(gate_id, "failed", reason)
        return
    try:
        live = LiveEvidenceReceipt.model_validate(load_strict_json(path))
    except (ArtifactContractError, ValidationError):
        ledger.set(gate_id, "failed", "invalid-live-receipt")
        return
    reasons: list[str] = []
    if live.candidate_id != candidate_id:
        reasons.append("live-candidate-mismatch")
    if live.project_id != receipt.project_id or live.source_kind != evidence.source_kind:
        reasons.append("live-project-mismatch")
    if live.project_manifest_sha256 != manifest_digest:
        reasons.append("live-project-fingerprint-stale")
    if (
        live.valid_through < evaluation_date
        or live.observed_at.date() > evaluation_date
    ):
        reasons.append("live-receipt-stale")
    if not live.cleanup_restored:
        reasons.append("live-cleanup-not-restored")
    if any(item.status != "passed" for item in live.smoke_checks):
        reasons.append("live-smoke-failure")
    if (
        manifest.target.expected_portal_id is not None
        and live.portal.portal_id != manifest.target.expected_portal_id
    ):
        reasons.append("live-portal-id-mismatch")
    if (
        manifest.target.expected_base_url is not None
        and live.portal.base_url != manifest.target.expected_base_url
    ):
        reasons.append("live-base-url-mismatch")
    publish_fingerprint = manifest.stages[ProjectStage.PUBLISH].output_fingerprint
    launch_fingerprint = manifest.stages[ProjectStage.LAUNCH].output_fingerprint
    if live.publish_fingerprint != publish_fingerprint:
        reasons.append("live-publish-fingerprint-mismatch")
    if live.launch_fingerprint != launch_fingerprint:
        reasons.append("live-launch-fingerprint-mismatch")
    capture_digests: list[str] = []
    for breakpoint, expected_dimensions in _CAPTURE_DIMENSIONS.items():
        capture = live.captures[breakpoint]
        capture_ok, capture_reason, capture_path = _verify_reference(
            root, capture.artifact
        )
        if not capture_ok or capture_path is None:
            reasons.append(f"capture-{capture_reason}")
        else:
            capture_digests.append(capture.artifact.sha256)
            if (capture.width, capture.height) != expected_dimensions:
                reasons.append(f"capture-{breakpoint}-declared-dimensions-invalid")
            try:
                observed_dimensions = _read_png_dimensions(capture_path)
            except (OSError, ValueError):
                reasons.append(f"capture-{breakpoint}-invalid-png")
            else:
                if observed_dimensions != expected_dimensions:
                    reasons.append(f"capture-{breakpoint}-pixel-dimensions-invalid")

    attestation_ok, attestation_reason, attestation_path = _verify_reference(
        root, live.attestation
    )
    if not attestation_ok or attestation_path is None:
        reasons.append(f"attestation-{attestation_reason}")
    else:
        try:
            attestation = LiveAttestationReceipt.model_validate(
                load_strict_json(attestation_path)
            )
        except (ArtifactContractError, ValidationError):
            reasons.append("invalid-live-attestation")
        else:
            if (
                attestation.candidate_id != candidate_id
                or attestation.project_id != live.project_id
                or attestation.source_kind != live.source_kind
            ):
                reasons.append("live-attestation-project-mismatch")
            if attestation.portal != live.portal:
                reasons.append("live-attestation-portal-mismatch")
            if attestation.observed_at != live.observed_at:
                reasons.append("live-attestation-time-mismatch")
            expected_capture_digests = {
                name: capture.artifact.sha256
                for name, capture in live.captures.items()
            }
            if attestation.capture_sha256 != expected_capture_digests:
                reasons.append("live-attestation-capture-mismatch")
            capture_digests.append(live.attestation.sha256)
    if reasons:
        ledger.set(
            gate_id,
            "failed",
            *reasons,
            evidence=(evidence.live_receipt.sha256, *capture_digests),
        )
        return
    if trusted_live_verifier is None:
        ledger.set(
            gate_id,
            "incomplete",
            "trusted-live-verification-required",
            evidence=(evidence.live_receipt.sha256, *capture_digests),
        )
        return
    try:
        trusted_reasons = trusted_live_verifier(live)
        if trusted_reasons is True:
            normalized_reasons: tuple[str, ...] = ()
        elif trusted_reasons is False:
            normalized_reasons = ("trusted-live-verification-failed",)
        elif isinstance(trusted_reasons, str):
            normalized_reasons = (trusted_reasons,)
        elif isinstance(trusted_reasons, tuple):
            normalized_reasons = trusted_reasons
        else:
            normalized_reasons = ("trusted-live-verifier-invalid-result",)
        if any(not isinstance(item, str) or not item for item in normalized_reasons):
            normalized_reasons = ("trusted-live-verifier-invalid-result",)
    except Exception:
        normalized_reasons = ("trusted-live-verification-failed",)
    ledger.set(
        gate_id,
        "failed" if normalized_reasons else "passed",
        *(normalized_reasons or ("trusted-live-evidence-current",)),
        evidence=(evidence.live_receipt.sha256, *capture_digests),
    )


def _verify_project_quality(
    quality: list[dict[str, float]], ledger: _GateLedger
) -> None:
    for metric, threshold in _PROJECT_QUALITY_THRESHOLDS.items():
        gate_id = f"quality-{metric}"
        if len(quality) != len(_SOURCE_KINDS):
            ledger.set(gate_id, "incomplete", "three-project-evidence-missing")
            continue
        values = [item[metric] for item in quality]
        if min(values) < threshold:
            ledger.set(gate_id, "failed", "threshold-not-met")
        else:
            ledger.set(gate_id, "passed", "threshold-met")


__all__ = [
    "TrustedLiveVerifier",
    "_verify_live_receipt",
    "_verify_project",
    "_verify_project_quality",
]
