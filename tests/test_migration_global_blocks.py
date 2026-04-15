"""Tests for vanjaro_cli.migration.global_blocks — direct builders for header/footer global blocks."""

from __future__ import annotations

from vanjaro_cli.migration.global_blocks import (
    build_footer_block,
    build_header_block,
)


def _flatten_types(tree: dict) -> list[str]:
    """Return every component type in the tree in depth-first order."""
    result: list[str] = []
    def _walk(node):
        if not isinstance(node, dict):
            return
        t = node.get("type")
        if isinstance(t, str):
            result.append(t)
        for child in node.get("components", []) or []:
            _walk(child)
    _walk(tree)
    return result


def _flatten_classes(tree: dict) -> list[str]:
    """Return every class name used in the tree, deduplicated."""
    result: set[str] = set()
    def _walk(node):
        if not isinstance(node, dict):
            return
        for cls in node.get("classes", []) or []:
            if isinstance(cls, dict) and isinstance(cls.get("name"), str):
                result.add(cls["name"])
        for child in node.get("components", []) or []:
            _walk(child)
    _walk(tree)
    return sorted(result)


def _flatten_content(tree: dict) -> list[str]:
    """Return every non-empty ``content`` string from the tree."""
    result: list[str] = []
    def _walk(node):
        if not isinstance(node, dict):
            return
        content = node.get("content")
        if isinstance(content, str) and content:
            result.append(content)
        for child in node.get("components", []) or []:
            _walk(child)
    _walk(tree)
    return result


