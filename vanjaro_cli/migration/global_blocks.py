"""Build GrapesJS global-block trees directly from crawled header/footer content.

Every source site has a different header and footer design, so pre-baked
block templates never quite fit. These builders take the section-shaped
content dict the crawler writes to ``global/header.json`` and
``global/footer.json`` and produce a GrapesJS component tree wrapped in
the shape ``vanjaro global-blocks create --file`` accepts
(``{components, styles}``).

The builders are opinionated about structure — header is a one-row
logo+nav layout, footer is N columns of links plus an optional
about/copyright row and an optional badges row — but the content comes
entirely from the crawl. Callers can hand-edit the output JSON before
registering if they want a different layout, or iterate on the builder
itself when a new source site exposes a pattern worth supporting.
"""

from __future__ import annotations

import uuid
from typing import Any

from vanjaro_cli.utils.block_compose import apply_section_background

__all__ = [
    "build_header_block",
    "build_footer_block",
    "make_global_block_wrapper",
    "GLOBAL_BLOCK_WRAPPER_TYPE_GUID",
    "MENU_BLOCK_GUID",
]

MENU_BLOCK_GUID = "3007ca5e-0c09-4824-ae81-0044f993c8f5"

# The globalblockwrapper component type is registered in Vanjaro's core GrapesJS
# schema. Its ``data-block-guid`` is a fixed identifier for the wrapper TYPE
# itself — the ``data-guid`` attribute points at the specific global block
# instance the wrapper references.
GLOBAL_BLOCK_WRAPPER_TYPE_GUID = "7a4be0f2-56ab-410a-9422-6bc91b488150"


def make_global_block_wrapper(name: str, block_guid: str) -> dict:
    """Build a ``globalblockwrapper`` component referencing a global block.

    Vanjaro renders these as empty divs at save time and expands them
    server-side by looking up the ``data-guid``, so the wrapper's nested
    ``components`` array is intentionally empty. ``block_guid`` may be a real
    GUID or a ``{{global:KEY}}`` placeholder the assemble step resolves later.
    """
    return {
        "type": "globalblockwrapper",
        "name": name,
        "content": "",
        "attributes": {
            "data-block-type": "global",
            "data-block-guid": GLOBAL_BLOCK_WRAPPER_TYPE_GUID,
            "data-guid": block_guid,
            "id": uuid.uuid4().hex[:5],
        },
        "components": [],
    }


