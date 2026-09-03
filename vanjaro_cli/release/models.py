"""Strict models for the aggregate agency release contract and receipts."""

from __future__ import annotations

from datetime import date, datetime
import math
import re
from typing import Literal, TypeAlias
from urllib.parse import urlsplit

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from vanjaro_cli.reliability.contracts import (
    CONTROL_EVIDENCE_SCHEMA,
    LIVE_ATTESTATION_SCHEMA,
    LIVE_EVIDENCE_SCHEMA,
    PROJECT_EFFORT_EVIDENCE_SCHEMA,
    PROJECT_QUALITY_EVIDENCE_SCHEMA,
    PROJECT_RELEASE_EVIDENCE_SCHEMA,
    RELEASE_AUDIT_SCHEMA,
    RELEASE_CONTRACT_SCHEMA,
    TEST_EVIDENCE_SCHEMA,
    TEST_POLICY_SCHEMA,
)


ReleaseSourceKind: TypeAlias = Literal["live_html", "figma", "image"]
GateStatus: TypeAlias = Literal["passed", "failed", "incomplete"]


class _ReleaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _relative_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
        or ".." in normalized.split("/")
    ):
        raise ValueError("release evidence paths must be non-empty and relative")
    return normalized


class ArtifactReference(_ReleaseModel):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _relative_path(value)


class BenchmarkEvidence(_ReleaseModel):
    source_kind: ReleaseSourceKind
    measurement_mode: Literal["autonomous", "assisted"]
    manifest: ArtifactReference
    baseline: ArtifactReference
    report: ArtifactReference
    inputs: tuple[ArtifactReference, ...] = Field(min_length=1)
    case_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_case_and_input_paths(self) -> "BenchmarkEvidence":
        if len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("benchmark case IDs must be unique")
        paths = [item.path.casefold() for item in self.inputs]
        if len(paths) != len(set(paths)):
            raise ValueError("benchmark input paths must be unique")
        return self


class ProjectEvidence(_ReleaseModel):
    source_kind: ReleaseSourceKind
    workspace: str
    receipt: ArtifactReference
    quality_evidence: ArtifactReference
    effort_evidence: ArtifactReference
    live_receipt: ArtifactReference

    @field_validator("workspace")
    @classmethod
    def validate_workspace(cls, value: str) -> str:
        return _relative_path(value)


class TestEvidence(_ReleaseModel):
    policy: ArtifactReference
    receipt: ArtifactReference
    source_files: tuple[ArtifactReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_source_files(self) -> "TestEvidence":
        paths = [item.path.casefold() for item in self.source_files]
        if len(paths) != len(set(paths)):
            raise ValueError("test source file paths must be unique")
        return self


class ControlEvidence(_ReleaseModel):
    receipt: ArtifactReference


class ReleaseContract(_ReleaseModel):
    schema_version: Literal["1.0"] = RELEASE_CONTRACT_SCHEMA
    candidate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    evaluation_date: date
    compatibility_policy: ArtifactReference
    benchmarks: tuple[BenchmarkEvidence, ...] = ()
    projects: tuple[ProjectEvidence, ...] = ()
    test_evidence: TestEvidence | None = None
    performance_evidence: ArtifactReference | None = None
    control_evidence: ControlEvidence | None = None
    secret_scan_files: tuple[str, ...] = ()
    deterministic_json_files: tuple[ArtifactReference, ...] = ()

    @field_validator("secret_scan_files")
    @classmethod
    def validate_scan_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_relative_path(value) for value in values)
        if len(normalized) != len(set(value.casefold() for value in normalized)):
            raise ValueError("secret scan file paths must be unique")
        return normalized

    @model_validator(mode="after")
    def require_unique_source_evidence(self) -> "ReleaseContract":
        benchmark_kinds = [item.source_kind for item in self.benchmarks]
        if len(benchmark_kinds) != len(set(benchmark_kinds)):
            raise ValueError("release benchmarks must have one entry per source kind")
        project_kinds = [item.source_kind for item in self.projects]
        if len(project_kinds) != len(set(project_kinds)):
            raise ValueError("release projects must have one entry per source kind")
        return self