def _image_srcs(tree: dict) -> list[str]:
    """Return every image src attribute from the tree."""
    result: list[str] = []
    def _walk(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "image":
            src = node.get("attributes", {}).get("src")
            if isinstance(src, str):
                result.append(src)
        for child in node.get("components", []) or []:
            _walk(child)
    _walk(tree)
    return result


def _first_component(built: dict) -> dict:
    """Return the first top-level component from a builder output."""
    return built["components"][0]


# --- build_header_block ---


def test_header_wraps_output_in_components_styles_shape():
    """Builder output must match `vanjaro global-blocks create --file` input shape."""
    built = build_header_block({})
    assert "components" in built
    assert "styles" in built
    assert isinstance(built["components"], list)
    assert len(built["components"]) == 1
    assert isinstance(built["styles"], list)


def test_header_uses_first_image_as_logo():
    built = build_header_block({
        "images": [
            {"src": "https://example.com/logo.png", "alt": "Example Corp"},
            {"src": "https://example.com/secondary.png", "alt": "Other"},
        ],
    })
    srcs = _image_srcs(_first_component(built))
    assert srcs == ["https://example.com/logo.png"]


def test_header_skips_images_without_src():
    built = build_header_block({
        "images": [{"alt": "no src here"}, {"src": "/real.png", "alt": "real"}],
    })
    assert _image_srcs(_first_component(built)) == ["/real.png"]


def test_header_prefers_nav_items_over_list_items():
    built = build_header_block({
        "nav_items": [
            {"label": "Home", "href": "/"},
            {"label": "About", "href": "/about"},
        ],
        "list_items": ["Something", "Else"],
    })
    contents = _flatten_content(_first_component(built))
    assert "Home" in contents
    assert "About" in contents
    assert "Something" not in contents


def test_header_falls_back_to_list_items_when_nav_items_empty():
    built = build_header_block({
        "list_items": ["Home", "Services", "Contact"],
    })
    contents = _flatten_content(_first_component(built))
    assert "Home" in contents
    assert "Services" in contents
    assert "Contact" in contents


def test_header_falls_back_to_links_when_nav_items_and_list_items_empty():
    built = build_header_block({
        "links": [{"text": "Link One", "href": "/one"}],
    })
    contents = _flatten_content(_first_component(built))
    assert "Link One" in contents


def test_header_empty_content_produces_placeholder_row():
    """Empty content still yields a valid tree so register doesn't error."""
    built = build_header_block({})
    tree = _first_component(built)
    assert tree["type"] == "section"
    assert "vj-section" in _flatten_classes(tree)
    contents = _flatten_content(tree)
    assert any("migrated header" in c.lower() for c in contents)


def test_header_produces_section_container_row_hierarchy():
    built = build_header_block({
        "images": [{"src": "/logo.png", "alt": "Logo"}],
        "nav_items": [{"label": "Home", "href": "/"}],
    })
    types = _flatten_types(_first_component(built))
    assert types[0] == "section"
    assert "grid" in types
    assert "row" in types
    assert "column" in types
    assert "image" in types
    assert "list-item" in types


def test_header_layout_splits_logo_and_nav_into_two_columns():
    built = build_header_block({
        "images": [{"src": "/logo.png", "alt": "Logo"}],
        "nav_items": [{"label": "Home", "href": "/"}, {"label": "About", "href": "/about"}],
    })
    # Find the row component and count its columns
    row = _first_component(built)["components"][0]["components"][0]
    assert row["type"] == "row"
    columns = [c for c in row["components"] if c.get("type") == "column"]
    assert len(columns) == 2


def test_header_layout_uses_full_width_column_when_no_logo():
    """A header with nav but no logo should still produce a usable single column."""
    built = build_header_block({"list_items": ["Home", "About"]})
    row = _first_component(built)["components"][0]["components"][0]
    columns = [c for c in row["components"] if c.get("type") == "column"]
    assert len(columns) == 1
    col_classes = [cls["name"] for cls in columns[0]["classes"]]
    assert "col-12" in col_classes


# --- build_footer_block ---


def test_footer_wraps_output_in_components_styles_shape():
    built = build_footer_block({})
    assert "components" in built
    assert "styles" in built
    assert len(built["components"]) == 1


def test_footer_splits_list_items_evenly_across_heading_columns():
    built = build_footer_block({
        "headings": ["Company", "Services", "Contact"],
        "list_items": [
            "About", "Team",       # Company
            "Web", "SEO",          # Services
            "Email", "Phone",      # Contact
        ],
    })
    contents = _flatten_content(_first_component(built))
    assert "Company" in contents
    assert "Services" in contents
    assert "Contact" in contents
    assert "About" in contents
    assert "Web" in contents
    assert "Email" in contents


def test_footer_uses_single_column_when_no_headings():
    built = build_footer_block({
        "list_items": ["Privacy", "Terms", "Sitemap"],
    })
    tree = _first_component(built)
    contents = _flatten_content(tree)
    assert "Privacy" in contents
    assert "Terms" in contents
    assert "Sitemap" in contents
    # Single col-12 column
    row = tree["components"][0]["components"][0]
    columns = [c for c in row["components"] if c.get("type") == "column"]
    assert len(columns) == 1
    col_classes = [cls["name"] for cls in columns[0]["classes"]]
    assert "col-12" in col_classes


def test_footer_includes_first_paragraph_as_about_text():
    built = build_footer_block({
        "paragraphs": ["© 2026 Example Corp. All rights reserved."],
    })
    contents = _flatten_content(_first_component(built))
    assert any("© 2026 Example Corp" in c for c in contents)


def test_footer_ignores_blank_paragraphs():
    built = build_footer_block({
        "paragraphs": ["   ", "", "Real copyright"],
    })
    contents = _flatten_content(_first_component(built))
    assert any("Real copyright" in c for c in contents)
    # Not including the empty paragraphs
    assert not any(c.strip() == "" for c in contents)


def test_footer_includes_up_to_six_images_as_badges():
    built = build_footer_block({
        "images": [
            {"src": f"/badge{i}.png", "alt": f"Badge {i}"}
            for i in range(10)
        ],
    })
    srcs = _image_srcs(_first_component(built))
    assert len(srcs) == 6
    assert srcs == [f"/badge{i}.png" for i in range(6)]


def test_footer_empty_content_produces_placeholder():
    built = build_footer_block({})
    tree = _first_component(built)
    assert tree["type"] == "section"
    contents = _flatten_content(tree)
    assert any("migrated footer" in c.lower() for c in contents)


def test_footer_uses_bg_light_section_class():
    built = build_footer_block({"list_items": ["One"]})
    classes = _flatten_classes(_first_component(built))
    assert "vj-section" in classes
    assert "bg-light" in classes
    assert "py-5" in classes


def test_footer_combines_columns_about_and_badges():
    """When all three content types exist, the footer contains all three rows."""
    built = build_footer_block({
        "headings": ["Quick Links"],
        "list_items": ["Home", "About"],
        "paragraphs": ["© 2026 Migrated Site"],
        "images": [{"src": "/logo.png", "alt": "Logo"}],
    })
    contents = _flatten_content(_first_component(built))
    srcs = _image_srcs(_first_component(built))
    assert "Quick Links" in contents
    assert "Home" in contents
    assert any("© 2026" in c for c in contents)
    assert "/logo.png" in srcs


# --- Real-world data shape (reuses crawled e2e-cmw content) ---


def test_header_handles_cmw_crawled_content_shape():
    """Regression: run the builder against the shape the real crawler writes."""
    crawled_content = {
        "headings": [],
        "paragraphs": [],
        "images": [
            {"src": "https://www.clicksandmortarwebsites.com/Portals/0/logo.png", "alt": "Clicks & Mortar"},
        ],
        "links": [],
        "buttons": [],
        "list_items": ["Home", "Who We Are", "What We Do", "What We Offer", "FAQs", "Blog", "Contact Us"],
        "nav_items": [
            {"label": "Home", "href": "https://www.clicksandmortarwebsites.com/", "children": []},
            {"label": "Who We Are", "href": "https://www.clicksandmortarwebsites.com/who-we-are", "children": []},
        ],
    }

    built = build_header_block(crawled_content)
    assert built["components"]
    tree = _first_component(built)
    srcs = _image_srcs(tree)
    contents = _flatten_content(tree)
    assert "https://www.clicksandmortarwebsites.com/Portals/0/logo.png" in srcs
    # nav_items takes precedence
    assert "Home" in contents
    assert "Who We Are" in contents


def test_footer_handles_cmw_crawled_content_shape():
    crawled_content = {
        "headings": [],
        "paragraphs": ["We make easy and affordable websites for small businesses looking to have an online presence."],
        "images": [
            {"src": "/badge1.jpg", "alt": "MMSDC"},
            {"src": "/badge2.jpg", "alt": "Royal Oak COC"},
        ],
        "links": [],
        "buttons": [],
        "list_items": ["email@example.com", "(248) 690-6559"],
    }

    built = build_footer_block(crawled_content)
    contents = _flatten_content(_first_component(built))
    srcs = _image_srcs(_first_component(built))

    assert "email@example.com" in contents
    assert "(248) 690-6559" in contents
    assert any("affordable websites" in c for c in contents)
    assert "/badge1.jpg" in srcs
    assert "/badge2.jpg" in srcs
