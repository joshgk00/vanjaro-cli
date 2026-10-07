"""Project-owned global-block composition and unpublished reconciliation."""

from __future__ import annotations

import re
from typing import Any

from vanjaro_cli.design.models import DesignDocument, Section
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
from vanjaro_cli.portal.global_footer import footer_builder_content
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
            content = footer_builder_content(section, assets)
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

    figma_name = _figma_file_brand(document.source.metadata.get("figma_file_name"))
    if figma_name:
        return figma_name

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


def _figma_file_brand(value: object) -> str | None:
    """Use the design file's name as the site name once copy markers are removed."""

    if not isinstance(value, str):
        return None
    name = re.sub(r"\s*[(\[]\s*copy(?:\s+\d+)?\s*[)\]]\s*$", "", value.strip(), flags=re.IGNORECASE)
    name = re.sub(r"^copy of\s+", "", name, flags=re.IGNORECASE).strip()
    if not name or name.casefold().startswith("untitled"):
        return None
    return name


__all__ = [
    "ProjectGlobalBlockError",
    "compose_project_global_blocks",
    "preview_project_global_blocks",
    "reconcile_project_global_blocks",
]