def _id() -> str:
    """Short random component id. Matches the shape GrapesJS generates."""
    return uuid.uuid4().hex[:8]


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    """Drop exact-duplicate strings, keeping the first occurrence's position."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _dedupe_links_preserve_order(links: list[dict]) -> list[dict]:
    """Drop links with a duplicate (text, href) pair, keeping first occurrence."""
    seen: set[tuple[str, str]] = set()
    result: list[dict] = []
    for link in links:
        key = (link.get("text", ""), link.get("href", ""))
        if key not in seen:
            seen.add(key)
            result.append(link)
    return result


def _component(
    type: str,
    *,
    classes: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
    content: str | None = None,
    children: list[dict] | None = None,
    tag_name: str | None = None,
) -> dict:
    """Build a single GrapesJS component dict.

    Keeps the call sites compact. ``classes`` is a flat list of CSS class
    names — the helper wraps them in ``{name, active: false}`` to match
    the GrapesJS serialization convention that block templates already use.
    """
    comp: dict[str, Any] = {
        "type": type,
        "attributes": {"id": _id(), **(attributes or {})},
    }
    if classes:
        comp["classes"] = [{"name": name, "active": False} for name in classes]
    if tag_name:
        comp["tagName"] = tag_name
    if content is not None:
        comp["content"] = content
    if children:
        comp["components"] = children
    return comp


def _section(children: list[dict], extra_classes: list[str] | None = None) -> dict:
    classes = ["vj-section"] + (extra_classes or [])
    return _component("section", classes=classes, children=children)


def _container(children: list[dict]) -> dict:
    return _component("grid", classes=["container"], children=children)


def _row(children: list[dict], extra_classes: list[str] | None = None) -> dict:
    classes = ["row"] + (extra_classes or [])
    return _component("row", classes=classes, children=children)


def _col(children: list[dict], size_classes: list[str]) -> dict:
    return _component("column", classes=size_classes, children=children)


def _image(src: str, alt: str, extra_classes: list[str] | None = None) -> dict:
    classes = ["vj-image", "img-fluid"] + (extra_classes or [])
    return _component("image", classes=classes, attributes={"src": src, "alt": alt})


def _heading(text: str, tag: str = "h4", extra_classes: list[str] | None = None) -> dict:
    classes = ["vj-heading"] + (extra_classes or [])
    return _component("heading", tag_name=tag, content=text, classes=classes)


def _text(text: str, extra_classes: list[str] | None = None) -> dict:
    classes = ["vj-text"] + (extra_classes or [])
    return _component("text", content=text, classes=classes)


def _list_item(text: str) -> dict:
    return _component("list-item", content=text)


def _wrap(component: dict, styles: list | None = None) -> dict:
    """Wrap a top-level section in the file shape ``global-blocks create`` expects."""
    return {"components": [component], "styles": styles or []}


# --- Header ---


def _menu_block() -> dict:
    """Return the Vanjaro native Menu blockwrapper component.

    This renders the live DNN page tree server-side via Block/RenderItem into
    a Bootstrap navbar, so it stays current as pages are added or renamed.
    The GUID is stable across Vanjaro installs.
    """
    return {
        "type": "blockwrapper",
        "name": "Menu",
        "content": "",
        "classes": [
            {"name": "align-ib", "active": False},
            {"name": "menu-style-1", "active": False},
        ],
        "attributes": {
            "data-block-global": "true",
            "data-block-type": "Menu",
            "data-block-alignment": "true",
            "data-block-styles": "true",
            "data-block-resizable": "false",
            "data-block-guid": MENU_BLOCK_GUID,
            "data-block-template": "Default",
            "data-block-nodeselector": "*",
            "data-block-includehidden": "false",
            "data-block-allow-customization": "true",
            "data-block-category": "Design",
            "id": _id(),
            "alignment": "right",
        },
        "custom-name": "Menu",
        "alignment": "none",
    }


def build_header_block(
    content: dict,
    base_url: str = "",
    static_nav: bool = False,
    palette: dict[str, tuple[int, int, int]] | None = None,
) -> dict:
    """Build a header global-block tree from a crawled header content dict.

    By default the nav column uses Vanjaro's native Menu blockwrapper, which
    renders the live DNN page tree server-side and stays current as pages are
    added or renamed. Pass ``static_nav=True`` to instead embed a static list
    built from the crawled nav entries (legacy behaviour).

    Layout: one row with the first image as a logo on the left and the nav on
    the right. Returns a dict with ``components`` and ``styles`` ready to feed
    ``vanjaro global-blocks create --file``. With a ``palette``, band colors
    become theme classes (and any per-id rules land in ``styles``).
    """
    logo = _header_logo(content)
    business_name = _header_business_name(content)
    phone_button = _header_phone_button(content)

    logo_children: list[dict] = []
    if logo is not None:
        logo_children.append(logo)
    if business_name:
        logo_children.append(_heading(business_name, tag="h5", extra_classes=["head-style-5", "mb-0", "mt-2"]))

    row_cols: list[dict] = []
    if logo_children:
        row_cols.append(_col(logo_children, size_classes=["col-md-3", "col-6"]))

    nav_children: list[dict] = []
    if static_nav:
        nav_entries = _header_nav_entries(content)
        if nav_entries:
            nav_classes = ["d-flex", "flex-wrap", "gap-3", "justify-content-md-end"]
            nav_children.append(_component("default", classes=nav_classes, children=nav_entries))
    else:
        nav_children.append(_menu_block())
    if phone_button is not None:
        nav_children.append(phone_button)

    if nav_children:
        nav_col_sizes = ["col-md-9", "col-6"] if logo_children else ["col-12"]
        nav_wrapper_classes = ["d-flex", "flex-wrap", "align-items-center", "gap-3", "justify-content-md-end"]
        row_cols.append(_col([_component("default", classes=nav_wrapper_classes, children=nav_children)], size_classes=nav_col_sizes))

    if not row_cols:
        # Empty content — produce a placeholder so the registered block
        # is still a valid GrapesJS tree and the caller can fill it in.
        row_cols = [_col([_text("(migrated header — no content captured)")], size_classes=["col-12"])]

    section = _section(
        extra_classes=["py-3"],
        children=[
            _container([
                _row(row_cols, extra_classes=["align-items-center"]),
            ]),
        ],
    )
    styles: list = []
    apply_section_background(section, content, palette=palette, styles=styles)
    return _wrap(section, styles)


def _header_logo(content: dict) -> dict | None:
    """Return the first usable image from the crawled header content, or None."""
    for image in content.get("images") or []:
        if not isinstance(image, dict):
            continue
        src = image.get("src")
        if isinstance(src, str) and src:
            alt = image.get("alt") if isinstance(image.get("alt"), str) else "Logo"
            return _image(src, alt, extra_classes=["header-logo"])
    return None


def _header_business_name(content: dict) -> str | None:
    """Return the first non-empty paragraph as the business name label, if any."""
    for paragraph in content.get("paragraphs") or []:
        if isinstance(paragraph, str) and paragraph.strip():
            return paragraph.strip()
    return None


def _header_phone_button(content: dict) -> dict | None:
    """Return a CTA button component for the first tel: link in the crawled content."""
    for link in content.get("links") or []:
        if not isinstance(link, dict):
            continue
        href = link.get("href")
        text = link.get("text")
        if isinstance(href, str) and href.startswith("tel:") and isinstance(text, str) and text:
            return _component(
                "link",
                tag_name="a",
                content=text,
                classes=["btn", "btn-primary", "button-style-1", "header-phone-btn"],
                attributes={"href": href},
            )
    return None


def _header_nav_entries(content: dict) -> list[dict]:
    """Return list-item components for each nav entry in the crawled content.

    Preference order: nested ``nav_items`` (post-Phase-E), flat
    ``list_items``, then flat ``links``. First non-empty source wins.
    """
    nav_items = content.get("nav_items") or []
    if isinstance(nav_items, list) and nav_items:
        return [_list_item(item["label"]) for item in nav_items if _has_label(item)]

    list_items = content.get("list_items") or []
    if isinstance(list_items, list) and list_items:
        return [_list_item(text) for text in list_items if isinstance(text, str) and text]

    links = content.get("links") or []
    if isinstance(links, list):
        return [_list_item(link["text"]) for link in links if _has_text(link)]

    return []


def _has_label(item: Any) -> bool:
    return isinstance(item, dict) and isinstance(item.get("label"), str) and bool(item["label"])


def _has_text(item: Any) -> bool:
    return isinstance(item, dict) and isinstance(item.get("text"), str) and bool(item["text"])


# --- Footer ---


def build_footer_block(
    content: dict,
    base_url: str = "",
    palette: dict[str, tuple[int, int, int]] | None = None,
) -> dict:
    """Build a footer global-block tree from a crawled footer content dict.

    Layout:
      - Top row: N columns built from crawled ``headings`` + ``list_items``
        (list items are split evenly across the headings). If no headings
        exist but list items do, one column holds everything.
      - Optional "about" row: the first paragraph centered as copyright/blurb.
      - Optional badges row: up to 6 images from the crawl (logos, chamber
        badges, etc.) centered in their own row.

    With a ``palette``, band colors become theme classes (and any per-id rules
    land in ``styles``).
    """
    link_columns = _footer_link_columns(content)
    about_text = _first_paragraph(content)
    badge_images = _footer_badge_images(content)

    container_children: list[dict] = []

    if link_columns:
        container_children.append(_row(link_columns))

    if about_text:
        container_children.append(
            _row(
                [_col([_text(about_text)], size_classes=["col-12"])],
                extra_classes=["mt-4", "text-center"],
            )
        )

    if badge_images:
        image_cols = [
            _col([img], size_classes=["col-md-2", "col-4"])
            for img in badge_images
        ]
        container_children.append(
            _row(image_cols, extra_classes=["mt-4", "justify-content-center", "align-items-center"])
        )

    social_row = _footer_social_row(content)
    if social_row is not None:
        container_children.append(social_row)

    copyright_row = _footer_copyright_row(content)
    if copyright_row is not None:
        container_children.append(copyright_row)

    # Only when nothing at all was captured — links, about, badges, social,
    # or copyright — does the placeholder stand in for an empty block.
    if not container_children:
        container_children.append(
            _row([_col([_text("(migrated footer — no content captured)")], size_classes=["col-12"])])
        )

    # Bootstrap's bg-light carries !important and would beat the inline band
    # style, so the fallback class only ships when no band color was crawled.
    has_band = bool(content.get("background_color") or content.get("background_image"))
    section = _section(
        extra_classes=["py-5"] if has_band else ["py-5", "bg-light"],
        children=[_container(container_children)],
    )
    styles: list = []
    apply_section_background(section, content, palette=palette, styles=styles)
    return _wrap(section, styles)


def _footer_social_row(content: dict) -> dict | None:
    """One centered row of social profile links (icon-only anchors get labels)."""
    social_links = content.get("social_links") or []
    links = [
        _component(
            "link",
            tag_name="a",
            content=item["label"],
            classes=["mx-2"],
            attributes={"href": item["href"], "target": "_blank"},
        )
        for item in social_links
        if isinstance(item, dict) and item.get("label") and item.get("href")
    ]
    if not links:
        return None
    return _row(
        [_col(links, size_classes=["col-12"])],
        extra_classes=["mt-4", "text-center"],
    )


def _footer_copyright_row(content: dict) -> dict | None:
    """Bottom bar: copyright line plus any Privacy/Terms links from the crawl."""
    copyright_text = content.get("copyright_text")
    legal_links = _dedupe_links_preserve_order([
        link for link in (content.get("links") or [])
        if isinstance(link, dict)
        and isinstance(link.get("text"), str)
        and link["text"].strip().lower() in ("privacy statement", "privacy policy", "terms of use", "terms of service")
    ])
    if not copyright_text and not legal_links:
        return None

    parts: list[dict] = []
    if copyright_text:
        parts.append(_text(copyright_text, extra_classes=["d-inline", "me-3"]))
    for link in legal_links:
        parts.append(
            _component(
                "link",
                tag_name="a",
                content=link["text"],
                classes=["mx-2"],
                attributes={"href": link["href"]},
            )
        )
    return _row(
        [_col(parts, size_classes=["col-12"])],
        extra_classes=["mt-4", "pt-3", "border-top", "text-center"],
    )


def _footer_link_columns(content: dict) -> list[dict]:
    """Build link columns for the footer using crawled headings + list_items.

    If the source footer has column headings, list items are split evenly
    across them. If no headings, all list items go in one column with the
    page's full width.
    """
    headings = _dedupe_preserve_order([h for h in (content.get("headings") or []) if isinstance(h, str) and h])
    list_items = _dedupe_preserve_order([item for item in (content.get("list_items") or []) if isinstance(item, str) and item])

    if not headings and not list_items:
        return []

    if not headings:
        column_children = [_list_item(text) for text in list_items]
        return [_col(column_children, size_classes=["col-12"])]

    columns: list[dict] = []
    n_headings = len(headings)
    items_per_col = max(1, len(list_items) // n_headings) if list_items else 0

    for index, heading in enumerate(headings):
        column_children: list[dict] = [_heading(heading, tag="h5", extra_classes=["mb-3"])]
        if list_items:
            start = index * items_per_col
            end = start + items_per_col if index < n_headings - 1 else len(list_items)
            for item in list_items[start:end]:
                column_children.append(_list_item(item))

        # Bootstrap column size: even split up to 4, otherwise col-md-3
        col_size = f"col-md-{max(3, 12 // n_headings)}"
        columns.append(_col(column_children, size_classes=[col_size]))

    return columns


def _first_paragraph(content: dict) -> str | None:
    """Return the first non-empty paragraph string for the copyright/about row."""
    for paragraph in content.get("paragraphs") or []:
        if isinstance(paragraph, str) and paragraph.strip():
            return paragraph
    return None


def _footer_badge_images(content: dict) -> list[dict]:
    """Return up to 6 image components for the footer badges row."""
    badges: list[dict] = []
    for image in content.get("images") or []:
        if not isinstance(image, dict):
            continue
        src = image.get("src")
        if not isinstance(src, str) or not src:
            continue
        alt = image.get("alt") if isinstance(image.get("alt"), str) else ""
        badges.append(_image(src, alt, extra_classes=["footer-badge"]))
        if len(badges) >= 6:
            break
    return badges