class QualityCount(_ReleaseModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(gt=0)

    @model_validator(mode="after")
    def numerator_cannot_exceed_denominator(self) -> "QualityCount":
        if self.numerator > self.denominator:
            raise ValueError("quality numerator cannot exceed its denominator")
        return self


class QualityCounts(_ReleaseModel):
    eligible_section_editable_coverage: QualityCount
    native_agency_component_ratio: QualityCount
    body_without_generic_fallback: QualityCount
    desktop_tablet_mobile_evidence: QualityCount


class ProjectQualityEvidence(_ReleaseModel):
    schema_version: Literal["project-quality-evidence-v1"] = PROJECT_QUALITY_EVIDENCE_SCHEMA
    candidate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    project_id: str = Field(min_length=1)
    source_kind: ReleaseSourceKind
    quality: QualityCounts


class EffortSession(_ReleaseModel):
    session_id: str = Field(min_length=1)
    operator_id: str = Field(min_length=1)
    minutes: float = Field(gt=0)

    @field_validator("minutes")
    @classmethod
    def require_finite_minutes(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("effort minutes must be finite")
        return value


class ProjectEffortEvidence(_ReleaseModel):
    schema_version: Literal["project-effort-evidence-v1"] = PROJECT_EFFORT_EVIDENCE_SCHEMA
    candidate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    project_id: str = Field(min_length=1)
    source_kind: ReleaseSourceKind
    measurement_protocol: ArtifactReference
    quality_policy: ArtifactReference
    baseline_sessions: tuple[EffortSession, ...] = Field(min_length=1)
    current_sessions: tuple[EffortSession, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_sessions(self) -> "ProjectEffortEvidence":
        identifiers = [
            item.session_id
            for item in (*self.baseline_sessions, *self.current_sessions)
        ]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("effort session IDs must be unique")
        return self


class ProjectReleaseReceipt(_ReleaseModel):
    schema_version: Literal["project-release-evidence-v1"] = PROJECT_RELEASE_EVIDENCE_SCHEMA
    candidate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    project_id: str = Field(min_length=1)
    source_kind: ReleaseSourceKind
    project_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    maintenance_scorecard_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    quality_evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    effort_evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class LiveCapture(_ReleaseModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    artifact: ArtifactReference


class SmokeCheck(_ReleaseModel):
    check_id: Literal["editor", "navigation", "public-route", "search"]
    status: Literal["passed", "failed"]


class PortalObservation(_ReleaseModel):
    portal_id: int = Field(ge=0)
    base_url: str
    dnn_version: str = Field(min_length=1)
    vanjaro_version: str = Field(min_length=1)
    vanjaro_ai_version: str = Field(min_length=1)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlsplit(value.strip().rstrip("/"))
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("live receipt base_url must be a credential-free HTTP(S) URL")
        return value.strip().rstrip("/")


class LiveEvidenceReceipt(_ReleaseModel):
    schema_version: Literal["agency-live-evidence-v1"] = LIVE_EVIDENCE_SCHEMA
    provenance: Literal["real-vanjaro-portal"]
    candidate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    project_id: str = Field(min_length=1)
    source_kind: ReleaseSourceKind
    portal: PortalObservation
    project_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    publish_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    launch_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed_at: AwareDatetime
    valid_through: date
    captures: dict[Literal["desktop", "tablet", "mobile"], LiveCapture]
    smoke_checks: tuple[SmokeCheck, ...]
    cleanup_restored: bool
    attestation: ArtifactReference

    @model_validator(mode="after")
    def require_complete_live_matrix(self) -> "LiveEvidenceReceipt":
        if set(self.captures) != {"desktop", "tablet", "mobile"}:
            raise ValueError("live receipt requires desktop, tablet, and mobile captures")
        identifiers = [item.check_id for item in self.smoke_checks]
        if set(identifiers) != {"editor", "navigation", "public-route", "search"}:
            raise ValueError("live receipt requires the complete smoke-check set")
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("live smoke check IDs must be unique")
        return self


class LiveAttestationReceipt(_ReleaseModel):
    schema_version: Literal["agency-live-attestation-v1"] = LIVE_ATTESTATION_SCHEMA
    candidate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    project_id: str = Field(min_length=1)
    source_kind: ReleaseSourceKind
    operator_id: str = Field(min_length=1)
    observed_at: AwareDatetime
    portal: PortalObservation
    capture_sha256: dict[Literal["desktop", "tablet", "mobile"], str]
    capture_routes: dict[Literal["desktop", "tablet", "mobile"], str]
    smoke_routes: dict[Literal["editor", "navigation", "public-route", "search"], str]
    statement: Literal[
        "I observed this candidate on the stated Vanjaro portal and recorded "
        "the linked captures and smoke checks."
    ]

    @field_validator("capture_sha256")
    @classmethod
    def validate_capture_digests(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != {"desktop", "tablet", "mobile"}:
            raise ValueError("live attestation requires all capture digests")
        if any(not re.fullmatch(r"[a-f0-9]{64}", digest) for digest in value.values()):
            raise ValueError("live attestation capture digests must be SHA-256 values")
        return value

    @field_validator("capture_routes", "smoke_routes")
    @classmethod
    def validate_routes(cls, value: dict[str, str]) -> dict[str, str]:
        for route in value.values():
            parsed = urlsplit(route)
            if (
                not route.startswith("/")
                or parsed.scheme
                or parsed.netloc
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("live attestation routes must be credential-free absolute paths")
        return value

    @model_validator(mode="after")
    def require_complete_attestation(self) -> "LiveAttestationReceipt":
        if set(self.capture_routes) != {"desktop", "tablet", "mobile"}:
            raise ValueError("live attestation requires all capture routes")
        if set(self.smoke_routes) != {"editor", "navigation", "public-route", "search"}:
            raise ValueError("live attestation requires all smoke routes")
        return self


class RequiredControlTests(_ReleaseModel):
    structured_diagnostics: tuple[str, ...] = Field(min_length=1)
    recovery_tests: tuple[str, ...] = Field(min_length=1)
    contract_migrations: tuple[str, ...] = Field(min_length=1)
    import_boundaries: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_test_ids_per_control(self) -> "RequiredControlTests":
        for field_name in self.__class__.model_fields:
            identifiers = getattr(self, field_name)
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{field_name} control test IDs must be unique")
        return self


class TestPolicy(_ReleaseModel):
    schema_version: Literal["agency-test-policy-v1"] = TEST_POLICY_SCHEMA
    command: str = Field(min_length=1)
    allowed_deselected: int = Field(ge=0)
    source_globs: tuple[str, ...] = Field(min_length=1)
    required_controls: RequiredControlTests

    @field_validator("source_globs")
    @classmethod
    def validate_source_globs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_relative_path(value) for value in values)
        if len(normalized) != len(set(value.casefold() for value in normalized)):
            raise ValueError("test source globs must be unique")
        return normalized


class TestEvidenceReceipt(_ReleaseModel):
    schema_version: Literal["test-evidence-v1"] = TEST_EVIDENCE_SCHEMA
    command: str = Field(min_length=1)
    collected: int = Field(gt=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    errors: int = Field(ge=0)
    deselected: int = Field(ge=0)
    allowed_deselected: int = Field(ge=0)
    node_ids: tuple[str, ...] = Field(min_length=1)
    node_ids_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_tree_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def require_unique_node_ids(self) -> "TestEvidenceReceipt":
        if len(self.node_ids) != len(set(self.node_ids)):
            raise ValueError("test node IDs must be unique")
        return self


class ControlResult(_ReleaseModel):
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class ControlEvidenceReceipt(_ReleaseModel):
    schema_version: Literal["reliability-control-evidence-v1"] = CONTROL_EVIDENCE_SCHEMA
    test_receipt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    structured_diagnostics: ControlResult
    recovery_tests: ControlResult
    contract_migrations: ControlResult
    import_boundaries: ControlResult


class GateResult(_ReleaseModel):
    gate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    status: GateStatus
    reason_codes: tuple[str, ...]
    evidence_sha256: tuple[str, ...] = ()


class ReleaseAuditSummary(_ReleaseModel):
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    incomplete: int = Field(ge=0)


class ReleaseAuditReport(_ReleaseModel):
    schema_version: Literal["agency-release-audit-v1"] = RELEASE_AUDIT_SCHEMA
    candidate_id: str
    contract_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: GateStatus
    summary: ReleaseAuditSummary
    gates: tuple[GateResult, ...]


__all__ = [
    "ArtifactReference",
    "BenchmarkEvidence",
    "ControlEvidenceReceipt",
    "GateResult",
    "LiveEvidenceReceipt",
    "LiveAttestationReceipt",
    "ProjectEffortEvidence",
    "ProjectQualityEvidence",
    "ProjectReleaseReceipt",
    "ReleaseAuditReport",
    "ReleaseAuditSummary",
    "ReleaseContract",
    "TestPolicy",
    "TestEvidenceReceipt",
]
