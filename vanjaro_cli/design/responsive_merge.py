"""Source-neutral responsive composition for explicitly paired design pages.

The canonical page owns editable content and section structure.  Lower-priority
viewport evidence becomes observed responsive evidence without making the
matcher or planner aware of the originating adapter.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from typing import Sequence

from vanjaro_cli.design.models import (
    BreakpointName,
    DesignWarning,
    EvidenceStatus,
    Page,
    ResponsiveObservation,
    Section,
    Viewport,
    WarningSeverity,
)
from vanjaro_cli.design.responsive_evidence import (
    content_signature,
    group_signature,
    layout_delta,
    merge_content_provenance,
    overlay_observation,
    overlay_style,
    unique_models,
)


_BREAKPOINT_ORDER = {
    BreakpointName.DESKTOP: 0,
    BreakpointName.TABLET: 1,
    BreakpointName.MOBILE: 2,
}
_CANONICAL_VIEWPORTS = {
    BreakpointName.DESKTOP: Viewport(width=1440, height=900),
    BreakpointName.TABLET: Viewport(width=768, height=1024),
    BreakpointName.MOBILE: Viewport(width=390, height=844),
}


@dataclass(frozen=True, slots=True)
class PairedPageEvidence:
    """One namespaced page and the project source that produced it."""

    source_id: str
    page: Page


@dataclass(frozen=True, slots=True)
class PairedPageMergeResult:
    page: Page
    warnings: tuple[DesignWarning, ...]


def merge_paired_page_evidence(
    page_reference: str,
    evidence: Sequence[PairedPageEvidence],
) -> PairedPageMergeResult:
    """Choose a canonical viewport and merge all secondary evidence into it."""

    if not evidence:
        raise ValueError("paired page evidence must not be empty")
    ordered = sorted(evidence, key=_canonical_sort_key)
    canonical = ordered[0]
    page = canonical.page
    warnings: list[DesignWarning] = []
    canonical_breakpoint = evidence_breakpoint(canonical.page)

    for secondary in ordered[1:]:
        page, secondary_warnings = _merge_secondary_page(
            page_reference,
            page,
            canonical.source_id,
            canonical_breakpoint,
            secondary,
        )
        warnings.extend(secondary_warnings)

    sources = sorted({item.source_id for item in evidence}, key=str.casefold)
    breakpoints = sorted(
        {breakpoint for item in evidence for breakpoint in item.page.breakpoints},
        key=lambda value: _BREAKPOINT_ORDER[value],
    )
    page = page.model_copy(
        update={
            "breakpoints": breakpoints,
            "provenance": unique_models(
                [value for item in ordered for value in item.page.provenance]
            ),
            "metadata": {
                **page.metadata,
                "canonical_project_source": canonical.source_id,
                "canonical_breakpoint": (
                    canonical_breakpoint.value if canonical_breakpoint else None
                ),
                "merged_project_sources": sources,
                "responsive_merge_policy": "canonical-breakpoint-v1",
            },
        }
    )
    if canonical_breakpoint is None:
        warnings.append(
            DesignWarning(
                code="paired_page_breakpoint_unknown",
                severity=WarningSeverity.WARNING,
                path=f"pages[{page_reference}]",
                message=(
                    f"Paired page {page_reference!r} has no declared breakpoint; "
                    f"source {canonical.source_id!r} was chosen deterministically "
                    "but responsive priority could not be established."
                ),
                provenance=page.provenance,
            )
        )
    return PairedPageMergeResult(page=page, warnings=tuple(warnings))


def evidence_breakpoint(page: Page) -> BreakpointName | None:
    """Return the strongest explicit viewport represented by one source page."""

    for key in ("source_breakpoint", "project_breakpoint", "breakpoint"):
        raw = page.metadata.get(key)
        try:
            if isinstance(raw, str):
                return BreakpointName(raw)
        except ValueError:
            pass
    provenance_values = {
        provenance.viewport
        for provenance in page.provenance
        if provenance.viewport is not None
    }
    if len(provenance_values) == 1:
        return next(iter(provenance_values))
    if not page.breakpoints:
        return None
    return min(page.breakpoints, key=lambda value: _BREAKPOINT_ORDER[value])


def _canonical_sort_key(item: PairedPageEvidence) -> tuple[int, str, str]:
    breakpoint = evidence_breakpoint(item.page)
    priority = _BREAKPOINT_ORDER.get(breakpoint, len(_BREAKPOINT_ORDER))
    return priority, item.source_id.casefold(), item.page.id


def _merge_secondary_page(
    page_reference: str,
    canonical: Page,
    canonical_source_id: str,
    canonical_breakpoint: BreakpointName | None,
    secondary: PairedPageEvidence,
) -> tuple[Page, list[DesignWarning]]:
    sections = list(canonical.sections)
    warnings: list[DesignWarning] = []
    used: set[int] = set()
    secondary_breakpoint = evidence_breakpoint(secondary.page)

    for secondary_section in sorted(
        secondary.page.sections, key=lambda item: (item.order, item.id)
    ):
        candidates = [
            (index, section)
            for index, section in enumerate(sections)
            if index not in used
            and section.metadata.get("composite_source_id") == canonical_source_id
        ]
        match, ambiguous = _match_section(secondary_section, candidates)
        if match is None:
            status = "ambiguous" if ambiguous else "unmatched"
            sections.append(
                secondary_section.model_copy(
                    update={
                        "metadata": {
                            **secondary_section.metadata,
                            "responsive_pairing_status": status,
                            "responsive_pairing_reference": page_reference,
                        }
                    }
                )
            )
            warnings.append(
                DesignWarning(
                    code=(
                        "ambiguous_paired_section"
                        if ambiguous
                        else "unmatched_paired_section"
                    ),
                    severity=WarningSeverity.WARNING,
                    path=f"pages[{page_reference}].sections[{secondary_section.id}]",
                    message=(
                        f"Section {secondary_section.id!r} from source "
                        f"{secondary.source_id!r} could not be paired "
                        f"{'unambiguously' if ambiguous else 'with a canonical section'}; "
                        "it was retained as a separate review section."
                    ),
                    provenance=secondary_section.provenance,
                )
            )
            continue

        index, primary_section = match
        used.add(index)
        merged, section_warnings = _merge_section_evidence(
            page_reference,
            primary_section,
            secondary_section,
            secondary.source_id,
            canonical_breakpoint,
            secondary_breakpoint,
        )
        sections[index] = merged
        warnings.extend(section_warnings)

    normalized = [
        section.model_copy(update={"order": order})
        for order, section in enumerate(sections)
    ]
    return (
        canonical.model_copy(update={"sections": normalized}),
        warnings,
    )


def _match_section(
    secondary: Section,
    candidates: Sequence[tuple[int, Section]],
) -> tuple[tuple[int, Section] | None, bool]:
    original_id = secondary.metadata.get("composite_original_id")
    exact_id = [
        item
        for item in candidates
        if original_id
        and item[1].metadata.get("composite_original_id") == original_id
    ]
    if len(exact_id) == 1:
        return exact_id[0], False
    if len(exact_id) > 1:
        return None, True

    same_role = [
        item for item in candidates if item[1].semantic_role == secondary.semantic_role
    ]
    same_order = [item for item in same_role if item[1].order == secondary.order]
    if len(same_order) == 1:
        return same_order[0], False
    if len(same_role) == 1:
        return same_role[0], False
    return None, len(same_role) > 1


def _merge_section_evidence(
    page_reference: str,
    primary: Section,
    secondary: Section,
    source_id: str,
    canonical_breakpoint: BreakpointName | None,
    secondary_breakpoint: BreakpointName | None,
) -> tuple[Section, list[DesignWarning]]:
    warnings: list[DesignWarning] = []
    responsive = {
        item.breakpoint: item for item in primary.responsive
    }
    incoming = list(secondary.responsive)
    if secondary_breakpoint is not None and secondary_breakpoint != canonical_breakpoint:
        incoming.append(
            _base_responsive_observation(primary, secondary, secondary_breakpoint)
        )
    elif secondary_breakpoint == canonical_breakpoint and (
        primary.layout != secondary.layout or primary.style != secondary.style
    ):
        warnings.append(
            DesignWarning(
                code="duplicate_paired_breakpoint_conflict",
                severity=WarningSeverity.WARNING,
                path=f"pages[{page_reference}].sections[{secondary.id}]",
                message=(
                    f"Source {source_id!r} supplies conflicting "
                    f"{secondary_breakpoint.value if secondary_breakpoint else 'unknown'} "
                    "layout/style evidence at the canonical breakpoint; canonical values "
                    "were retained for review."
                ),
                provenance=secondary.provenance,
            )
        )

    for observation in incoming:
        current = responsive.get(observation.breakpoint)
        if current is None:
            responsive[observation.breakpoint] = observation
            continue
        if current != observation and (
            current.status == EvidenceStatus.OBSERVED
            and observation.status == EvidenceStatus.OBSERVED
        ):
            warnings.append(
                DesignWarning(
                    code="paired_responsive_observation_conflict",
                    severity=WarningSeverity.WARNING,
                    path=f"pages[{page_reference}].sections[{secondary.id}]",
                    message=(
                        f"Source {source_id!r} conflicts with existing observed "
                        f"{observation.breakpoint.value} evidence; the explicitly paired "
                        "secondary observation takes precedence and both provenances are retained."
                    ),
                    provenance=unique_models(
                        current.provenance + observation.provenance
                    ),
                )
            )
        responsive[observation.breakpoint] = overlay_observation(
            current, observation
        )

    content, unmatched_secondary = merge_content_provenance(
        primary.content, secondary.content, source_id
    )
    content_differs = Counter(map(content_signature, primary.content)) != Counter(
        map(content_signature, secondary.content)
    )
    groups_differ = Counter(map(group_signature, primary.groups)) != Counter(
        map(group_signature, secondary.groups)
    )
    difference_records = list(primary.metadata.get("paired_evidence_differences", []))
    if content_differs or groups_differ:
        difference_records.append(
            {
                "source_id": source_id,
                "breakpoint": (
                    secondary_breakpoint.value if secondary_breakpoint else None
                ),
                "secondary_section_id": secondary.id,
                "unmatched_secondary_content_ids": unmatched_secondary,
                "secondary_group_ids": [group.id for group in secondary.groups],
            }
        )
        warnings.append(
            DesignWarning(
                code="paired_section_structure_divergence",
                severity=WarningSeverity.WARNING,
                path=f"pages[{page_reference}].sections[{secondary.id}]",
                message=(
                    f"Source {source_id!r} has different visitor content or repeat-group "
                    "ownership for paired section; canonical editable structure was retained "
                    "and the divergence was recorded for review."
                ),
                provenance=secondary.provenance,
            )
        )

    merged_sources = sorted(
        {
            *primary.metadata.get("merged_project_sources", []),
            source_id,
        },
        key=str.casefold,
    )
    merged = primary.model_copy(
        update={
            "content": content,
            "responsive": [
                responsive[breakpoint]
                for breakpoint in sorted(responsive, key=lambda value: _BREAKPOINT_ORDER[value])
            ],
            "provenance": unique_models(primary.provenance + secondary.provenance),
            "candidate_roles": unique_models(
                primary.candidate_roles + secondary.candidate_roles
            ),
            "metadata": {
                **primary.metadata,
                "merged_project_sources": merged_sources,
                **(
                    {"paired_evidence_differences": difference_records}
                    if difference_records
                    else {}
                ),
            },
        }
    )
    return merged, warnings


def _base_responsive_observation(
    primary: Section,
    secondary: Section,
    breakpoint: BreakpointName,
) -> ResponsiveObservation:
    existing = next(
        (item for item in secondary.responsive if item.breakpoint == breakpoint),
        None,
    )
    layout_changes = layout_delta(primary, secondary)
    style = secondary.style
    provenance = list(secondary.provenance)
    hidden = None
    viewport = _CANONICAL_VIEWPORTS[breakpoint]
    if existing is not None:
        layout_changes.update(existing.layout_changes)
        style = overlay_style(style, existing.style)
        provenance.extend(existing.provenance)
        hidden = existing.hidden
        viewport = existing.viewport
    return ResponsiveObservation(
        breakpoint=breakpoint,
        viewport=viewport,
        status=EvidenceStatus.OBSERVED,
        layout_changes=layout_changes,
        style=style,
        hidden=hidden,
        provenance=unique_models(provenance),
    )


__all__ = [
    "PairedPageEvidence",
    "PairedPageMergeResult",
    "evidence_breakpoint",
    "merge_paired_page_evidence",
]
