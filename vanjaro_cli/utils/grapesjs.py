"""GrapesJS component tree manipulation helpers."""

from __future__ import annotations

import copy
import uuid
from typing import Any

__all__ = [
    "find_component",
    "list_components",
    "insert_component",
    "remove_component",
    "create_component",
]


def find_component(components: list[dict], component_id: str) -> dict | None:
    """Recursively find a component by its ID (attributes.id) in the tree."""
    for component in components:
        if component.get("attributes", {}).get("id") == component_id:
            return component
        children = component.get("components", [])
        found = find_component(children, component_id)
        if found is not None:
            return found
    return None


def list_components(components: list[dict], depth: int = 0) -> list[dict]:
    """Flatten the component tree into a list of summaries for display."""
    result: list[dict] = []
    for component in components:
        children = component.get("components", [])
        content_raw = component.get("content", "")
        content_preview = content_raw.strip()[:60] if content_raw else ""

        result.append({
            "id": component.get("attributes", {}).get("id", ""),
            "type": component.get("type", ""),
            "depth": depth,
            "name": component.get("name") or component.get("custom-name") or "",
            "content_preview": content_preview,
            "child_count": len(children),
        })

        result.extend(list_components(children, depth + 1))
    return result


def insert_component(
    components: list[dict],
    component: dict,
    parent_id: str | None = None,
    position: int = -1,
) -> list[dict]:
    """Insert a component into the tree without mutating the input."""
    tree = copy.deepcopy(components)

    if parent_id is None:
        if position == -1:
            tree.append(component)
        else:
            tree.insert(position, component)
        return tree

    parent = find_component(tree, parent_id)
    if parent is None:
        raise ValueError(f"Parent component '{parent_id}' not found")

    if "components" not in parent:
        parent["components"] = []

    if position == -1:
        parent["components"].append(component)
    else:
        parent["components"].insert(position, component)

    return tree


def remove_component(components: list[dict], component_id: str) -> list[dict]:
    """Remove a component from the tree by ID without mutating the input."""
    tree = copy.deepcopy(components)

    if not _remove_from_list(tree, component_id):
        raise ValueError(f"Component '{component_id}' not found")

    return tree


def _remove_from_list(components: list[dict], component_id: str) -> bool:
    """Remove a component in-place from a list, returning True if found."""
    for i, component in enumerate(components):
        if component.get("attributes", {}).get("id") == component_id:
            components.pop(i)
            return True
        children = component.get("components", [])
        if _remove_from_list(children, component_id):
            return True
    return False


def create_component(
    component_type: str,
    content: str = "",
    classes: list[str] | None = None,
    attributes: dict | None = None,
    children: list[dict] | None = None,
) -> dict:
    """Create a GrapesJS component dict with auto-generated ID if needed."""
    attrs = dict(attributes) if attributes else {}
    if "id" not in attrs:
        attrs["id"] = uuid.uuid4().hex[:5]

    result: dict[str, Any] = {
        "type": component_type,
        "attributes": attrs,
    }

    if content:
        result["content"] = content

    if classes:
        result["classes"] = [{"name": name, "active": False} for name in classes]

    if children:
        result["components"] = children

    return result
