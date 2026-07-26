"""Pure conversion from validated reference-image evidence to Design Document v1."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from vanjaro_cli.design.image_evidence import (
    ImageEvidenceSet,
    ImageObservationEvidence,
    ImageSectionEvidence,
)
from vanjaro_cli.design.image_conversion_support import (
    BREAKPOINT_ORDER,
    convert_assets,
    convert_tokens,
    evidence_warnings,
    has_action_target,
    image_provenance,
    observation_key,
    style_set,
)
from vanjaro_cli.design.models import (
    BreakpointName,
    ContentElement,
    ContentKind,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignWarning,
    EvidenceStatus,
    LayoutObservation,
    NavigationVisibility,
    ObservationMethod,
    Page,
    RepeatGroup,
    RepeatGroupItem,
    ResponsiveObservation,
    Section,
    SourceKind,
    WarningSeverity,
)
from vanjaro_cli.design.serialization import stable_design_id


class ImageEvidenceConversionError(ValueError):
    """Raised when validated evidence does not exactly own the request images."""


class ReferenceImageLike(Protocol):
    path: Path
    page_slug: str
    breakpoint: BreakpointName
    viewport_width: int
    viewport_height: int
    sha256: str


def design_document_from_image_evidence(
    images: Sequence[ReferenceImageLike],
    evidence: ImageEvidenceSet,
    *,
    project_id: str,
    captured_at: datetime | None = None,
) -> DesignDocument:
    """Convert exact, pre-acquired evidence without filesystem or network I/O.

    Orchestration must hash the image bytes and construct ``ReferenceImage``
    records before calling this function.  Every request image must match one
    and only one evidence observation, and unclaimed observations are rejected.
    """

    observations = _owned_observations(images, evidence)
    references = _reference_map(images)
    assets, asset_ids = convert_assets(observations, evidence, project_id)
    warnings = evidence_warnings(observations, evidence, references)
    pages: list[Page] = []
    confidences: list[float] = []
    unsupported: list[str] = []

    by_page: dict[str, list[ImageObservationEvidence]] = defaultdict(list)
    for observation in observations:
        by_page[observation.page_slug].append(observation)

    for page_slug in sorted(by_page):
        variants = sorted(
            by_page[page_slug],
            key=lambda item: (BREAKPOINT_ORDER[item.breakpoint], item.source_sha256),
        )
        breakpoints = [item.breakpoint for item in variants]
        if len(breakpoints) != len(set(breakpoints)):
            raise ImageEvidenceConversionError(
                f"page {page_slug!r} has more than one image for the same breakpoint"
            )
        base = variants[0]
        page_id = stable_design_id("image-page", project_id, page_slug)
        sections: list[Section] = []
        for source_section in sorted(base.sections, key=lambda item: (item.order, item.id)):
            section, section_warnings = _convert_section(
                source_section,
                base,
                variants,
                evidence,
                project_id,
                asset_ids,
            )
            sections.append(section)
            warnings.extend(section_warnings)
            confidences.append(source_section.role_confidence)
        missing = {
            BreakpointName.DESKTOP,
            BreakpointName.MOBILE,
        } - set(breakpoints)
        for breakpoint in sorted(missing, key=lambda item: BREAKPOINT_ORDER[item]):
            warnings.append(
                DesignWarning(
                    code="IMAGE_BREAKPOINT_MISSING",
                    message=(
                        f"Page {page_slug!r} has no observed {breakpoint.value} image; "
                        "responsive behavior was not fabricated."
                    ),
                    path=page_id,
                    provenance=[image_provenance(base, evidence, page_slug, base_image=True)],
                )
            )
            unsupported.append(f"missing_{breakpoint.value}_image_evidence")
        title = base.page_title or page_slug.replace("-", " ").title()
        if base.page_title is None:
            warnings.append(
                DesignWarning(
                    code="IMAGE_PAGE_TITLE_INFERRED",
                    severity=WarningSeverity.INFO,
                    message=f"Page title for {page_slug!r} was inferred from its explicit slug.",
                    path=page_id,
                    provenance=[image_provenance(base, evidence, page_slug, method=ObservationMethod.INFERRED)],
                )
            )
        reference = references[observation_key(base)]
        pages.append(
            Page(
                id=page_id,
                source_reference=reference.path.as_posix(),
                title=title,
                slug="" if page_slug.casefold() == "home" else page_slug,
                sections=sections,
                breakpoints=breakpoints,
                navigation_visibility=NavigationVisibility.UNKNOWN,
                provenance=[image_provenance(base, evidence, page_id, base_image=True)],
                metadata={
                    "image_page_slug": page_slug,
                    "base_breakpoint": base.breakpoint.value,
                    "title_inferred": base.page_title is None,
                    "observed_image_sha256": [item.source_sha256 for item in variants],
                },
            )
        )

    for warning in warnings:
        if warning.code == "IMAGE_ORIGINAL_ASSET_UNAVAILABLE":
            unsupported.append("original_asset_unavailable_from_reference_image")
        elif warning.code == "IMAGE_ACTION_TARGET_UNKNOWN":
            unsupported.append("action_target_unavailable_from_reference_image")

    capture_time = captured_at or max(item.captured_at for item in observations)
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.IMAGE,
            identifier=f"image-set:{project_id}",
            captured_at=capture_time,
            adapter_version="image-evidence/1.0",
            metadata={
                "producer": evidence.producer.model_dump(mode="json"),
                "images": [
                    {
                        "path": reference.path.as_posix(),
                        "sha256": reference.sha256,
                        "page_slug": reference.page_slug,
                        "breakpoint": reference.breakpoint.value,
                        "viewport": {
                            "width": reference.viewport_width,
                            "height": reference.viewport_height,
                        },
                    }
                    for reference in sorted(
                        images,
                        key=lambda item: (
                            item.page_slug.casefold(),
                            BREAKPOINT_ORDER[item.breakpoint],
                            item.sha256,
                        ),
                    )
                ],
            },
        ),
        tokens=convert_tokens(observations, evidence),
        assets=assets,
        pages=pages,
        warnings=warnings,
        analysis=DesignAnalysis(
            section_confidence_mean=(sum(confidences) / len(confidences) if confidences else 0.0),
            unsupported_traits=list(dict.fromkeys(unsupported)),
            metadata={
                "evidence_schema_version": evidence.schema_version,
                "observation_count": len(observations),
            },
        ),
    )


def _owned_observations(
    images: Sequence[ReferenceImageLike], evidence: ImageEvidenceSet
) -> list[ImageObservationEvidence]:
    requested = [_reference_key(item) for item in images]
    if len(requested) != len(set(requested)):
        raise ImageEvidenceConversionError("reference images must have unique evidence ownership")
    available = {observation_key(item): item for item in evidence.observations}
    missing = [key for key in requested if key not in available]
    if missing:
        raise ImageEvidenceConversionError(
            "image evidence does not match request hash/page/breakpoint/viewport: "
            + ", ".join(_format_key(key) for key in missing)
        )
    extras = sorted(set(available) - set(requested))
    if extras:
        raise ImageEvidenceConversionError(
            "image evidence contains unclaimed observations: "
            + ", ".join(_format_key(key) for key in extras)
        )
    return [available[key] for key in requested]


def _reference_map(images: Sequence[ReferenceImageLike]) -> dict[tuple[object, ...], ReferenceImageLike]:
    return {_reference_key(item): item for item in images}


def _reference_key(item: ReferenceImageLike) -> tuple[object, ...]:
    return (
        item.sha256,
        item.page_slug.casefold(),
        item.breakpoint.value,
        item.viewport_width,
        item.viewport_height,
    )


def _format_key(key: tuple[object, ...]) -> str:
    return f"{key[1]}:{key[2]}:{key[3]}x{key[4]}:{str(key[0])[:12]}"


def _convert_section(
    source: ImageSectionEvidence,
    base: ImageObservationEvidence,
    variants: Sequence[ImageObservationEvidence],
    evidence: ImageEvidenceSet,
    project_id: str,
    asset_ids: dict[tuple[str, str, str], str],
) -> tuple[Section, list[DesignWarning]]:
    section_id = stable_design_id("image-section", project_id, base.page_slug, source.id)
    source_elements = sorted(
        (item for item in base.elements if item.section_id == source.id),
        key=lambda item: (item.order, item.id),
    )
    element_ids = {
        item.id: stable_design_id("image-element", project_id, base.page_slug, source.id, item.id)
        for item in source_elements
    }
    source_groups = sorted(
        (item for item in base.groups if item.section_id == source.id), key=lambda item: item.id
    )
    group_ids = {
        item.id: stable_design_id("image-group", project_id, base.page_slug, source.id, item.id)
        for item in source_groups
    }
    warnings: list[DesignWarning] = []
    content: list[ContentElement] = []
    for item in source_elements:
        attributes = dict(item.attributes)
        if item.kind in {ContentKind.BUTTON, ContentKind.LINK} and not has_action_target(attributes):
            warnings.append(
                DesignWarning(
                    code="IMAGE_ACTION_TARGET_UNKNOWN",
                    message=(
                        f"Action {item.role!r} has visible content but no observed target; "
                        "no href was fabricated."
                    ),
                    path=element_ids[item.id],
                    provenance=[image_provenance(base, evidence, item.id, bounds=item.bounds, method=ObservationMethod.INFERRED)],
                )
            )
        content.append(
            ContentElement(
                id=element_ids[item.id],
                kind=item.kind,
                role=item.role,
                value=item.value,
                attributes=attributes,
                asset_id=(
                    asset_ids[(base.source_sha256, base.breakpoint.value, item.asset_id)]
                    if item.asset_id is not None
                    else None
                ),
                group_id=group_ids.get(item.group_id or ""),
                order=item.order,
                style=style_set(item.styles, base, evidence, item.id, item.bounds),
                provenance=[image_provenance(base, evidence, item.id, bounds=item.bounds, method=ObservationMethod.INFERRED)],
                confidence=item.confidence,
                metadata={
                    **item.metadata,
                    "image_evidence_id": item.id,
                    "evidence_status": item.status.value,
                    "bounds": item.bounds.model_dump(mode="json"),
                },
            )
        )
    groups = [
        RepeatGroup(
            id=group_ids[group.id],
            kind=group.kind,
            items=[
                RepeatGroupItem(
                    id=stable_design_id("image-repeat-item", project_id, base.page_slug, group.id, item.id),
                    fields={
                        field: (
                            [element_ids[value] for value in reference]
                            if isinstance(reference, list)
                            else element_ids[reference]
                        )
                        for field, reference in item.fields.items()
                    },
                    provenance=[image_provenance(base, evidence, item.id, method=ObservationMethod.INFERRED)],
                )
                for item in group.items
            ],
            provenance=[image_provenance(base, evidence, group.id, method=ObservationMethod.INFERRED)],
        )
        for group in source_groups
    ]
    responsive: list[ResponsiveObservation] = []
    for variant in variants:
        if variant is base:
            continue
        paired = _paired_section(source, variant)
        if paired is None:
            warnings.append(
                DesignWarning(
                    code="IMAGE_RESPONSIVE_SECTION_UNMATCHED",
                    message=(
                        f"Section {source.id!r} has no {variant.breakpoint.value} evidence match; "
                        "no responsive behavior was invented."
                    ),
                    path=section_id,
                    provenance=[image_provenance(variant, evidence, source.id, method=ObservationMethod.INFERRED)],
                )
            )
            continue
        responsive.append(
            ResponsiveObservation(
                breakpoint=variant.breakpoint,
                viewport=variant.viewport,
                status=EvidenceStatus.OBSERVED,
                layout_changes=_absolute_layout(paired),
                style=style_set(paired.styles, variant, evidence, paired.id, paired.bounds),
                hidden=paired.hidden,
                provenance=[image_provenance(variant, evidence, paired.id, bounds=paired.bounds)],
            )
        )
    for item in source_elements:
        if item.asset_id is not None:
            asset = next(asset for asset in base.assets if asset.id == item.asset_id)
            if not asset.original_source_url and not asset.original_local_path:
                warnings.append(
                    DesignWarning(
                        code="IMAGE_ORIGINAL_ASSET_UNAVAILABLE",
                        message=(
                            f"Media {item.role!r} is visible only inside the reference image; "
                            "an original editable asset must be supplied or cropped by orchestration."
                        ),
                        path=element_ids[item.id],
                        provenance=[image_provenance(base, evidence, asset.id, bounds=asset.bounds)],
                    )
                )
    return (
        Section(
            id=section_id,
            order=source.order,
            semantic_role=source.semantic_role,
            role_confidence=source.role_confidence,
            candidate_roles=source.candidate_roles,
            layout=_layout(source),
            content=content,
            groups=groups,
            style=style_set(source.styles, base, evidence, source.id, source.bounds),
            responsive=responsive,
            decorative_layers=[],
            interactions=[],
            provenance=[image_provenance(base, evidence, source.id, bounds=source.bounds)],
            metadata={
                **source.metadata,
                "image_evidence_id": source.id,
                "bounds": source.bounds.model_dump(mode="json"),
            },
        ),
        warnings,
    )


def _layout(section: ImageSectionEvidence) -> LayoutObservation:
    value = section.layout
    return LayoutObservation(
        kind=value.kind,
        contained=value.contained,
        columns=value.columns,
        media_position=value.media_position,
        alignment=value.alignment,
        full_bleed=value.full_bleed,
        direction=value.direction,
        wrap=value.wrap,
        metadata=value.metadata,
    )


def _absolute_layout(section: ImageSectionEvidence) -> dict[str, object]:
    value = section.layout
    result: dict[str, object] = {
        "kind": value.kind.value,
        "contained": value.contained,
        "full_bleed": value.full_bleed,
    }
    for name in ("columns", "direction", "wrap"):
        item = getattr(value, name)
        if item is not None:
            result[name] = item
    if value.media_position is not None:
        result["media_position"] = value.media_position.value
    if value.alignment is not None:
        result["alignment"] = value.alignment.value
    return result


def _paired_section(
    source: ImageSectionEvidence, variant: ImageObservationEvidence
) -> ImageSectionEvidence | None:
    exact = next((item for item in variant.sections if item.id == source.id), None)
    if exact is not None:
        return exact
    matches = [
        item
        for item in variant.sections
        if item.order == source.order and item.semantic_role == source.semantic_role
    ]
    return matches[0] if len(matches) == 1 else None


__all__ = [
    "ImageEvidenceConversionError",
    "ReferenceImageLike",
    "design_document_from_image_evidence",
]
