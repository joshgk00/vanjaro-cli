"""Block template resolution, slot enumeration, and content override application."""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Generator

__all__ = [
    "TemplateNotFoundError",
    "apply_overrides",
    "check_overflow",
    "enumerate_slots",
    "expand_image_slots",
    "expand_text_slots",
    "find_template",
    "get_templates_dir",
]

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_TEMPLATES_DIR = _PACKAGE_ROOT / "artifacts" / "block-templates"

# Component types whose `content` field can be overridden
CONTENT_TYPES = frozenset({"heading", "text", "button", "link", "list-item"})

# Component types with overridable attributes beyond content
ATTRIBUTE_SLOTS: dict[str, list[tuple[str, str]]] = {
    "button": [("href", "href")],
    "link": [("href", "href")],
    "image": [("src", "src"), ("alt", "alt")],
}


class TemplateNotFoundError(Exception):
    """Raised when a template name doesn't match any file in the library."""

    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
        available_str = ", ".join(available) if available else "none found"
        super().__init__(f"Template '{name}' not found. Available: {available_str}")


def get_templates_dir() -> Path:
    """Return the block templates directory, checking env var override first."""
    override = os.environ.get("VANJARO_TEMPLATES_DIR")
    if override:
        return Path(override)
    return _DEFAULT_TEMPLATES_DIR


