"""Deterministic colour fidelity metric (VF-003).

Scores how closely rendered colours match design tokens, using CIEDE2000
perceptual distance rather than raw RGB difference. RGB distance badly
misrepresents how wrong a colour looks: a small numeric shift in a saturated
hue is glaring, while the same shift in a dark neutral is invisible.

Background, text, and accent roles are scored separately so a correct
background cannot mask a wrong accent, and so the finding says which role
drifted.

Implemented with the standard library only. sRGB is converted to linear RGB,
then CIE XYZ under a D65 white point, then CIE L*a*b*, then compared with the
full CIEDE2000 formula including the hue-rotation term.

This module is pure: no network, filesystem, or model calls.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum
import math
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vanjaro_cli.design.fidelity import DimensionScore, FidelityDimension

__all__ = [
    "MAX_PERCEPTUAL_DISTANCE",
    "ROLE_WEIGHTS",
    "ColorRole",
    "InvalidColorError",
    "Lab",
    "SectionPalette",
    "delta_e_2000",
    "distance_to_score",
    "hex_to_lab",
    "hex_to_rgb",
    "score_section_color",
]

# CIEDE2000 distance at which a colour is treated as fully wrong. A delta under
# ~1 is imperceptible and ~2-3 is a close match, so a linear falloff to zero at
# 25 keeps ordinary drift in the upper range while still separating a near miss
# from an unrelated hue. Part of the frozen regime.
MAX_PERCEPTUAL_DISTANCE = 25.0

_HEX_PATTERN = re.compile(r"^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# D65 reference white, matching the sRGB specification.
_WHITE_X = 0.95047
_WHITE_Y = 1.00000
_WHITE_Z = 1.08883

_DELTA = 6.0 / 29.0


class InvalidColorError(ValueError):
    """Raised when a colour string cannot be parsed."""


class ColorRole(str, Enum):
    """Colour roles scored independently within a section."""

    BACKGROUND = "background"
    TEXT = "text"
    ACCENT = "accent"


# Backgrounds dominate perceived colour fidelity, text is next because it
# covers large area at high contrast, accents are smallest by area.
ROLE_WEIGHTS: Mapping[ColorRole, float] = {
    ColorRole.BACKGROUND: 0.45,
    ColorRole.TEXT: 0.35,
    ColorRole.ACCENT: 0.20,
}


def _round(value: float) -> float:
    return round(value + 0.0, 4)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """Parse ``#rgb`` or ``#rrggbb`` into 8-bit channels."""

    if not isinstance(value, str) or not _HEX_PATTERN.match(value.strip()):
        raise InvalidColorError(
            f"{value!r} is not a valid hex colour; expected #rgb or #rrggbb"
        )
    digits = value.strip().lstrip("#")
    if len(digits) == 3:
        digits = "".join(channel * 2 for channel in digits)
    return (
        int(digits[0:2], 16),
        int(digits[2:4], 16),
        int(digits[4:6], 16),
    )


