"""Walk a GrapesJS component tree and collect text, images, and link targets.

Mirror of :mod:`vanjaro_cli.migration.sections` on the opposite side of the
migration: where ``sections.py`` extracts content from the source HTML, this
extracts the same shape of content from the migrated GrapesJS JSON so Phase 5
verify can compare the two sides.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["WalkedContent", "walk_grapesjs_tree"]


_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


@dataclass
class WalkedContent:
    """Flat snapshot of everything a GrapesJS tree contains."""

    headings: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    link_labels: list[str] = field(default_factory=list)
    section_count: int = 0


def walk_grapesjs_tree(components: list[dict]) -> WalkedContent:
    """Recurse through a list of GrapesJS components and collect content.

    ``section_count`` counts only top-level section components — nested
    sections inside a ``cards`` layout do not inflate the count so that the
    structural comparison against the source matches like-for-like.
    """
    walked = WalkedContent()
    if not isinstance(components, list):
        return walked

    for component in components:
        if isinstance(component, dict) and component.get("type") == "section":
            walked.section_count += 1
        _walk(component, walked)
    return walked


def _walk(node: object, walked: WalkedContent) -> None:
    if not isinstance(node, dict):
        return

    node_type = node.get("type")
    tag_name = node.get("tagName")

    if _is_heading(node_type, tag_name):
        text = _extract_text(node)
        if text:
            walked.headings.append(text)
    elif _is_paragraph(node_type, tag_name):
        text = _extract_text(node)
        if text:
            walked.paragraphs.append(text)

    if node_type == "image":
        src = _attr(node, "src")
        if src:
            walked.images.append(src)

    if _is_link(node_type, tag_name):
        href = _attr(node, "href")
        if href and not href.startswith("#") and _is_http_or_relative(href):
            walked.links.append(href)
        label = _extract_text(node)
        if label:
            walked.link_labels.append(label)

    children = node.get("components")
    if isinstance(children, list):
        for child in children:
            _walk(child, walked)


def _is_heading(node_type: object, tag_name: object) -> bool:
    if node_type == "heading":
        return True
    return isinstance(tag_name, str) and tag_name in _HEADING_TAGS


def _is_paragraph(node_type: object, tag_name: object) -> bool:
    if node_type == "text":
        return True
    return tag_name == "p"


def _is_link(node_type: object, tag_name: object) -> bool:
    if node_type in ("link", "button"):
        return True
    return tag_name == "a"


def _extract_text(node: dict) -> str:
    content = node.get("content")
    if isinstance(content, str):
        return content.strip()
    return ""


def _attr(node: dict, name: str) -> str:
    attributes = node.get("attributes")
    if isinstance(attributes, dict):
        value = attributes.get(name)
        if isinstance(value, str):
            return value
    return ""


def _is_http_or_relative(href: str) -> bool:
    """Drop ``mailto:``, ``tel:``, ``javascript:`` and other non-navigable schemes."""
    colon_index = href.find(":")
    if colon_index == -1:
        return True
    scheme = href[:colon_index].lower()
    return scheme in ("http", "https")
