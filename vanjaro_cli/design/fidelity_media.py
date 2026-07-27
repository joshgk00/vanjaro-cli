"""Deterministic media and integrity fidelity metrics (VF-005).

Media scores how faithfully imagery survived the build: aspect ratio, focal
point, and how much of the source asset remains visible after cropping. A
correctly sourced image cropped through someone's face is a real fidelity
failure that geometry and colour metrics both miss.

Integrity scores defects that make a page wrong regardless of how well it
matches the design — horizontal overflow, empty template slots, console
errors, and placeholder leakage.

Placeholder leakage is special. Shipping `Lorem ipsum` or a stock placeholder
image is never an acceptable build at any score, so it sets `forces_zero` and
drives the whole section score to zero through the VF-001 contract. Every
other defect is proportional.

This module is pure: no network, filesystem, or model calls.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import math

from pydantic import BaseModel, ConfigDict, Field

from vanjaro_cli.design.fidelity import DimensionScore, FidelityDimension

__all__ = [
    "ASPECT_WEIGHT",
    "CONSOLE_ERROR_PENALTY",
    "CROP_WEIGHT",
    "EMPTY_SLOT_PENALTY",
    "FOCAL_WEIGHT",
    "MAX_FOCAL_DISTANCE",
    "OVERFLOW_PENALTY",
    "OVERFLOW_TOLERANCE_PX",
    "IntegrityObservation",
    "MediaSample",
    "SectionMedia",
    "score_section_integrity",
    "score_section_media",
]

# Sub-weights within the media dimension. Part of the frozen regime.
ASPECT_WEIGHT = 0.40
FOCAL_WEIGHT = 0.35
CROP_WEIGHT = 0.25

# Normalized focal distance at which the focal point is treated as fully wrong.
# Half the image diagonal means the subject has effectively been lost.
MAX_FOCAL_DISTANCE = 0.5

# Integrity penalties, subtracted from 100. Overflow is weighted heaviest
# because it breaks the layout for every visitor on that breakpoint.
OVERFLOW_PENALTY = 40.0
EMPTY_SLOT_PENALTY = 15.0
CONSOLE_ERROR_PENALTY = 10.0

# Sub-pixel differences are rounding, not overflow.
OVERFLOW_TOLERANCE_PX = 1.0


class _MediaModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _round(value: float) -> float:
    return round(value + 0.0, 4)


def _ratio_score(expected: float, observed: float) -> float | None:
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


class MediaSample(_MediaModel):
    """One image as designed or as rendered.

    `crop_coverage` is the fraction of the source asset still visible, so 1.0
    is uncropped. `focal_x` and `focal_y` are normalized to the image box.
    """

    aspect_ratio: float | None = Field(default=None, gt=0)
    focal_x: float | None = Field(default=None, ge=0, le=1)
    focal_y: float | None = Field(default=None, ge=0, le=1)
    crop_coverage: float | None = Field(default=None, gt=0, le=1)


class SectionMedia(_MediaModel):
    """Media samples for one section, keyed by a stable media ID."""

    media: Mapping[str, MediaSample] = Field(default_factory=dict)

    def get(self, media_id: str) -> MediaSample | None:
        return self.media.get(media_id)


def _score_focal(expected: MediaSample, observed: MediaSample) -> float | None:
    if (
        expected.focal_x is None
        or expected.focal_y is None
        or observed.focal_x is None
        or observed.focal_y is None
    ):
        return None
    distance = math.dist(
        (expected.focal_x, expected.focal_y), (observed.focal_x, observed.focal_y)
    )
    if distance >= MAX_FOCAL_DISTANCE:
        return 0.0
    return _round(100.0 * (1 - distance / MAX_FOCAL_DISTANCE))


def _score_media_sample(expected: MediaSample, observed: MediaSample) -> float | None:
    aspect: float | None = None
    if expected.aspect_ratio is not None and observed.aspect_ratio is not None:
        aspect = _ratio_score(expected.aspect_ratio, observed.aspect_ratio)

    crop: float | None = None
    if expected.crop_coverage is not None and observed.crop_coverage is not None:
        crop = _ratio_score(expected.crop_coverage, observed.crop_coverage)

    return _combine(
        (
            (ASPECT_WEIGHT, aspect),
            (FOCAL_WEIGHT, _score_focal(expected, observed)),
            (CROP_WEIGHT, crop),
        )
    )


def score_section_media(
    expected: SectionMedia,
    observed: SectionMedia,
) -> DimensionScore:
    """Score a section's imagery against the source assets."""

    scored: list[float] = []
    missing: list[str] = []
    unmeasured: list[str] = []

    for media_id in sorted(expected.media):
        observed_sample = observed.get(media_id)
        if observed_sample is None:
            # A designed image that never made it into the build is a failure,
            # not absent evidence.
            missing.append(media_id)
            scored.append(0.0)
            continue

        value = _score_media_sample(expected.media[media_id], observed_sample)
        if value is None:
            unmeasured.append(media_id)
        else:
            scored.append(value)

    details: list[str] = []
    if missing:
        details.append("media absent from the build: " + ", ".join(missing))
    if unmeasured:
        details.append("no media evidence for " + ", ".join(unmeasured))

    return DimensionScore(
        dimension=FidelityDimension.MEDIA,
        score=_mean(scored),
        detail="; ".join(details) if details else None,
    )


