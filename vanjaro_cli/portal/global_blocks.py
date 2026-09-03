"""Project-owned global-block composition and unpublished reconciliation."""

from __future__ import annotations

from typing import Any

from vanjaro_cli.design.models import ContentKind, DesignDocument, Section
from vanjaro_cli.migration.global_blocks import build_footer_block
from vanjaro_cli.portal.global_block_reconciliation import (
    CREATE_BLOCK,
    GET_BLOCK,
    LIST_BLOCKS,
    ProjectGlobalBlockError,
    UPDATE_BLOCK,
    preview_project_global_blocks,
    reconcile_project_global_blocks,
)
from vanjaro_cli.portal.global_block_manifest import global_block_content_hash
from vanjaro_cli.portal.global_header_matching import compose_header_block
from vanjaro_cli.portal.pages import namespace_component_payload
from vanjaro_cli.utils.grapesjs import render_components, render_styles


def compose_project_global_blocks(
    document: DesignDocument,
    global_plan: dict[str, Any],
    *,
    project_id: str,
) -> list[dict[str, Any]]:
    sections = {
        section.id: section
        for page in document.pages
        for section in page.sections
    }
    assets = {asset.id: asset for asset in document.assets}
    desired: list[dict[str, Any]] = []
    for entry in global_plan.get("entries", []):
        if not isinstance(entry, dict) or entry.get("status") != "ready":
            raise ProjectGlobalBlockError("global block plan contains a non-ready entry")
        section_id = entry.get("source_section_id")
        section = sections.get(section_id)
        if section is None:
            raise ProjectGlobalBlockError(f"global source section is missing: {section_id}")
        kind = entry.get("kind")
        if kind == "header":
            built = compose_header_block(
                section,
                assets,
                brand_text=_project_brand_text(document, section, project_id),
            )
        elif kind == "footer":
            content = _builder_content(section, assets)
            built = build_footer_block(content)
        else:
            raise ProjectGlobalBlockError(f"unsupported global kind: {kind!r}")
        # The section's identity is the design's section ID, not the block key.
        # `data-agency-section` is how the fidelity measurer pairs a rendered
        # element with the section the design described; stamping "global-header"
        # made the nav unpairable, so it read as a section absent from the build
        # and scored zero on a page where it was rendering correctly. The block
        # key still identifies the *location* through `page_key`.
        components, styles = namespace_component_payload(
            built.get("components", []),
            built.get("styles", []),
            owner_key=str(section_id),
            project_id=project_id,
            page_key=f"global:{entry['id']}",
        )
        html = render_components(components)
        css = render_styles(styles)
        if css:
            html = f"<style>{css}</style>{html}"
        desired.append(
            {
                "key": entry["id"],
                "kind": kind,
                "source_section_id": section_id,
                "name": entry["name"],
                "category": entry["category"],
                "components": components,
                "styles": styles,
                "html": html,
                "desired_hash": global_block_content_hash(components, styles),
                "warnings": list(built.get("warnings", [])),
                "composition_path": built.get("composition_path", "composer"),
                "template_id": built.get("template_id"),
            }
        )
    return desired


def _builder_content(section: Section, assets: dict[str, Any]) -> dict[str, Any]:
    headings: list[str] = []
    list_items: list[str] = []
    paragraphs: list[str] = []
    images: list[dict[str, str]] = []
    links: list[dict[str, str]] = []
    for element in sorted(section.content, key=lambda value: (value.order, value.id)):
        text = str(element.value or "").strip()
        if element.kind == ContentKind.IMAGE and element.asset_id in assets:
            asset = assets[element.asset_id]
            src = asset.source_url or asset.local_path
            if src:
                images.append({"src": src, "alt": asset.alt_text or ""})
        elif element.kind == ContentKind.HEADING and text:
            headings.append(text)
        elif element.kind in {ContentKind.BUTTON, ContentKind.LINK} and text:
            href = str(element.attributes.get("href") or "")
            links.append({"text": text, "href": href})
            list_items.append(text)
        elif text:
            if len(text) > 100:
                paragraphs.append(text)
            else:
                list_items.append(text)
    return {
        "headings": headings,
        "list_items": list_items,
        "paragraphs": paragraphs,
        "images": images,
        "links": links,
    }


def _project_brand_text(
    document: DesignDocument,
    section: Section,
    project_id: str,
) -> str:
    """Select accessible brand copy from explicit source metadata or identity."""

    keys = ("brand_name", "site_name", "portal_name", "title", "name")
    metadata_sources: list[dict[str, object]] = [section.metadata]
    containing_page = None
    for page in document.pages:
        if any(candidate.id == section.id for candidate in page.sections):
            containing_page = page
            metadata_sources.append(page.metadata)
            break
    metadata_sources.append(document.source.metadata)
    for metadata in metadata_sources:
        for key in keys:
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    # Project IDs are site-owned stable identities.  Remove orchestration-only
    # suffixes before presenting one to visitors.
    words = [word for word in project_id.replace("_", "-").split("-") if word]
    while words and words[-1].casefold() in {"project", "agency", "site"}:
        words.pop()
    if words:
        return " ".join(word.capitalize() for word in words)
    if containing_page is not None and containing_page.title.strip():
        return containing_page.title.strip()
    return "Site"


__all__ = [
    "ProjectGlobalBlockError",
    "compose_project_global_blocks",
    "preview_project_global_blocks",
    "reconcile_project_global_blocks",
]
