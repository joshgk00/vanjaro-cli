"""Tests for vanjaro_cli.migration.audit — pure check functions."""

from __future__ import annotations

from bs4 import BeautifulSoup

from vanjaro_cli.migration.audit import (
    audit_page,
    audit_site,
    check_composition,
    check_global_blocks,
    check_inline_styles,
    check_responsive_images,
    check_theme_classes,
)


# ---------------------------------------------------------------------------
# HTML fixture builders
# ---------------------------------------------------------------------------


def _wrap_in_editor(inner_html: str) -> str:
    return (
        "<html><body>"
        "<div id='dnn_ContentPane'><div class='vj-wrapper'>"
        f"<div id='vjEditor'>{inner_html}</div>"
        "</div></div>"
        "</body></html>"
    )


def _clean_page_html() -> str:
    """A well-structured Vanjaro page: few inline styles, theme classes, responsive images."""
    return _wrap_in_editor(
        """
        <div data-guid="aaaa-1111" published="true">
          <h1 class="vj-heading head-style-1">Welcome</h1>
        </div>
        <section>
          <h2 class="vj-heading head-style-2">About us</h2>
          <p class="vj-text paragraph-style-1">We build great things.</p>
          <picture>
            <source srcset="/DesktopModules/Vanjaro/API/Page/.versions/image.webp" type="image/webp">
            <img src="/images/image.jpg" alt="hero">
          </picture>
          <a class="btn button-style-1" href="/contact">Contact</a>
        </section>
        <section>
          <h3 class="vj-heading head-style-3">Services</h3>
          <p class="vj-text paragraph-style-2">Quality work.</p>
        </section>
        <section>
          <p class="vj-text paragraph-style-1">Footer content.</p>
        </section>
        """
    )


def _dirty_page_html() -> str:
    """A poorly structured page: many inline styles, no theme classes, unwrapped images."""
    return _wrap_in_editor(
        """
        <div style="color: red;">
          <h1 style="font-size: 36px;">Welcome</h1>
          <p style="margin: 10px;">Text here</p>
          <span style="background: blue;">Highlight</span>
        </div>
        <div>
          <img src="/images/hero.jpg" alt="hero">
          <img src="/images/team.jpg" alt="team">
        </div>
        """
        + "".join(f"<div><div><div><div><div>deep{i}</div></div></div></div></div>" for i in range(5))
    )


def _make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _get_editor(html: str):
    soup = _make_soup(html)
    return soup.find(id="vjEditor"), soup


# ---------------------------------------------------------------------------
# check_inline_styles
# ---------------------------------------------------------------------------


def test_inline_styles_clean_page_scores_high():
    editor, _ = _get_editor(_clean_page_html())
    finding = check_inline_styles(editor)
    assert finding["check"] == "inline-styles"
    assert finding["score"] == 100
    assert "0" in finding["summary"]


def test_inline_styles_dirty_page_scores_low():
    editor, _ = _get_editor(_dirty_page_html())
    finding = check_inline_styles(editor)
    assert finding["score"] < 70
    assert len(finding["details"]) > 0


def test_inline_styles_excludes_dnn_module_subtree():
    html = _wrap_in_editor(
        """
        <div class="DnnModule">
          <div style="color: red;">Module inline style — should be excluded</div>
        </div>
        <section>
          <p>Clean content</p>
        </section>
        """
    )
    editor, _ = _get_editor(html)
    finding = check_inline_styles(editor)
    assert finding["score"] == 100


def test_inline_styles_excludes_vjmod_subtree():
    html = _wrap_in_editor(
        """
        <div vjmod="true">
          <span style="font-weight: bold;">Third-party module</span>
        </div>
        """
    )
    editor, _ = _get_editor(html)
    finding = check_inline_styles(editor)
    assert finding["score"] == 100


def test_inline_styles_score_formula():
    html = _wrap_in_editor(
        "<div style='a:b'></div>"
        "<div style='c:d'></div>"
        "<div style='e:f'></div>"
    )
    editor, _ = _get_editor(html)
    finding = check_inline_styles(editor)
    assert finding["score"] == 70  # 100 - 10*3


# ---------------------------------------------------------------------------
# check_theme_classes
# ---------------------------------------------------------------------------


def test_theme_classes_fully_styled_scores_100():
    editor, soup = _get_editor(_clean_page_html())
    finding = check_theme_classes(editor, soup)
    assert finding["score"] == 100


def test_theme_classes_no_theme_elements_scores_100():
    html = _wrap_in_editor("<section><p>Plain content, no theme classes.</p></section>")
    editor, soup = _get_editor(html)
    finding = check_theme_classes(editor, soup)
    assert finding["score"] == 100
    assert "No theme-classified elements" in finding["summary"]


