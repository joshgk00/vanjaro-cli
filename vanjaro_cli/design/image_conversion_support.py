"""Focused conversion helpers shared by the pure reference-image adapter."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from vanjaro_cli.design.image_evidence import (
    ImageEvidenceSet,
    ImageObservationEvidence,
    ImageStyleEvidence,
)
from vanjaro_cli.design.models import (
    AssetRecord,
    BoundingBox,
    BreakpointName,
    DesignTokens,
    DesignWarning,
    ObservationMethod,
    Provenance,
    SourceKind,
    StyleObservation,
    StyleSet,
    TokenValue,
    TypographyToken,
)
from vanjaro_cli.design.serialization import stable_design_id


class ImageReferencePathLike(Protocol):
    path: Path


BREAKPOINT_ORDER = {
    BreakpointName.DESKTOP: 0,
    BreakpointName.TABLET: 1,
    BreakpointName.MOBILE: 2,
}


def observation_key(item: ImageObservationEvidence) -> tuple[object, ...]:
    return (
        item.source_sha256,
        item.page_slug.casefold(),
        item.breakpoint.value,
        item.viewport.width,
        item.viewport.height,
    )


def convert_assets(
    observations: Sequence[ImageObservationEvidence],
    evidence: ImageEvidenceSet,
    project_id: str,
) -> tuple[list[AssetRecord], dict[tuple[str, str, str], str]]:
    records: list[AssetRecord] = []
    identifiers: dict[tuple[str, str, str], str] = {}
    for observation in sorted(
        observations,
        key=lambda item: (item.page_slug, BREAKPOINT_ORDER[item.breakpoint], item.source_sha256),
    ):
        for asset in sorted(observation.assets, key=lambda item: item.id):
            identifier = stable_design_id(
                "image-asset",
                project_id,
                observation.page_slug,
                observation.breakpoint.value,
                asset.id,
            )
            identifiers[(observation.source_sha256, observation.breakpoint.value, asset.id)] = identifier
            records.append(
                AssetRecord(
                    id=identifier,
                    kind=asset.kind,
                    role=asset.role,
                    source_url=asset.original_source_url,
                    local_path=asset.original_local_path,
                    mime_type=asset.mime_type,
                    width=round(asset.bounds.width),
                    height=round(asset.bounds.height),
                    alt_text=asset.alt_text,
                    missing_reason=(
                        asset.missing_reason
                        or (
                            None
                            if asset.original_source_url or asset.original_local_path
                            else "Original asset is unavailable from the reference image."
                        )
                    ),
                    provenance=[image_provenance(observation, evidence, asset.id, bounds=asset.bounds)],
                    metadata={
                        **asset.metadata,
                        "image_evidence_id": asset.id,
                        "source_image_sha256": observation.source_sha256,
                        "confidence": asset.confidence,
                    },
                )
            )
    return records, identifiers


def style_set(
    styles: Sequence[ImageStyleEvidence],
    observation: ImageObservationEvidence,
    evidence: ImageEvidenceSet,
    evidence_id: str,
    bounds: BoundingBox,
) -> StyleSet:
    return StyleSet(
        observations=[
            StyleObservation(
                property=item.property,
                value=item.value,
                status=item.status,
                confidence=item.confidence,
                provenance=[image_provenance(observation, evidence, evidence_id, bounds=bounds)],
            )
            for item in styles
        ]
    )


def convert_tokens(
    observations: Sequence[ImageObservationEvidence], evidence: ImageEvidenceSet
) -> DesignTokens:
    colors: dict[str, TokenValue] = {}
    spacing: dict[str, TokenValue] = {}
    typography: list[TypographyToken] = []
    for observation in sorted(
        observations,
        key=lambda item: (item.page_slug, BREAKPOINT_ORDER[item.breakpoint], item.source_sha256),
    ):
        provenance = [image_provenance(observation, evidence, "tokens")]
        for item in observation.colors:
            colors.setdefault(item.name, TokenValue(value=item.value, provenance=provenance))
        for item in observation.spacing:
            spacing.setdefault(item.name, TokenValue(value=item.value, provenance=provenance))
        for item in observation.typography:
            token = TypographyToken(
                role=item.role,
                font_family=item.font_family,
                font_size=item.font_size,
                font_weight=item.font_weight,
                line_height=item.line_height,
                letter_spacing=item.letter_spacing,
                provenance=provenance,
            )
            if token not in typography:
                typography.append(token)
    return DesignTokens(colors=colors, spacing=spacing, typography=typography)


def evidence_warnings(
    observations: Sequence[ImageObservationEvidence],
    evidence: ImageEvidenceSet,
    references: dict[tuple[object, ...], ImageReferencePathLike],
) -> list[DesignWarning]:
    warnings: list[DesignWarning] = []
    for observation in observations:
        reference = references[observation_key(observation)]
        lookup: dict[str, BoundingBox] = {
            item.id: item.bounds
            for values in (observation.sections, observation.elements, observation.assets)
            for item in values
        }
        for item in observation.warnings:
            warnings.append(
                DesignWarning(
                    code=item.code,
                    message=item.message,
                    severity=item.severity,
                    path=item.evidence_id,
                    provenance=[
                        image_provenance(
                            observation,
                            evidence,
                            item.evidence_id or reference.path.as_posix(),
                            bounds=lookup.get(item.evidence_id or ""),
                        )
                    ],
                )
            )
    return warnings


def has_action_target(attributes: dict[str, object]) -> bool:
    return any(
        isinstance(attributes.get(name), str) and bool(str(attributes[name]).strip())
        for name in ("href", "url", "target_url")
    )


def image_provenance(
    observation: ImageObservationEvidence,
    evidence: ImageEvidenceSet,
    evidence_id: str,
    *,
    bounds: BoundingBox | None = None,
    method: ObservationMethod = ObservationMethod.RENDERED,
    base_image: bool = False,
) -> Provenance:
    return Provenance(
        source_kind=SourceKind.IMAGE,
        method=method,
        viewport=observation.breakpoint,
        bounds=bounds,
        metadata={
            "image_evidence_id": evidence_id,
            "source_image_sha256": observation.source_sha256,
            "producer": evidence.producer.name,
            "producer_version": evidence.producer.version,
            "producer_model": evidence.producer.model,
            "prompt_version": evidence.producer.prompt_version,
            "base_image": base_image,
            "viewport": observation.viewport.model_dump(mode="json"),
        },
    )


__all__ = [
    "BREAKPOINT_ORDER",
    "convert_assets",
    "convert_tokens",
    "evidence_warnings",
    "has_action_target",
    "image_provenance",
    "observation_key",
    "style_set",
]
