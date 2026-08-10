"""Source-neutral conversion primitives shared by HTML design adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import JsonValue

from vanjaro_cli.design.serialization import stable_design_id


GRID_SECTION_TYPES = frozenset(
    {"cards", "team", "testimonial", "gallery", "blog_cards", "pricing", "stats"}
)


def asset_kind(source: str, mime_type: str | None) -> str:
    """Classify an HTML-discovered asset from its MIME type or suffix."""

    lowered = (mime_type or "").casefold()
    suffix = Path(urlsplit(source).path).suffix.casefold()
    if "svg" in lowered or suffix == ".svg":
        return "svg"
    if lowered.startswith("video/") or suffix in {".mp4", ".webm", ".mov"}:
        return "video"
    if lowered.startswith("font/") or suffix in {".woff", ".woff2", ".ttf", ".otf"}:
        return "font"
    return "image"


def register_asset(
    assets: dict[str, dict[str, JsonValue]],
    *,
    source_url: str | None,
    local_path: str | None = None,
    mime_type: str | None = None,
    alt_text: str | None = None,
    role: str = "editorial",
    provenance: Sequence[dict[str, JsonValue]] = (),
) -> str | None:
    """Register or enrich a deterministic asset record."""

    identity = source_url or local_path
    if not identity:
        return None
    asset_id = stable_design_id("asset", identity)
    current = assets.get(asset_id)
    if current is None:
        assets[asset_id] = {
            "id": asset_id,
            "kind": asset_kind(identity, mime_type),
            "role": role,
            "source_url": source_url,
            "local_path": local_path,
            "mime_type": mime_type,
            "alt_text": alt_text,
            "provenance": list(provenance),
            "metadata": {},
        }
    elif alt_text and not current.get("alt_text"):
        current["alt_text"] = alt_text
    if current is not None and provenance:
        current_provenance = current.setdefault("provenance", [])
        for item in provenance:
            if item not in current_provenance:
                current_provenance.append(item)
    return asset_id


def layout_for_section(
    section_type: str, template: str, item_count: int
) -> dict[str, JsonValue]:
    """Translate a legacy HTML section type into a source-neutral layout."""

    if section_type in GRID_SECTION_TYPES:
        return {
            "kind": "grid",
            "contained": True,
            "columns": max(1, min(item_count or 3, 4)),
            "media_position": "top",
            "alignment": "left",
            "full_bleed": False,
        }
    if section_type in {"split", "bio"}:
        media_position = "right" if "reverse" in template.casefold() else "left"
        return {
            "kind": "split",
            "contained": True,
            "columns": 2,
            "media_position": media_position,
            "alignment": "left",
            "full_bleed": False,
        }
    return {
        "kind": "stack",
        "contained": section_type not in {"hero", "cta"},
        "columns": 1,
        "media_position": "background" if section_type in {"hero", "cta"} else None,
        "alignment": "center" if section_type in {"hero", "cta"} else "left",
        "full_bleed": section_type in {"hero", "cta"},
    }


def content_element(
    element_id: str,
    kind: str,
    role: str,
    order: int,
    provenance: dict[str, JsonValue],
    *,
    value: JsonValue = None,
    attributes: Mapping[str, JsonValue] | None = None,
    asset_id: str | None = None,
    group_id: str | None = None,
    confidence: float = 0.85,
) -> dict[str, JsonValue]:
    """Create a serialized Design Document content element."""

    return {
        "id": element_id,
        "kind": kind,
        "role": role,
        "value": value,
        "attributes": dict(attributes or {}),
        "asset_id": asset_id,
        "group_id": group_id,
        "order": order,
        "style": {},
        "provenance": [provenance],
        "confidence": confidence,
        "metadata": {},
    }


__all__ = [
    "GRID_SECTION_TYPES",
    "asset_kind",
    "content_element",
    "layout_for_section",
    "register_asset",
]
