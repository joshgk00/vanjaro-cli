"""Translate observed design styles into maintainable Vanjaro decisions.

The translator is intentionally source-neutral.  HTML and Figma adapters emit
``StyleObservation`` values; this module applies the agency precedence policy
without inspecting DOM nodes or Figma JSON.
"""

from __future__ import annotations

import math
import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from vanjaro_cli.design.models import (
    BreakpointName,
    EvidenceStatus,
    ObservationMethod,
    ResponsiveObservation,
    StyleObservation,
    StyleProperty,
    StyleSet,
)
from vanjaro_cli.design.template_catalog import CapabilityManifest

__all__ = [
    "StyleDecision",
    "StyleTranslationConfig",
    "StyleTranslationResult",
    "TranslationLayer",
    "translate_responsive_observations",
    "translate_style_set",
]


class TranslationLayer(str, Enum):
    """Ordered maintenance layers used to represent a source property."""

    THEME = "theme"
    PLATFORM_UTILITY = "platform_utility"
    TEMPLATE_MODIFIER = "template_modifier"
    AGENCY_UTILITY = "agency_utility"
    SCOPED_CSS = "scoped_css"
    MEASUREMENT_ONLY = "measurement_only"
    MANUAL = "manual"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StyleDecision(_StrictModel):
    """One explainable source-style translation decision."""

    property: StyleProperty
    source_value: str
    layer: TranslationLayer
    target: str
    confidence: float = Field(ge=0, le=1)
    distance: float | None = Field(default=None, ge=0)
    reason: str
    breakpoint: BreakpointName | None = None
    evidence_status: EvidenceStatus = EvidenceStatus.OBSERVED


class StyleTranslationConfig(_StrictModel):
    """Available theme values, utilities, and policy limits."""

    palette: dict[str, str] = Field(default_factory=dict)
    typography: dict[str, str] = Field(default_factory=dict)
    spacing: dict[str, str] = Field(default_factory=dict)
    radii: dict[str, str] = Field(default_factory=dict)
    agency_utilities: dict[str, str] = Field(default_factory=dict)
    modifier_properties: dict[StyleProperty, str] = Field(default_factory=dict)
    project_prefix: str = "vj-generated"
    palette_distance_threshold: float = Field(default=0.12, ge=0, le=1)
    max_scoped_rules_per_section: int = Field(default=12, ge=0)
    important_allowlist: frozenset[StyleProperty] = frozenset()


class StyleTranslationResult(_StrictModel):
    """Decisions and scoped CSS declarations for one style owner."""

    decisions: tuple[StyleDecision, ...]
    css_declarations: dict[str, str]
    warnings: tuple[str, ...]

    @property
    def scoped_rule_count(self) -> int:
        return len(self.css_declarations)


_COLOR_PROPERTIES = {
    StyleProperty.BACKGROUND_COLOR,
    StyleProperty.TEXT_COLOR,
    StyleProperty.BORDER,
    StyleProperty.OVERLAY_COLOR,
}

_CSS_PROPERTY_NAMES: dict[StyleProperty, str] = {
    StyleProperty.BACKGROUND_COLOR: "background-color",
    StyleProperty.BACKGROUND_IMAGE: "background-image",
    StyleProperty.BACKGROUND_POSITION: "background-position",
    StyleProperty.TEXT_COLOR: "color",
    StyleProperty.FONT_FAMILY: "font-family",
    StyleProperty.FONT_SIZE: "font-size",
    StyleProperty.FONT_WEIGHT: "font-weight",
    StyleProperty.LINE_HEIGHT: "line-height",
    StyleProperty.LETTER_SPACING: "letter-spacing",
    StyleProperty.WIDTH: "width",
    StyleProperty.HEIGHT: "height",
    StyleProperty.MIN_HEIGHT: "min-height",
    StyleProperty.MAX_WIDTH: "max-width",
    StyleProperty.MARGIN: "margin",
    StyleProperty.PADDING: "padding",
    StyleProperty.ROW_GAP: "row-gap",
    StyleProperty.COLUMN_GAP: "column-gap",
    StyleProperty.TEXT_ALIGN: "text-align",
    StyleProperty.ITEM_ALIGN: "align-items",
    StyleProperty.BORDER: "border",
    StyleProperty.BORDER_RADIUS: "border-radius",
    StyleProperty.BOX_SHADOW: "box-shadow",
    StyleProperty.OBJECT_FIT: "object-fit",
    StyleProperty.OBJECT_POSITION: "object-position",
    StyleProperty.POSITION: "position",
    StyleProperty.OVERLAP: "inset",
    StyleProperty.TRANSFORM: "transform",
    StyleProperty.ROTATION: "rotate",
    StyleProperty.OPACITY: "opacity",
    StyleProperty.OVERLAY_COLOR: "background-color",
    StyleProperty.DISPLAY: "display",
    StyleProperty.VISIBILITY: "visibility",
    StyleProperty.FLEX_DIRECTION: "flex-direction",
    StyleProperty.FLEX_WRAP: "flex-wrap",
    StyleProperty.ORDER: "order",
    StyleProperty.COLUMN_COUNT: "column-count",
}

# A browser reports the *complete* computed style for every section, because the
# fidelity metrics need it to compare. Only some of it is design intent worth
# reproducing. Emitting the rest as scoped CSS pins a block to one browser's
# layout and works against the native-component and editable-coverage ratios.
#
# This set governs translation only. Scoring still reads every measured
# property. Non-rendered sources are unaffected: a Figma frame that declares
# min-height is stating intent, while a browser reporting min-height is not.
_RENDERED_REPRODUCIBLE_PROPERTIES: frozenset[StyleProperty] = frozenset(
    {
        StyleProperty.BACKGROUND_COLOR,
        StyleProperty.BACKGROUND_IMAGE,
        StyleProperty.BACKGROUND_POSITION,
        StyleProperty.TEXT_COLOR,
        StyleProperty.OVERLAY_COLOR,
        StyleProperty.FONT_FAMILY,
        StyleProperty.FONT_SIZE,
        StyleProperty.FONT_WEIGHT,
        StyleProperty.LINE_HEIGHT,
        StyleProperty.LETTER_SPACING,
        StyleProperty.PADDING,
        StyleProperty.ROW_GAP,
        StyleProperty.COLUMN_GAP,
        StyleProperty.TEXT_ALIGN,
        StyleProperty.ITEM_ALIGN,
        StyleProperty.BORDER_RADIUS,
        StyleProperty.BOX_SHADOW,
        StyleProperty.OBJECT_FIT,
        StyleProperty.OBJECT_POSITION,
    }
)

# A computed value equal to the CSS initial value is the absence of a decision,
# not a decision to use the default. Reproducing it costs a rule and says
# nothing. Keyed by CSS property name so one entry covers every alias.
_CSS_INITIAL_VALUES: dict[str, frozenset[str]] = {
    "background-image": frozenset({"none"}),
    "background-position": frozenset({"0% 0%", "0px 0px"}),
    "border-radius": frozenset({"0px", "0"}),
    "box-shadow": frozenset({"none"}),
    "column-gap": frozenset({"normal", "0px"}),
    "row-gap": frozenset({"normal", "0px"}),
    "letter-spacing": frozenset({"normal"}),
    "line-height": frozenset({"normal"}),
    "object-fit": frozenset({"fill"}),
    "object-position": frozenset({"50% 50%"}),
    "padding": frozenset({"0px"}),
    "text-align": frozenset({"start", "auto"}),
}

_UTILITY_VALUES: dict[StyleProperty, dict[str, str]] = {
    StyleProperty.TEXT_ALIGN: {
        "left": "text-start",
        "center": "text-center",
        "right": "text-end",
    },
    StyleProperty.ITEM_ALIGN: {
        "start": "align-items-start",
        "center": "align-items-center",
        "end": "align-items-end",
        "stretch": "align-items-stretch",
    },
    StyleProperty.DISPLAY: {
        "none": "d-none",
        "block": "d-block",
        "inline": "d-inline",
        "inline-block": "d-inline-block",
        "flex": "d-flex",
        "grid": "d-grid",
    },
    StyleProperty.FLEX_DIRECTION: {
        "row": "flex-row",
        "row-reverse": "flex-row-reverse",
        "column": "flex-column",
        "column-reverse": "flex-column-reverse",
    },
    StyleProperty.FLEX_WRAP: {
        "wrap": "flex-wrap",
        "nowrap": "flex-nowrap",
    },
    StyleProperty.OBJECT_FIT: {
        "contain": "object-fit-contain",
        "cover": "object-fit-cover",
    },
    StyleProperty.POSITION: {
        "relative": "position-relative",
        "absolute": "position-absolute",
        "fixed": "position-fixed",
        "sticky": "position-sticky",
    },
    StyleProperty.VISIBILITY: {
        "visible": "visible",
        "hidden": "invisible",
    },
}

