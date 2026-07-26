"""Source-neutral separation and planning of site-global design sections."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from vanjaro_cli.design.models import DesignDocument, Page, Section


_HEADER_ROLES = frozenset({"header", "navigation", "navbar", "site_header", "site_navigation"})
_FOOTER_ROLES = frozenset({"footer", "site_footer"})


def split_global_sections(
    document: DesignDocument,
) -> tuple[DesignDocument, dict[str, Any], tuple[str, ...]]:
    """Remove global sections from body pages and plan canonical shared owners."""

    occurrences: dict[str, list[tuple[Page, Section, str]]] = {
        "header": [],
        "footer": [],
    }
    pages: list[Page] = []
    for page in document.pages:
        body_sections: list[Section] = []
        for section in page.sections:
            kind = _global_kind(section.semantic_role)
            if kind is None:
                body_sections.append(section)
                continue
            occurrences[kind].append((page, section, _section_signature(section)))
        pages.append(page.model_copy(update={"sections": body_sections}))

    entries: list[dict[str, Any]] = []
    issues: list[str] = []
    for kind in ("header", "footer"):
        found = occurrences[kind]
        if not found:
            continue
        signatures = list(dict.fromkeys(signature for _, _, signature in found))
        canonical_page, canonical_section, canonical_signature = found[0]
        entry_issues: list[str] = []
        if len(signatures) > 1:
            entry_issues.append(
                f"global {kind} has {len(signatures)} conflicting content variants; "
                "choose one canonical section before portal mutation"
            )
        issues.extend(entry_issues)
        entries.append(
            {
                "id": f"global-{kind}",
                "kind": kind,
                "strategy": "standard_vanjaro_global_block",
                "source_page_id": canonical_page.id,
                "source_section_id": canonical_section.id,
                "source_signature": canonical_signature,
                "role_confidence": canonical_section.role_confidence,
                "occurrences": [
                    {"page_id": page.id, "section_id": section.id}
                    for page, section, _ in found
                ],
                "status": "blocked" if entry_issues else "ready",
                "issues": entry_issues,
            }
        )

    return (
        document.model_copy(update={"pages": pages}),
        {
            "schema_version": "1.0",
            "strategy": "standard_vanjaro_global_blocks",
            "entries": entries,
            "section_count": sum(len(values) for values in occurrences.values()),
            "ready": not issues,
            "issues": issues,
        },
        tuple(issues),
    )


def _global_kind(role: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", role.casefold()).strip("_")
    if normalized in _HEADER_ROLES:
        return "header"
    if normalized in _FOOTER_ROLES:
        return "footer"
    return None


def _section_signature(section: Section) -> str:
    elements = {element.id: element for element in section.content}
    content = [
        {
            "kind": element.kind.value,
            "role": element.role,
            "value": element.value,
            "asset_id": element.asset_id,
            "attributes": {
                key: value
                for key, value in element.attributes.items()
                if key in {"href", "src", "alt", "url"}
            },
        }
        for element in sorted(section.content, key=lambda item: (item.order, item.id))
    ]
    groups = []
    for group in section.groups:
        items = []
        for item in group.items:
            fields: dict[str, list[dict[str, Any]]] = {}
            for field, references in item.fields.items():
                ids = references if isinstance(references, list) else [references]
                fields[field] = [
                    {
                        "kind": elements[identifier].kind.value,
                        "value": elements[identifier].value,
                        "asset_id": elements[identifier].asset_id,
                    }
                    for identifier in ids
                    if identifier in elements
                ]
            items.append(fields)
        groups.append({"kind": group.kind.value, "items": items})
    payload = json.dumps(
        {"role": section.semantic_role, "content": content, "groups": groups},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["split_global_sections"]
