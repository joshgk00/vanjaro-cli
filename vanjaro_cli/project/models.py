"""Versioned contracts for resumable Vanjaro agency projects."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
import re
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from vanjaro_cli.design.models import BreakpointName, SourceKind, Viewport


PROJECT_SCHEMA_VERSION = "1.0"
PROJECT_STAGE_ORDER = (
    "intake",
    "analyze",
    "plan",
    "theme",
    "assets",
    "library",
    "pages",
    "global_blocks",
    "verify",
    "publish",
)

_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|credentials?)(?:$|[_-])",
    re.IGNORECASE,
)


class _ProjectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectStage(str, Enum):
    INTAKE = "intake"
    ANALYZE = "analyze"
    PLAN = "plan"
    THEME = "theme"
    ASSETS = "assets"
    LIBRARY = "library"
    PAGES = "pages"
    GLOBAL_BLOCKS = "global_blocks"
    VERIFY = "verify"
    PUBLISH = "publish"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ApprovalGate(str, Enum):
    PLAN = "plan"
    PORTAL_MUTATION = "portal_mutation"
    PUBLISH = "publish"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ProjectIdentity(_ProjectModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("project name must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_timestamps(self) -> "ProjectIdentity":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        return self


class TargetPortal(_ProjectModel):
    profile: str = Field(min_length=1)
    expected_portal_id: int | None = Field(default=None, ge=0)
    expected_base_url: str | None = None

    @field_validator("profile")
    @classmethod
    def normalize_profile(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("target profile must not be empty")
        return normalized

    @field_validator("expected_base_url")
    @classmethod
    def normalize_expected_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "expected_base_url must be an HTTP(S) origin/path without credentials, query, or fragment"
            )
        return normalized


class AgencyPack(_ProjectModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("name", "version")
    @classmethod
    def normalize_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("agency pack name and version must not be empty")
        return normalized


class ProjectSource(_ProjectModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    kind: SourceKind
    reference: str = Field(min_length=1)
    evidence_reference: str | None = None
    page_reference: str | None = None
    breakpoint: BreakpointName | None = None
    viewport: Viewport | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("reference", "evidence_reference")
    @classmethod
    def validate_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("source reference must not be empty")
        parsed = urlsplit(normalized)
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
            if _SENSITIVE_KEY.search(key):
                raise ValueError(
                    f"source reference must not contain secret query parameter {key!r}"
                )
        return normalized

    @field_validator("metadata")
    @classmethod
    def reject_secret_metadata(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _assert_secret_free(value, path="metadata")
        return value

    @model_validator(mode="after")
    def validate_viewport(self) -> "ProjectSource":
        if self.kind == SourceKind.COMPOSITE:
            raise ValueError("composite is a derived design source, not a project input")
        if self.kind == SourceKind.IMAGE:
            missing: list[str] = []
            if self.page_reference is None or not self.page_reference.strip():
                missing.append("page_reference")
            if self.breakpoint is None:
                missing.append("breakpoint")
            if self.viewport is None:
                missing.append("viewport")
            if missing:
                raise ValueError(
                    "image sources require explicit " + ", ".join(missing)
                )
        elif self.evidence_reference is not None:
            raise ValueError("evidence_reference is only valid for image sources")
        return self


class StageRecord(_ProjectModel):
    stage: ProjectStage
    status: StageStatus = StageStatus.PENDING
    attempt: int = Field(default=0, ge=0)
    input_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    output_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    artifacts: list[str] = Field(default_factory=list)
    message: str | None = None

    @field_validator("artifacts")
    @classmethod
    def validate_artifacts(cls, values: list[str]) -> list[str]:
        for value in values:
            normalized = value.replace("\\", "/")
            if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
                raise ValueError("stage artifact paths must be workspace-relative")
            if ".." in normalized.split("/"):
                raise ValueError("stage artifact paths must not escape the workspace")
        return values

    @model_validator(mode="after")
    def validate_state(self) -> "StageRecord":
        if self.status == StageStatus.RUNNING and self.started_at is None:
            raise ValueError("running stages require started_at")
        if self.status == StageStatus.COMPLETED:
            if (
                self.started_at is None
                or self.completed_at is None
                or self.input_fingerprint is None
                or self.output_fingerprint is None
            ):
                raise ValueError(
                    "completed stages require timestamps plus input and output fingerprints"
                )
        if self.status == StageStatus.FAILED and not self.message:
            raise ValueError("failed stages require a message")
        if self.status == StageStatus.SKIPPED and (
            self.completed_at is None or not self.message
        ):
            raise ValueError("skipped stages require completed_at and a message")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at must not be earlier than started_at")
        return self


class DecisionRecord(_ProjectModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    topic: str = Field(min_length=1)
    selection: str = Field(min_length=1)
    rationale: str | None = None
    decided_by: str = Field(min_length=1)
    decided_at: AwareDatetime
    stage: ProjectStage | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def reject_secret_metadata(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _assert_secret_free(value, path="metadata")
        return value


class ApprovalRecord(_ProjectModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    gate: ApprovalGate
    status: ApprovalStatus = ApprovalStatus.PENDING
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    requested_by: str = Field(min_length=1)
    requested_at: AwareDatetime
    resolved_at: AwareDatetime | None = None
    resolved_by: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> "ApprovalRecord":
        resolved = self.status in {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.SUPERSEDED,
        }
        if resolved and (self.resolved_at is None or not self.resolved_by):
            raise ValueError("resolved approvals require resolved_at and resolved_by")
        if self.resolved_at is not None and self.resolved_at < self.requested_at:
            raise ValueError("resolved_at must not be earlier than requested_at")
        return self


class AuditEvent(_ProjectModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    occurred_at: AwareDatetime
    kind: str = Field(min_length=1)
    message: str = Field(min_length=1)
    stage: ProjectStage | None = None
    fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    artifacts: list[str] = Field(default_factory=list)


class ProjectManifest(_ProjectModel):
    schema_version: Literal["1.0"] = PROJECT_SCHEMA_VERSION
    project: ProjectIdentity
    target: TargetPortal
    agency_pack: AgencyPack
    sources: list[ProjectSource] = Field(min_length=1)
    stages: dict[ProjectStage, StageRecord]
    decisions: list[DecisionRecord]
    approvals: list[ApprovalRecord]
    audit: list[AuditEvent]
    metadata: dict[str, JsonValue]

    @field_validator("metadata")
    @classmethod
    def reject_secret_metadata(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _assert_secret_free(value, path="metadata")
        return value

    @model_validator(mode="after")
    def validate_relationships(self) -> "ProjectManifest":
        source_ids = [source.id for source in self.sources]
        _require_unique(source_ids, "source id")
        _require_unique([decision.id for decision in self.decisions], "decision id")
        _require_unique([approval.id for approval in self.approvals], "approval id")
        _require_unique([event.id for event in self.audit], "audit event id")

        required_stages = set(ProjectStage)
        actual_stages = set(self.stages)
        if actual_stages != required_stages:
            missing = sorted(stage.value for stage in required_stages - actual_stages)
            extra = sorted(stage.value for stage in actual_stages - required_stages)
            raise ValueError(
                f"stages must contain the complete workflow; missing={missing}, extra={extra}"
            )
        for stage, record in self.stages.items():
            if record.stage != stage:
                raise ValueError(
                    f"stage mapping key {stage.value!r} does not match record {record.stage.value!r}"
                )
        return self


def _assert_secret_free(value: JsonValue, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if _SENSITIVE_KEY.search(str(key)) and child not in (None, "", False):
                raise ValueError(f"secret-bearing metadata key is not allowed: {child_path}")
            _assert_secret_free(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_secret_free(child, path=f"{path}[{index}]")
    elif isinstance(value, str):
        if re.match(r"^\s*(?:bearer|basic)\s+\S+", value, re.IGNORECASE):
            raise ValueError(f"authorization value is not allowed in metadata: {path}")
        parsed = urlsplit(value)
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
            if _SENSITIVE_KEY.search(key):
                raise ValueError(
                    f"secret query parameter is not allowed in metadata: {path}.{key}"
                )


def _require_unique(values: list[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value!r}")
        seen.add(value)


__all__ = [
    "AgencyPack",
    "ApprovalGate",
    "ApprovalRecord",
    "ApprovalStatus",
    "AuditEvent",
    "DecisionRecord",
    "PROJECT_SCHEMA_VERSION",
    "PROJECT_STAGE_ORDER",
    "ProjectIdentity",
    "ProjectManifest",
    "ProjectSource",
    "ProjectStage",
    "StageRecord",
    "StageStatus",
    "TargetPortal",
]