class IntegrityObservation(_MediaModel):
    """Defects observed in a rendered section.

    `placeholder_leaks` names any placeholder content that reached the build.
    Any entry forces the section score to zero.
    """

    horizontal_overflow_px: float | None = Field(default=None, ge=0)
    empty_slot_count: int | None = Field(default=None, ge=0)
    console_error_count: int | None = Field(default=None, ge=0)
    placeholder_leaks: tuple[str, ...] = ()


def score_section_integrity(observation: IntegrityObservation) -> DimensionScore:
    """Score rendered integrity, forcing zero on placeholder leakage."""

    if observation.placeholder_leaks:
        leaks = ", ".join(sorted(observation.placeholder_leaks))
        return DimensionScore(
            dimension=FidelityDimension.INTEGRITY,
            score=0.0,
            forces_zero=True,
            detail=f"placeholder content leaked into the build: {leaks}",
        )

    penalties = 0.0
    findings: list[str] = []
    unmeasured: list[str] = []

    if observation.horizontal_overflow_px is None:
        unmeasured.append("horizontal-overflow")
    elif observation.horizontal_overflow_px > OVERFLOW_TOLERANCE_PX:
        penalties += OVERFLOW_PENALTY
        findings.append(
            f"horizontal overflow of {observation.horizontal_overflow_px:g}px"
        )

    if observation.empty_slot_count is None:
        unmeasured.append("empty-slots")
    elif observation.empty_slot_count > 0:
        penalties += EMPTY_SLOT_PENALTY * observation.empty_slot_count
        findings.append(f"{observation.empty_slot_count} empty slot(s)")

    if observation.console_error_count is None:
        unmeasured.append("console-errors")
    elif observation.console_error_count > 0:
        penalties += CONSOLE_ERROR_PENALTY * observation.console_error_count
        findings.append(f"{observation.console_error_count} console error(s)")

    if len(unmeasured) == 3:
        # Nothing at all was observed, so integrity is unknown rather than clean.
        return DimensionScore(
            dimension=FidelityDimension.INTEGRITY,
            score=None,
            detail="no integrity evidence for " + ", ".join(unmeasured),
        )

    details = list(findings)
    if unmeasured:
        details.append("no integrity evidence for " + ", ".join(unmeasured))

    return DimensionScore(
        dimension=FidelityDimension.INTEGRITY,
        score=_round(max(0.0, 100.0 - penalties)),
        detail="; ".join(details) if details else None,
    )
