"""Deterministic visual fidelity score contracts and regime versioning.

The score produced here is the authoritative signal for whether a build matches
its design. It is computed from measured geometry, colour, and typography only.
No language model contributes to it, so a repeated run over unchanged inputs
returns byte-identical output and a rising series means real improvement.

Every record carries the `regime_version` that produced it. Scores from
different regimes are not comparable: changing a weight, adding a dimension, or
altering how a dimension is measured silently shifts every number. Aggregating
across regimes therefore raises `RegimeMismatchError` rather than averaging
values that mean different things.

This module is pure. It performs no network, filesystem, or model calls.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum
import json
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from vanjaro_cli.design.models import BreakpointName

__all__ = [
    "CURRENT_REGIME_VERSION",
    "DIMENSION_WEIGHTS",
    "BreakpointFidelityScore",
    "DimensionScore",
    "FidelityDimension",
    "FidelityReport",
    "RegimeMismatchError",
    "SectionFidelityScore",
    "UnavailableScoreError",
    "aggregate_breakpoint",
    "build_fidelity_report",
    "serialize_fidelity_report",
    "to_viewport_visual_score",
]

# Frozen scoring regime. Bump ONLY alongside re-scoring every committed
# baseline in the same commit; see docs/visual-fidelity-goal.md (VF-1).
CURRENT_REGIME_VERSION = 1


class FidelityDimension(str, Enum):
    """Measured dimensions that make up a section score."""

    LAYOUT = "layout"
    COLOR = "color"
    TYPOGRAPHY = "typography"
    SPACING = "spacing"
    MEDIA = "media"
    INTEGRITY = "integrity"


# The single typed location for regime weights. Editing these changes the
# meaning of every score and requires a regime version bump.
DIMENSION_WEIGHTS: Mapping[FidelityDimension, float] = MappingProxyType(
    {
        FidelityDimension.LAYOUT: 0.30,
        FidelityDimension.COLOR: 0.20,
        FidelityDimension.TYPOGRAPHY: 0.15,
        FidelityDimension.MEDIA: 0.15,
        FidelityDimension.SPACING: 0.10,
        FidelityDimension.INTEGRITY: 0.10,
    }
)

_DIMENSION_ORDER = {dimension: index for index, dimension in enumerate(FidelityDimension)}


class RegimeMismatchError(ValueError):
    """Raised when records from different scoring regimes are combined."""

    def __init__(self, versions: Iterable[int]):
        self.versions = tuple(sorted(set(versions)))
        super().__init__(
            "Cannot combine fidelity scores from different regimes: "
            + ", ".join(str(version) for version in self.versions)
            + ". Re-score every baseline under one regime before comparing."
        )


class UnavailableScoreError(ValueError):
    """Raised when a score is requested but no dimension could be measured."""


class _FidelityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DimensionScore(_FidelityModel):
    """One measured dimension of one section at one breakpoint.

    A `score` of ``None`` means the dimension could not be measured. It is
    excluded from the weighted mean rather than counted as a failure, so
    missing evidence never masquerades as a poor build.
    """

    dimension: FidelityDimension
    score: float | None = Field(default=None, ge=0, le=100)
    # Set when a defect invalidates the section outright regardless of other
    # dimensions, such as leaked placeholder content (VF-005).
    forces_zero: bool = False
    detail: str | None = None
    # How many of this dimension's own subscores contributed. A dimension counts
    # as "measured" as soon as one subscore lands, so layout scoring on column
    # agreement alone looks identical to layout comparing real boxes. Recording
    # the split is what keeps `dimension_coverage` from overstating evidence.
    measured_subscores: int | None = Field(default=None, ge=0)
    total_subscores: int | None = Field(default=None, ge=1)

    @property
    def subscore_coverage(self) -> float | None:
        """Share of this dimension's subscores that contributed, if reported."""

        if self.measured_subscores is None or self.total_subscores is None:
            return None
        return _round(self.measured_subscores / self.total_subscores)

    @model_validator(mode="after")
    def zero_requires_detail(self) -> "DimensionScore":
        if self.forces_zero and not self.detail:
            raise ValueError("forces_zero requires a detail explaining the defect")
        return self

    @property
    def available(self) -> bool:
        return self.score is not None


