"""Pure conversion from provider detections to strict image evidence v1."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import JsonValue, ValidationError

from vanjaro_cli.design.image_evidence import (
    ImageAssetEvidence,
    ImageColorEvidence,
    ImageElementEvidence,
    ImageEvidenceProducer,
    ImageEvidenceSet,
    ImageEvidenceWarning,
    ImageLayoutEvidence,
    ImageObservationEvidence,
    ImageRepeatGroupEvidence,
    ImageRepeatItemEvidence,
    ImageSectionEvidence,
    ImageSpacingEvidence,
    ImageStyleEvidence,
    ImageTypographyEvidence,
)
from vanjaro_cli.design.models import AssetKind, ContentKind, EvidenceStatus
from vanjaro_cli.evidence.models import (
    DetectedEvidenceBundle,
    DetectedObservation,
    ImageEvidenceGenerationRequest,
)


class ImageEvidenceNormalizationError(ValueError):
    """Raised when provider output cannot safely own the requested images."""


def normalize_detected_evidence(
    request: ImageEvidenceGenerationRequest,
    detected: DetectedEvidenceBundle,
    *,
    producer_name: str,
    producer_version: str,
    model: str | None,
    prompt_version: str | None,
    metadata: Mapping[str, JsonValue] | None = None,
) -> ImageEvidenceSet:
    """Bind untrusted detections to exact acquired bytes and validate references."""

    requested = {item.source_id: item for item in request.images}
    available = {item.source_id: item for item in detected.observations}
    if set(requested) != set(available):
        missing = sorted(set(requested) - set(available))
        extras = sorted(set(available) - set(requested))
        parts: list[str] = []
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if extras:
            parts.append("unclaimed: " + ", ".join(extras))
        raise ImageEvidenceNormalizationError(
            "provider observations do not exactly own requested source IDs ("
            + "; ".join(parts)
            + ")"
        )

    try:
        observations = [
            _normalize_observation(requested[source_id], available[source_id], request)
            for source_id in sorted(requested)
        ]
        return ImageEvidenceSet(
            producer=ImageEvidenceProducer(
                name=producer_name,
                version=producer_version,
                model=model,
                prompt_version=prompt_version,
                metadata=dict(metadata or {}),
            ),
            observations=observations,
        )
    except ValidationError as exc:
        raise ImageEvidenceNormalizationError(
            f"provider evidence failed the image evidence contract: {exc}"
        ) from exc


def _normalize_observation(image: Any, detected: DetectedObservation, request: Any):
    sections = [
        ImageSectionEvidence(
            id=item.id,
            order=item.order,
            semantic_role=item.semantic_role,
            role_confidence=item.role_confidence,
            candidate_roles=[],
            bounds=item.bounds,
            layout=ImageLayoutEvidence(
                kind=item.layout.kind,
                contained=item.layout.contained,
                columns=item.layout.columns,
                media_position=item.layout.media_position,
                alignment=item.layout.alignment,
                full_bleed=item.layout.full_bleed,
                direction=item.layout.direction,
                wrap=item.layout.wrap,
                metadata={},
            ),
            styles=_styles(item.styles),
            hidden=item.hidden,
            metadata={"provider_source_id": detected.source_id},
        )
        for item in detected.sections
    ]
    elements = []
    for item in detected.elements:
        attributes: dict[str, JsonValue] = {}
        if item.heading_level is not None:
            if item.kind != ContentKind.HEADING:
                raise ImageEvidenceNormalizationError(
                    f"non-heading element {item.id!r} supplied heading_level"
                )
            if not 1 <= item.heading_level <= 6:
                raise ImageEvidenceNormalizationError(
                    f"heading element {item.id!r} has invalid level {item.heading_level}"
                )
            attributes["level"] = item.heading_level
        elements.append(
            ImageElementEvidence(
                id=item.id,
                section_id=item.section_id,
                kind=item.kind,
                role=item.role,
                order=item.order,
                bounds=item.bounds,
                value=item.value,
                attributes=attributes,
                asset_id=item.asset_id,
                group_id=item.group_id,
                styles=_styles(item.styles),
                status=EvidenceStatus.OBSERVED,
                confidence=item.confidence,
                metadata={"provider_source_id": detected.source_id},
            )
        )

    groups = []
    for group in detected.groups:
        repeat_items = []
        for item in group.items:
            fields: dict[str, str | list[str]] = {}
            for field in item.fields:
                if field.name in fields:
                    raise ImageEvidenceNormalizationError(
                        f"repeat item {item.id!r} contains duplicate field {field.name!r}"
                    )
                fields[field.name] = (
                    field.element_ids[0]
                    if len(field.element_ids) == 1
                    else list(field.element_ids)
                )
            repeat_items.append(
                ImageRepeatItemEvidence(
                    id=item.id,
                    fields=fields,
                    confidence=item.confidence,
                )
            )
        groups.append(
            ImageRepeatGroupEvidence(
                id=group.id,
                section_id=group.section_id,
                kind=group.kind,
                items=repeat_items,
                confidence=group.confidence,
            )
        )

    return ImageObservationEvidence(
        source_sha256=image.sha256,
        captured_at=request.captured_at,
        page_slug=image.page_slug,
        page_title=detected.page_title,
        breakpoint=image.breakpoint,
        viewport=image.viewport,
        image_width=image.image_width,
        image_height=image.image_height,
        sections=sections,
        elements=elements,
        groups=groups,
        assets=[
            ImageAssetEvidence(
                id=item.id,
                kind=AssetKind(item.kind),
                role=item.role,
                bounds=item.bounds,
                confidence=item.confidence,
                metadata={"provider_source_id": detected.source_id},
            )
            for item in detected.assets
        ],
        colors=[
            ImageColorEvidence(name=item.name, value=item.value, confidence=item.confidence)
            for item in detected.colors
        ],
        spacing=[
            ImageSpacingEvidence(name=item.name, value=item.value, confidence=item.confidence)
            for item in detected.spacing
        ],
        typography=[
            ImageTypographyEvidence(
                role=item.role,
                font_family=item.font_family,
                font_size=item.font_size,
                font_weight=item.font_weight,
                line_height=item.line_height,
                letter_spacing=item.letter_spacing,
                confidence=item.confidence,
            )
            for item in detected.typography
        ],
        warnings=[
            ImageEvidenceWarning(
                code=item.code,
                message=item.message,
                severity=item.severity,
                evidence_id=item.evidence_id,
            )
            for item in detected.warnings
        ],
        metadata={
            "project_id": request.project_id,
            "provider_source_id": detected.source_id,
        },
    )


def _styles(values: list[Any]) -> list[ImageStyleEvidence]:
    return [
        ImageStyleEvidence(
            property=item.property,
            value=item.value,
            status=EvidenceStatus.OBSERVED,
            confidence=item.confidence,
        )
        for item in values
    ]


__all__ = ["ImageEvidenceNormalizationError", "normalize_detected_evidence"]
