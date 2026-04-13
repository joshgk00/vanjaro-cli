"""Tests for vanjaro_cli.migration.crawler pure helpers.

These tests cover ``slugify_path`` and ``infer_page_hierarchy`` — the
non-HTTP helpers that don't need the ``responses`` mock. The HTTP-fetching
side of the crawler (``discover_pages``, ``fetch_url_text``) is exercised
through the ``migrate crawl`` command integration tests.
"""

from __future__ import annotations

from vanjaro_cli.migration.crawler import infer_page_hierarchy, slugify_path


def _page(path: str, slug: str | None = None) -> dict:
    """Build a minimal inventory page entry."""
    return {
        "url": f"https://example.com{path}",
        "path": path,
        "title": path.strip("/").replace("/", " ").title() or "Home",
        "slug": slug if slug is not None else slugify_path(path),
        "sections": [],
    }


# --- slugify_path ---


def test_slugify_path_root_becomes_home():
    assert slugify_path("/") == "home"
    assert slugify_path("") == "home"


def test_slugify_path_flattens_nested_segments():
    assert slugify_path("/services/web-design") == "services-web-design"


def test_slugify_path_preserves_alphanumerics_and_dashes():
    assert slugify_path("/about-us") == "about-us"
    assert slugify_path("/About/Team_Page") == "About-Team_Page"


# --- infer_page_hierarchy ---


def test_infer_hierarchy_sets_parent_slug_for_nested_path():
    pages = [_page("/"), _page("/services"), _page("/services/web-design")]

    result = infer_page_hierarchy(pages)

    by_slug = {p["slug"]: p for p in result}
    assert by_slug["home"]["parent_slug"] is None
    assert by_slug["services"]["parent_slug"] is None
    assert by_slug["services-web-design"]["parent_slug"] == "services"


def test_infer_hierarchy_top_level_pages_are_siblings_of_home():
    """DNN treats top-level pages as siblings of home, not children."""
    pages = [_page("/"), _page("/about"), _page("/contact")]

    result = infer_page_hierarchy(pages)

    for page in result:
        assert page["parent_slug"] is None


def test_infer_hierarchy_handles_three_level_nesting():
    pages = [
        _page("/"),
        _page("/services"),
        _page("/services/web"),
        _page("/services/web/redesign"),
    ]

    result = infer_page_hierarchy(pages)

    by_slug = {p["slug"]: p for p in result}
    assert by_slug["services"]["parent_slug"] is None
    assert by_slug["services-web"]["parent_slug"] == "services"
    assert by_slug["services-web-redesign"]["parent_slug"] == "services-web"


def test_infer_hierarchy_orphan_child_gets_no_parent():
    """A /services/web page without a /services page has no parent."""
    pages = [_page("/"), _page("/services/web-design")]

    result = infer_page_hierarchy(pages)

    by_slug = {p["slug"]: p for p in result}
    assert by_slug["services-web-design"]["parent_slug"] is None


def test_infer_hierarchy_tolerates_trailing_slash_and_html_extension():
    """/services.html and /services/ must match /services as the same page."""
    pages = [
        _page("/"),
        _page("/services.html", slug="services"),
        _page("/services/web-design"),
    ]

    result = infer_page_hierarchy(pages)

    by_slug = {p["slug"]: p for p in result}
    assert by_slug["services-web-design"]["parent_slug"] == "services"


def test_infer_hierarchy_skips_entries_missing_path_or_slug():
    pages = [
        _page("/"),
        {"url": "broken", "title": "Broken"},  # missing path and slug
        _page("/about"),
    ]

    result = infer_page_hierarchy(pages)

    assert len(result) == 3
    broken = next(p for p in result if "slug" not in p)
    assert "parent_slug" not in broken
    assert result[0]["parent_slug"] is None
    assert result[2]["parent_slug"] is None


def test_infer_hierarchy_returns_same_list_reference():
    """Callers can use either the return value or the mutated input."""
    pages = [_page("/"), _page("/about")]

    result = infer_page_hierarchy(pages)

    assert result is pages
    assert pages[0]["parent_slug"] is None


def test_infer_hierarchy_self_is_not_its_own_parent():
    """A page must not be set as its own parent even if slug collides."""
    pages = [_page("/"), _page("/services")]

    result = infer_page_hierarchy(pages)

    assert result[1]["parent_slug"] is None  # /services has no /services ancestor


def test_infer_hierarchy_empty_inventory_returns_empty():
    assert infer_page_hierarchy([]) == []
