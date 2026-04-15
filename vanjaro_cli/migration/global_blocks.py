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

__all__ = [
    "build_header_block",
    "build_footer_block",
]


def _id() -> str:
    """Short random component id. Matches the shape GrapesJS generates."""
    return uuid.uuid4().hex[:8]


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


def _wrap(component: dict) -> dict:
    """Wrap a top-level section in the file shape ``global-blocks create`` expects."""
    return {"components": [component], "styles": []}


# --- Header ---


def build_header_block(content: dict, base_url: str = "") -> dict:
    """Build a header global-block tree from a crawled header content dict.

    Layout: one row with the first image as a logo on the left and the nav
    (preferred source: ``nav_items``, falling back to ``list_items``,
    falling back to ``links``) as a horizontal list on the right.

    Returns a dict with ``components`` (a list containing the top-level
    section) and ``styles`` (empty). Ready to feed
    ``vanjaro global-blocks create --file``.
    """
    logo = _header_logo(content)
    nav_entries = _header_nav_entries(content)

    row_cols: list[dict] = []
    if logo is not None:
        row_cols.append(_col([logo], size_classes=["col-md-3", "col-6"]))
    if nav_entries:
        nav_classes = ["d-flex", "flex-wrap", "gap-3", "justify-content-md-end"]
        nav_wrapper = _component("default", classes=nav_classes, children=nav_entries)
        nav_col_sizes = ["col-md-9", "col-6"] if logo is not None else ["col-12"]
        row_cols.append(_col([nav_wrapper], size_classes=nav_col_sizes))

    if not row_cols:
        # Empty content — produce a placeholder so the registered block
        # is still a valid GrapesJS tree and the caller can fill it in.
        row_cols = [_col([_text("(migrated header — no content captured)")], size_classes=["col-12"])]

    return _wrap(
        _section(
            extra_classes=["py-3"],
            children=[
                _container([
                    _row(row_cols, extra_classes=["align-items-center"]),
                ]),
            ],
        )
    )


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


def build_footer_block(content: dict, base_url: str = "") -> dict:
    """Build a footer global-block tree from a crawled footer content dict.

    Layout:
      - Top row: N columns built from crawled ``headings`` + ``list_items``
        (list items are split evenly across the headings). If no headings
        exist but list items do, one column holds everything.
      - Optional "about" row: the first paragraph centered as copyright/blurb.
      - Optional badges row: up to 6 images from the crawl (logos, chamber
        badges, etc.) centered in their own row.
    """
    link_columns = _footer_link_columns(content)
    about_text = _first_paragraph(content)
    badge_images = _footer_badge_images(content)

    container_children: list[dict] = []

    if link_columns:
        container_children.append(_row(link_columns))
    elif not (about_text or badge_images):
        container_children.append(
            _row([_col([_text("(migrated footer — no content captured)")], size_classes=["col-12"])])
        )

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

    return _wrap(
        _section(
            extra_classes=["py-5", "bg-light"],
            children=[_container(container_children)],
        )
    )


def _footer_link_columns(content: dict) -> list[dict]:
    """Build link columns for the footer using crawled headings + list_items.

    If the source footer has column headings, list items are split evenly
    across them. If no headings, all list items go in one column with the
    page's full width.
    """
    headings = [h for h in (content.get("headings") or []) if isinstance(h, str) and h]
    list_items = [item for item in (content.get("list_items") or []) if isinstance(item, str) and item]

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
