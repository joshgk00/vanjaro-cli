"""Pure helpers for responsive evidence overlays and structural comparison."""

from __future__ import annotations

import json
from typing import Any, Sequence

from vanjaro_cli.design.models import (
    ContentElement,
    EvidenceStatus,
    ResponsiveObservation,
    Section,
    StyleSet,
)


def layout_delta(primary: Section, secondary: Section) -> dict[str, Any]:
    before = primary.layout.model_dump(mode="json")
    after = secondary.layout.model_dump(mode="json")
    return {
        key: {"from": before.get(key), "to": after.get(key)}
        for key in sorted(before)
        if before.get(key) != after.get(key)
    }


def overlay_observation(
    current: ResponsiveObservation,
    incoming: ResponsiveObservation,
) -> ResponsiveObservation:
    return incoming.model_copy(
        update={
            "status": (
                EvidenceStatus.OBSERVED
                if EvidenceStatus.OBSERVED in {current.status, incoming.status}
                else EvidenceStatus.INFERRED
            ),
            "layout_changes": {
                **current.layout_changes,
                **incoming.layout_changes,
            },
            "style": overlay_style(current.style, incoming.style),
            "hidden": (
                incoming.hidden if incoming.hidden is not None else current.hidden
            ),
            "provenance": unique_models(
                current.provenance + incoming.provenance
            ),
        }
    )


def overlay_style(primary: StyleSet, incoming: StyleSet) -> StyleSet:
    by_property = {item.property: item for item in primary.observations}
    for item in incoming.observations:
        by_property[item.property] = item
    return StyleSet(
        observations=[
            by_property[key]
            for key in sorted(by_property, key=lambda value: value.value)
        ],
        raw={**primary.raw, **incoming.raw},
    )


def merge_content_provenance(
    primary: Sequence[ContentElement],
    secondary: Sequence[ContentElement],
    source_id: str,
) -> tuple[list[ContentElement], list[str]]:
    available: dict[str, list[ContentElement]] = {}
    for element in secondary:
        available.setdefault(content_signature(element), []).append(element)
    merged: list[ContentElement] = []
    matched_ids: set[str] = set()
    for element in primary:
        matches = available.get(content_signature(element), [])
        match = next((item for item in matches if item.id not in matched_ids), None)
        if match is None:
            merged.append(element)
            continue
        matched_ids.add(match.id)
        merged.append(
            element.model_copy(
                update={
                    "provenance": unique_models(
                        element.provenance + match.provenance
                    ),
                    "metadata": {
                        **element.metadata,
                        "merged_project_sources": sorted(
                            {
                                *element.metadata.get("merged_project_sources", []),
                                source_id,
                            },
                            key=str.casefold,
                        ),
                    },
                }
            )
        )
    return merged, [item.id for item in secondary if item.id not in matched_ids]


def content_signature(element: ContentElement) -> str:
    return json.dumps(
        {
            "kind": element.kind.value,
            "role": element.role,
            "value": element.value,
            "attributes": element.attributes,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def group_signature(group: Any) -> str:
    return json.dumps(
        {
            "kind": group.kind.value,
            "items": [sorted(item.fields) for item in group.items],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def unique_models(values: Sequence[Any]) -> list[Any]:
    seen: set[str] = set()
    output: list[Any] = []
    for value in values:
        key = json.dumps(
            value.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        if key not in seen:
            seen.add(key)
            output.append(value)
    return output


__all__ = [
    "content_signature",
    "group_signature",
    "layout_delta",
    "merge_content_provenance",
    "overlay_observation",
    "overlay_style",
    "unique_models",
]
