"""Recover source-faithful semantic ownership from static HTML subtrees."""

from __future__ import annotations

from collections.abc import Mapping
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from pydantic import JsonValue

from vanjaro_cli.design.html_primitives import (
    content_element as _element,
    layout_for_section as _layout_for_section,
    register_asset as _register_asset,
)
from vanjaro_cli.design.models import BreakpointName, Viewport


CANONICAL_VIEWPORTS: dict[BreakpointName, Viewport] = {
    BreakpointName.DESKTOP: Viewport(width=1440, height=900),
    BreakpointName.TABLET: Viewport(width=768, height=1024),
    BreakpointName.MOBILE: Viewport(width=390, height=844),
}


def enrich_section_from_static_dom(
    section: dict[str, JsonValue],
    static_html: str,
    *,
    source_url: str,
    assets: dict[str, dict[str, JsonValue]],
    provenance: dict[str, JsonValue],
) -> None:
    """Replace lossy flat arrays with source-DOM element relationships."""

    soup = BeautifulSoup(static_html, "html.parser")
    root = soup.find(True)
    if not isinstance(root, Tag):
        return
    section_id = str(section["id"])
    role = str(section["semantic_role"])
    if role == "faq":
        return
    elements: list[dict[str, JsonValue]] = []
    groups: list[dict[str, JsonValue]] = []
    counters: dict[str, int] = {}

    def add(
        kind: str,
        element_role: str,
        value: JsonValue,
        *,
        group_id: str | None = None,
        attributes: Mapping[str, JsonValue] | None = None,
        asset_id: str | None = None,
    ) -> str:
        key = re.sub(r"[^a-z0-9]+", "-", element_role.casefold()).strip("-") or kind
        counters[key] = counters.get(key, 0) + 1
        element_id = f"{section_id}.{key}.{counters[key]}"
        elements.append(
            _element(
                element_id,
                kind,
                element_role,
                len(elements),
                provenance,
                value=value,
                attributes=attributes,
                asset_id=asset_id,
                group_id=group_id,
                confidence=0.95,
            )
        )
        return element_id

    def image(tag: Tag, image_role: str, group_id: str | None = None) -> str | None:
        source = tag.get("src") or tag.get("data-src")
        if not isinstance(source, str) or not source:
            return None
        absolute = urljoin(source_url, source)
        asset_id = _register_asset(
            assets,
            source_url=absolute,
            alt_text=str(tag.get("alt") or ""),
            role="editorial",
            provenance=[provenance],
        )
        return add(
            "image",
            image_role,
            absolute,
            group_id=group_id,
            attributes={"alt": str(tag.get("alt") or "")},
            asset_id=asset_id,
        )

    if role == "navigation":
        links = root.find_all("a", href=True)
        nav = root.find("nav")
        nav_links = nav.find_all("a", href=True) if isinstance(nav, Tag) else links
        nav_ids = {id(link) for link in nav_links}
        brand = next((link for link in links if id(link) not in nav_ids), None)
        if brand is None:
            brand = next((link for link in links if "brand" in " ".join(link.get("class", [])).casefold()), None)
        if isinstance(brand, Tag):
            add("link", "brand", brand.get_text(" ", strip=True), attributes={"href": brand.get("href")})
        group_id = f"{section_id}.navigation-items"
        items: list[dict[str, JsonValue]] = []
        for link in nav_links:
            if link is brand:
                continue
            label_id = add(
                "link",
                "navigation_item",
                link.get_text(" ", strip=True),
                group_id=group_id,
                attributes={"href": link.get("href")},
            )
            items.append({"id": f"{group_id}.{len(items) + 1}", "fields": {"label": label_id}, "provenance": [provenance]})
        if items:
            groups.append({"id": group_id, "kind": "navigation_item", "items": items, "provenance": [provenance]})
        section["layout"] = _layout_for_section("navigation", "", len(items))
        section["layout"]["kind"] = "flex"  # type: ignore[index]
    else:
        repeat_kind: str | None = None
        repeat_items: list[Tag] = []
        if role == "testimonials":
            repeat_kind = "testimonial"
            repeat_items = list(root.find_all("figure", recursive=True)) or list(root.find_all("blockquote", recursive=True))
        elif role == "stats":
            repeat_kind = "stat"
            repeat_items = [tag for tag in root.find_all("li") if tag.find("strong") is not None]
        elif role == "process_steps":
            repeat_kind = "other"
            repeat_items = list(root.select(".elementor-column, [class*='step']"))
        elif role in {"feature_cards", "project_gallery"}:
            repeat_kind = "card"
            repeat_items = list(root.find_all("article")) or list(
                root.select(".card, .e-loop-item, .service-list > *")
            )
        elif role == "split_feature":
            repeat_kind = "other"
            repeat_items = list(root.find_all("li"))

        repeated_nodes = {id(node) for item in repeat_items for node in [item, *item.find_all(True)]}
        title = next(
            (heading for heading in root.find_all(["h1", "h2", "h3"]) if id(heading) not in repeated_nodes),
            None,
        )
        if isinstance(title, Tag):
            add("heading", "section_title", title.get_text(" ", strip=True), attributes={"level": int(title.name[1])})

        group_id = f"{section_id}.items"
        group_items: list[dict[str, JsonValue]] = []
        for item in repeat_items:
            fields: dict[str, JsonValue] = {}
            if role == "testimonials":
                quote = item.find("blockquote") if item.name != "blockquote" else item
                author = item.find(["cite", "figcaption"])
                if isinstance(quote, Tag):
                    quote_text = " ".join(
                        text.strip() for text in quote.stripped_strings
                        if not isinstance(author, Tag) or text.strip() != author.get_text(" ", strip=True)
                    )
                    fields["quote"] = add("quote", "testimonial_quote", quote_text, group_id=group_id)
                if isinstance(author, Tag):
                    fields["author"] = add("text", "author", author.get_text(" ", strip=True), group_id=group_id)
            elif role == "stats":
                value_tag = item.find("strong")
                label_tag = item.find("span")
                if isinstance(value_tag, Tag):
                    fields["value"] = add("stat", "stat_value", value_tag.get_text(" ", strip=True), group_id=group_id)
                if isinstance(label_tag, Tag):
                    fields["label"] = add("text", "stat_label", label_tag.get_text(" ", strip=True), group_id=group_id)
            elif role == "process_steps":
                heading = item.find(["h2", "h3", "h4"])
                number = next((tag for tag in item.find_all(["span", "strong"]) if re.fullmatch(r"\d+[.)]?", tag.get_text(" ", strip=True))), None)
                if isinstance(number, Tag):
                    fields["number"] = add("stat", "step_number", number.get_text(" ", strip=True), group_id=group_id)
                if isinstance(heading, Tag):
                    fields["title"] = add("heading", "step_title", heading.get_text(" ", strip=True), group_id=group_id)
            elif role in {"feature_cards", "project_gallery"}:
                media = item.find("img")
                heading = item.find(["h2", "h3", "h4"])
                body = item.find("p")
                if isinstance(media, Tag):
                    media_id = image(media, "card_media", group_id)
                    if media_id:
                        fields["media"] = media_id
                if isinstance(heading, Tag):
                    fields["title"] = add("heading", "card_title", heading.get_text(" ", strip=True), group_id=group_id)
                if isinstance(body, Tag):
                    field = "type" if role == "project_gallery" else "body"
                    element_role = "eyebrow" if field == "type" else "card_body"
                    fields[field] = add("text", element_role, body.get_text(" ", strip=True), group_id=group_id)
            else:
                fields["text"] = add("list_item", "benefit", item.get_text(" ", strip=True), group_id=group_id)
            if fields:
                group_items.append({"id": f"{group_id}.{len(group_items) + 1}", "fields": fields, "provenance": [provenance]})
        if repeat_kind and group_items:
            groups.append({"id": group_id, "kind": repeat_kind, "items": group_items, "provenance": [provenance]})

        for img in root.find_all("img"):
            if id(img) not in repeated_nodes:
                image_role = "hero_media" if role == "hero" else "section_media"
                image(img, image_role)
        background_match = re.search(
            r"background(?:-image)?\s*:\s*(?:[^;]*?)url\((['\"]?)([^)'\"]+)\1\)",
            str(root.get("style") or ""),
            re.IGNORECASE,
        )
        if background_match:
            source = background_match.group(2).strip()
            absolute = urljoin(source_url, source)
            asset_id = _register_asset(
                assets,
                source_url=absolute,
                role="decorative",
                provenance=[provenance],
            )
            add(
                "image",
                "background_media",
                absolute,
                attributes={"alt": "", "decorative": True},
                asset_id=asset_id,
            )
        for paragraph in root.find_all("p"):
            if id(paragraph) not in repeated_nodes:
                add("text", "body", paragraph.get_text(" ", strip=True))
        for link in root.find_all("a", href=True):
            if id(link) in repeated_nodes:
                continue
            kind = "button" if role in {"hero", "call_to_action"} or any("btn" in value.casefold() for value in link.get("class", [])) else "link"
            add(kind, "primary_action", link.get_text(" ", strip=True), attributes={"href": link.get("href")})

    if elements:
        section["content"] = elements
        section["groups"] = groups
    item_count = len(groups[0]["items"]) if groups else 0
    if role in {"feature_cards", "project_gallery", "testimonials"}:
        section["layout"] = {
            "kind": "grid",
            "contained": True,
            "columns": max(1, min(item_count or 3, 4)),
            "media_position": "top" if role in {"feature_cards", "project_gallery"} else "none",
            "alignment": "left",
            "full_bleed": False,
        }
    elif role == "stats":
        section["layout"] = {
            "kind": "stack", "contained": False, "columns": max(1, item_count),
            "media_position": "none", "alignment": "center", "full_bleed": True,
        }
    elif role == "process_steps":
        section["layout"] = {
            "kind": "stack", "contained": True, "columns": max(1, item_count),
            "media_position": "none", "alignment": "center", "full_bleed": False,
        }
    elif role == "split_feature" or (role == "hero" and root.find("img") is not None):
        section["layout"] = {
            "kind": "split", "contained": True, "columns": 2,
            "media_position": "left", "alignment": "left", "full_bleed": False,
        }
    add_inferred_static_responsive(section, root, provenance)


