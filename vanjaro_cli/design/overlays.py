"""Typed, audited human corrections applied over immutable design evidence."""

from __future__ import annotations

from enum import Enum
import json
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from vanjaro_cli.design.models import (
    ContentElement,
    ContentKind,
    DesignDocument,
    ObservationMethod,
    Provenance,
)
from vanjaro_cli.design.serialization import stable_design_id


class DesignOverlayError(ValueError):
    """Raised when an overlay is invalid or cannot be applied exactly once."""


class OverlayOperation(str, Enum):
    ADD_REPEAT_FIELD = "add_repeat_field"
    SET_ELEMENT_VALUE = "set_element_value"


class _OverlayModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DesignOverlay(_OverlayModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    operation: OverlayOperation
    target_id: str = Field(min_length=1)
    field: str | None = None
    content_kind: ContentKind | None = None
    value: JsonValue
    author: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_operation_fields(self) -> "DesignOverlay":
        if self.operation == OverlayOperation.ADD_REPEAT_FIELD:
            if not self.field or self.content_kind is None:
                raise ValueError(
                    "add_repeat_field requires field and content_kind"
                )
        elif self.field is not None or self.content_kind is not None:
            raise ValueError(
                "set_element_value does not accept field or content_kind"
            )
        return self


class DesignOverlaySet(_OverlayModel):
    schema_version: Literal["1.0"] = "1.0"
    overlays: list[DesignOverlay]

    @model_validator(mode="after")
    def require_unique_ids(self) -> "DesignOverlaySet":
        ids = [overlay.id for overlay in self.overlays]
        if len(ids) != len(set(ids)):
            raise ValueError("design overlay IDs must be unique")
        return self


def apply_design_overlays(
    document: DesignDocument, overlay_set: DesignOverlaySet
) -> DesignDocument:
    """Apply overlays in audited order and revalidate all document references."""

    resolved = document
    for overlay in overlay_set.overlays:
        if overlay.operation == OverlayOperation.ADD_REPEAT_FIELD:
            resolved = _add_repeat_field(resolved, overlay)
        else:
            resolved = _set_element_value(resolved, overlay)
    return DesignDocument.model_validate(resolved.model_dump())


def read_design_overlays(path: Path) -> DesignOverlaySet:
    try:
        value = path.read_text(encoding="utf-8")
        return DesignOverlaySet.model_validate_json(value)
    except (OSError, ValueError) as exc:
        raise DesignOverlayError(f"invalid design overlay artifact {path}: {exc}") from exc


def serialize_design_overlays(overlay_set: DesignOverlaySet) -> str:
    return json.dumps(
        overlay_set.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _add_repeat_field(
    document: DesignDocument, overlay: DesignOverlay
) -> DesignDocument:
    matched = 0
    pages = []
    for page in document.pages:
        sections = []
        for section in page.sections:
            content = list(section.content)
            groups = []
            for group in section.groups:
                items = []
                for item in group.items:
                    if item.id != overlay.target_id:
                        items.append(item)
                        continue
                    matched += 1
                    assert overlay.field is not None
                    assert overlay.content_kind is not None
                    if overlay.field in item.fields:
                        raise DesignOverlayError(
                            f"overlay {overlay.id!r} would replace existing repeat field "
                            f"{overlay.field!r}; use an element-value overlay instead"
                        )
                    element_id = stable_design_id(
                        "manual-element", overlay.id, overlay.target_id, overlay.field
                    )
                    content.append(
                        ContentElement(
                            id=element_id,
                            kind=overlay.content_kind,
                            role=overlay.field,
                            value=overlay.value,
                            group_id=group.id,
                            order=max((element.order for element in content), default=-1) + 1,
                            provenance=[_provenance(document, overlay)],
                            confidence=1.0,
                            metadata={"design_overlay_id": overlay.id},
                        )
                    )
                    items.append(
                        item.model_copy(
                            update={"fields": {**item.fields, overlay.field: element_id}}
                        )
                    )
                groups.append(group.model_copy(update={"items": items}))
            sections.append(
                section.model_copy(update={"content": content, "groups": groups})
            )
        pages.append(page.model_copy(update={"sections": sections}))
    if matched != 1:
        raise DesignOverlayError(
            f"overlay {overlay.id!r} target {overlay.target_id!r} matched {matched} repeat items"
        )
    return document.model_copy(update={"pages": pages})


def _set_element_value(
    document: DesignDocument, overlay: DesignOverlay
) -> DesignDocument:
    matched = 0
    pages = []
    for page in document.pages:
        sections = []
        for section in page.sections:
            content = []
            for element in section.content:
                if element.id != overlay.target_id:
                    content.append(element)
                    continue
                matched += 1
                content.append(
                    element.model_copy(
                        update={
                            "value": overlay.value,
                            "provenance": [
                                *element.provenance,
                                _provenance(document, overlay),
                            ],
                            "metadata": {
                                **element.metadata,
                                "design_overlay_id": overlay.id,
                            },
                        }
                    )
                )
            sections.append(section.model_copy(update={"content": content}))
        pages.append(page.model_copy(update={"sections": sections}))
    if matched != 1:
        raise DesignOverlayError(
            f"overlay {overlay.id!r} target {overlay.target_id!r} matched {matched} elements"
        )
    return document.model_copy(update={"pages": pages})


def _provenance(document: DesignDocument, overlay: DesignOverlay) -> Provenance:
    return Provenance(
        source_kind=document.source.kind,
        method=ObservationMethod.MANUAL,
        metadata={
            "overlay_id": overlay.id,
            "author": overlay.author,
            "reason": overlay.reason,
            "created_at": overlay.created_at.isoformat(),
        },
    )


__all__ = [
    "DesignOverlay",
    "DesignOverlayError",
    "DesignOverlaySet",
    "OverlayOperation",
    "apply_design_overlays",
    "read_design_overlays",
    "serialize_design_overlays",
]
