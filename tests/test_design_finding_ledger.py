"""Tests for the corpus finding ledger (VF-102)."""

from __future__ import annotations

import pytest

from vanjaro_cli.design.fidelity import (
    BreakpointFidelityScore,
    DimensionScore,
    FidelityDimension,
    FidelityReport,
    RegimeMismatchError,
    SectionFidelityScore,
)
from vanjaro_cli.design.finding_ledger import (
    ClusterKind,
    SiteEvidence,
    build_finding_ledger,
    serialize_ledger,
)
from vanjaro_cli.design.models import BreakpointName
from vanjaro_cli.design.reports import (
    FindingCategory,
    PipelineStage,
    ReportFinding,
    ReportSeverity,
)
from vanjaro_cli.design.vision_review import VisionReviewOutcome


def _section(
    section_id: str,
    breakpoint: BreakpointName,
    dimensions: dict[FidelityDimension, float | None],
    *,
    forces_zero: FidelityDimension | None = None,
) -> SectionFidelityScore:
    return SectionFidelityScore(
        regime_version=1,
        section_id=section_id,
        breakpoint=breakpoint,
        dimensions=tuple(
            DimensionScore(
                dimension=dimension,
                score=score,
                forces_zero=dimension is forces_zero,
                detail="placeholder text leaked" if dimension is forces_zero else None,
            )
            for dimension, score in dimensions.items()
        ),
    )


def _report(
    page_id: str,
    sections: dict[BreakpointName, list[SectionFidelityScore]],
    *,
    regime_version: int = 1,
) -> FidelityReport:
    return FidelityReport(
        regime_version=regime_version,
        page_id=page_id,
        breakpoints=tuple(
            BreakpointFidelityScore(
                regime_version=regime_version,
                breakpoint=breakpoint,
                sections=tuple(entries),
            )
            for breakpoint, entries in sections.items()
        ),
    )


def _simple_report(
    page_id: str,
    *,
    color: float | None = 100.0,
    layout: float | None = 100.0,
    breakpoint: BreakpointName = BreakpointName.DESKTOP,
    section_id: str = "s1",
    regime_version: int = 1,
) -> FidelityReport:
    section = SectionFidelityScore(
        regime_version=regime_version,
        section_id=section_id,
        breakpoint=breakpoint,
        dimensions=(
            DimensionScore(dimension=FidelityDimension.COLOR, score=color),
            DimensionScore(dimension=FidelityDimension.LAYOUT, score=layout),
        ),
    )
    return _report(page_id, {breakpoint: [section]}, regime_version=regime_version)


def _finding(
    finding_id: str,
    *,
    section_id: str = "s1",
    breakpoint: BreakpointName = BreakpointName.DESKTOP,
    stage: PipelineStage = PipelineStage.STYLE_TRANSLATION,
    category: FindingCategory = FindingCategory.STYLE,
    source_file: str | None = "vanjaro_cli/design/style_translation.py",
    severity: ReportSeverity = ReportSeverity.MEDIUM,
) -> ReportFinding:
    return ReportFinding(
        id=finding_id,
        severity=severity,
        category=category,
        message=f"message for {finding_id}",
        recommendation="fix it",
        pipeline_stage=stage,
        section_id=section_id,
        breakpoint=breakpoint,
        source_file=source_file,
    )


def _cluster(ledger, key: str):
    return next(cluster for cluster in ledger.clusters if cluster.key == key)


def test_a_deficit_becomes_a_cluster_and_a_healthy_dimension_does_not() -> None:
    ledger = build_finding_ledger(
        [SiteEvidence(site_id="alpha", report=_simple_report("home", color=40.0))]
    )

    assert [cluster.key for cluster in ledger.clusters] == ["color"]
    assert _cluster(ledger, "color").kind is ClusterKind.DEFICIT


def test_an_unmeasured_dimension_is_not_a_defect() -> None:
    """Queueing it would rank "we could not look" as "it is broken"."""

    ledger = build_finding_ledger(
        [SiteEvidence(site_id="alpha", report=_simple_report("home", color=None))]
    )

    assert ledger.clusters == ()


def test_a_forced_zero_is_a_deficit_even_without_a_score() -> None:
    section = _section(
        "s1",
        BreakpointName.DESKTOP,
        {FidelityDimension.MEDIA: None},
        forces_zero=FidelityDimension.MEDIA,
    )
    ledger = build_finding_ledger(
        [SiteEvidence(site_id="alpha", report=_report("home", {BreakpointName.DESKTOP: [section]}))]
    )

    cluster = _cluster(ledger, "media")
    assert cluster.forces_zero is True


def test_one_cause_across_sites_becomes_one_cluster_keeping_every_site() -> None:
    ledger = build_finding_ledger(
        [
            SiteEvidence(site_id="alpha", report=_simple_report("home", color=30.0)),
            SiteEvidence(site_id="beta", report=_simple_report("home", color=20.0)),
        ]
    )

    cluster = _cluster(ledger, "color")
    assert cluster.site_count == 2
    assert cluster.site_ids == ("alpha", "beta")
    assert len(cluster.occurrences) == 2


def test_a_widespread_defect_and_a_local_one_stay_distinguishable() -> None:
    """The whole point: twelve sections across five sites is not one section."""

    wide = [
        SiteEvidence(
            site_id=f"site{index}",
            report=_simple_report("home", color=30.0, section_id=f"s{index}"),
        )
        for index in range(5)
    ]
    narrow = SiteEvidence(
        site_id="lonely", report=_simple_report("home", layout=10.0, color=100.0)
    )

    ledger = build_finding_ledger([*wide, narrow])

    assert _cluster(ledger, "color").site_count == 5
    assert _cluster(ledger, "layout").site_count == 1


