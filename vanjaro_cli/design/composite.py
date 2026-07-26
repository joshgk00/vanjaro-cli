"""Pure, source-neutral composition of multiple Design Document artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, Sequence

from vanjaro_cli.design.models import (
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    DesignWarning,
    Page,
    Section,
    SourceKind,
    TokenValue,
    WarningSeverity,
)
from vanjaro_cli.design.responsive_merge import (
    PairedPageEvidence,
    merge_paired_page_evidence,
)


class DesignMergeError(ValueError):
    """Raised when source documents cannot be combined without ambiguity."""


@dataclass(frozen=True, slots=True)
class CompositeDesignInput:
    """One analyzed source and its explicit project-level page relationship."""

    source_id: str
    page_reference: str | None
    document: DesignDocument


def merge_design_documents(
    project_id: str,
    inputs: Sequence[CompositeDesignInput],
) -> DesignDocument:
    """Merge independent pages and explicitly paired responsive evidence."""

    if not inputs:
        raise DesignMergeError("project has no analyzed sources")
    if len(inputs) == 1:
        return inputs[0].document

    source_ids = [item.source_id for item in inputs]
    if len(source_ids) != len(set(source_ids)):
        raise DesignMergeError("project design source IDs must be unique")
    ordered_inputs = sorted(
        inputs, key=lambda item: (item.source_id.casefold(), item.source_id)
    )

    assets: list[Any] = []
    assets_by_id: dict[str, Any] = {}
    warnings: list[DesignWarning] = []
    page_slots: list[tuple[str, Any]] = []
    paired_page_groups: dict[str, list[PairedPageEvidence]] = {}
    tokens = DesignTokens()
    source_metadata: list[dict[str, Any]] = []
    confidence_weight = 0
    confidence_total = 0.0
    unsupported: list[str] = []
    analysis_metadata: dict[str, Any] = {"source_analyses": {}}

    for source_input in ordered_inputs:
        source_id = source_input.source_id
        page_reference = source_input.page_reference
        original_document = source_input.document
        document = _namespace_document(original_document, source_id)
        source_metadata.append(
            {
                "project_source_id": source_id,
                "kind": document.source.kind.value,
                "identifier": document.source.identifier,
                "adapter_version": document.source.adapter_version,
                "captured_at": document.source.captured_at.isoformat(),
                "page_reference": page_reference,
            }
        )
        tokens = _merge_tokens(tokens, document.tokens, source_id)
        for asset in document.assets:
            previous = assets_by_id.get(asset.id)
            if previous is None:
                assets_by_id[asset.id] = asset
                assets.append(asset)
            elif previous != asset:
                raise DesignMergeError(
                    f"asset ID collision while merging source {source_id!r}: {asset.id!r}"
                )
        warnings.extend(document.warnings)
        if page_reference:
            if len(document.pages) != 1:
                raise DesignMergeError(
                    f"source {source_id!r} declares page_reference but produced "
                    f"{len(document.pages)} pages; select one source page/frame"
                )
            pairing_key = page_reference.strip().casefold()
            if pairing_key not in paired_page_groups:
                paired_page_groups[pairing_key] = []
                page_slots.append(("paired", pairing_key))
            paired_page_groups[pairing_key].append(
                PairedPageEvidence(source_id=source_id, page=document.pages[0])
            )
        else:
            page_slots.extend(("page", page) for page in document.pages)
        section_count = sum(len(page.sections) for page in document.pages)
        confidence_weight += section_count
        confidence_total += document.analysis.section_confidence_mean * section_count
        unsupported.extend(document.analysis.unsupported_traits)
        analysis_metadata["source_analyses"][source_id] = document.analysis.model_dump(
            mode="json"
        )

    pages: list[Page] = []
    for slot_kind, slot_value in page_slots:
        if slot_kind == "page":
            pages.append(slot_value)
            continue
        result = merge_paired_page_evidence(
            slot_value, paired_page_groups[slot_value]
        )
        pages.append(result.page)
        warnings.extend(result.warnings)

    captured_at: datetime = max(
        item.document.source.captured_at for item in ordered_inputs
    )
    source = DesignSource(
        kind=SourceKind.COMPOSITE,
        identifier=f"project:{project_id}",
        captured_at=captured_at,
        adapter_version="project-merge/1.1",
        metadata={
            "sources": source_metadata,
            "merge_policy": "explicit-page-reference-v2",
        },
    )
    if any(item.page_reference is None for item in inputs):
        warnings.append(
            DesignWarning(
                code="independent_project_sources",
                severity=WarningSeverity.INFO,
                message=(
                    "Sources without the same explicit page_reference were retained as "
                    "independent pages; no speculative visual overlay was performed."
                ),
            )
        )
    return DesignDocument(
        schema_version="1.0",
        source=source,
        tokens=tokens,
        assets=assets,
        pages=pages,
        warnings=warnings,
        analysis=DesignAnalysis(
            section_confidence_mean=(
                confidence_total / confidence_weight if confidence_weight else 0.0
            ),
            unsupported_traits=list(dict.fromkeys(unsupported)),
            metadata=analysis_metadata,
        ),
    )


def _namespace_document(document: DesignDocument, namespace: str) -> DesignDocument:
    """Namespace internal IDs so independent source documents cannot collide."""

    prefix = f"{namespace}--"
    asset_ids = {asset.id: f"{prefix}{asset.id}" for asset in document.assets}
    page_ids = {page.id: f"{prefix}{page.id}" for page in document.pages}
    assets = [
        asset.model_copy(update={"id": asset_ids[asset.id]})
        for asset in document.assets
    ]
    pages: list[Page] = []
    for page in document.pages:
        sections: list[Section] = []
        for section in page.sections:
            element_ids = {
                element.id: f"{prefix}{element.id}" for element in section.content
            }
            region_ids = {
                region.id: f"{prefix}{region.id}" for region in section.regions
            }
            group_ids = {group.id: f"{prefix}{group.id}" for group in section.groups}
            owner_ids = {**region_ids, **group_ids}
            content = [
                element.model_copy(
                    update={
                        "id": element_ids[element.id],
                        "asset_id": (
                            asset_ids[element.asset_id] if element.asset_id else None
                        ),
                        "group_id": (
                            owner_ids[element.group_id] if element.group_id else None
                        ),
                    }
                )
                for element in section.content
            ]
            regions = [
                region.model_copy(
                    update={
                        "id": region_ids[region.id],
                        "parent_region_id": (
                            region_ids[region.parent_region_id]
                            if region.parent_region_id
                            else None
                        ),
                    }
                )
                for region in section.regions
            ]
            groups = [
                group.model_copy(
                    update={
                        "id": group_ids[group.id],
                        "items": [
                            item.model_copy(
                                update={
                                    "id": f"{prefix}{item.id}",
                                    "fields": {
                                        key: (
                                            [element_ids[value] for value in reference]
                                            if isinstance(reference, list)
                                            else element_ids[reference]
                                        )
                                        for key, reference in item.fields.items()
                                    },
                                }
                            )
                            for item in group.items
                        ],
                    }
                )
                for group in section.groups
            ]
            layers = [
                layer.model_copy(
                    update={
                        "id": f"{prefix}{layer.id}",
                        "asset_id": asset_ids[layer.asset_id] if layer.asset_id else None,
                    }
                )
                for layer in section.decorative_layers
            ]
            interactions = [
                interaction.model_copy(
                    update={
                        "id": f"{prefix}{interaction.id}",
                        "target_element_ids": [
                            element_ids[element_id]
                            for element_id in interaction.target_element_ids
                        ],
                    }
                )
                for interaction in section.interactions
            ]
            sections.append(
                section.model_copy(
                    update={
                        "id": f"{prefix}{section.id}",
                        "content": content,
                        "regions": regions,
                        "groups": groups,
                        "decorative_layers": layers,
                        "interactions": interactions,
                        "metadata": {
                            **section.metadata,
                            "composite_original_id": section.id,
                            "composite_source_id": namespace,
                        },
                    }
                )
            )
        pages.append(
            page.model_copy(
                update={
                    "id": page_ids[page.id],
                    "parent_page_id": (
                        page_ids[page.parent_page_id] if page.parent_page_id else None
                    ),
                    "sections": sections,
                    "metadata": {
                        **page.metadata,
                        "composite_original_id": page.id,
                        "composite_source_id": namespace,
                    },
                }
            )
        )
    return document.model_copy(update={"assets": assets, "pages": pages})


def _merge_tokens(
    primary: DesignTokens, incoming: DesignTokens, source_id: str
) -> DesignTokens:
    return DesignTokens(
        colors=_merge_token_map(primary.colors, incoming.colors, source_id),
        typography=_unique_models(primary.typography + incoming.typography),
        spacing=_merge_token_map(primary.spacing, incoming.spacing, source_id),
        raw={**primary.raw, source_id: incoming.raw},
    )


def _merge_token_map(
    primary: Mapping[str, TokenValue],
    incoming: Mapping[str, TokenValue],
    source_id: str,
) -> dict[str, TokenValue]:
    merged = dict(primary)
    for name, value in incoming.items():
        if name not in merged or merged[name] == value:
            merged.setdefault(name, value)
        else:
            merged[f"{source_id}.{name}"] = value
    return merged


def _unique_models(values: Sequence[Any]) -> list[Any]:
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
    "CompositeDesignInput",
    "DesignMergeError",
    "merge_design_documents",
]
