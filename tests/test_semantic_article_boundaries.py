"""A genuine semantic `<article>` must extract as one owning section.

Root cause: `migration/sections.py::_top_level_sections` treated `<article>`
as an ordinary layout wrapper (`_WRAPPER_TAGS`), so single-child descent
unwrapped a lone article into its heading, body and local footer as separate
top-level nodes before the distinct-nested-sections guard ever ran. The
detached local footer/header was then dropped outright by the chrome filter
in `extract_sections` (it is a `<footer>`/`<header>` element with no siblings
to give it context) — a genuine article byline had no content owner at all.
A second, related bug let a *dominant* article beside short siblings expand
the same way: any header/footer-tagged child of a dominant container was
read as proof the container was page-level layout chrome, which is true for
an anonymous `div`/`form`/`main` wrapper but not for a `<section>`/`<article>`
that legitimately owns a local header or attribution footer.

`vanjaro_cli/design/html_boundaries.py` previously patched around this with
`_rescue_local_footer_text`, a heuristic that decided whether to fold a local
footer's text back in using a global "word novelty" test rather than DOM
ownership — which silently dropped a footer whose words happened to already
occur in a longer body paragraph
(`artifacts/test_footer_rescue_ownership_independent.py`). That rescue is
now removed: correcting extraction at the source means the local
header/footer's own paragraphs are captured directly as part of the
article's content, with real DOM provenance, and no heuristic guesswork.

These are maintained regressions alongside the root acceptance file
(`artifacts/test_nested_chrome_independent.py`, not owned here). They run
the real pipeline end to end — `extract_sections` for the raw legacy
extraction shape, `design_document_from_html` for the full static adapter —
never a browser probe.
"""

from __future__ import annotations

import pytest

from vanjaro_cli.design.html_adapter import design_document_from_html
from vanjaro_cli.migration.sections import extract_sections

BASE_URL = "https://example.com/"


def _footer_sections(document):
    return [
        section
        for section in document.pages[0].sections
        if section.semantic_role == "footer"
    ]


def _owners(document, marker: str):
    return [
        section
        for section in document.pages[0].sections
        if any(marker in str(element.value) for element in section.content)
    ]


@pytest.mark.parametrize("site_footer", [False, True])
def test_lone_article_byline_has_exactly_one_owner(site_footer):
    """A single, isolated article is the root failure's exact shape."""

    html = (
        '<html><body><main><article id="story"><h2>A studio update</h2>'
        "<p>Our team finished the new community project.</p>"
        "<footer><p>By Independent Author</p></footer></article></main>"
        + (
            '<footer id="site-footer"><p>Agency copyright</p></footer>'
            if site_footer
            else ""
        )
        + "</body></html>"
    )
    document = design_document_from_html(html, "https://fixture.invalid/story")
    footers = _footer_sections(document)
    assert len(footers) == int(site_footer)
    owners = _owners(document, "By Independent Author")
    assert len(owners) == 1, "the byline must be retained exactly once"
    owner = owners[0]
    assert owner.semantic_role != "footer"
    assert any(p.css_selector == "#story" for p in owner.provenance)
    assert any("A studio update" in str(e.value) for e in owner.content)
    if site_footer:
        assert owner is not footers[0]
        assert any(p.css_selector == "#site-footer" for p in footers[0].provenance)


def test_dominant_article_beside_short_siblings_keeps_its_footer():
    """A dominant article's own local footer must not read as page chrome.

    The article carries the overwhelming majority of the page's text, which
    is exactly the condition that used to make the "any chrome-like child
    implies a page-level wrapper" heuristic misfire on its footer child.
    """

    long_body = "".join(
        f"<p>Sentence {i} of the long article body that dominates the page "
        "text share by a wide margin.</p>"
        for i in range(6)
    )
    html = (
        "<html><body><main>"
        f'<article id="post"><h2>Big story</h2>{long_body}'
        "<footer><p>By Priya Nair</p></footer></article>"
        '<aside id="short"><p>Short blurb.</p></aside>'
        "</main></body></html>"
    )
    document = design_document_from_html(html, "https://fixture.invalid/post")
    assert _footer_sections(document) == []
    owners = _owners(document, "By Priya Nair")
    assert len(owners) == 1
    assert any(p.css_selector == "#post" for p in owners[0].provenance)
    assert any("Big story" in str(e.value) for e in owners[0].content)


def test_footer_words_already_present_in_body_are_still_retained():
    """Adversarial case for the removed word-novelty rescue.

    The byline's words ("By Independent Author") already occur inside a
    longer body sentence; a global word-set novelty test reads the footer as
    contributing nothing new and drops it. Ownership must come from DOM
    structure, not from whether the words are unique on the page.
    """

    html = (
        '<html><body><main><article id="story"><h2>A studio update</h2>'
        "<p>By Independent Author is the attribution used for this story.</p>"
        "<footer><p>By Independent Author</p></footer></article></main></body></html>"
    )
    document = design_document_from_html(html, "https://fixture.invalid/story")
    owners = [
        section
        for section in document.pages[0].sections
        if any(
            str(element.value).strip() == "By Independent Author"
            for element in section.content
        )
    ]
    assert len(owners) == 1, "the distinct footer paragraph must not be dropped"
    assert owners[0].semantic_role != "footer"
    assert any(p.css_selector == "#story" for p in owners[0].provenance)


