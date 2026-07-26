"""Provider-neutral contracts for extracting structured evidence from rasters."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vanjaro_cli.design.image_evidence import ImageEvidenceSet
from vanjaro_cli.design.models import (
    Alignment,
    AssetRole,
    BoundingBox,
    BreakpointName,
    ContentKind,
    LayoutKind,
    MediaPosition,
    RepeatGroupKind,
    StyleProperty,
    Viewport,
    WarningSeverity,
)


class _DetectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImageEvidenceProviderError(ValueError):
    """Provider-neutral categorized failure with recovery guidance."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        recommended_action: str,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.recommended_action = recommended_action
        self.status_code = status_code
        super().__init__(message)

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "category": self.code,
            "message": str(self),
            "recommended_action": self.recommended_action,
            "status_code": self.status_code,
        }


class DetectedStyle(_DetectionModel):
    property: StyleProperty
    value: str
    confidence: float = Field(ge=0, le=1)


class DetectedLayout(_DetectionModel):
    kind: LayoutKind
    contained: bool
    columns: int | None
    media_position: MediaPosition | None
    alignment: Alignment | None
    full_bleed: bool
    direction: Literal["horizontal", "vertical"] | None
    wrap: bool | None


class DetectedSection(_DetectionModel):
    id: str = Field(min_length=1)
    order: int = Field(ge=0)
    semantic_role: str = Field(min_length=1)
    role_confidence: float = Field(ge=0, le=1)
    bounds: BoundingBox
    layout: DetectedLayout
    styles: list[DetectedStyle]
    hidden: bool


class DetectedElement(_DetectionModel):
    id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    kind: ContentKind
    role: str = Field(min_length=1)
    order: int = Field(ge=0)
    bounds: BoundingBox
    value: str | None
    heading_level: int | None
    asset_id: str | None
    group_id: str | None
    styles: list[DetectedStyle]
    confidence: float = Field(ge=0, le=1)


class DetectedRepeatField(_DetectionModel):
    name: str = Field(min_length=1)
    element_ids: list[str] = Field(min_length=1)


class DetectedRepeatItem(_DetectionModel):
    id: str = Field(min_length=1)
    fields: list[DetectedRepeatField] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class DetectedRepeatGroup(_DetectionModel):
    id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    kind: RepeatGroupKind
    items: list[DetectedRepeatItem] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class DetectedAsset(_DetectionModel):
    id: str = Field(min_length=1)
    kind: Literal["image", "video"]
    role: AssetRole
    bounds: BoundingBox
    confidence: float = Field(ge=0, le=1)


class DetectedColor(_DetectionModel):
    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class DetectedSpacing(_DetectionModel):
    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class DetectedTypography(_DetectionModel):
    role: str = Field(min_length=1)
    font_family: str | None
    font_size: str | None
    font_weight: str | None
    line_height: str | None
    letter_spacing: str | None
    confidence: float = Field(ge=0, le=1)


class DetectedWarning(_DetectionModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: WarningSeverity
    evidence_id: str | None


class DetectedObservation(_DetectionModel):
    source_id: str = Field(min_length=1)
    page_title: str | None
    sections: list[DetectedSection] = Field(min_length=1)
    elements: list[DetectedElement]
    groups: list[DetectedRepeatGroup]
    assets: list[DetectedAsset]
    colors: list[DetectedColor]
    spacing: list[DetectedSpacing]
    typography: list[DetectedTypography]
    warnings: list[DetectedWarning]


class DetectedEvidenceBundle(_DetectionModel):
    observations: list[DetectedObservation] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_sources(self) -> "DetectedEvidenceBundle":
        source_ids = [item.source_id for item in self.observations]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("detected observations must have unique source_id values")
        return self


@dataclass(frozen=True, slots=True)
class EvidenceImageInput:
    """One verified image supplied to an evidence provider."""

    source_id: str
    path: Path
    mime_type: str
    payload: bytes
    sha256: str
    page_slug: str
    breakpoint: BreakpointName
    viewport: Viewport
    image_width: int
    image_height: int

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("evidence image source_id must not be empty")
        if self.mime_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError(f"unsupported evidence image MIME type: {self.mime_type}")
        if not self.payload:
            raise ValueError("evidence image payload must not be empty")
        invalid_sha_character = any(
            character not in "0123456789abcdef" for character in self.sha256
        )
        if len(self.sha256) != 64 or invalid_sha_character:
            raise ValueError("evidence image sha256 must contain 64 hexadecimal characters")
        actual_sha256 = hashlib.sha256(self.payload).hexdigest()
        if actual_sha256 != self.sha256:
            raise ValueError(
                "evidence image sha256 does not match the supplied payload bytes"
            )
        if not self.page_slug.strip():
            raise ValueError("evidence image page_slug must not be empty")
        if self.image_width <= 0 or self.image_height <= 0:
            raise ValueError("evidence image pixel dimensions must be positive")


@dataclass(frozen=True, slots=True)
class ImageEvidenceGenerationRequest:
    project_id: str
    images: tuple[EvidenceImageInput, ...]
    captured_at: datetime

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise ValueError("image evidence project_id must not be empty")
        if not self.images:
            raise ValueError("image evidence generation requires at least one image")
        if self.captured_at.utcoffset() is None:
            raise ValueError("image evidence captured_at must include a timezone")
        source_ids = [item.source_id for item in self.images]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("image evidence source_id values must be unique")
        page_slugs = {item.page_slug.casefold() for item in self.images}
        if len(page_slugs) != 1:
            raise ValueError("one evidence request may contain images for only one page")
        breakpoints = [item.breakpoint for item in self.images]
        if len(breakpoints) != len(set(breakpoints)):
            raise ValueError("one evidence request may contain only one image per breakpoint")


@dataclass(frozen=True, slots=True)
class ImageEvidenceGenerationResult:
    evidence: ImageEvidenceSet
    provider: str
    model: str
    response_id: str | None
    request_fingerprint: str


class ImageEvidenceProvider(Protocol):
    def generate(
        self, request: ImageEvidenceGenerationRequest
    ) -> ImageEvidenceGenerationResult: ...


def strict_detection_schema() -> dict[str, object]:
    """Return the strict JSON Schema sent to structured-output providers."""

    schema = deepcopy(DetectedEvidenceBundle.model_json_schema())
    _require_strict_objects(schema)
    return schema


def _require_strict_objects(value: object) -> None:
    if isinstance(value, list):
        for item in value:
            _require_strict_objects(item)
        return
    if not isinstance(value, dict):
        return
    if value.get("type") == "object" and isinstance(value.get("properties"), dict):
        properties = value["properties"]
        value["additionalProperties"] = False
        value["required"] = list(properties)
    value.pop("default", None)
    for item in value.values():
        _require_strict_objects(item)


__all__ = [
    "DetectedEvidenceBundle",
    "DetectedObservation",
    "EvidenceImageInput",
    "ImageEvidenceGenerationRequest",
    "ImageEvidenceGenerationResult",
    "ImageEvidenceProvider",
    "ImageEvidenceProviderError",
    "strict_detection_schema",
]
