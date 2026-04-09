"""Tests for the GrapesJS content walker used by Phase 5 verify."""

from __future__ import annotations

from vanjaro_cli.migration.content_walk import WalkedContent, walk_grapesjs_tree


# -- Helpers --


def _heading(text: str, tag: str = "h2", use_type: bool = True) -> dict:
    node: dict = {"content": text, "attributes": {"id": f"h-{text[:5]}"}}
    if use_type:
        node["type"] = "heading"
    node["tagName"] = tag
    return node


def _paragraph(text: str, use_type: bool = True) -> dict:
    node: dict = {"content": text, "attributes": {"id": f"p-{text[:5]}"}}
    if use_type:
        node["type"] = "text"
    else:
        node["tagName"] = "p"
    return node


def _image(src: str) -> dict:
    return {"type": "image", "attributes": {"id": "img", "src": src}}


def _link(href: str, text: str = "Click", use_type: str = "link") -> dict:
    return {
        "type": use_type,
        "tagName": "a",
        "content": text,
        "attributes": {"id": "l", "href": href},
    }


def _section(*children: dict) -> dict:
    return {
        "type": "section",
        "attributes": {"id": "section"},
        "components": list(children),
    }


# -- Headings --


def test_walk_extracts_headings_from_type_heading():
    tree = [_section(_heading("Welcome"), _heading("Features", tag="h3"))]

    result = walk_grapesjs_tree(tree)

    assert result.headings == ["Welcome", "Features"]


def test_walk_extracts_headings_from_raw_tag_names():
    tree = [
        _section(
            {"tagName": "h1", "content": "Hello"},
            {"tagName": "h4", "content": "Details"},
        )
    ]

    result = walk_grapesjs_tree(tree)

    assert result.headings == ["Hello", "Details"]


def test_walk_skips_empty_heading_content():
    tree = [_section(_heading(""), _heading("  "), _heading("Real"))]

    result = walk_grapesjs_tree(tree)

    assert result.headings == ["Real"]


# -- Paragraphs --


def test_walk_extracts_paragraphs_from_type_text_and_tag_p():
    tree = [
        _section(
            _paragraph("First paragraph."),
            _paragraph("Second paragraph.", use_type=False),
        )
    ]

    result = walk_grapesjs_tree(tree)

    assert result.paragraphs == ["First paragraph.", "Second paragraph."]


# -- Images --


def test_walk_extracts_image_src_values():
    tree = [_section(_image("/a.jpg"), _image("https://cdn.example.com/b.png"))]

    result = walk_grapesjs_tree(tree)

    assert result.images == ["/a.jpg", "https://cdn.example.com/b.png"]


def test_walk_skips_images_without_src():
    tree = [_section({"type": "image", "attributes": {"alt": "nope"}})]

    result = walk_grapesjs_tree(tree)

    assert result.images == []


# -- Links --


def test_walk_extracts_link_href_values():
    tree = [
        _section(
            _link("/about"),
            _link("https://example.com", use_type="button"),
            {"tagName": "a", "attributes": {"href": "/services"}},
        )
    ]

    result = walk_grapesjs_tree(tree)

    assert result.links == ["/about", "https://example.com", "/services"]


def test_walk_skips_anchor_and_mailto_and_tel_links():
    tree = [
        _section(
            _link("#top"),
            _link("mailto:hi@example.com"),
            _link("tel:+15551234567"),
            _link("javascript:void(0)"),
            _link("/keep"),
        )
    ]

    result = walk_grapesjs_tree(tree)

    assert result.links == ["/keep"]


# -- Sections --


def test_walk_counts_only_top_level_sections():
    tree = [
        _section(_heading("A"), _section(_heading("inner"))),
        _section(_heading("B")),
    ]

    result = walk_grapesjs_tree(tree)

    # Two top-level sections. The nested section inside the first one is
    # reached by recursion but must not inflate section_count.
    assert result.section_count == 2
    assert "A" in result.headings and "B" in result.headings and "inner" in result.headings


def test_walk_empty_tree_produces_empty_content():
    result = walk_grapesjs_tree([])

    assert result == WalkedContent()


def test_walk_non_list_input_returns_empty_content():
    # Defensive: callers pass the raw field from a JSON response, which
    # could be None when the page has no content.
    result = walk_grapesjs_tree(None)  # type: ignore[arg-type]

    assert result == WalkedContent()


def test_walk_handles_deep_nesting_without_recursion_error():
    # Build a 200-deep nested tree to make sure recursion works.
    leaf = {"type": "heading", "tagName": "h3", "content": "Deep"}
    node: dict = leaf
    for _ in range(200):
        node = {"type": "section", "attributes": {"id": "x"}, "components": [node]}

    result = walk_grapesjs_tree([node])

    assert result.headings == ["Deep"]
