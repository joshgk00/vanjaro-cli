"""Strict, source-specific evidence accepted by the reference-image adapter.

The models in this module describe claims made about pixels in one or more
reference images.  They deliberately stop short of being a Design Document:
the image adapter owns the auditable conversion into the shared representation.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from vanjaro_cli.design.models import (
    Alignment,
    AssetKind,
    AssetRole,
    BoundingBox,
    BreakpointName,
    CandidateRole,
    ContentKind,
    EvidenceStatus,
    LayoutKind,
    MediaPosition,
    RepeatGroupKind,
    StyleProperty,
    Viewport,
    WarningSeverity,
)


_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_DRIVE_PATH = re.compile(r"^[A-Za-z]:[/\\]")


class _EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImageEvidenceProducer(_EvidenceModel):
    """Identity of the human, tool, or model that produced the evidence."""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    model: str | None = None
    prompt_version: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ImageStyleEvidence(_EvidenceModel):
    property: StyleProperty
    value: JsonValue
    status: EvidenceStatus = EvidenceStatus.OBSERVED
    confidence: float = Field(default=1.0, ge=0, le=1)


class ImageLayoutEvidence(_EvidenceModel):
    kind: LayoutKind
    contained: bool
    columns: int | None = Field(default=None, ge=1)
    media_position: MediaPosition | None = None
    alignment: Alignment | None = None
    full_bleed: bool = False
    direction: str | None = None
    wrap: bool | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ImageAssetEvidence(_EvidenceModel):
    """A visible media region and any explicitly supplied original asset."""

    id: str = Field(min_length=1)
    kind: AssetKind = AssetKind.IMAGE
    role: AssetRole
    bounds: BoundingBox
    original_source_url: str | None = None
    original_local_path: str | None = None
    mime_type: str | None = None
    alt_text: str | None = None
    missing_reason: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("original_local_path")
    @classmethod
    def require_workspace_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().replace("\\", "/")
        if not normalized or normalized.startswith("/") or _DRIVE_PATH.match(value):
            raise ValueError("original_local_path must be workspace-relative")
        if ".." in normalized.split("/"):
            raise ValueError("original_local_path must not escape the workspace")
        return normalized


class ImageElementEvidence(_EvidenceModel):
    """One visitor-facing item observed inside an image section."""

    id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    kind: ContentKind
    role: str = Field(min_length=1)
    order: int = Field(ge=0)
    bounds: BoundingBox
    value: JsonValue | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    asset_id: str | None = None
    group_id: str | None = None
    styles: list[ImageStyleEvidence] = Field(default_factory=list)
    status: EvidenceStatus = EvidenceStatus.OBSERVED
    confidence: float = Field(ge=0, le=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_media_asset(self) -> "ImageElementEvidence":
        if self.kind in {ContentKind.IMAGE, ContentKind.VIDEO} and self.asset_id is None:
            raise ValueError(f"{self.kind.value} elements require asset_id")
        return self


class ImageRepeatItemEvidence(_EvidenceModel):
    id: str = Field(min_length=1)
    fields: dict[str, str | list[str]]
    confidence: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def require_fields(self) -> "ImageRepeatItemEvidence":
        if not self.fields:
            raise ValueError("repeat items require at least one field")
        if any(not name.strip() for name in self.fields):
            raise ValueError("repeat field names must not be empty")
        if any(not values for values in self.fields.values() if isinstance(values, list)):
            raise ValueError("repeat field reference lists must not be empty")
        return self


class ImageRepeatGroupEvidence(_EvidenceModel):
    id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    kind: RepeatGroupKind
    items: list[ImageRepeatItemEvidence] = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0, le=1)


class ImageSectionEvidence(_EvidenceModel):
    """An ordered image region that is expected to become one section."""

    id: str = Field(min_length=1)
    order: int = Field(ge=0)
    semantic_role: str = Field(min_length=1)
    role_confidence: float = Field(ge=0, le=1)
    candidate_roles: list[CandidateRole] = Field(default_factory=list)
    bounds: BoundingBox
    layout: ImageLayoutEvidence
    styles: list[ImageStyleEvidence] = Field(default_factory=list)
    hidden: bool = False
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ImageColorEvidence(_EvidenceModel):
    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0, le=1)


class ImageSpacingEvidence(_EvidenceModel):
    name: str = Field(min_length=1)
    value: str | int | float
    confidence: float = Field(default=1.0, ge=0, le=1)


class ImageTypographyEvidence(_EvidenceModel):
    role: str = Field(min_length=1)
    font_family: str | None = None
    font_size: str | None = None
    font_weight: int | str | None = None
    line_height: str | None = None
    letter_spacing: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)


class ImageEvidenceWarning(_EvidenceModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: WarningSeverity = WarningSeverity.WARNING
    evidence_id: str | None = None


class ImageObservationEvidence(_EvidenceModel):
    """All normalized evidence derived from one exact image byte stream."""

    source_sha256: str
    captured_at: AwareDatetime
    page_slug: str = Field(min_length=1)
    page_title: str | None = None
    breakpoint: BreakpointName
    viewport: Viewport
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    sections: list[ImageSectionEvidence] = Field(min_length=1)
    elements: list[ImageElementEvidence] = Field(default_factory=list)
    groups: list[ImageRepeatGroupEvidence] = Field(default_factory=list)
    assets: list[ImageAssetEvidence] = Field(default_factory=list)
    colors: list[ImageColorEvidence] = Field(default_factory=list)
    spacing: list[ImageSpacingEvidence] = Field(default_factory=list)
    typography: list[ImageTypographyEvidence] = Field(default_factory=list)
    warnings: list[ImageEvidenceWarning] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("source_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256.fullmatch(normalized):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        return normalized

    @field_validator("page_slug")
    @classmethod
    def normalize_page_slug(cls, value: str) -> str:
        normalized = value.strip().strip("/")
        if not normalized:
            raise ValueError("page_slug must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_geometry_and_references(self) -> "ImageObservationEvidence":
        section_ids = _unique_ids(self.sections, "section")
        element_ids = _unique_ids(self.elements, "element")
        group_ids = _unique_ids(self.groups, "group")
        asset_ids = _unique_ids(self.assets, "asset")
        _require_unique_orders(self.sections, "section")
        for section in self.sections:
            _require_in_image(section.bounds, self.image_width, self.image_height, section.id)

        sections = {item.id: item for item in self.sections}
        groups = {item.id: item for item in self.groups}
        for group in self.groups:
            if group.section_id not in section_ids:
                raise ValueError(
                    f"group {group.id!r} references missing section {group.section_id!r}"
                )
            _unique_ids(group.items, f"repeat item in group {group.id!r}")
            for item in group.items:
                for field, reference in item.fields.items():
                    references = reference if isinstance(reference, list) else [reference]
                    for element_id in references:
                        if element_id not in element_ids:
                            raise ValueError(
                                f"group {group.id!r} field {field!r} references missing "
                                f"element {element_id!r}"
                            )

        orders: dict[str, list[ImageElementEvidence]] = {}
        for element in self.elements:
            section = sections.get(element.section_id)
            if section is None:
                raise ValueError(
                    f"element {element.id!r} references missing section {element.section_id!r}"
                )
            _require_in_image(element.bounds, self.image_width, self.image_height, element.id)
            if not _contains(section.bounds, element.bounds):
                raise ValueError(
                    f"element {element.id!r} bounds are outside section {section.id!r}"
                )
            orders.setdefault(element.section_id, []).append(element)
            if element.asset_id is not None and element.asset_id not in asset_ids:
                raise ValueError(
                    f"element {element.id!r} references missing asset {element.asset_id!r}"
                )
            if element.group_id is not None:
                group = groups.get(element.group_id)
                if group is None:
                    raise ValueError(
                        f"element {element.id!r} references missing group {element.group_id!r}"
                    )
                if group.section_id != element.section_id:
                    raise ValueError(
                        f"element {element.id!r} and group {group.id!r} belong to different sections"
                    )
        for section_id, values in orders.items():
            _require_unique_orders(values, f"element in section {section_id!r}")

        for group in self.groups:
            for item in group.items:
                for reference in item.fields.values():
                    references = reference if isinstance(reference, list) else [reference]
                    for element_id in references:
                        element = next(item for item in self.elements if item.id == element_id)
                        if element.section_id != group.section_id or element.group_id != group.id:
                            raise ValueError(
                                f"group {group.id!r} references element {element_id!r} "
                                "without matching section/group ownership"
                            )

        for asset in self.assets:
            _require_in_image(asset.bounds, self.image_width, self.image_height, asset.id)
        return self


class ImageEvidenceSet(_EvidenceModel):
    """Versioned evidence payload consumed by :class:`ImageSourceAdapter`."""

    schema_version: Literal["1.0"] = "1.0"
    producer: ImageEvidenceProducer
    observations: list[ImageObservationEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_observations(self) -> "ImageEvidenceSet":
        keys = [
            (
                item.source_sha256,
                item.page_slug.casefold(),
                item.breakpoint.value,
                item.viewport.width,
                item.viewport.height,
            )
            for item in self.observations
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("image evidence observations must have unique source ownership")
        return self


def _unique_ids(values: list[object], label: str) -> set[str]:
    identifiers = [str(getattr(item, "id")) for item in values]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"duplicate {label} id")
    return set(identifiers)


def _require_unique_orders(values: list[object], label: str) -> None:
    orders = [int(getattr(item, "order")) for item in values]
    if len(orders) != len(set(orders)):
        raise ValueError(f"duplicate {label} order")


def _require_in_image(bounds: BoundingBox, width: int, height: int, label: str) -> None:
    if bounds.x < 0 or bounds.y < 0:
        raise ValueError(f"{label!r} bounds must not start outside the image")
    if bounds.x + bounds.width > width or bounds.y + bounds.height > height:
        raise ValueError(f"{label!r} bounds exceed image dimensions")


def _contains(owner: BoundingBox, child: BoundingBox, tolerance: float = 1.0) -> bool:
    return (
        child.x >= owner.x - tolerance
        and child.y >= owner.y - tolerance
        and child.x + child.width <= owner.x + owner.width + tolerance
        and child.y + child.height <= owner.y + owner.height + tolerance
    )


__all__ = [
    "ImageAssetEvidence",
    "ImageColorEvidence",
    "ImageElementEvidence",
    "ImageEvidenceProducer",
    "ImageEvidenceSet",
    "ImageEvidenceWarning",
    "ImageLayoutEvidence",
    "ImageObservationEvidence",
    "ImageRepeatGroupEvidence",
    "ImageRepeatItemEvidence",
    "ImageSectionEvidence",
    "ImageSpacingEvidence",
    "ImageStyleEvidence",
    "ImageTypographyEvidence",
]
