"""GrapesJS component tree manipulation and rendering helpers."""

from __future__ import annotations

import copy
import uuid
from html import escape as html_escape
from typing import Any

__all__ = [
    "find_component",
    "list_components",
    "insert_component",
    "remove_component",
    "create_component",
    "render_components",
    "render_component",
]

# GrapesJS component type → HTML tag name mapping. Components with an
# explicit ``tagName`` field take precedence over this lookup.
TYPE_TO_TAG: dict[str, str] = {
    "section": "section",
    "grid": "div",
    "row": "div",
    "column": "div",
    "heading": "h2",
    "text": "div",
    "image": "img",
    "link": "a",
    "button": "a",
    "video": "video",
    "iframe": "iframe",
    "icon": "i",
    "default": "div",
    "textnode": "",
}

# HTML void elements — self-closing, cannot contain children or text.
VOID_ELEMENTS: frozenset[str] = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})

# Attribute names that are GrapesJS editor state rather than real HTML
# attributes. They must not be serialized into the output — the Vanjaro
# editor omits them and consumers would choke on the extra data.
GRAPESJS_INTERNAL_ATTRS: frozenset[str] = frozenset({
    "published",
})


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


def _active_class_names(classes: list[Any] | None) -> list[str]:
    """Return the class names from a GrapesJS ``classes`` array."""
    names: list[str] = []
    for entry in classes or []:
        if isinstance(entry, dict):
            name = entry.get("name")
            if isinstance(name, str) and name:
                names.append(name)
        elif isinstance(entry, str):
            names.append(entry)
    return names


def _serialize_attributes(attributes: dict[str, Any] | None, classes: list[str]) -> str:
    """Serialize attributes and classes into an HTML attribute string.

    Attribute ordering matches what the Vanjaro GrapesJS editor emits when
    it saves a page — ``data-*`` attributes first, then ``id``, then other
    attributes, with ``class`` last. This is load-bearing for
    ``contentHtml`` payloads: Vanjaro stores the editor-generated string
    and uses it verbatim at render time, so matching the byte shape avoids
    gratuitous diffs on round-tripping. ``GRAPESJS_INTERNAL_ATTRS`` are
    dropped entirely.
    """
    data_attrs: list[tuple[str, Any]] = []
    id_attr: tuple[str, Any] | None = None
    other_attrs: list[tuple[str, Any]] = []

    for key, value in (attributes or {}).items():
        if value is None or key in GRAPESJS_INTERNAL_ATTRS:
            continue
        if key.startswith("data-"):
            data_attrs.append((key, value))
        elif key == "id":
            id_attr = (key, value)
        else:
            other_attrs.append((key, value))

    parts: list[str] = []
    for key, value in data_attrs:
        parts.append(f'{key}="{html_escape(str(value), quote=True)}"')
    if id_attr is not None:
        parts.append(f'{id_attr[0]}="{html_escape(str(id_attr[1]), quote=True)}"')
    for key, value in other_attrs:
        parts.append(f'{key}="{html_escape(str(value), quote=True)}"')
    if classes:
        parts.append(f'class="{" ".join(classes)}"')
    return (" " + " ".join(parts)) if parts else ""


def render_component(component: dict) -> str:
    """Render a single GrapesJS component subtree to HTML.

    Walks the component's type/tagName, attributes, classes, content, and
    nested ``components`` array. ``globalblockwrapper`` components are
    rendered as empty ``<div>`` tags with their data attributes — Vanjaro
    expands them server-side at render time by looking up the
    ``data-guid``. ``textnode`` components emit their content with no
    wrapping tag.
    """
    if not isinstance(component, dict):
        return ""

    ctype = component.get("type", "default")

    if ctype == "globalblockwrapper":
        attrs = component.get("attributes", {}) or {}
        serialized = _serialize_attributes(attrs, _active_class_names(component.get("classes")))
        return f"<div{serialized}></div>"

    if ctype == "textnode":
        return html_escape(str(component.get("content", "")), quote=False)

    tag = component.get("tagName") or TYPE_TO_TAG.get(ctype, "div") or "div"
    serialized = _serialize_attributes(
        component.get("attributes"),
        _active_class_names(component.get("classes")),
    )

    if tag in VOID_ELEMENTS:
        return f"<{tag}{serialized}>"

    inner_parts: list[str] = []
    content = component.get("content", "")
    if content:
        inner_parts.append(str(content))
    for child in component.get("components", []) or []:
        inner_parts.append(render_component(child))

    return f"<{tag}{serialized}>{''.join(inner_parts)}</{tag}>"


def render_components(components: list[dict]) -> str:
    """Render a list of top-level GrapesJS components to an HTML string.

    The output matches the ``contentHtml`` field that the Vanjaro GrapesJS
    editor writes when it saves a page. ``contentHtml`` is the pre-rendered
    form that Vanjaro's server-side rendering pipeline uses to emit the
    visitor-facing HTML — without it, pushing only ``contentJSON`` via
    ``AIPage/Update`` leaves a page that's stored correctly but renders
    blank to anonymous visitors.
    """
    return "".join(render_component(c) for c in components if isinstance(c, dict))
