"""Corpus finding ledger (VF-102): what is wrong, everywhere, grouped by cause.

The ledger answers "what would bring the most value to fix" by refusing to look
at one site at a time. A defect on one section of one site and a defect on
twelve sections across five sites look identical in a per-site report and are
not remotely the same piece of work.

Two kinds of evidence land here. Layer 1 deficits are dimensions that scored
badly, which is authoritative but says nothing about cause. Layer 2 findings are
advisory diagnoses that name a stage and a file. They are kept as separate
cluster kinds rather than merged, because one is measurement and the other is
opinion, and collapsing them would let opinion inherit the authority of a score.

This module is pure. It ranks nothing — ranking is VF-103. It only aggregates,
clusters, and counts, so that ranking has something honest to sort.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vanjaro_cli.design.fidelity import (
    FidelityDimension,
    FidelityReport,
    RegimeMismatchError,
)
from vanjaro_cli.design.models import BreakpointName
from vanjaro_cli.design.reports import (
    FindingCategory,
    PipelineStage,
    ReportFinding,
    ReportSeverity,
)
from vanjaro_cli.design.vision_review import VisionReviewOutcome


__all__ = [
    "ClusterKind",
    "CorpusLedger",
    "LedgerCluster",
    "LedgerOccurrence",
    "SiteEvidence",
    "build_finding_ledger",
    "serialize_ledger",
]


# Below this a dimension is a deficit worth queueing. At or above it the
# dimension is working well enough that the fix belongs behind other work.
DEFICIT_SCORE_CEILING = 75.0

_BREAKPOINT_ORDER = {
    BreakpointName.DESKTOP: 0,
    BreakpointName.TABLET: 1,
    BreakpointName.MOBILE: 2,
}

_SEVERITY_ORDER = {
    ReportSeverity.INFO: 0,
    ReportSeverity.LOW: 1,
    ReportSeverity.MEDIUM: 2,
    ReportSeverity.HIGH: 3,
}


class ClusterKind(str, Enum):
    """Which measurement layer produced a cluster."""

    DEFICIT = "deficit"
    FINDING = "finding"


class _LedgerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SiteEvidence(_LedgerModel):
    """One corpus site's authoritative scores and its advisory findings."""

    site_id: str = Field(min_length=1)
    report: FidelityReport
    review: VisionReviewOutcome | None = None


class LedgerOccurrence(_LedgerModel):
    """One place a cluster's root cause was observed."""

    site_id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    breakpoint: BreakpointName
    detail: str | None = None


class LedgerCluster(_LedgerModel):
    """Every observation sharing one root cause, across the whole corpus."""

    key: str = Field(min_length=1)
    kind: ClusterKind
    occurrences: tuple[LedgerOccurrence, ...] = Field(min_length=1)
    dimension: FidelityDimension | None = None
    pipeline_stage: PipelineStage | None = None
    category: FindingCategory | None = None
    source_file: str | None = None
    max_severity: ReportSeverity | None = None
    forces_zero: bool = False

    @property
    def site_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.site_id for item in self.occurrences}))

    @property
    def site_count(self) -> int:
        return len(self.site_ids)

    @property
    def section_count(self) -> int:
        return len({(item.site_id, item.section_id) for item in self.occurrences})

    @property
    def breakpoints(self) -> tuple[BreakpointName, ...]:
        return tuple(
            sorted(
                {item.breakpoint for item in self.occurrences},
                key=lambda value: _BREAKPOINT_ORDER.get(value, 99),
            )
        )


