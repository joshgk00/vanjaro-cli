"""Value ranking over the corpus ledger (VF-103).

The ledger says what is wrong everywhere. This says what to fix first, using the
formula the goal declares:

    value = (sites × sections × severity weight × breakpoint weight) / effort

Ranking never touches a score. Changing a weight here changes which work comes
first and nothing about what any build measured, so these weights are
deliberately *not* part of the scoring regime and need no re-baseline.

Effort is an input, not a guess. A cluster with no declared effort ranks at
effort 1.0 and is reported as having used the default, because inventing an
estimate would order real work by a number nobody measured.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from vanjaro_cli.design.finding_ledger import ClusterKind, CorpusLedger, LedgerCluster
from vanjaro_cli.design.models import BreakpointName
from vanjaro_cli.design.reports import ReportSeverity


__all__ = [
    "BREAKPOINT_WEIGHTS",
    "SEVERITY_WEIGHTS",
    "RankedCluster",
    "RankedQueue",
    "rank_ledger",
    "render_ranked_queue",
    "serialize_ranked_queue",
]


SEVERITY_WEIGHTS: dict[ReportSeverity, float] = {
    ReportSeverity.INFO: 0.5,
    ReportSeverity.LOW: 1.0,
    ReportSeverity.MEDIUM: 2.0,
    ReportSeverity.HIGH: 4.0,
}

# Mobile outranks desktop because the ship gate carries a mobile-specific floor,
# so a mobile defect can block a release that the same defect on desktop would
# not.
BREAKPOINT_WEIGHTS: dict[BreakpointName, float] = {
    BreakpointName.DESKTOP: 1.0,
    BreakpointName.TABLET: 1.15,
    BreakpointName.MOBILE: 1.4,
}

# A deficit carries no severity label. An invalidated section is treated as high
# and everything else as medium, which is a ranking choice, not a score.
_DEFICIT_SEVERITY = {True: ReportSeverity.HIGH, False: ReportSeverity.MEDIUM}

DEFAULT_EFFORT = 1.0


class _RankModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RankedCluster(_RankModel):
    """One cluster with its computed value and the inputs that produced it."""

    key: str
    kind: ClusterKind
    value: float = Field(ge=0)
    site_count: int = Field(ge=1)
    section_count: int = Field(ge=1)
    severity_weight: float = Field(gt=0)
    breakpoint_weight: float = Field(gt=0)
    effort: float = Field(gt=0)
    effort_is_default: bool
    breakpoints: tuple[BreakpointName, ...]
    site_ids: tuple[str, ...]
    blocked: bool = False
    blocked_reason: str | None = None


class RankedQueue(_RankModel):
    """The work queue, regenerated from evidence rather than remembered."""

    schema_version: str = "1.0"
    regime_version: int = Field(ge=1)
    site_ids: tuple[str, ...]
    clusters: tuple[RankedCluster, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def next_unblocked(self) -> RankedCluster | None:
        return next(
            (cluster for cluster in self.clusters if not cluster.blocked), None
        )


def _severity_weight(cluster: LedgerCluster) -> float:
    if cluster.kind is ClusterKind.DEFICIT:
        return SEVERITY_WEIGHTS[_DEFICIT_SEVERITY[cluster.forces_zero]]
    if cluster.max_severity is None:
        return SEVERITY_WEIGHTS[ReportSeverity.MEDIUM]
    return SEVERITY_WEIGHTS[cluster.max_severity]


def _breakpoint_weight(cluster: LedgerCluster) -> float:
    """The heaviest breakpoint the cluster touches decides its weight.

    Averaging would let two desktop occurrences dilute one mobile occurrence,
    which is backwards: the mobile instance is the one that can block a ship.
    """

    return max(
        (BREAKPOINT_WEIGHTS.get(value, 1.0) for value in cluster.breakpoints),
        default=1.0,
    )


def rank_ledger(
    ledger: CorpusLedger,
    *,
    effort: Mapping[str, float] | None = None,
    blocked: Mapping[str, str] | None = None,
) -> RankedQueue:
    """Rank every cluster by measured corpus-wide impact over declared effort.

    Blocked clusters keep their value and their evidence and sort last, so the
    reason a cluster is blocked stays visible instead of vanishing from the
    queue.
    """

    effort_by_key = dict(effort or {})
    blocked_by_key = dict(blocked or {})
    warnings: list[str] = []

    for key in sorted(set(effort_by_key) | set(blocked_by_key)):
        if all(cluster.key != key for cluster in ledger.clusters):
            warnings.append(
                f"no cluster named {key!r}; its effort or blocked entry was ignored"
            )

    ranked: list[RankedCluster] = []
    for cluster in ledger.clusters:
        declared = effort_by_key.get(cluster.key)
        if declared is not None and declared <= 0:
            warnings.append(
                f"cluster {cluster.key!r} declared effort {declared}; "
                "a non-positive effort is not usable and the default was applied"
            )
            declared = None
        cluster_effort = DEFAULT_EFFORT if declared is None else declared
        severity_weight = _severity_weight(cluster)
        breakpoint_weight = _breakpoint_weight(cluster)
        value = (
            cluster.site_count
            * cluster.section_count
            * severity_weight
            * breakpoint_weight
        ) / cluster_effort
        ranked.append(
            RankedCluster(
                key=cluster.key,
                kind=cluster.kind,
                value=value,
                site_count=cluster.site_count,
                section_count=cluster.section_count,
                severity_weight=severity_weight,
                breakpoint_weight=breakpoint_weight,
                effort=cluster_effort,
                effort_is_default=declared is None,
                breakpoints=cluster.breakpoints,
                site_ids=cluster.site_ids,
                blocked=cluster.key in blocked_by_key,
                blocked_reason=blocked_by_key.get(cluster.key),
            )
        )

    # Blocked last, then by value, then by key so ties never reorder run to run.
    ranked.sort(key=lambda item: (item.blocked, -item.value, item.key))
    return RankedQueue(
        regime_version=ledger.regime_version,
        site_ids=ledger.site_ids,
        clusters=tuple(ranked),
        warnings=tuple([*ledger.warnings, *warnings]),
    )


def render_ranked_queue(queue: RankedQueue) -> str:
    """Render the queue for a human deciding what to work on next."""

    lines = [
        f"Ranked work queue — regime {queue.regime_version}, "
        f"{len(queue.site_ids)} site(s), {len(queue.clusters)} cluster(s)",
        "",
    ]
    if not queue.clusters:
        lines.append("No clusters. Either nothing is wrong or nothing was measured.")
    for position, cluster in enumerate(queue.clusters, start=1):
        marker = " [BLOCKED]" if cluster.blocked else ""
        lines.append(
            f"{position}. {cluster.key}{marker}  value={cluster.value:.2f}"
        )
        lines.append(
            f"   {cluster.kind.value}: {cluster.site_count} site(s), "
            f"{cluster.section_count} section(s), "
            f"breakpoints {', '.join(value.value for value in cluster.breakpoints)}"
        )
        detail = (
            f"   severity x{cluster.severity_weight:g}, "
            f"breakpoint x{cluster.breakpoint_weight:g}, effort {cluster.effort:g}"
        )
        if cluster.effort_is_default:
            detail += " (default, not estimated)"
        lines.append(detail)
        if cluster.blocked_reason:
            lines.append(f"   blocked: {cluster.blocked_reason}")
        lines.append(f"   sites: {', '.join(cluster.site_ids)}")
    for warning in queue.warnings:
        lines.append(f"warning: {warning}")
    return "\n".join(lines)


def serialize_ranked_queue(queue: RankedQueue) -> str:
    return queue.model_dump_json(indent=2)