def test_theme_classes_partial_coverage_scores_proportionally():
    html = _wrap_in_editor(
        """
        <h2 class="vj-heading head-style-1">Styled</h2>
        <h3 class="vj-heading">Unstyled</h3>
        """
    )
    editor, soup = _get_editor(html)
    finding = check_theme_classes(editor, soup)
    assert finding["score"] == 50
    assert "1/2" in finding["details"][0]


def test_theme_classes_flags_unstyled_buttons():
    html = _wrap_in_editor(
        '<a class="btn">Click me</a>'
    )
    editor, soup = _get_editor(html)
    finding = check_theme_classes(editor, soup)
    assert finding["score"] == 0
    assert any(".btn" in d for d in finding["details"])


def test_theme_classes_flags_per_page_inline_color():
    html = (
        "<html><head>"
        "<style>#vjEditor .hero { color: red; background-color: blue; }</style>"
        "</head><body>"
        "<div id='dnn_ContentPane'><div class='vj-wrapper'>"
        "<div id='vjEditor'><section><p>Content</p></section></div>"
        "</div></div></body></html>"
    )
    editor, soup = _get_editor(html)
    finding = check_theme_classes(editor, soup)
    assert any("Per-page <style>" in d for d in finding["details"])


# ---------------------------------------------------------------------------
# check_responsive_images
# ---------------------------------------------------------------------------


def test_responsive_images_all_wrapped_scores_100():
    html = _wrap_in_editor(
        """
        <picture>
          <source srcset="/DesktopModules/Vanjaro/API/Page/.versions/img1.webp" type="image/webp">
          <img src="/images/img1.jpg">
        </picture>
        """
    )
    editor, _ = _get_editor(html)
    finding = check_responsive_images(editor)
    assert finding["score"] == 100
    assert "1/1" in finding["summary"]


def test_responsive_images_no_images_scores_100():
    html = _wrap_in_editor("<p>No images here.</p>")
    editor, _ = _get_editor(html)
    finding = check_responsive_images(editor)
    assert finding["score"] == 100
    assert "No images" in finding["summary"]


def test_responsive_images_unwrapped_scores_zero():
    html = _wrap_in_editor(
        '<img src="/images/hero.jpg" alt="hero">'
    )
    editor, _ = _get_editor(html)
    finding = check_responsive_images(editor)
    assert finding["score"] == 0
    assert len(finding["details"]) == 1
    assert "Unwrapped" in finding["details"][0]


def test_responsive_images_picture_without_versions_scores_zero():
    html = _wrap_in_editor(
        """
        <picture>
          <source srcset="/images/img.webp" type="image/webp">
          <img src="/images/img.jpg">
        </picture>
        """
    )
    editor, _ = _get_editor(html)
    finding = check_responsive_images(editor)
    assert finding["score"] == 0
    assert any("missing /.versions/" in d for d in finding["details"])


def test_responsive_images_excludes_module_subtree():
    html = _wrap_in_editor(
        """
        <div class="DnnModule"><img src="/module/img.jpg"></div>
        <picture>
          <source srcset="/DesktopModules/Vanjaro/API/Page/.versions/hero.webp">
          <img src="/images/hero.jpg">
        </picture>
        """
    )
    editor, _ = _get_editor(html)
    finding = check_responsive_images(editor)
    assert finding["score"] == 100


def test_responsive_images_mixed_partial_score():
    html = _wrap_in_editor(
        """
        <picture>
          <source srcset="/DesktopModules/Vanjaro/API/Page/.versions/a.webp">
          <img src="/images/a.jpg">
        </picture>
        <img src="/images/b.jpg">
        """
    )
    editor, _ = _get_editor(html)
    finding = check_responsive_images(editor)
    assert finding["score"] == 50


# ---------------------------------------------------------------------------
# check_composition
# ---------------------------------------------------------------------------


def test_composition_good_child_count_scores_100():
    sections = "".join(f"<section>{i}</section>" for i in range(5))
    html = _wrap_in_editor(sections)
    editor, _ = _get_editor(html)
    finding = check_composition(editor)
    assert finding["score"] == 100


def test_composition_too_few_children_penalized():
    html = _wrap_in_editor("<section>Only one section</section>")
    editor, _ = _get_editor(html)
    finding = check_composition(editor)
    assert finding["score"] < 100
    assert any("Too few" in d for d in finding["details"])