def _weighted_mean(dimensions: Iterable[DimensionScore]) -> float | None:
    total_weight = 0.0
    total = 0.0
    for entry in dimensions:
        if entry.score is None:
            continue
        weight = DIMENSION_WEIGHTS[entry.dimension]
        total += entry.score * weight
        total_weight += weight
    if total_weight == 0:
        return None
    # Renormalize across available weights so unmeasured dimensions neither
    # inflate nor deflate the result.
    return _round(total / total_weight)


def _round(value: float) -> float:
    # Fixed precision keeps repeated serialization byte-identical across
    # platforms with differing float repr behaviour.
    return round(value + 0.0, 4)


class SectionFidelityScore(_FidelityModel):
    """Per-section, per-breakpoint score with its contributing dimensions."""

    regime_version: int = Field(ge=1)
    section_id: str = Field(min_length=1)
    breakpoint: BreakpointName
    dimensions: tuple[DimensionScore, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ordered_dimensions(self) -> "SectionFidelityScore":
        seen = [entry.dimension for entry in self.dimensions]
        if len(seen) != len(set(seen)):
            raise ValueError("each dimension may appear at most once per section")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def score(self) -> float | None:
        if any(entry.forces_zero for entry in self.dimensions):
            return 0.0
        return _weighted_mean(self.dimensions)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def measured(self) -> bool:
        return self.score is not None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def measured_dimensions(self) -> int:
        """How many of the regime's dimensions actually contributed.

        A score built from two dimensions and one built from six are not
        comparable, and the weighted mean hides the difference by renormalizing.
        Reporting the count keeps "we measured little" from reading as "this
        scored well" — which matters most at mobile, where the ship gate has its
        own floor and the expected side usually supplies the least evidence.

        Derived from dimensions already present, so this reports the regime
        rather than changing it.
        """

        return sum(1 for entry in self.dimensions if entry.score is not None)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dimension_coverage(self) -> float:
        return _round(self.measured_dimensions / len(DIMENSION_WEIGHTS))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def evidence_coverage(self) -> float:
        """Weighted share of the regime's *signals* that contributed.

        `dimension_coverage` counts dimensions and cannot tell a layout scored
        on three subscores from one scored on two — which is exactly how a
        quarter of the layout dimension stayed dark on every section while
        coverage read 0.800. This counts signals, weighted as the regime weights
        the dimensions they belong to.

        A dimension that reports no split counts as fully measured when it
        scored, which is the conservative reading: it can only make this number
        higher, never invent evidence.
        """

        total = 0.0
        measured = 0.0
        for entry in self.dimensions:
            weight = DIMENSION_WEIGHTS[entry.dimension]
            total += weight
            if entry.score is None:
                continue
            share = entry.subscore_coverage
            measured += weight * (1.0 if share is None else share)
        if total == 0:
            return 0.0
        return _round(measured / total)

    def require_score(self) -> float:
        """Return the score, or raise when nothing could be measured."""

        value = self.score
        if value is None:
            raise UnavailableScoreError(
                f"Section {self.section_id!r} at {self.breakpoint.value} has no "
                "measurable dimension; capture evidence before scoring."
            )
        return value


def _require_single_regime(versions: Iterable[int]) -> int:
    distinct = {version for version in versions}
    if not distinct:
        raise ValueError("at least one scored record is required")
    if len(distinct) > 1:
        raise RegimeMismatchError(distinct)
    return distinct.pop()


def _sorted_sections(
    sections: Iterable[SectionFidelityScore],
) -> tuple[SectionFidelityScore, ...]:
    return tuple(sorted(sections, key=lambda item: item.section_id.casefold()))


class BreakpointFidelityScore(_FidelityModel):
    """All section scores captured at one breakpoint."""

    regime_version: int = Field(ge=1)
    breakpoint: BreakpointName
    sections: tuple[SectionFidelityScore, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_sections(self) -> "BreakpointFidelityScore":
        identifiers = [section.section_id.casefold() for section in self.sections]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("section IDs must be unique within a breakpoint")
        mismatched = sorted(
            section.section_id
            for section in self.sections
            if section.breakpoint != self.breakpoint
        )
        if mismatched:
            raise ValueError(
                f"sections must share the breakpoint {self.breakpoint.value}: "
                f"{mismatched}"
            )
        _require_single_regime(
            [self.regime_version, *(section.regime_version for section in self.sections)]
        )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall_score(self) -> float | None:
        measured = [
            section.score for section in self.sections if section.score is not None
        ]
        if not measured:
            return None
        return _round(sum(measured) / len(measured))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unmeasured_section_ids(self) -> tuple[str, ...]:
        return tuple(
            section.section_id for section in self.sections if section.score is None
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dimension_coverage(self) -> float:
        """Mean share of the regime's dimensions measured across this viewport."""

        if not self.sections:
            return 0.0
        return _round(
            sum(section.dimension_coverage for section in self.sections)
            / len(self.sections)
        )


def aggregate_breakpoint(
    breakpoint: BreakpointName,
    sections: Iterable[SectionFidelityScore],
) -> BreakpointFidelityScore:
    """Group section scores into one breakpoint result.

    Raises `RegimeMismatchError` when the sections were not all produced by the
    same scoring regime.
    """

    ordered = _sorted_sections(sections)
    regime = _require_single_regime(section.regime_version for section in ordered)
    return BreakpointFidelityScore(
        regime_version=regime, breakpoint=breakpoint, sections=ordered
    )


class FidelityReport(_FidelityModel):
    """Complete deterministic fidelity result for one page."""

    schema_version: Literal["1.0"] = "1.0"
    regime_version: int = Field(ge=1)
    page_id: str = Field(min_length=1)
    breakpoints: tuple[BreakpointFidelityScore, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_breakpoints(self) -> "FidelityReport":
        names = [entry.breakpoint for entry in self.breakpoints]
        if len(names) != len(set(names)):
            raise ValueError("each breakpoint may appear at most once per report")
        _require_single_regime(
            [self.regime_version, *(entry.regime_version for entry in self.breakpoints)]
        )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall_score(self) -> float | None:
        measured = [
            entry.overall_score
            for entry in self.breakpoints
            if entry.overall_score is not None
        ]
        if not measured:
            return None
        return _round(sum(measured) / len(measured))

    def breakpoint(self, name: BreakpointName) -> BreakpointFidelityScore | None:
        for entry in self.breakpoints:
            if entry.breakpoint == name:
                return entry
        return None


def build_fidelity_report(
    page_id: str,
    breakpoints: Iterable[BreakpointFidelityScore],
) -> FidelityReport:
    """Assemble a page report in canonical breakpoint order."""

    ordered = tuple(
        sorted(
            breakpoints,
            key=lambda entry: _BREAKPOINT_ORDER.get(entry.breakpoint, len(_BREAKPOINT_ORDER)),
        )
    )
    regime = _require_single_regime(entry.regime_version for entry in ordered)
    return FidelityReport(regime_version=regime, page_id=page_id, breakpoints=ordered)


_BREAKPOINT_ORDER = {
    BreakpointName.DESKTOP: 0,
    BreakpointName.TABLET: 1,
    BreakpointName.MOBILE: 2,
}


def to_viewport_visual_score(score: BreakpointFidelityScore):
    """Adapt a breakpoint result to the visual gate's score contract.

    Imported lazily so the pure scoring contracts stay independent of the gate.
    Sections with no measurable dimension are rejected rather than defaulted,
    because a missing score must never be presented to the gate as a passing one.
    """

    from vanjaro_cli.design.visual_gate import SectionVisualScore, ViewportVisualScore

    unmeasured = score.unmeasured_section_ids
    if unmeasured:
        raise UnavailableScoreError(
            f"Cannot gate {score.breakpoint.value}: sections without measurable "
            f"evidence: {list(unmeasured)}"
        )
    return ViewportVisualScore(
        breakpoint=score.breakpoint,
        overall_score=score.overall_score,
        sections=tuple(
            SectionVisualScore(
                section_id=section.section_id, score=section.require_score()
            )
            for section in score.sections
        ),
    )


def serialize_fidelity_report(report: FidelityReport, *, indent: int = 2) -> str:
    """Serialize a report with stable ordering and a trailing newline."""

    return (
        json.dumps(
            report.model_dump(mode="json"),
            indent=indent,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )
