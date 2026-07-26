"""Deterministic DesignDocument to Vanjaro theme-control planning.

This module is deliberately pure: it consumes a committed DesignDocument and
an already-read ``AIDesign/GetSettings`` payload, and produces a strict plan.
It never owns a portal client and therefore cannot mutate a site.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Any, Literal

from vanjaro_cli.design.models import DesignDocument, TypographyToken
from vanjaro_cli.design.theme_palette_plan import PALETTE_ORDER, plan_palette
from vanjaro_cli.design.theme_plan_models import (
    ProjectThemePlan,
    THEME_PLAN_SCHEMA_VERSION,
    ThemeControlPlan,
    ThemeFontDecision,
    ThemePlanWarning,
)


_PALETTE_CONTROLS = {
    "primary": "$primarycolor",
    "secondary": "$secondarycolor",
    "tertiary": "$tertiary",
    "quaternary": "$quaternary",
    "success": "$successcolor",
    "info": "$infocolor",
    "warning": "$warningcolor",
    "danger": "$dangercolor",
    "light": "$lightcolor",
    "dark": "$darkcolor",
}


def build_project_theme_plan(
    document: DesignDocument,
    settings: dict[str, Any],
) -> ProjectThemePlan:
    """Map design tokens only to controls and fonts present in ``settings``.

    The planner intentionally does not synthesize font stacks or arbitrary
    control names. A font family must exactly match an available Vanjaro font
    name/first-family before any font control is proposed.
    """

    controls, control_warnings = _normalize_controls(settings.get("controls"))
    controls_by_variable = _by_variable(controls)
    warnings = list(control_warnings)
    palette, color_sources, color_warnings = plan_palette(document)
    warnings.extend(color_warnings)
    proposed: dict[tuple[str, str], ThemeControlPlan] = {}

    for slot in PALETTE_ORDER:
        value = palette.get(slot)
        if value is None:
            continue
        variable = _PALETTE_CONTROLS[slot]
        control = controls_by_variable.get(variable.casefold())
        if control is None:
            warnings.append(
                ThemePlanWarning(
                    code="THEME_CONTROL_UNAVAILABLE",
                    message=(
                        f"Palette slot '{slot}' resolved to {value}, but the live theme "
                        f"does not expose {variable}."
                    ),
                    token_paths=color_sources[slot],
                )
            )
            continue
        item = _control_plan(
            control,
            value,
            color_sources[slot],
            f"mapped design color token to the existing '{slot}' palette slot",
        )
        proposed[(item.less_variable.casefold(), item.guid.casefold())] = item

    font_decisions, font_targets, font_warnings = _plan_fonts(
        document.tokens.typography,
        settings.get("availableFonts", settings.get("available_fonts")),
    )
    warnings.extend(font_warnings)
    for target, target_value in sorted(font_targets.items()):
        target_controls = _font_controls_for_target(controls, target)
        if not target_controls:
            warnings.append(
                ThemePlanWarning(
                    code="THEME_FONT_CONTROL_UNAVAILABLE",
                    message=(
                        f"Font role '{target}' resolved to '{target_value[0]}', but the "
                        "live theme exposes no matching font-family control."
                    ),
                    token_paths=target_value[1],
                )
            )
            continue
        for control in target_controls:
            item = _control_plan(
                control,
                target_value[0],
                target_value[1],
                f"mapped observed '{target}' typography to an existing font value",
            )
            proposed[(item.less_variable.casefold(), item.guid.casefold())] = item

    for index, token_id in enumerate(sorted(document.tokens.spacing)):
        warnings.append(
            ThemePlanWarning(
                code="UNRESOLVED_SPACING_TOKEN",
                message=(
                    f"Spacing token '{token_id}' has no unambiguous global Vanjaro "
                    "control mapping and was left for review."
                ),
                token_paths=[f"tokens.spacing.{token_id}"],
            )
        )

    return ProjectThemePlan(
        theme_name=_nonempty(settings.get("themeName", settings.get("theme_name"))) or "unknown",
        current_palette={
            slot: controls_by_variable[_PALETTE_CONTROLS[slot].casefold()]["current_value"]
            for slot in PALETTE_ORDER
            if _PALETTE_CONTROLS[slot].casefold() in controls_by_variable
        },
        proposed_palette={slot: palette[slot] for slot in PALETTE_ORDER if slot in palette},
        controls=sorted(
            proposed.values(),
            key=lambda item: (item.less_variable.casefold(), item.guid.casefold()),
        ),
        fonts=font_decisions,
        warnings=sorted(
            warnings,
            key=lambda item: (item.code, item.token_paths, item.message),
        ),
    )


def _normalize_controls(value: object) -> tuple[list[dict[str, str]], list[ThemePlanWarning]]:
    if not isinstance(value, list):
        return [], [
            ThemePlanWarning(
                code="THEME_CONTROL_CATALOG_INVALID",
                message="Live theme settings did not contain a controls array.",
            )
        ]
    controls: list[dict[str, str]] = []
    warnings: list[ThemePlanWarning] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            warnings.append(
                ThemePlanWarning(
                    code="THEME_CONTROL_INVALID",
                    message=f"Theme control at index {index} is not an object.",
                )
            )
            continue
        normalized = {
            key: _nonempty(raw.get(source)) or ""
            for key, source in (
                ("guid", "guid"),
                ("less_variable", "lessVariable"),
                ("category", "category"),
                ("title", "title"),
                ("type", "type"),
                ("current_value", "currentValue"),
            )
        }
        if not normalized["guid"] or not normalized["less_variable"]:
            warnings.append(
                ThemePlanWarning(
                    code="THEME_CONTROL_INVALID",
                    message=(
                        f"Theme control at index {index} lacks a guid or lessVariable and "
                        "cannot be targeted safely."
                    ),
                )
            )
            continue
        controls.append(normalized)
    controls.sort(key=lambda item: (item["less_variable"].casefold(), item["guid"].casefold()))
    counts = Counter(control["less_variable"].casefold() for control in controls)
    ambiguous = {variable for variable, count in counts.items() if count > 1}
    for variable in sorted(ambiguous):
        warnings.append(
            ThemePlanWarning(
                code="THEME_CONTROL_AMBIGUOUS",
                message=(
                    f"The live theme exposes multiple controls for lessVariable '{variable}'; "
                    "none will be targeted until the collision is resolved."
                ),
            )
        )
    controls = [
        control
        for control in controls
        if control["less_variable"].casefold() not in ambiguous
    ]
    return controls, warnings


def _plan_fonts(
    typography: list[TypographyToken],
    available_value: object,
) -> tuple[
    list[ThemeFontDecision],
    dict[str, tuple[str, list[str]]],
    list[ThemePlanWarning],
]:
    available = _available_fonts(available_value)
    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    display_names: dict[tuple[str, str], str] = {}
    warnings: list[ThemePlanWarning] = []
    for index, token in enumerate(typography):
        family = _nonempty(token.font_family)
        if family is None:
            warnings.append(
                ThemePlanWarning(
                    code="UNRESOLVED_FONT_TOKEN",
                    message=(
                        f"Typography token {index} has no observed font family and cannot "
                        "be mapped to a global Vanjaro font control."
                    ),
                    token_paths=[f"tokens.typography[{index}]"],
                )
            )
            continue
        role = _font_target(token.role)
        path = f"tokens.typography[{index}].font_family"
        normalized_family = _normalized_font(family)
        grouped[role][normalized_family].append(path)
        display_names[(role, normalized_family)] = family

    decisions: list[ThemeFontDecision] = []
    targets: dict[str, tuple[str, list[str]]] = {}
    for role in sorted(grouped):
        families = grouped[role]
        selected = min(
            families,
            key=lambda family: (-len(families[family]), family),
        )
        for family in sorted(families):
            paths = sorted(families[family])
            observed = display_names[(role, family)]
            existing = available.get(family)
            if existing is None:
                status: Literal["mapped", "unresolved", "not_selected"] = "unresolved"
                warnings.append(
                    ThemePlanWarning(
                        code="UNRESOLVED_FONT_TOKEN",
                        message=(
                            f"Observed font '{observed}' for role '{role}' is not in the "
                            "portal's available-font catalog; register its real source before applying it."
                        ),
                        token_paths=paths,
                    )
                )
            elif family != selected:
                status = "not_selected"
                warnings.append(
                    ThemePlanWarning(
                        code="FONT_ROLE_VARIANT_REQUIRES_REVIEW",
                        message=(
                            f"Observed font '{observed}' is available but is not the dominant "
                            f"family for role '{role}'; no global substitution was made."
                        ),
                        token_paths=paths,
                    )
                )
            else:
                status = "mapped"
                targets[role] = (existing, paths)
            decisions.append(
                ThemeFontDecision(
                    role=role,
                    observed_family=observed,
                    occurrences=len(paths),
                    status=status,
                    available_value=existing if status in {"mapped", "not_selected"} else None,
                    source_token_paths=paths,
                )
            )
    decisions.sort(key=lambda item: (item.role, _normalized_font(item.observed_family)))
    return decisions, targets, warnings


def _available_fonts(value: object) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    result: dict[str, str] = {}
    for raw in value:
        if not isinstance(raw, dict):
            continue
        name = _nonempty(raw.get("name", raw.get("Name")))
        family = _nonempty(raw.get("value", raw.get("Value", raw.get("family", raw.get("Family")))))
        if not name or not family:
            continue
        for identity in (name, family.split(",", 1)[0].strip(" '\"")):
            result.setdefault(_normalized_font(identity), family)
    return result


def _font_target(role: str) -> str:
    normalized = _normalized_identifier(role)
    if normalized in {"display", "heading", "title", "subtitle"}:
        return "headings"
    if normalized in {"button", "cta"}:
        return "buttons"
    if normalized in {"menu", "navigation", "nav"}:
        return "menu"
    if normalized in {"link", "anchor"}:
        return "links"
    return "body"


def _font_controls_for_target(
    controls: list[dict[str, str]], target: str
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for control in controls:
        category = control["category"].casefold()
        variable = control["less_variable"].casefold()
        is_font = control["type"].casefold() == "fonts" or "font family" in control["title"].casefold()
        if not is_font:
            continue
        matches = (
            target == "body" and (variable == "$sitefontfamily" or category == "styles: text")
            or target == "headings" and category == "styles: heading"
            or target == "buttons" and category == "styles: button"
            or target == "menu" and category == "styles: menu"
            or target == "links" and category == "link"
        )
        if matches:
            result.append(control)
    return result


def _control_plan(
    control: dict[str, str],
    planned_value: str,
    source_paths: list[str],
    reason: str,
) -> ThemeControlPlan:
    return ThemeControlPlan(
        guid=control["guid"],
        less_variable=control["less_variable"],
        category=control["category"],
        title=control["title"],
        current_value=control["current_value"],
        planned_value=planned_value,
        changed=control["current_value"] != planned_value,
        source_token_paths=sorted(source_paths),
        reason=reason,
    )


def _by_variable(controls: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for control in controls:
        result.setdefault(control["less_variable"].casefold(), control)
    return result


def _normalized_font(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" '\"").casefold())


def _normalized_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _nonempty(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


__all__ = [
    "ProjectThemePlan",
    "THEME_PLAN_SCHEMA_VERSION",
    "ThemeControlPlan",
    "ThemeFontDecision",
    "ThemePlanWarning",
    "build_project_theme_plan",
]