def find_template(name: str, templates_dir: Path | None = None) -> dict:
    """Find and load a template by name (case-insensitive exact match).

    Raises TemplateNotFoundError with a list of available names if not found.
    """
    if templates_dir is None:
        templates_dir = get_templates_dir()
    if not templates_dir.is_dir():
        raise TemplateNotFoundError(name, [])

    available: list[str] = []
    for json_file in sorted(templates_dir.rglob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        tpl_name = data.get("name", json_file.stem)
        if tpl_name.lower() == name.lower():
            return data
        available.append(tpl_name)

    raise TemplateNotFoundError(name, available)


def _walk_overridable(
    component: dict,
    counters: dict[str, int] | None = None,
) -> Generator[tuple[dict, str, int], None, None]:
    """Yield (component, type, index) for each overridable component in document order.

    Counters are per-type and 1-based, shared across the entire tree walk.
    """
    if counters is None:
        counters = {}

    comp_type = component.get("type", "")
    if comp_type in CONTENT_TYPES or comp_type in ATTRIBUTE_SLOTS:
        counters[comp_type] = counters.get(comp_type, 0) + 1
        yield component, comp_type, counters[comp_type]

    for child in component.get("components", []):
        yield from _walk_overridable(child, counters)


def enumerate_slots(template_component: dict) -> list[dict]:
    """List all override slots for a template's component tree.

    Returns a list of dicts with keys: key, type, field, value.
    Slot keys follow the pattern: {type}_{n} for content,
    {type}_{n}_{attr} for attributes (e.g. button_1_href).
    """
    slots: list[dict] = []
    for comp, comp_type, n in _walk_overridable(template_component):
        if comp_type in CONTENT_TYPES:
            slots.append({
                "key": f"{comp_type}_{n}",
                "type": comp_type,
                "field": "content",
                "value": comp.get("content", ""),
            })
        for suffix, attr_name in ATTRIBUTE_SLOTS.get(comp_type, []):
            slots.append({
                "key": f"{comp_type}_{n}_{suffix}",
                "type": comp_type,
                "field": f"attributes.{attr_name}",
                "value": comp.get("attributes", {}).get(attr_name, ""),
            })
    return slots


_TEXT_OVERRIDE_KEY = re.compile(r"^text_(\d+)$")
_IMAGE_SRC_OVERRIDE_KEY = re.compile(r"^image_(\d+)_src$")


def _max_requested_text_slot(overrides: dict[str, str]) -> int:
    indices = [
        int(match.group(1))
        for key in overrides
        if (match := _TEXT_OVERRIDE_KEY.match(key))
    ]
    return max(indices, default=0)


def _max_requested_image_slot(overrides: dict[str, str]) -> int:
    indices = [
        int(match.group(1))
        for key in overrides
        if (match := _IMAGE_SRC_OVERRIDE_KEY.match(key)) and overrides[key]
    ]
    return max(indices, default=0)


def _rewrite_component_ids(component: dict, suffix: str) -> None:
    attributes = component.get("attributes")
    if attributes and attributes.get("id"):
        attributes["id"] = f"{attributes['id']}{suffix}"
    for child in component.get("components", []):
        _rewrite_component_ids(child, suffix)


def _find_last_of_type(
    component: dict, comp_type: str, parent: dict | None = None
) -> tuple[dict, dict] | None:
    """Return (component, parent) for the last component of ``comp_type``."""
    found = (component, parent) if component.get("type") == comp_type else None
    for child in component.get("components", []):
        child_found = _find_last_of_type(child, comp_type, component)
        if child_found is not None:
            found = child_found
    return found


def expand_text_slots(template_data: dict, overrides: dict[str, str]) -> dict:
    """Clone the last text slot until every ``text_N`` override has a home.

    Crawled pages routinely carry more paragraphs than a template ships slots
    for (a blog post body vs. Rich Text Block's four). Clones land directly
    after the template's last text component — same parent, so they inherit
    its column/styling — with ``-xN`` id suffixes to keep ids unique.
    """
    requested = _max_requested_text_slot(overrides)
    if requested == 0:
        return template_data

    existing = sum(
        1 for _, comp_type, _ in _walk_overridable(template_data["template"])
        if comp_type == "text"
    )
    if existing == 0 or requested <= existing:
        return template_data

    result = copy.deepcopy(template_data)
    located = _find_last_of_type(result["template"], "text")
    if located is None or located[1] is None:
        return template_data
    last_text, parent = located

    insert_at = parent["components"].index(last_text) + 1
    for clone_number in range(requested - existing):
        clone = copy.deepcopy(last_text)
        _rewrite_component_ids(clone, f"-x{clone_number + 2}")
        parent["components"].insert(insert_at + clone_number, clone)
    return result


def expand_image_slots(template_data: dict, overrides: dict[str, str]) -> dict:
    """Make room for every ``image_N_src`` override.

    Clones the template's last image component in place when slots run out.
    Templates with no image component at all (e.g. Rich Text Block) get a
    plain responsive image appended next to their last text component —
    dropping page imagery on the floor is worse than a generic placement.
    """
    requested = _max_requested_image_slot(overrides)
    if requested == 0:
        return template_data

    existing = sum(
        1 for _, comp_type, _ in _walk_overridable(template_data["template"])
        if comp_type == "image"
    )
    if 0 < existing >= requested:
        return template_data

    result = copy.deepcopy(template_data)
    located = _find_last_of_type(result["template"], "image")
    if located is not None and located[1] is not None:
        last_image, parent = located
        insert_at = parent["components"].index(last_image) + 1
        for clone_number in range(requested - existing):
            clone = copy.deepcopy(last_image)
            _rewrite_component_ids(clone, f"-x{clone_number + 2}")
            parent["components"].insert(insert_at + clone_number, clone)
        return result

    anchor = _find_last_of_type(result["template"], "text") or _find_last_of_type(
        result["template"], "heading"
    )
    if anchor is None or anchor[1] is None:
        return template_data
    _, parent = anchor
    for slot_number in range(1, requested + 1):
        parent["components"].append({
            "type": "image",
            "tagName": "img",
            "classes": [{"name": "img-fluid", "active": False}],
            "attributes": {"id": f"tpl-auto-img{slot_number}", "src": "", "alt": ""},
        })
    return result


def apply_overrides(template_data: dict, overrides: dict[str, str]) -> dict:
    """Deep-copy a template and apply content overrides to matching slots.

    Text and image slots are expanded first so content beyond the template's
    capacity is absorbed instead of silently dropped.

    Returns the full template dict (name, category, description, template, styles)
    with the component tree modified according to the overrides.
    """
    expanded = expand_image_slots(expand_text_slots(template_data, overrides), overrides)
    result = copy.deepcopy(expanded)
    for comp, comp_type, n in _walk_overridable(result["template"]):
        content_key = f"{comp_type}_{n}"
        if content_key in overrides and comp_type in CONTENT_TYPES:
            comp["content"] = overrides[content_key]
        for suffix, attr_name in ATTRIBUTE_SLOTS.get(comp_type, []):
            attr_key = f"{comp_type}_{n}_{suffix}"
            if attr_key in overrides:
                comp.setdefault("attributes", {})[attr_name] = overrides[attr_key]
    return result


def check_overflow(template_data: dict, overrides: dict[str, str]) -> list[str]:
    """Return override keys that don't match any slot in the template.

    Useful for detecting silent data loss when a migration plan has more
    content items than a template can hold (e.g. 11 portfolio items mapped
    to a 3-up card template). Text overflow doesn't count — apply_overrides
    expands text slots to absorb it.
    """
    expanded = expand_image_slots(expand_text_slots(template_data, overrides), overrides)
    available_keys = {slot["key"] for slot in enumerate_slots(expanded["template"])}
    return sorted(key for key in overrides if key not in available_keys)
