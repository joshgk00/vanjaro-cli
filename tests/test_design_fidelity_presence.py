"""RT-37 — a presence dimension scales a section's score instead of averaging into it.

Averaging the share of designed wording that is present into the weighted mean
credits every section for the words it has: on trial 4 a 0.20 weight lifted
sections that were mostly right and cost almost nothing to the ones missing a
paragraph. Scaling means a section that shows everything keeps the score its
other dimensions earned, and a section missing words loses that share of it.
"""

from __future__ import annotations

import pytest

from vanjaro_cli.design.fidelity import (
    DIMENSION_WEIGHTS,
    PRESENCE_DIMENSIONS,
    BreakpointFidelityScore,
    DimensionScore,
    FidelityDimension,
    FidelityReport,
    SectionFidelityScore,
)
from vanjaro_cli.design.finding_ledger import ClusterKind, SiteEvidence, build_finding_ledger
from vanjaro_cli.design.models import BreakpointName

COPY = FidelityDimension.COPY


def _section(
    scores: dict[FidelityDimension, float | None], *, forces_zero: FidelityDimension | None = None
) -> SectionFidelityScore:
    return SectionFidelityScore(
        regime_version=4,
        section_id="page.section.1",
        breakpoint=BreakpointName.DESKTOP,
        dimensions=tuple(
            DimensionScore(
                dimension=dimension,
                score=score,
                forces_zero=dimension is forces_zero,
                detail="leaked" if dimension is forces_zero else None,
            )
            for dimension, score in scores.items()
        ),
    )


BASE = {FidelityDimension.LAYOUT: 80.0, FidelityDimension.COLOR: 60.0}
BASE_MEAN = (80 * DIMENSION_WEIGHTS[FidelityDimension.LAYOUT] + 60 * DIMENSION_WEIGHTS[FidelityDimension.COLOR]) / (
    DIMENSION_WEIGHTS[FidelityDimension.LAYOUT] + DIMENSION_WEIGHTS[FidelityDimension.COLOR]
)


def test_copy_is_a_presence_dimension_with_no_weight() -> None:
    assert COPY in PRESENCE_DIMENSIONS
    assert COPY not in DIMENSION_WEIGHTS


def test_all_the_designed_words_present_leaves_the_score_exactly_as_it_was() -> None:
    without = _section(BASE)
    with_copy = _section({**BASE, COPY: 100.0})

    assert with_copy.score == without.score == pytest.approx(BASE_MEAN, abs=0.0001)


def test_missing_words_take_half_their_share_off_the_score() -> None:
    section = _section({**BASE, COPY: 75.0})

    assert section.score == pytest.approx(BASE_MEAN * 0.875, abs=0.0001)


def test_a_section_with_none_of_its_words_keeps_half_its_score() -> None:
    assert _section({**BASE, COPY: 0.0}).score == pytest.approx(BASE_MEAN * 0.5, abs=0.0001)


def test_unmeasured_wording_does_not_move_the_score() -> None:
    assert _section({**BASE, COPY: None}).score == _section(BASE).score


def test_wording_alone_cannot_score_a_section() -> None:
    section = _section({FidelityDimension.LAYOUT: None, COPY: 90.0})

    assert section.score is None
    assert section.measured is False


def test_a_forced_zero_still_wins() -> None:
    section = _section({**BASE, FidelityDimension.INTEGRITY: 0.0, COPY: 90.0}, forces_zero=FidelityDimension.INTEGRITY)

    assert section.score == 0.0


def test_coverage_describes_the_weighted_signals_and_ignores_the_presence_factor() -> None:
    without = _section(BASE)
    with_copy = _section({**BASE, COPY: 50.0})

    assert with_copy.measured_dimensions == without.measured_dimensions == 2
    assert with_copy.dimension_coverage == without.dimension_coverage
    assert with_copy.evidence_coverage == without.evidence_coverage


def test_a_wording_shortfall_is_a_ranked_deficit_in_the_ledger() -> None:
    section = _section({**BASE, COPY: 50.0})
    report = FidelityReport(
        regime_version=4,
        page_id="home",
        breakpoints=(
            BreakpointFidelityScore(
                regime_version=4, breakpoint=BreakpointName.DESKTOP, sections=(section,)
            ),
        ),
    )

    ledger = build_finding_ledger([SiteEvidence(site_id="trial-4", report=report)])

    deficits = {
        cluster.key for cluster in ledger.clusters if cluster.kind is ClusterKind.DEFICIT
    }
    assert "copy" in deficits