def test_composition_too_many_children_penalized():
    sections = "".join(f"<section>{i}</section>" for i in range(15))
    html = _wrap_in_editor(sections)
    editor, _ = _get_editor(html)
    finding = check_composition(editor)
    assert finding["score"] < 100
    assert any("Too many" in d for d in finding["details"])


def test_composition_deep_dom_penalized():
    # 25 levels deep — exceeds the 20-level threshold
    deep = "<div>" * 25 + "content" + "</div>" * 25
    html = _wrap_in_editor(
        "<section>one</section><section>two</section>"
        f"<section>three</section><section>{deep}</section>"
        "<section>five</section>"
    )
    editor, _ = _get_editor(html)
    finding = check_composition(editor)
    assert finding["score"] < 100
    assert any("DOM depth" in d for d in finding["details"])


def test_composition_reports_section_count_informational():
    html = _wrap_in_editor(
        "<section>one</section><section>two</section>"
        "<section>three</section><section>four</section>"
        "<section>five</section>"
    )
    editor, _ = _get_editor(html)
    finding = check_composition(editor)
    assert any("section" in d.lower() for d in finding["details"])


# ---------------------------------------------------------------------------
# check_global_blocks (site-level)
# ---------------------------------------------------------------------------


def _make_soup_pair(url: str, html: str) -> tuple[str, BeautifulSoup]:
    return url, BeautifulSoup(html, "html.parser")


def test_global_blocks_all_pages_have_wrappers():
    html_a = _wrap_in_editor('<div data-guid="guid-1" published="true">Header</div>')
    html_b = _wrap_in_editor('<div data-guid="guid-1" published="true">Header</div>')
    pages = [
        _make_soup_pair("http://site.com/", html_a),
        _make_soup_pair("http://site.com/about", html_b),
    ]
    finding = check_global_blocks(pages)
    assert finding["score"] > 50
    assert not any("missing" in d.lower() for d in finding["details"] if "Sitewide" not in d)


def test_global_blocks_page_missing_wrapper_reported():
    html_a = _wrap_in_editor('<div data-guid="guid-1" published="true">Header</div>')
    html_b = _wrap_in_editor('<section>No global blocks here</section>')
    pages = [
        _make_soup_pair("http://site.com/", html_a),
        _make_soup_pair("http://site.com/about", html_b),
    ]
    finding = check_global_blocks(pages)
    assert any("missing" in d.lower() for d in finding["details"])
    assert "http://site.com/about" in " ".join(finding["details"])


def test_global_blocks_duplicate_section_detected():
    shared_markup = "<section><h2>Shared Section</h2><p>Same content on every page</p></section>"
    html_a = _wrap_in_editor(shared_markup)
    html_b = _wrap_in_editor(shared_markup)
    pages = [
        _make_soup_pair("http://site.com/", html_a),
        _make_soup_pair("http://site.com/about", html_b),
    ]
    finding = check_global_blocks(pages)
    assert any("duplicate" in d.lower() or "2+" in d for d in finding["details"])


def test_global_blocks_guid_wrapped_duplicate_not_flagged():
    """A duplicate wrapped in data-guid is already a global block — don't flag it."""
    shared = '<div data-guid="guid-nav" published="true"><nav>Nav</nav></div>'
    html_a = _wrap_in_editor(shared)
    html_b = _wrap_in_editor(shared)
    pages = [
        _make_soup_pair("http://site.com/", html_a),
        _make_soup_pair("http://site.com/about", html_b),
    ]
    finding = check_global_blocks(pages)
    # Should NOT flag the GUID-wrapped block as a duplicate non-global section
    duplicate_detail = [
        d for d in finding["details"]
        if "duplicate" in d.lower() or "2+" in d
    ]
    assert not duplicate_detail


def test_global_blocks_no_vjEditor_pages_handled():
    """Pages without #vjEditor are noted as missing wrappers, not crashed."""
    html = "<html><body><p>Not a Vanjaro page</p></body></html>"
    pages = [_make_soup_pair("http://site.com/", html)]
    finding = check_global_blocks(pages)
    assert any("missing" in d.lower() for d in finding["details"])


# ---------------------------------------------------------------------------
# audit_page (integration of per-page checks)
# ---------------------------------------------------------------------------


def test_audit_page_clean_scores_high():
    result = audit_page("http://site.com/", _clean_page_html())
    assert result["score"] >= 70
    assert set(result["checks"].keys()) == {"inline-styles", "theme-classes", "responsive-images", "composition"}


def test_audit_page_dirty_scores_low():
    result = audit_page("http://site.com/", _dirty_page_html())
    assert result["score"] < 80
    assert result["checks"]["inline-styles"]["score"] < 70