class CorpusLedger(_LedgerModel):
    """Clustered corpus-wide evidence under one frozen scoring regime."""

    schema_version: str = "1.0"
    regime_version: int = Field(ge=1)
    site_ids: tuple[str, ...] = Field(min_length=1)
    clusters: tuple[LedgerCluster, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_sites(self) -> "CorpusLedger":
        if len(self.site_ids) != len(set(self.site_ids)):
            raise ValueError("each corpus site may appear at most once")
        return self


def _cluster_sort_key(cluster: LedgerCluster) -> tuple[str, str]:
    return (cluster.kind.value, cluster.key)


def _occurrence_sort_key(item: LedgerOccurrence) -> tuple[str, str, int, str]:
    return (
        item.site_id,
        item.section_id,
        _BREAKPOINT_ORDER.get(item.breakpoint, 99),
        item.detail or "",
    )


def _deficit_occurrences(
    evidence: SiteEvidence,
) -> dict[FidelityDimension, tuple[list[LedgerOccurrence], bool]]:
    collected: dict[FidelityDimension, tuple[list[LedgerOccurrence], bool]] = {}
    for breakpoint_score in evidence.report.breakpoints:
        for section in breakpoint_score.sections:
            for dimension_score in section.dimensions:
                # An unmeasured dimension is missing evidence, not a defect.
                # Queueing it would rank "we could not look" as "it is broken".
                if dimension_score.score is None and not dimension_score.forces_zero:
                    continue
                score = 0.0 if dimension_score.forces_zero else dimension_score.score
                if score is None or score >= DEFICIT_SCORE_CEILING:
                    continue
                occurrences, forces_zero = collected.setdefault(
                    dimension_score.dimension, ([], False)
                )
                occurrences.append(
                    LedgerOccurrence(
                        site_id=evidence.site_id,
                        section_id=section.section_id,
                        breakpoint=section.breakpoint,
                        detail=dimension_score.detail,
                    )
                )
                collected[dimension_score.dimension] = (
                    occurrences,
                    forces_zero or dimension_score.forces_zero,
                )
    return collected


def _finding_key(finding: ReportFinding) -> str:
    """Group by the unit someone would actually fix in one change."""

    return "|".join(
        (
            finding.pipeline_stage.value,
            finding.category.value,
            finding.source_file or "unattributed",
        )
    )


def build_finding_ledger(evidence: Sequence[SiteEvidence]) -> CorpusLedger:
    """Cluster Layer 1 deficits and Layer 2 findings across the whole corpus.

    Raises `RegimeMismatchError` when the sites were not scored under one
    regime. Averaging or ranking across regimes compares numbers that mean
    different things, which is the false signal this goal exists to prevent.
    """

    if not evidence:
        raise ValueError("a corpus ledger needs at least one site")

    regimes = {item.report.regime_version for item in evidence}
    if len(regimes) > 1:
        raise RegimeMismatchError(regimes)

    site_ids = tuple(item.site_id for item in evidence)
    deficit_groups: dict[FidelityDimension, tuple[list[LedgerOccurrence], bool]] = {}
    finding_groups: dict[str, list[tuple[ReportFinding, LedgerOccurrence]]] = {}
    warnings: list[str] = []

    for item in evidence:
        for dimension, (occurrences, forces_zero) in _deficit_occurrences(item).items():
            existing, existing_forces = deficit_groups.setdefault(dimension, ([], False))
            existing.extend(occurrences)
            deficit_groups[dimension] = (existing, existing_forces or forces_zero)

        if item.review is None:
            continue
        warnings.extend(f"{item.site_id}: {warning}" for warning in item.review.warnings)
        for finding in item.review.findings:
            if finding.section_id is None or finding.breakpoint is None:
                warnings.append(
                    f"{item.site_id}: finding {finding.id} has no section or breakpoint "
                    "and was not clustered"
                )
                continue
            finding_groups.setdefault(_finding_key(finding), []).append(
                (
                    finding,
                    LedgerOccurrence(
                        site_id=item.site_id,
                        section_id=finding.section_id,
                        breakpoint=finding.breakpoint,
                        detail=finding.message,
                    ),
                )
            )

    clusters: list[LedgerCluster] = []
    for dimension, (occurrences, forces_zero) in deficit_groups.items():
        clusters.append(
            LedgerCluster(
                key=dimension.value,
                kind=ClusterKind.DEFICIT,
                dimension=dimension,
                forces_zero=forces_zero,
                occurrences=tuple(sorted(occurrences, key=_occurrence_sort_key)),
            )
        )
    for key, grouped in finding_groups.items():
        first = grouped[0][0]
        clusters.append(
            LedgerCluster(
                key=key,
                kind=ClusterKind.FINDING,
                pipeline_stage=first.pipeline_stage,
                category=first.category,
                source_file=first.source_file,
                max_severity=max(
                    (finding.severity for finding, _ in grouped),
                    key=lambda value: _SEVERITY_ORDER[value],
                ),
                occurrences=tuple(
                    sorted(
                        (occurrence for _, occurrence in grouped),
                        key=_occurrence_sort_key,
                    )
                ),
            )
        )

    return CorpusLedger(
        regime_version=regimes.pop(),
        site_ids=site_ids,
        clusters=tuple(sorted(clusters, key=_cluster_sort_key)),
        warnings=tuple(warnings),
    )


def serialize_ledger(ledger: CorpusLedger) -> str:
    """Serialize deterministically so two identical runs produce identical bytes."""

    return ledger.model_dump_json(indent=2)