def add_inferred_static_responsive(
    section: dict[str, JsonValue], root: Tag, provenance: dict[str, JsonValue]
) -> None:
    """Record conservative responsive inferences from explicit structure."""

    if section.get("responsive"):
        return
    role = str(section.get("semantic_role") or "")
    groups = section.get("groups")
    item_count = 0
    if isinstance(groups, list) and groups and isinstance(groups[0], dict):
        items = groups[0].get("items")
        item_count = len(items) if isinstance(items, list) else 0
    changes: dict[BreakpointName, dict[str, JsonValue]] = {}
    if role == "navigation" and any("navbar-expand" in value for value in root.get("class", [])):
        changes[BreakpointName.MOBILE] = {"navigation": "collapsed", "direction": "vertical"}
    elif role == "process_steps" and item_count > 1:
        changes[BreakpointName.MOBILE] = {"direction": "vertical"}
    elif item_count > 1 and role in {"feature_cards", "project_gallery", "testimonials", "stats"}:
        changes[BreakpointName.MOBILE] = {"columns": 1}
        if item_count >= 3:
            changes[BreakpointName.TABLET] = {"columns": 2}
    elif role in {"hero", "split_feature"} and root.find("img") is not None:
        changes[BreakpointName.MOBILE] = {"columns": 1, "media_position": "top"}
    responsive: list[dict[str, JsonValue]] = []
    for breakpoint in (BreakpointName.TABLET, BreakpointName.MOBILE):
        if breakpoint not in changes:
            continue
        inferred_provenance = {
            **provenance,
            "method": "inferred",
            "viewport": breakpoint.value,
        }
        responsive.append({
            "breakpoint": breakpoint.value,
            "viewport": CANONICAL_VIEWPORTS[breakpoint].model_dump(mode="json"),
            "status": "inferred",
            "layout_changes": changes[breakpoint],
            "style": {"observations": [], "raw": {}},
            "hidden": None,
            "provenance": [inferred_provenance],
        })
    section["responsive"] = responsive


__all__ = [
    "CANONICAL_VIEWPORTS",
    "add_inferred_static_responsive",
    "enrich_section_from_static_dom",
]
