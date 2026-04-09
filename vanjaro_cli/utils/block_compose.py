"""Block template resolution, slot enumeration, and content override application."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Generator

__all__ = [
    "TemplateNotFoundError",
    "apply_overrides",
    "enumerate_slots",
    "find_template",
    "get_templates_dir",
]

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_TEMPLATES_DIR = _PACKAGE_ROOT / "artifacts" / "block-templates"

# Component types whose `content` field can be overridden
CONTENT_TYPES = frozenset({"heading", "text", "button", "link"})

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


def apply_overrides(template_data: dict, overrides: dict[str, str]) -> dict:
    """Deep-copy a template and apply content overrides to matching slots.

    Returns the full template dict (name, category, description, template, styles)
    with the component tree modified according to the overrides.
    """
    result = copy.deepcopy(template_data)
    for comp, comp_type, n in _walk_overridable(result["template"]):
        content_key = f"{comp_type}_{n}"
        if content_key in overrides and comp_type in CONTENT_TYPES:
            comp["content"] = overrides[content_key]
        for suffix, attr_name in ATTRIBUTE_SLOTS.get(comp_type, []):
            attr_key = f"{comp_type}_{n}_{suffix}"
            if attr_key in overrides:
                comp.setdefault("attributes", {})[attr_name] = overrides[attr_key]
    return result
