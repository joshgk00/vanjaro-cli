"""Deterministic typography and spacing fidelity metrics (VF-004).

Typography is scored per type role — display, heading, body, label, button —
across font family, rendered size, and weight. Spacing is scored from section
padding and the rhythm between elements.

One rule shapes the family comparison. When the pipeline **refuses** a font
substitution because the design's font is unavailable, that is correct
behaviour: the theme planner declines to guess a near match rather than
silently shipping the wrong typeface. Scoring the refusal as a failure would
punish the pipeline for its own honesty and push the fix loop toward
fabricating a substitute. A refused substitution is therefore unavailable
evidence, excluded from the mean, and reported in the detail.

This module is pure: no network, filesystem, or model calls.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from vanjaro_cli.design.fidelity import DimensionScore, FidelityDimension

__all__ = [
    "FAMILY_WEIGHT",
    "PADDING_WEIGHT",
    "RHYTHM_WEIGHT",
    "SIZE_WEIGHT",
    "WEIGHT_WEIGHT",
    "SectionSpacing",
    "SectionTypography",
    "SpacingSample",
    "TypeSample",
    "normalize_family",
    "score_section_spacing",
    "score_section_typography",
    "type_scale_ratio",
]

# Sub-weights within the typography dimension. Family carries the most weight
# because the wrong typeface is the most visible single failure. Part of the
# frozen regime.
FAMILY_WEIGHT = 0.40
SIZE_WEIGHT = 0.40
WEIGHT_WEIGHT = 0.20

# Sub-weights within the spacing dimension.
PADDING_WEIGHT = 0.60
RHYTHM_WEIGHT = 0.40


class _TypeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _round(value: float) -> float:
    return round(value + 0.0, 4)


def normalize_family(family: str) -> str:
    """Reduce a CSS font stack to its comparable primary family.

    ``"Playfair Display", Georgia, serif`` and ``playfair display`` are the
    same typeface for scoring purposes; quoting and fallbacks are presentation
    detail, not a fidelity difference.
    """

    primary = family.split(",")[0]
    return primary.strip().strip("'\"").strip().casefold()


def _ratio_score(expected: float, observed: float) -> float | None:
    """Score two magnitudes by their ratio.

    Zero is a measured value, not missing evidence. Design padding of 96px
    rendered as 0px is a total mismatch, not an unmeasurable one — treating it
    as unavailable would drop a section whose spacing was stripped entirely
    out of the score instead of failing it.
    """

    if expected < 0 or observed < 0:
        return None
    if expected == observed:
        return 100.0
    largest = max(expected, observed)
    if largest == 0:
        return 100.0
    return _round(100.0 * min(expected, observed) / largest)


def _combine(parts: Iterable[tuple[float, float | None]]) -> float | None:
    total = 0.0
    total_weight = 0.0
    for weight, value in parts:
        if value is None:
            continue
        total += weight * value
        total_weight += weight
    if total_weight == 0:
        return None
    return _round(total / total_weight)


def _mean(values: Iterable[float]) -> float | None:
    collected = list(values)
    if not collected:
        return None
    return _round(sum(collected) / len(collected))


class TypeSample(_TypeModel):
    """Typography measured for one type role.

    `substitution_refused` marks that the design's family was unavailable and
    the pipeline declined to substitute one. It makes the family comparison
    unavailable rather than a mismatch.
    """

    family: str | None = None
    size_px: float | None = Field(default=None, gt=0)
    weight: int | None = Field(default=None, ge=1, le=1000)
    substitution_refused: bool = False


class SectionTypography(_TypeModel):
    """Type samples for one section, keyed by type role."""

    samples: Mapping[str, TypeSample] = Field(default_factory=dict)

    def get(self, role: str) -> TypeSample | None:
        return self.samples.get(role)


def type_scale_ratio(typography: SectionTypography, role: str, base_role: str = "body") -> float | None:
    """Ratio of one role's size to the base role, or None if unmeasurable.

    Exposes the scale itself so a uniformly shrunk design can be told apart
    from a compressed one during diagnosis.
    """

    sample = typography.get(role)
    base = typography.get(base_role)
    if sample is None or base is None:
        return None
    if sample.size_px is None or base.size_px is None or base.size_px <= 0:
        return None
    return _round(sample.size_px / base.size_px)


def _score_family(expected: TypeSample, observed: TypeSample) -> float | None:
    if observed.substitution_refused or expected.substitution_refused:
        return None
    if expected.family is None or observed.family is None:
        return None
    return 100.0 if normalize_family(expected.family) == normalize_family(observed.family) else 0.0


def _score_sample(expected: TypeSample, observed: TypeSample) -> float | None:
    family = _score_family(expected, observed)

    size: float | None = None
    if expected.size_px is not None and observed.size_px is not None:
        size = _ratio_score(expected.size_px, observed.size_px)

    weight: float | None = None
    if expected.weight is not None and observed.weight is not None:
        weight = _ratio_score(float(expected.weight), float(observed.weight))

    return _combine(
        (
            (FAMILY_WEIGHT, family),
            (SIZE_WEIGHT, size),
            (WEIGHT_WEIGHT, weight),
        )
    )


def score_section_typography(
    expected: SectionTypography,
    observed: SectionTypography,
) -> DimensionScore:
    """Score a section's typography role by role."""

    scored: list[float] = []
    refused: list[str] = []
    mismatched_families: list[str] = []
    unmeasured: list[str] = []

    for role in sorted(expected.samples):
        expected_sample = expected.samples[role]
        observed_sample = observed.get(role)
        if observed_sample is None:
            unmeasured.append(role)
            continue

        if observed_sample.substitution_refused or expected_sample.substitution_refused:
            refused.append(role)
        elif _score_family(expected_sample, observed_sample) == 0.0:
            mismatched_families.append(role)

        value = _score_sample(expected_sample, observed_sample)
        if value is None:
            unmeasured.append(role)
        else:
            scored.append(value)

    details: list[str] = []
    if mismatched_families:
        details.append("family mismatch in " + ", ".join(sorted(mismatched_families)))
    if refused:
        details.append(
            "font substitution refused for " + ", ".join(sorted(refused))
        )
    if unmeasured:
        details.append("no type evidence for " + ", ".join(sorted(set(unmeasured))))

    return DimensionScore(
        dimension=FidelityDimension.TYPOGRAPHY,
        score=_mean(scored),
        detail="; ".join(details) if details else None,
        measured_subscores=len(scored),
        total_subscores=max(1, len(scored) + len(set(unmeasured))),
    )