def test_identical_byline_in_two_separate_articles_stays_with_each():
    """Two articles sharing one byline text must each keep their own copy."""

    html = (
        "<html><body><main>"
        '<article id="a1"><h2>First post</h2>'
        "<p>First body text here for the story.</p>"
        "<footer><p>By Same Author</p></footer></article>"
        '<article id="a2"><h2>Second post</h2>'
        "<p>Second body text here for the story.</p>"
        "<footer><p>By Same Author</p></footer></article>"
        "</main></body></html>"
    )
    document = design_document_from_html(html, "https://fixture.invalid/")
    owners = _owners(document, "By Same Author")
    assert len(owners) == 2, "each article must retain its own byline"
    selectors = {p.css_selector for owner in owners for p in owner.provenance}
    assert selectors == {"#a1", "#a2"}
    first = next(o for o in owners if any(p.css_selector == "#a1" for p in o.provenance))
    second = next(o for o in owners if any(p.css_selector == "#a2" for p in o.provenance))
    assert any("First post" in str(e.value) for e in first.content)
    assert any("Second post" in str(e.value) for e in second.content)


def test_linked_attribution_keeps_text_and_destination():
    """A byline that is itself a link must keep both its label and href."""

    html = (
        '<html><body><main><article id="story"><h2>A studio update</h2>'
        "<p>Our team finished the new community project.</p>"
        '<footer><a href="/authors/priya">By Priya Nair</a></footer>'
        "</article></main></body></html>"
    )
    document = design_document_from_html(html, "https://fixture.invalid/story")
    assert _footer_sections(document) == []
    owners = _owners(document, "By Priya Nair")
    assert len(owners) == 1
    owner = owners[0]
    assert any(p.css_selector == "#story" for p in owner.provenance)
    linked = next(e for e in owner.content if "By Priya Nair" in str(e.value))
    assert linked.attributes.get("href") == "/authors/priya"


def test_article_local_header_stays_with_its_article():
    """A local `<header>` (not just a footer) must not become site chrome."""

    html = (
        '<html><body><main><article id="story">'
        "<header><h2>A studio update</h2><p>Filed under Studio News</p></header>"
        "<p>Our team finished the new community project.</p>"
        "</article></main></body></html>"
    )
    document = design_document_from_html(html, "https://fixture.invalid/story")
    sections = document.pages[0].sections
    assert not any(s.semantic_role in ("header", "navigation") for s in sections)
    owners = _owners(document, "Filed under Studio News")
    assert len(owners) == 1
    assert any(p.css_selector == "#story" for p in owners[0].provenance)
    assert any(
        "Our team finished the new community project" in str(e.value)
        for e in owners[0].content
    )


def test_dnn_layout_div_wrapping_chrome_still_descends():
    """Ordinary div/form/main layout wrappers must still unwrap normally.

    Unlike a `<section>`/`<article>`, an anonymous `div` wrapping a header,
    a content pane and a footer as direct children really is page-level
    layout chrome, and must still expand so the real content sections
    surface and the chrome is excluded.
    """

    html = (
        "<!doctype html><html><body>"
        '<form id="Form"><div class="dnngo-main"><div id="dnn_wrapper">'
        '<header class="header_bg"><nav><a href="/a">A</a><a href="/b">B</a></nav></header>'
        '<section id="dnn_content">'
        '<div class="TopOutPane"><h1>Welcome to the Site</h1>'
        "<p>We build great websites for you.</p></div>"
        '<div class="dnn_layout clearfix"><h2>Our Prices</h2>'
        "<p>$99 Website Only plan with hosting.</p></div>"
        "</section>"
        '<footer class="footer_box"><p>Copyright 2026</p></footer>'
        "</div></div></form></body></html>"
    )
    sections = extract_sections(html, BASE_URL)
    types = [s["type"] for s in sections]
    assert "header" not in types and "footer" not in types
    headings = [h for s in sections for h in s["content"].get("headings", [])]
    assert "Welcome to the Site" in headings
    assert "Our Prices" in headings


def test_article_wrapping_genuinely_distinct_sections_still_descends():
    """An article that truly wraps multiple distinct sections must still
    split apart — the fix must not turn every `<article>` into an
    unconditional single owning section, only stop the unconditional
    unwrap for one that is genuinely a leaf."""

    html = (
        '<html><body><main><article id="wrapper">'
        '<section class="intro"><h2>Intro</h2><p>Intro copy here for the reader.</p></section>'
        '<section class="details"><h2>Details</h2>'
        "<p>Details copy that differs from the intro entirely.</p></section>"
        "</article></main></body></html>"
    )
    sections = extract_sections(html, BASE_URL)
    assert len(sections) == 2
    headings = [h for s in sections for h in s["content"].get("headings", [])]
    assert headings == ["Intro", "Details"]


def test_uniform_article_card_grid_stays_one_group():
    """A grid of `<article class="card">` cards must stay one section, not
    be shredded into one top-level section per card."""

    cards = "".join(
        f'<article class="card"><h3>Card {i}</h3><img src="/c{i}.jpg">'
        f"<p>Card body {i}.</p></article>"
        for i in range(3)
    )
    html = f'<html><body><main><section id="cards"><h2>Our Work</h2>{cards}</section></main></body></html>'
    document = design_document_from_html(html, "https://fixture.invalid/")
    sections = document.pages[0].sections
    assert len(sections) == 1
    assert any(p.css_selector == "#cards" for p in sections[0].provenance)
    for i in range(3):
        assert any(f"Card {i}" in str(e.value) for e in sections[0].content)