_HEX_RE = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$", re.IGNORECASE)
_RGB_RE = re.compile(
    r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,[^)]*)?\)$",
    re.IGNORECASE,
)
_SAFE_CSS_VALUE = re.compile(r"^[^{};]+$")
_SAFE_PREFIX = re.compile(r"^[a-z][a-z0-9-]*$")


def _string_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _rgb(value: str) -> tuple[int, int, int] | None:
    normalized = value.strip().lower()
    match = _HEX_RE.fullmatch(normalized)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(character * 2 for character in digits)
        return tuple(int(digits[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
    match = _RGB_RE.fullmatch(normalized)
    if not match:
        return None
    channels = tuple(int(channel) for channel in match.groups())
    if any(channel > 255 for channel in channels):
        return None
    return channels  # type: ignore[return-value]


def _color_distance(left: str, right: str) -> float | None:
    left_rgb = _rgb(left)
    right_rgb = _rgb(right)
    if left_rgb is None or right_rgb is None:
        return None
    squared = sum((a - b) ** 2 for a, b in zip(left_rgb, right_rgb))
    return math.sqrt(squared) / math.sqrt(3 * (255**2))


def _nearest_palette(
    value: str, palette: dict[str, str]
) -> tuple[str, float] | None:
    candidates: list[tuple[str, float]] = []
    for slot, color in palette.items():
        distance = _color_distance(value, color)
        if distance is not None:
            candidates.append((slot, distance))
    return min(candidates, key=lambda item: (item[1], item[0])) if candidates else None


def _theme_decision(
    observation: StyleObservation,
    value: str,
    config: StyleTranslationConfig,
    breakpoint: BreakpointName | None,
) -> StyleDecision | None:
    if observation.property in _COLOR_PROPERTIES:
        nearest = _nearest_palette(value, config.palette)
        if nearest is not None and nearest[1] <= config.palette_distance_threshold:
            slot, distance = nearest
            target = f"bg-{slot}" if observation.property in {
                StyleProperty.BACKGROUND_COLOR,
                StyleProperty.OVERLAY_COLOR,
            } else f"text-{slot}"
            return StyleDecision(
                property=observation.property,
                source_value=value,
                layer=TranslationLayer.THEME,
                target=target,
                confidence=max(0.0, 1.0 - distance),
                distance=distance,
                reason=f"nearest configured theme palette slot '{slot}'",
                breakpoint=breakpoint,
                evidence_status=observation.status,
            )

    lookup: dict[str, str] | None = None
    if observation.property in {
        StyleProperty.FONT_FAMILY,
        StyleProperty.FONT_SIZE,
        StyleProperty.FONT_WEIGHT,
        StyleProperty.LINE_HEIGHT,
        StyleProperty.LETTER_SPACING,
    }:
        lookup = config.typography
    elif observation.property in {
        StyleProperty.MARGIN,
        StyleProperty.PADDING,
        StyleProperty.ROW_GAP,
        StyleProperty.COLUMN_GAP,
    }:
        lookup = config.spacing
    elif observation.property == StyleProperty.BORDER_RADIUS:
        lookup = config.radii
    if lookup is not None:
        target = lookup.get(value.casefold()) or lookup.get(value)
        if target:
            return StyleDecision(
                property=observation.property,
                source_value=value,
                layer=TranslationLayer.THEME,
                target=target,
                confidence=1.0,
                distance=0.0,
                reason="exact configured theme value",
                breakpoint=breakpoint,
                evidence_status=observation.status,
            )
    return None


def _utility_decision(
    observation: StyleObservation,
    value: str,
    breakpoint: BreakpointName | None,
) -> StyleDecision | None:
    utility = _UTILITY_VALUES.get(observation.property, {}).get(value.casefold())
    if utility is None:
        return None
    return StyleDecision(
        property=observation.property,
        source_value=value,
        layer=TranslationLayer.PLATFORM_UTILITY,
        target=utility,
        confidence=1.0,
        distance=0.0,
        reason="exact Bootstrap/Vanjaro utility",
        breakpoint=breakpoint,
        evidence_status=observation.status,
    )


def _modifier_decision(
    observation: StyleObservation,
    value: str,
    capabilities: CapabilityManifest,
    config: StyleTranslationConfig,
    breakpoint: BreakpointName | None,
) -> StyleDecision | None:
    modifier = config.modifier_properties.get(observation.property)
    if modifier is None or modifier not in capabilities.supported_modifiers:
        return None
    return StyleDecision(
        property=observation.property,
        source_value=value,
        layer=TranslationLayer.TEMPLATE_MODIFIER,
        target=f"{modifier}={value}",
        confidence=0.95,
        distance=0.0,
        reason=f"template declares modifier '{modifier}'",
        breakpoint=breakpoint,
        evidence_status=observation.status,
    )


def _agency_decision(
    observation: StyleObservation,
    value: str,
    config: StyleTranslationConfig,
    breakpoint: BreakpointName | None,
) -> StyleDecision | None:
    key = f"{observation.property.value}:{value.casefold()}"
    utility = config.agency_utilities.get(key)
    if utility is None:
        return None
    return StyleDecision(
        property=observation.property,
        source_value=value,
        layer=TranslationLayer.AGENCY_UTILITY,
        target=utility,
        confidence=0.9,
        distance=0.0,
        reason="existing agency utility matches the observed value",
        breakpoint=breakpoint,
        evidence_status=observation.status,
    )


def _is_rendered(observation: StyleObservation) -> bool:
    return any(
        record.method is ObservationMethod.RENDERED for record in observation.provenance
    )


def _measurement_only_decision(
    observation: StyleObservation,
    value: str,
    breakpoint: BreakpointName | None,
) -> StyleDecision | None:
    """Keep a measured value out of the build without discarding it.

    Only rendered observations are filtered. A browser reports every computed
    property whether or not anyone chose it, so its output needs a design-intent
    filter that a Figma frame's declared values do not.
    """

    if not _is_rendered(observation):
        return None
    css_property = _CSS_PROPERTY_NAMES.get(observation.property)
    if observation.property not in _RENDERED_REPRODUCIBLE_PROPERTIES:
        reason = "measured for scoring; not design intent to reproduce"
    elif value.strip().casefold() in _CSS_INITIAL_VALUES.get(css_property or "", ()):
        reason = "measured value is the CSS initial value, so it states no intent"
    else:
        return None
    return StyleDecision(
        property=observation.property,
        source_value=value,
        layer=TranslationLayer.MEASUREMENT_ONLY,
        target="measurement_only",
        confidence=1.0,
        distance=0.0,
        reason=reason,
        breakpoint=breakpoint,
        evidence_status=observation.status,
    )


def _css_decision(
    observation: StyleObservation,
    value: str,
    config: StyleTranslationConfig,
    breakpoint: BreakpointName | None,
) -> tuple[StyleDecision, tuple[str, str] | None, str | None]:
    css_property = _CSS_PROPERTY_NAMES.get(observation.property)
    if css_property is None or not value or not _SAFE_CSS_VALUE.fullmatch(value):
        decision = StyleDecision(
            property=observation.property,
            source_value=value,
            layer=TranslationLayer.MANUAL,
            target="manual_review",
            confidence=0.0,
            reason="value cannot be represented safely by the automatic translator",
            breakpoint=breakpoint,
            evidence_status=observation.status,
        )
        return decision, None, f"manual review required for {observation.property.value}: {value}"

    suffix = ""
    if "!important" in value:
        if observation.property not in config.important_allowlist:
            decision = StyleDecision(
                property=observation.property,
                source_value=value,
                layer=TranslationLayer.MANUAL,
                target="manual_review",
                confidence=0.0,
                reason="!important is not allowlisted for this property",
                breakpoint=breakpoint,
                evidence_status=observation.status,
            )
            return decision, None, f"blocked non-allowlisted !important for {observation.property.value}"
        value = value.replace("!important", "").strip()
        suffix = " !important"

    decision = StyleDecision(
        property=observation.property,
        source_value=value,
        layer=TranslationLayer.SCOPED_CSS,
        target=f"{css_property}:{value}{suffix}",
        confidence=0.75,
        reason="no theme value, utility, or supported reusable modifier matched",
        breakpoint=breakpoint,
        evidence_status=observation.status,
    )
    key = f"{breakpoint.value}:{css_property}" if breakpoint else css_property
    return decision, (key, f"{value}{suffix}"), None


def _translate_observations(
    observations: list[StyleObservation],
    capabilities: CapabilityManifest,
    config: StyleTranslationConfig,
    breakpoint: BreakpointName | None,
) -> StyleTranslationResult:
    if not _SAFE_PREFIX.fullmatch(config.project_prefix):
        raise ValueError("project_prefix must be a lowercase CSS-safe name")

    decisions: list[StyleDecision] = []
    declarations: dict[str, str] = {}
    warnings: list[str] = []
    for observation in observations:
        value = _string_value(observation.value)
        decision = (
            _theme_decision(observation, value, config, breakpoint)
            or _utility_decision(observation, value, breakpoint)
            or _modifier_decision(observation, value, capabilities, config, breakpoint)
            or _agency_decision(observation, value, config, breakpoint)
            or _measurement_only_decision(observation, value, breakpoint)
        )
        if decision is not None:
            decisions.append(decision)
            continue
        decision, declaration, warning = _css_decision(
            observation, value, config, breakpoint
        )
        decisions.append(decision)
        if declaration is not None:
            declarations[declaration[0]] = declaration[1]
        if warning:
            warnings.append(warning)

    if len(declarations) > config.max_scoped_rules_per_section:
        warnings.append(
            f"scoped CSS budget exceeded: {len(declarations)} declarations "
            f"(maximum {config.max_scoped_rules_per_section}); review for a new template"
        )
    return StyleTranslationResult(
        decisions=tuple(decisions),
        css_declarations=declarations,
        warnings=tuple(warnings),
    )


def translate_style_set(
    style: StyleSet,
    capabilities: CapabilityManifest,
    config: StyleTranslationConfig,
) -> StyleTranslationResult:
    """Translate a base style set using the required maintenance precedence."""

    result = _translate_observations(style.observations, capabilities, config, None)
    if not style.raw:
        return result
    return StyleTranslationResult(
        decisions=result.decisions,
        css_declarations=result.css_declarations,
        warnings=result.warnings
        + ("raw source styles were preserved as evidence but not copied automatically",),
    )


def translate_responsive_observations(
    observations: list[ResponsiveObservation],
    capabilities: CapabilityManifest,
    config: StyleTranslationConfig,
) -> StyleTranslationResult:
    """Translate breakpoint style deltas without treating inferred data as observed."""

    decisions: list[StyleDecision] = []
    declarations: dict[str, str] = {}
    warnings: list[str] = []
    for responsive in observations:
        result = _translate_observations(
            responsive.style.observations,
            capabilities,
            config,
            responsive.breakpoint,
        )
        decisions.extend(result.decisions)
        declarations.update(result.css_declarations)
        warnings.extend(result.warnings)
        if responsive.status == EvidenceStatus.INFERRED:
            warnings.append(
                f"{responsive.breakpoint.value} behavior is inferred rather than observed"
            )
        if responsive.layout_changes.get("navigation") == "collapsed" and responsive.hidden:
            warnings.append(
                f"{responsive.breakpoint.value} navigation is marked collapsed and hidden; "
                "verify a visible menu trigger exists"
            )
        if responsive.style.raw:
            warnings.append(
                f"raw {responsive.breakpoint.value} styles were not copied automatically"
            )
    if len(declarations) > config.max_scoped_rules_per_section:
        warnings.append(
            f"responsive scoped CSS budget exceeded: {len(declarations)} declarations "
            f"(maximum {config.max_scoped_rules_per_section})"
        )
    return StyleTranslationResult(
        decisions=tuple(decisions),
        css_declarations=declarations,
        warnings=tuple(dict.fromkeys(warnings)),
    )
