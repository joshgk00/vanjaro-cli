"""Route project header composition through navigation template matching.

VF-206.  Headers used to be composed only by the bespoke builder in
``portal.global_header``.  A navigation template family now exists, so a header
section is matched against the catalog like any other section and composed from
the winning template.  The bespoke composer stays as the fallback until a portal
run confirms parity — every result records which path produced it so that
comparison is possible.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from vanjaro_cli.design.matcher import ConfidenceLevel, match_section
from vanjaro_cli.design.models import AssetRecord, Section, StyleProperty
from vanjaro_cli.design.planner import PlanningError, bind_section
from vanjaro_cli.design.style_transport import build_style_rules, ensure_scoped_selector_id
from vanjaro_cli.design.template_catalog import (
    TemplateCatalogEntry,
    load_template_catalog,
    load_template_data,
)
from vanjaro_cli.portal.global_header import build_project_header
from vanjaro_cli.utils.block_compose import apply_overrides, enumerate_slots


HEADER_TEMPLATE_ROLES = frozenset({"navigation", "primary_navigation", "site_header"})
HEADER_MATCH_CONFIDENCE_FLOOR = ConfidenceLevel.MEDIUM
_BRAND_FIELD = "brand"

_ACCEPTED_CONFIDENCE = frozenset({ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM})


def compose_header_block(
    section: Section,
    assets: Mapping[str, AssetRecord],
    *,
    brand_text: str,
    catalog: Sequence[TemplateCatalogEntry] | None = None,
) -> dict[str, Any]:
    """Compose a header, preferring a matched navigation template.

    The returned mapping carries the same ``components``/``styles``/``warnings``
    contract as :func:`build_project_header`, plus ``composition_path`` and
    ``template_id`` so a portal parity run can attribute any difference.
    """

    entries = tuple(catalog) if catalog is not None else load_template_catalog()
    navigation = [entry for entry in entries if _is_navigation_template(entry)]
    if navigation:
        matched = _compose_from_template(section, assets, brand_text, navigation)
        if matched is not None:
            return _with_designed_height(matched, section)
    built = build_project_header(section, assets, brand_text=brand_text)
    return _with_designed_height(
        {**built, "composition_path": "composer", "template_id": None}, section
    )


# Strict enough to need no further style validation: digits and "px" only.
_POSITIVE_PIXELS = re.compile(r"^(?=.*[1-9])\d+(?:\.\d+)?px$")


def _with_designed_height(built: dict[str, Any], section: Section) -> dict[str, Any]:
    """Give a composed header the minimum height its design section carried.

    Body sections get this from the composition plan. A header is composed
    outside that plan, so without this its height was whatever its content
    needed (53px against a 131px design). Only a positive pixel minimum is
    carried: a rendered page reports ``auto`` or ``0px`` for "no minimum".
    """

    minimum = next(
        (
            observation.value.strip()
            for observation in section.style.observations
            if observation.property is StyleProperty.MIN_HEIGHT
            and observation.condition is None
            and isinstance(observation.value, str)
            and _POSITIVE_PIXELS.fullmatch(observation.value.strip())
        ),
        None,
    )
    components = built.get("components")
    if minimum is None or not components or not isinstance(components[0], dict):
        return built
    element_id = ensure_scoped_selector_id(components[0], section.id)
    return {
        **built,
        "styles": [
            *built.get("styles", []),
            *build_style_rules(element_id, {(): {"min-height": minimum}}),
        ],
    }


def _is_navigation_template(entry: TemplateCatalogEntry) -> bool:
    return bool(HEADER_TEMPLATE_ROLES.intersection(entry.capabilities.roles))


def _compose_from_template(
    section: Section,
    assets: Mapping[str, AssetRecord],
    brand_text: str,
    navigation: Sequence[TemplateCatalogEntry],
) -> dict[str, Any] | None:
    result = match_section(section, navigation)
    candidate = result.selected_candidate
    if result.blocking or candidate.confidence not in _ACCEPTED_CONFIDENCE:
        return None
    entry = next(
        (item for item in navigation if item.template_id == candidate.template_id),
        None,
    )
    if entry is None:
        return None
    try:
        bindings = bind_section(section, entry, assets=assets)
    except PlanningError:
        # A declared-but-unbindable header is exactly the case the bespoke
        # composer still exists to cover.
        return None

    overrides = {binding.slot: binding.value for binding in bindings}
    warnings: list[str] = []
    if not any(binding.semantic_field == _BRAND_FIELD for binding in bindings):
        brand_slot = _first_slot(entry, "heading")
        if brand_slot is None:
            return None
        overrides[brand_slot] = brand_text
        warnings.append(
            f"header had no observed brand element; rendered accessible brand text {brand_text!r}"
        )

    template_data = load_template_data(entry)
    composed = apply_overrides(template_data, _blank_unfilled_slots(template_data, overrides))
    root = composed.get("template")
    if not isinstance(root, dict):
        return None
    styles = composed.get("styles")
    return {
        "components": [root],
        "styles": styles if isinstance(styles, list) else [],
        "warnings": warnings,
        "composition_path": "template",
        "template_id": entry.template_id,
    }


def _first_slot(entry: TemplateCatalogEntry, slot_type: str) -> str | None:
    for contract in entry.capabilities.physical_fields.values():
        if contract.slot_type == slot_type and contract.slots:
            return contract.slots[0]
    return None


def _blank_unfilled_slots(
    template_data: dict[str, Any], overrides: dict[str, str]
) -> dict[str, str]:
    """Blank the content slots no binding filled so template copy never ships."""

    filled = dict(overrides)
    expanded = apply_overrides(template_data, overrides)
    for slot in enumerate_slots(expanded["template"]):
        if slot["field"] == "content" and slot["key"] not in filled:
            filled[slot["key"]] = ""
    return filled


__all__ = [
    "HEADER_MATCH_CONFIDENCE_FLOOR",
    "HEADER_TEMPLATE_ROLES",
    "compose_header_block",
]