class SpacingSample(_TypeModel):
    """Spacing measured for one section."""

    padding_top: float | None = Field(default=None, ge=0)
    padding_bottom: float | None = Field(default=None, ge=0)
    element_gap: float | None = Field(default=None, ge=0)


class SectionSpacing(_TypeModel):
    """Spacing observations for one section at one breakpoint."""

    spacing: SpacingSample = Field(default_factory=SpacingSample)


def score_section_spacing(
    expected: SectionSpacing,
    observed: SectionSpacing,
) -> DimensionScore:
    """Score section padding and inter-element rhythm."""

    first = expected.spacing
    second = observed.spacing

    padding_parts: list[float] = []
    unmeasured: list[str] = []

    for label, expected_value, observed_value in (
        ("padding-top", first.padding_top, second.padding_top),
        ("padding-bottom", first.padding_bottom, second.padding_bottom),
    ):
        if expected_value is None or observed_value is None:
            unmeasured.append(label)
            continue
        value = _ratio_score(expected_value, observed_value)
        if value is None:
            unmeasured.append(label)
        else:
            padding_parts.append(value)

    padding = _mean(padding_parts)

    rhythm: float | None = None
    if first.element_gap is None or second.element_gap is None:
        unmeasured.append("element-gap")
    else:
        rhythm = _ratio_score(first.element_gap, second.element_gap)
        if rhythm is None:
            unmeasured.append("element-gap")

    score = _combine(((PADDING_WEIGHT, padding), (RHYTHM_WEIGHT, rhythm)))

    detail = None
    if unmeasured:
        detail = "no spacing evidence for " + ", ".join(sorted(set(unmeasured)))

    subscores = (padding, rhythm)
    return DimensionScore(
        dimension=FidelityDimension.SPACING,
        score=score,
        detail=detail,
        measured_subscores=sum(1 for entry in subscores if entry is not None),
        total_subscores=len(subscores),
    )