def test_audit_page_no_vjEditor():
    html = "<html><body><p>Not a Vanjaro page</p></body></html>"
    result = audit_page("http://site.com/", html)
    assert result["score"] == 0
    for check in ("inline-styles", "theme-classes", "responsive-images", "composition"):
        assert result["checks"][check]["score"] == 0
        assert "#vjEditor" in result["checks"][check]["summary"]


# ---------------------------------------------------------------------------
# audit_site (integration)
# ---------------------------------------------------------------------------


def test_audit_site_returns_expected_schema():
    pages = [
        ("http://site.com/", _clean_page_html()),
        ("http://site.com/about", _clean_page_html()),
    ]
    report = audit_site(pages)
    assert "pages" in report
    assert "site_checks" in report
    assert "score" in report
    assert "global-blocks" in report["site_checks"]
    assert len(report["pages"]) == 2
    assert report["score"] > 0


def test_audit_site_composite_score_blends_page_and_site_checks():
    pages = [("http://site.com/", _clean_page_html())]
    report = audit_site(pages)
    page_score = report["pages"][0]["score"]
    gb_score = report["site_checks"]["global-blocks"]["score"]
    expected = (page_score + gb_score) / 2
    assert abs(report["score"] - expected) < 0.5


# ---------------------------------------------------------------------------
# check_global_blocks — live-site regression (Task B)
# ---------------------------------------------------------------------------
#
# Vanjaro renders global-block wrappers as bare <div data-guid="..."> with no
# ``published`` attribute in the page HTML. The previous implementation
# required el.get("published") to be truthy, which caused every page to be
# reported as "missing wrappers" on a real Vanjaro site.
#
# Verbatim snippet from http://vanjarocli.local/ (fetched 2026-06-12):
#   <div data-guid="74b54357-6b87-4eee-b0c3-5ec10a3dcfbb" id="323b9">
#   <div data-guid="3131d4cd-123d-41a6-af56-e951785cdfdc" id="a1a67">


def _make_live_site_page_html(guid_1: str, guid_2: str) -> str:
    """HTML that mirrors the actual Vanjaro rendered output — no published attribute."""
    return (
        "<html><body>"
        "<div id='dnn_ContentPane'><div class='vj-wrapper'>"
        "<div id='vjEditor'>"
        f"<div data-guid='{guid_1}' id='323b9'><nav>Header nav</nav></div>"
        "<section id='tpl-hero-s1' class='vj-section py-5'>"
        "<h1 class='vj-heading head-style-1'>Welcome</h1>"
        "</section>"
        "<section id='tpl-fc3-s1' class='vj-section py-5'>"
        "<p class='vj-text paragraph-style-1'>Content block</p>"
        "</section>"
        f"<div data-guid='{guid_2}' id='a1a67'><footer>Footer</footer></div>"
        "</div>"
        "</div></div>"
        "</body></html>"
    )


def test_global_blocks_detects_guid_without_published_attribute():
    """data-guid wrappers must be detected even when the published attribute is absent."""
    guid_1 = "74b54357-6b87-4eee-b0c3-5ec10a3dcfbb"
    guid_2 = "3131d4cd-123d-41a6-af56-e951785cdfdc"
    html = _make_live_site_page_html(guid_1, guid_2)
    pages = [_make_soup_pair("http://site.com/", html)]
    finding = check_global_blocks(pages)
    assert not any("missing" in d.lower() for d in finding["details"])
    assert finding["score"] > 0


def test_global_blocks_sitewide_guid_detected_without_published_attribute():
    """Sitewide GUIDs are identified correctly without published attribute."""
    guid_header = "35665768-28e6-4cfe-9c91-0a1f40db5cf5"
    guid_footer = "064e9f13-9b23-4a4d-9a17-a61fe1a47bf3"
    html_contact = _make_live_site_page_html(guid_header, guid_footer)
    html_lighting = _make_live_site_page_html(guid_header, guid_footer)
    pages = [
        _make_soup_pair("http://site.com/contact", html_contact),
        _make_soup_pair("http://site.com/lighting", html_lighting),
    ]
    finding = check_global_blocks(pages)
    assert any("Sitewide global blocks" in d for d in finding["details"])
    assert not any("missing" in d.lower() for d in finding["details"])


def test_global_blocks_no_wrappers_summary_distinguishes_zero_case():
    """When no data-guid wrappers exist on any page, the summary says so explicitly."""
    html = _wrap_in_editor("<section><p>No global blocks</p></section>")
    pages = [_make_soup_pair("http://site.com/page1", html)]
    finding = check_global_blocks(pages)
    assert "No global-block wrappers found" in finding["summary"]