def _linearize(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def _pivot(value: float) -> float:
    if value > _DELTA**3:
        return value ** (1.0 / 3.0)
    return value / (3 * _DELTA**2) + 4.0 / 29.0


class Lab(BaseModel):
    """CIE L*a*b* coordinates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lightness: float
    a: float
    b: float


def hex_to_lab(value: str) -> Lab:
    """Convert an sRGB hex colour to CIE L*a*b* under a D65 white point."""

    red, green, blue = hex_to_rgb(value)
    linear_r = _linearize(red / 255.0)
    linear_g = _linearize(green / 255.0)
    linear_b = _linearize(blue / 255.0)

    x = 0.4124564 * linear_r + 0.3575761 * linear_g + 0.1804375 * linear_b
    y = 0.2126729 * linear_r + 0.7151522 * linear_g + 0.0721750 * linear_b
    z = 0.0193339 * linear_r + 0.1191920 * linear_g + 0.9503041 * linear_b

    fx = _pivot(x / _WHITE_X)
    fy = _pivot(y / _WHITE_Y)
    fz = _pivot(z / _WHITE_Z)

    return Lab(
        lightness=_round(116 * fy - 16),
        a=_round(500 * (fx - fy)),
        b=_round(200 * (fy - fz)),
    )


def delta_e_2000(first: Lab, second: Lab) -> float:
    """CIEDE2000 perceptual distance between two Lab colours."""

    l1, a1, b1 = first.lightness, first.a, first.b
    l2, a2, b2 = second.lightness, second.a, second.b

    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0

    c_bar7 = c_bar**7
    g = 0.5 * (1 - math.sqrt(c_bar7 / (c_bar7 + 25.0**7))) if c_bar > 0 else 0.0

    a1_prime = (1 + g) * a1
    a2_prime = (1 + g) * a2
    c1_prime = math.hypot(a1_prime, b1)
    c2_prime = math.hypot(a2_prime, b2)

    h1_prime = _hue_angle(b1, a1_prime)
    h2_prime = _hue_angle(b2, a2_prime)

    delta_l = l2 - l1
    delta_c = c2_prime - c1_prime

    chroma_product = c1_prime * c2_prime
    if chroma_product == 0:
        delta_h_angle = 0.0
    else:
        difference = h2_prime - h1_prime
        if difference > 180:
            difference -= 360
        elif difference < -180:
            difference += 360
        delta_h_angle = difference
    delta_h = 2 * math.sqrt(chroma_product) * math.sin(math.radians(delta_h_angle) / 2)

    l_bar = (l1 + l2) / 2.0
    c_bar_prime = (c1_prime + c2_prime) / 2.0

    if chroma_product == 0:
        h_bar = h1_prime + h2_prime
    elif abs(h1_prime - h2_prime) <= 180:
        h_bar = (h1_prime + h2_prime) / 2.0
    elif h1_prime + h2_prime < 360:
        h_bar = (h1_prime + h2_prime + 360) / 2.0
    else:
        h_bar = (h1_prime + h2_prime - 360) / 2.0

    t = (
        1
        - 0.17 * math.cos(math.radians(h_bar - 30))
        + 0.24 * math.cos(math.radians(2 * h_bar))
        + 0.32 * math.cos(math.radians(3 * h_bar + 6))
        - 0.20 * math.cos(math.radians(4 * h_bar - 63))
    )

    delta_theta = 30 * math.exp(-(((h_bar - 275) / 25.0) ** 2))
    c_bar_prime7 = c_bar_prime**7
    rc = 2 * math.sqrt(c_bar_prime7 / (c_bar_prime7 + 25.0**7)) if c_bar_prime > 0 else 0.0

    sl = 1 + (0.015 * (l_bar - 50) ** 2) / math.sqrt(20 + (l_bar - 50) ** 2)
    sc = 1 + 0.045 * c_bar_prime
    sh = 1 + 0.015 * c_bar_prime * t
    rt = -math.sin(math.radians(2 * delta_theta)) * rc

    lightness_term = delta_l / sl
    chroma_term = delta_c / sc
    hue_term = delta_h / sh

    return _round(
        math.sqrt(
            lightness_term**2
            + chroma_term**2
            + hue_term**2
            + rt * chroma_term * hue_term
        )
    )


def _hue_angle(b: float, a_prime: float) -> float:
    if a_prime == 0 and b == 0:
        return 0.0
    angle = math.degrees(math.atan2(b, a_prime))
    return angle + 360 if angle < 0 else angle


def distance_to_score(distance: float) -> float:
    """Map a CIEDE2000 distance to a 0-100 score with linear falloff."""

    if distance <= 0:
        return 100.0
    if distance >= MAX_PERCEPTUAL_DISTANCE:
        return 0.0
    return _round(100.0 * (1 - distance / MAX_PERCEPTUAL_DISTANCE))


class SectionPalette(BaseModel):
    """Colours observed or expected for one section, keyed by role.

    A role absent from the mapping is unmeasured. It is excluded from the score
    rather than counted as a mismatch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    colors: Mapping[ColorRole, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def colors_are_parseable(self) -> "SectionPalette":
        for role, value in self.colors.items():
            hex_to_rgb(value)  # raises InvalidColorError on malformed input
        return self

    def get(self, role: ColorRole) -> str | None:
        return self.colors.get(role)


def role_distance(expected: str, observed: str) -> float:
    """CIEDE2000 distance between two hex colours."""

    return delta_e_2000(hex_to_lab(expected), hex_to_lab(observed))


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


def score_section_color(
    expected: SectionPalette,
    observed: SectionPalette,
) -> DimensionScore:
    """Score a section's colours against its design tokens, role by role."""

    subscores: dict[ColorRole, float | None] = {}
    for role in ColorRole:
        expected_value = expected.get(role)
        observed_value = observed.get(role)
        if expected_value is None or observed_value is None:
            subscores[role] = None
            continue
        subscores[role] = distance_to_score(role_distance(expected_value, observed_value))

    score = _combine((ROLE_WEIGHTS[role], subscores[role]) for role in ColorRole)

    unmeasured = [role.value for role in ColorRole if subscores[role] is None]
    drifted = sorted(
        role.value
        for role in ColorRole
        if subscores[role] is not None and subscores[role] < 100.0
    )

    details: list[str] = []
    if drifted:
        details.append("drift in " + ", ".join(drifted))
    if unmeasured:
        details.append("no colour evidence for " + ", ".join(unmeasured))

    return DimensionScore(
        dimension=FidelityDimension.COLOR,
        score=score,
        detail="; ".join(details) if details else None,
    )
