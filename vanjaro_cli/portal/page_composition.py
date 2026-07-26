"""Deterministic composition helpers for project page drafts."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from vanjaro_cli.design.models import DesignDocument
from vanjaro_cli.migration.url_rewrite import build_variant_lookup, rewrite_tree
from vanjaro_cli.utils.grapesjs import render_components, render_styles


GLOBAL_BLOCK_WRAPPER_TYPE_GUID = "7a4be0f2-56ab-410a-9422-6bc91b488150"


class ProjectPageError(ValueError):
    """Raised when a project page cannot be assembled or reconciled safely."""


def compose_project_pages(
    document: DesignDocument,
    composed_blocks: list[object],
    global_plan: dict[str, Any],
    *,
    project_id: str,
    isolated: bool,
    asset_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Assemble every body section into deterministic page draft payloads."""

    blocks: dict[str, dict[str, Any]] = {}
    for raw in composed_blocks:
        if not isinstance(raw, dict) or not isinstance(raw.get("key"), str):
            raise ProjectPageError("composed block catalog requires stable string keys")
        if raw["key"] in blocks:
            raise ProjectPageError(f"duplicate composed block key: {raw['key']}")
        blocks[raw["key"]] = raw
    global_ids = {
        entry.get("source_section_id")
        for entry in global_plan.get("entries", [])
        if isinstance(entry, dict)
    }
    body_ids = {
        section.id
        for page in document.pages
        for section in page.sections
        if section.id not in global_ids
    }
    missing = sorted(body_ids - set(blocks))
    extra = sorted(set(blocks) - body_ids)
    if missing or extra:
        raise ProjectPageError(
            f"section-to-block coverage mismatch; missing={missing}, extra={extra}"
        )

    ordered_pages = _parent_first(document)
    desired: list[dict[str, Any]] = []
    variant_lookup = build_variant_lookup(asset_records or [])
    names: set[str] = set()
    for page in ordered_pages:
        components: list[dict[str, Any]] = []
        styles: list[dict[str, Any]] = []
        for section in sorted(page.sections, key=lambda item: (item.order, item.id)):
            if section.id in global_ids:
                continue
            block = blocks[section.id]
            block_components = copy.deepcopy(block.get("content_json", []))
            block_styles = copy.deepcopy(block.get("style_json", []))
            if not isinstance(block_components, list) or not isinstance(block_styles, list):
                raise ProjectPageError(f"invalid composed payload for {section.id}")
            if variant_lookup:
                rewrite_tree(
                    {"components": block_components, "styles": block_styles},
                    {},
                    {},
                    variant_lookup,
                )
            namespaced, renamed = _namespace_components(
                block_components,
                section_key=section.id,
                project_id=project_id,
                page_key=page.id,
            )
            components.extend(namespaced)
            styles.extend(_namespace_styles(block_styles, renamed))
        components = _group_top_level(components, page_key=page.id)
        css = render_styles(styles)
        content_html = render_components(components)
        if css:
            content_html = f"<style>{css}</style>{content_html}"
        base_slug = page.slug.strip("/") or page_slug(page.title)
        name = f"{project_id}-{base_slug}" if isolated else base_slug
        title = f"[Agency Draft] {page.title}" if isolated else page.title
        if name.casefold() in names:
            raise ProjectPageError(f"duplicate generated page name: {name}")
        names.add(name.casefold())
        content_hash = page_content_hash(components, styles, content_html)
        desired.append(
            {
                "key": page.id,
                "source_reference": page.source_reference,
                "name": name,
                "title": title,
                "description": page.seo.description if page.seo else "",
                "keywords": "",
                "parent_key": page.parent_page_id,
                "is_visible": False if isolated else page.navigation_visibility.value == "visible",
                "components": components,
                "styles": styles,
                "content_html": content_html,
                "content_hash": content_hash,
                "isolated": isolated,
            }
        )
    return desired