def test_findings_cluster_by_stage_category_and_file() -> None:
    review = VisionReviewOutcome(
        findings=(
            _finding("a"),
            _finding("b", section_id="s2"),
            _finding("c", source_file="vanjaro_cli/design/planner.py"),
        )
    )
    ledger = build_finding_ledger(
        [SiteEvidence(site_id="alpha", report=_simple_report("home"), review=review)]
    )

    finding_clusters = [c for c in ledger.clusters if c.kind is ClusterKind.FINDING]
    assert len(finding_clusters) == 2
    shared = _cluster(
        ledger, "style_translation|style|vanjaro_cli/design/style_translation.py"
    )
    assert shared.section_count == 2


def test_deficits_and_findings_never_merge_into_one_cluster() -> None:
    """One is a measurement, the other an opinion. Merging lends it authority."""

    review = VisionReviewOutcome(findings=(_finding("a"),))
    ledger = build_finding_ledger(
        [
            SiteEvidence(
                site_id="alpha", report=_simple_report("home", color=10.0), review=review
            )
        ]
    )

    kinds = {cluster.kind for cluster in ledger.clusters}
    assert kinds == {ClusterKind.DEFICIT, ClusterKind.FINDING}
    assert len(ledger.clusters) == 2


def test_a_cluster_keeps_its_highest_severity() -> None:
    review = VisionReviewOutcome(
        findings=(
            _finding("a", severity=ReportSeverity.LOW),
            _finding("b", section_id="s2", severity=ReportSeverity.HIGH),
            _finding("c", section_id="s3", severity=ReportSeverity.INFO),
        )
    )
    ledger = build_finding_ledger(
        [SiteEvidence(site_id="alpha", report=_simple_report("home"), review=review)]
    )

    cluster = next(c for c in ledger.clusters if c.kind is ClusterKind.FINDING)
    assert cluster.max_severity is ReportSeverity.HIGH


def test_breakpoints_are_retained_in_canonical_order() -> None:
    review = VisionReviewOutcome(
        findings=(
            _finding("a", breakpoint=BreakpointName.MOBILE),
            _finding("b", section_id="s2", breakpoint=BreakpointName.DESKTOP),
        )
    )
    ledger = build_finding_ledger(
        [SiteEvidence(site_id="alpha", report=_simple_report("home"), review=review)]
    )

    cluster = next(c for c in ledger.clusters if c.kind is ClusterKind.FINDING)
    assert cluster.breakpoints == (BreakpointName.DESKTOP, BreakpointName.MOBILE)


def test_mixed_regimes_raise_rather_than_aggregate() -> None:
    with pytest.raises(RegimeMismatchError):
        build_finding_ledger(
            [
                SiteEvidence(site_id="alpha", report=_simple_report("home", color=10.0)),
                SiteEvidence(
                    site_id="beta",
                    report=_simple_report("home", color=10.0, regime_version=2),
                ),
            ]
        )


def test_an_empty_corpus_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one site"):
        build_finding_ledger([])


def test_review_warnings_are_carried_with_their_site() -> None:
    review = VisionReviewOutcome(warnings=("provider timed out at mobile",))
    ledger = build_finding_ledger(
        [SiteEvidence(site_id="alpha", report=_simple_report("home"), review=review)]
    )

    assert ledger.warnings == ("alpha: provider timed out at mobile",)


def test_a_finding_without_a_section_is_reported_not_clustered() -> None:
    review = VisionReviewOutcome(
        findings=(
            ReportFinding(
                id="loose",
                severity=ReportSeverity.HIGH,
                category=FindingCategory.STYLE,
                message="something is wrong somewhere",
                recommendation="look into it",
                pipeline_stage=PipelineStage.QUALITY_GATE,
            ),
        )
    )
    ledger = build_finding_ledger(
        [SiteEvidence(site_id="alpha", report=_simple_report("home"), review=review)]
    )

    assert ledger.clusters == ()
    assert any("was not clustered" in warning for warning in ledger.warnings)


def test_the_ledger_is_byte_identical_for_the_same_evidence_in_any_order() -> None:
    alpha = SiteEvidence(
        site_id="alpha",
        report=_simple_report("home", color=30.0),
        review=VisionReviewOutcome(findings=(_finding("a"),)),
    )
    beta = SiteEvidence(
        site_id="beta",
        report=_simple_report("home", layout=20.0, color=40.0),
        review=VisionReviewOutcome(findings=(_finding("b", section_id="s2"),)),
    )

    forward = build_finding_ledger([alpha, beta])
    reverse = build_finding_ledger([beta, alpha])

    assert [c.key for c in forward.clusters] == [c.key for c in reverse.clusters]
    for left, right in zip(forward.clusters, reverse.clusters):
        assert left.occurrences == right.occurrences
    assert serialize_ledger(forward) == serialize_ledger(forward)


def test_the_ledger_does_not_rank() -> None:
    """Ranking is VF-103. A ledger that sorted by value would preempt it."""

    fields = set(type(build_finding_ledger(
        [SiteEvidence(site_id="alpha", report=_simple_report("home", color=10.0))]
    )).model_fields)
    assert "rank" not in fields and "value" not in fields
