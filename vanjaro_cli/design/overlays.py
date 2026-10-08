"""Typed, audited human corrections applied over immutable design evidence."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
import json
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from vanjaro_cli.design.models import (
    ContentElement,
    ContentKind,
    DesignDocument,
    EvidenceStatus,
    ObservationMethod,
    Provenance,
    RepeatGroup,
    StyleObservation,
    StyleProperty,
    StyleSet,
)
from vanjaro_cli.design.serialization import stable_design_id
from vanjaro_cli.utils.image_links import is_safe_link_href


class DesignOverlayError(ValueError):
    """Raised when an overlay is invalid or cannot be applied exactly once."""


class OverlayOperation(str, Enum):
    ADD_REPEAT_FIELD = "add_repeat_field"
    SET_ELEMENT_VALUE = "set_element_value"
    SET_ACTION_URL = "set_action_url"


_ACTION_KINDS = frozenset({ContentKind.BUTTON, ContentKind.LINK})


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
                f"{self.operation.value} does not accept field or content_kind"
            )
        if self.operation == OverlayOperation.SET_ACTION_URL and not (
            isinstance(self.value, str) and is_safe_link_href(self.value)
        ):
            raise ValueError(
                "set_action_url requires a relative path or an http, https, "
                "mailto, or tel destination"
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
        elif overlay.operation == OverlayOperation.SET_ACTION_URL:
            resolved = _update_element(resolved, overlay, _with_action_url)
        else:
            resolved = _update_element(resolved, overlay, _with_value)
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
                            style=_sibling_font_size(document, overlay, group, content),
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


def _sibling_font_size(
    document: DesignDocument,
    overlay: DesignOverlay,
    group: RepeatGroup,
    content: list[ContentElement],
) -> StyleSet:
    """Give an added repeat field the size its siblings were drawn at.

    A stat figure drawn as outlines has no text node to read a size from, so it
    would sit beside its siblings at the template's default size. Siblings that
    disagree give no size to copy.
    """

    by_id = {element.id: element for element in content}
    sibling_ids = [
        item.fields.get(overlay.field) for item in group.items if item.id != overlay.target_id
    ]
    sizes = {
        observation.value
        for element_id in sibling_ids
        if isinstance(element_id, str) and element_id in by_id
        for observation in by_id[element_id].style.observations
        if observation.property is StyleProperty.FONT_SIZE
        and observation.condition is None
        and isinstance(observation.value, str)
    }
    if len(sizes) != 1:
        return StyleSet()
    return StyleSet(
        observations=[
            StyleObservation(
                property=StyleProperty.FONT_SIZE,
                value=sizes.pop(),
                status=EvidenceStatus.INFERRED,
                confidence=0.8,
                provenance=[_provenance(document, overlay)],
            )
        ]
    )


def _with_value(element: ContentElement, overlay: DesignOverlay) -> dict[str, object]:
    return {"value": overlay.value}


def _with_action_url(element: ContentElement, overlay: DesignOverlay) -> dict[str, object]:
    if element.kind not in _ACTION_KINDS:
        raise DesignOverlayError(
            f"overlay {overlay.id!r} target {overlay.target_id!r} is a "
            f"{element.kind.value}, not a button or link"
        )
    return {"attributes": {**element.attributes, "href": overlay.value}}


def _update_element(
    document: DesignDocument,
    overlay: DesignOverlay,
    changes: Callable[[ContentElement, DesignOverlay], dict[str, object]],
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
                            **changes(element, overlay),
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