def namespace_component_payload(
    components: list[dict[str, Any]],
    styles: list[dict[str, Any]],
    *,
    owner_key: str,
    project_id: str,
    page_key: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Give a component/style payload deterministic IDs and ownership markers."""

    namespaced, renamed = _namespace_components(
        copy.deepcopy(components),
        section_key=owner_key,
        project_id=project_id,
        page_key=page_key,
    )
    return namespaced, _namespace_styles(copy.deepcopy(styles), renamed)


def attach_global_wrappers(
    desired_pages: list[dict[str, Any]],
    global_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach deterministic header/footer references to complete page drafts."""

    by_kind = {record.get("kind"): record for record in global_records}
    if set(by_kind) != {"header", "footer"}:
        raise ProjectPageError("page chrome requires exactly one header and one footer")
    output = copy.deepcopy(desired_pages)
    for page in output:
        wrappers = {
            kind: _global_wrapper(page["key"], kind, by_kind[kind])
            for kind in ("header", "footer")
        }
        page["components"] = [
            wrappers["header"],
            *page["components"],
            wrappers["footer"],
        ]
        css = render_styles(page["styles"])
        html = render_components(page["components"])
        if css:
            html = f"<style>{css}</style>{html}"
        page["content_html"] = html
        page["content_hash"] = page_content_hash(
            page["components"], page["styles"], html
        )
    return output


def page_content_hash(components: object, styles: object, html: object) -> str:
    """Return the stable hash used to compare desired and portal page content."""

    value = {"components": components, "styles": styles, "content_html": html}
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def page_slug(value: str) -> str:
    """Return a stable filesystem/page-safe slug."""

    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "page"


def _parent_first(document: DesignDocument) -> list[Any]:
    pages = {page.id: page for page in document.pages}
    ordered: list[Any] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise ProjectPageError(f"page hierarchy cycle detected at {key}")
        if key in visited:
            return
        visiting.add(key)
        parent = pages[key].parent_page_id
        if parent:
            if parent not in pages:
                raise ProjectPageError(f"page {key} has missing parent {parent}")
            visit(parent)
        visiting.remove(key)
        visited.add(key)
        ordered.append(pages[key])

    for key in pages:
        visit(key)
    return ordered


def _namespace_components(
    components: list[dict[str, Any]],
    *,
    section_key: str,
    project_id: str,
    page_key: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    prefix = "ag-" + hashlib.sha256(section_key.encode("utf-8")).hexdigest()[:10]
    renamed: dict[str, str] = {}
    sequence = 0

    def visit(component: dict[str, Any]) -> None:
        nonlocal sequence
        attributes = component.setdefault("attributes", {})
        old = attributes.get("id")
        sequence += 1
        new = f"{prefix}-{sequence}"
        if isinstance(old, str) and old:
            if old in renamed:
                raise ProjectPageError(f"duplicate component ID {old!r} in {section_key}")
            renamed[old] = new
        attributes["id"] = new
        attributes.setdefault("data-agency-project", project_id)
        attributes.setdefault("data-agency-page", page_key)
        attributes.setdefault("data-agency-section", section_key)
        for child in component.get("components", []):
            if isinstance(child, dict):
                visit(child)

    for component in components:
        if not isinstance(component, dict):
            raise ProjectPageError(f"section {section_key} contains a non-object component")
        visit(component)
    _rewrite_component_id_references(components, renamed)
    return components, renamed


def _rewrite_component_id_references(
    components: list[dict[str, Any]],
    renamed: dict[str, str],
) -> None:
    """Keep Bootstrap/ARIA local-ID relationships valid after namespacing."""

    plain_attributes = {
        "for",
        "aria-activedescendant",
        "aria-controls",
        "aria-details",
    }
    token_attributes = {"aria-describedby", "aria-labelledby", "aria-owns"}
    selector_attributes = {
        "data-bs-parent",
        "data-bs-target",
        "data-parent",
        "data-target",
        "href",
    }

    def rewrite(component: dict[str, Any]) -> None:
        attributes = component.get("attributes", {})
        if isinstance(attributes, dict):
            for key in plain_attributes:
                value = attributes.get(key)
                if isinstance(value, str) and value in renamed:
                    attributes[key] = renamed[value]
            for key in token_attributes:
                value = attributes.get(key)
                if isinstance(value, str):
                    attributes[key] = " ".join(
                        renamed.get(token, token) for token in value.split()
                    )
            for key in selector_attributes:
                value = attributes.get(key)
                if isinstance(value, str) and value.startswith("#"):
                    target = value[1:]
                    if target in renamed:
                        attributes[key] = f"#{renamed[target]}"
        for child in component.get("components", []):
            if isinstance(child, dict):
                rewrite(child)

    for component in components:
        rewrite(component)


def _namespace_styles(
    styles: list[dict[str, Any]], renamed: dict[str, str]
) -> list[dict[str, Any]]:
    for rule in styles:
        if not isinstance(rule, dict):
            continue
        selectors = rule.get("selectors", [])
        for index, selector in enumerate(selectors):
            if isinstance(selector, dict) and selector.get("type") == 2:
                name = selector.get("name")
                if name in renamed:
                    selector["name"] = renamed[name]
            elif isinstance(selector, str) and selector.startswith("#"):
                selectors[index] = "#" + renamed.get(selector[1:], selector[1:])
    return styles


def _group_top_level(
    components: list[dict[str, Any]], *, page_key: str
) -> list[dict[str, Any]]:
    if len(components) <= 9:
        return components
    group_count = min(3, len(components))
    base, remainder = divmod(len(components), group_count)
    result: list[dict[str, Any]] = []
    start = 0
    digest = hashlib.sha256(page_key.encode("utf-8")).hexdigest()[:10]
    for index in range(group_count):
        size = base + (1 if index < remainder else 0)
        result.append(
            {
                "type": "default",
                "attributes": {"id": f"ag-{digest}-group-{index + 1}"},
                "classes": [{"name": "vj-section-group", "active": False}],
                "components": components[start:start + size],
            }
        )
        start += size
    return result


def _global_wrapper(
    page_key: str, kind: str, record: dict[str, Any]
) -> dict[str, Any]:
    guid = record.get("guid")
    if not isinstance(guid, str) or not guid:
        raise ProjectPageError(f"{kind} global block has no GUID")
    digest = hashlib.sha256(f"{page_key}:{kind}".encode("utf-8")).hexdigest()[:10]
    return {
        "type": "globalblockwrapper",
        "name": f"Global: {kind.title()}",
        "content": "",
        "attributes": {
            "data-block-type": "global",
            "data-block-guid": GLOBAL_BLOCK_WRAPPER_TYPE_GUID,
            "data-guid": guid,
            "id": f"ag-global-{digest}",
        },
        "components": [],
    }


__all__ = [
    "ProjectPageError",
    "attach_global_wrappers",
    "compose_project_pages",
    "namespace_component_payload",
    "page_content_hash",
    "page_slug",
]
