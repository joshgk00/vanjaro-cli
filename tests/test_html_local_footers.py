"""Content-local `<footer>` elements (byline/attribution) must not become
global site chrome, while a genuine page footer still must.

`static_boundary_candidates` used to add every `<footer>` in the document as
its own candidate, regardless of nesting. A `<footer>` nested inside a
`<blockquote>`, `<article>` or `<section>` is the HTML5 citation/byline idiom
— content the visitor reads as part of that quote or article, not the site's
footer — and `_trailing_footer` would promote whichever one happened to be
last in document order into a standalone "Site Footer" section, dropping it
(and sometimes its neighbours) from the section that actually owns it.

These tests exercise the full static pipeline through
`design_document_from_html`, the same entry point the root acceptance test
(`artifacts/test_nested_chrome_independent.py`) uses, and add direct
`static_boundary_candidates` checks so the candidate set itself is asserted,
not just the resulting document.
"""

from __future__ import annotations

from datetime import datetime, timezone

from vanjaro_cli.design.html_adapter import design_document_from_html
from vanjaro_cli.design.html_boundaries import static_boundary_candidates

CAPTURE_TIME = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def _footer_sections(document):
    return [
        section
        for section in document.pages[0].sections
        if section.semantic_role == "footer"
    ]


def _owning_section(document, marker: str):
    return next(
        section
        for section in document.pages[0].sections
        if any(marker in str(element.value) for element in section.content)
    )


def test_blockquote_local_footer_stays_in_its_own_section() -> None:
    html = """
    <html><body><main>
      <section id="lone-quote">
        <blockquote><p>Best redesign we have ever shipped.</p>
        <footer>Dana Price, Operations Lead</footer></blockquote>
      </section>
    </main></body></html>
    """
    document = design_document_from_html(
        html, "https://fixture.invalid/", captured_at=CAPTURE_TIME
    )
    sections = document.pages[0].sections
    assert len(sections) == 1
    assert _footer_sections(document) == []
    owner = _owning_section(document, "Dana Price, Operations Lead")
    assert any(
        p.css_selector == "#lone-quote" for p in owner.provenance
    )


def test_article_local_footer_byline_stays_with_its_article() -> None:
    # Sibling sections give the article company: the legacy raw extractor
    # (migration/sections.py, out of scope for this fix) unwraps a boundary
    # into its children when that boundary holds most of the page's text, and
    # an isolated single-article fixture always does. Diluting the share below
    # that unrelated threshold isolates the boundary-ownership behaviour this
    # fix actually changes.
    html = """
    <html><body><main>
      <section id="intro"><h2>Latest update</h2>
      <p>Rolling out now across every region we serve, with more detail soon.</p></section>
      <article id="post">
        <h2>Shipping the new dashboard</h2>
        <p>We rebuilt the reporting screen from the ground up this quarter, adding
        filters, exports and faster loads throughout.</p>
        <footer><p>By Priya Nair</p></footer>
      </article>
      <section id="outro"><h2>What is next</h2>
      <p>We are already planning the next round of improvements from your feedback.</p></section>
    </main></body></html>
    """
    document = design_document_from_html(
        html, "https://fixture.invalid/", captured_at=CAPTURE_TIME
    )
    assert _footer_sections(document) == []
    owner = _owning_section(document, "By Priya Nair")
    assert any(p.css_selector == "#post" for p in owner.provenance)
    assert any(
        "Shipping the new dashboard" in str(element.value) for element in owner.content
    )


def test_section_local_footer_attribution_stays_with_its_section() -> None:
    html = """
    <html><body><main>
      <section id="case-study">
        <h2>Case study: Acme Corp</h2>
        <p>Acme cut onboarding time in half after the rollout.</p>
        <footer><p>Source: Acme Corp annual report</p></footer>
      </section>
    </main></body></html>
    """
    document = design_document_from_html(
        html, "https://fixture.invalid/", captured_at=CAPTURE_TIME
    )
    assert _footer_sections(document) == []
    owner = _owning_section(document, "Source: Acme Corp annual report")
    assert any(p.css_selector == "#case-study" for p in owner.provenance)
    assert any(
        "Case study: Acme Corp" in str(element.value) for element in owner.content
    )


def test_genuine_footer_nested_under_a_layout_div_is_still_chrome() -> None:
    html = """
    <html><body>
      <main><section id="hero"><h1>Welcome</h1></section></main>
      <div class="site-wrap">
        <footer id="site-footer"><p>Copyright 2026 Acme</p>
        <a href="/privacy">Privacy</a></footer>
      </div>
    </body></html>
    """
    document = design_document_from_html(
        html, "https://fixture.invalid/", captured_at=CAPTURE_TIME
    )
    footers = _footer_sections(document)
    assert len(footers) == 1
    assert any(p.css_selector == "#site-footer" for p in footers[0].provenance)


def test_genuine_footer_with_copyright_bar_and_dnn_pane_is_still_chrome() -> None:
    html = """
    <html><body>
      <main><section id="hero"><h1>Welcome</h1></section></main>
      <div id="dnn_FooterPane">
        <footer id="site-footer">
          <div class="copyright-bar">Copyright 2026 Acme</div>
          <nav><a href="/privacy">Privacy</a><a href="/terms">Terms</a></nav>
        </footer>
      </div>
    </body></html>
    """
    document = design_document_from_html(
        html, "https://fixture.invalid/", captured_at=CAPTURE_TIME
    )
    footers = _footer_sections(document)
    assert len(footers) == 1
    assert any(p.css_selector == "#site-footer" for p in footers[0].provenance)


def test_outermost_footer_with_no_wrapper_is_still_chrome() -> None:
    html = """
    <html><body>
      <main><section id="hero"><h1>Welcome</h1></section></main>
      <footer id="site-footer"><p>Copyright 2026 Acme</p>
      <a href="/privacy">Privacy</a></footer>
    </body></html>
    """
    document = design_document_from_html(
        html, "https://fixture.invalid/", captured_at=CAPTURE_TIME
    )
    footers = _footer_sections(document)
    assert len(footers) == 1
    assert any(p.css_selector == "#site-footer" for p in footers[0].provenance)


def test_content_local_footer_does_not_get_conflated_with_genuine_site_footer() -> None:
    html = """
    <html><body><main>
      <section id="case-study">
        <h2>Case study: Acme Corp</h2>
        <p>Acme cut onboarding time in half after the rollout.</p>
        <footer><p>Source: Acme Corp annual report</p></footer>
      </section>
    </main>
      <footer id="site-footer"><p>Copyright 2026 Acme</p>
      <a href="/privacy">Privacy</a></footer>
    </body></html>
    """
    document = design_document_from_html(
        html, "https://fixture.invalid/", captured_at=CAPTURE_TIME
    )
    footers = _footer_sections(document)
    assert len(footers) == 1
    assert any(p.css_selector == "#site-footer" for p in footers[0].provenance)
    byline_owner = _owning_section(document, "Source: Acme Corp annual report")
    assert byline_owner is not footers[0]
    assert any(p.css_selector == "#case-study" for p in byline_owner.provenance)


def test_candidate_discovery_excludes_content_local_footers_but_keeps_their_owner() -> None:
    """`static_boundary_candidates` itself must agree with the document-level result.

    A `<section>` holding only a quote and its attribution must remain a
    candidate — the local footer inside it must not be picked up as a second,
    separate candidate, and its presence must not make the rule drop the
    section entirely.
    """

    html = """
    <html><body><main>
      <section id="quote-one">
        <blockquote><p>Great partners.</p><footer>Alex Rivera</footer></blockquote>
      </section>
      <article id="quote-two">
        <blockquote><p>Fast turnaround.</p><footer>Sam Lee</footer></blockquote>
      </article>
    </main></body></html>
    """
    candidates = static_boundary_candidates(html)
    ids = [tag.get("id") for tag in candidates]
    assert ids == ["quote-one", "quote-two"]
    for tag in candidates:
        assert tag.find("footer") is not None


def test_candidate_discovery_still_finds_a_footer_outside_content_sectioning() -> None:
    html = """
    <html><body>
      <main><section id="hero"><h1>Welcome</h1></section></main>
      <footer id="site-footer"><p>Copyright</p></footer>
    </body></html>
    """
    candidates = static_boundary_candidates(html)
    names = [(tag.get("id"), tag.name) for tag in candidates]
    assert ("site-footer", "footer") in names


def test_isolated_article_local_byline_is_rescued_when_its_owner_is_unclaimed() -> None:
    """An isolated `<article>` is the case the root acceptance test exercises.

    The legacy extractor (`migration/sections.py`, out of scope here) splits
    a lone article's heading and paragraph into two separate raw sections
    with no selector of their own. Both fit entirely inside the article's own
    text, which makes the article a "container" — held back from claiming so
    it cannot flatten two genuinely distinct sections into one (see
    `test_a_pane_holding_two_sections_is_claimed_by_neither` in
    test_html_boundaries.py). Excluding the byline's `<footer>` from
    candidacy is then not enough on its own: nothing else ever reads its text,
    because the legacy extractor never captured it as content in the first
    place. `prepare_static_sections` must notice the article went unclaimed
    and recover the byline into one of its own raw sections rather than
    dropping it.
    """

    html = """
    <html><body><main>
      <article id="story">
        <h2>A studio update</h2>
        <p>Our team finished the new community project.</p>
        <footer><p>By Independent Author</p></footer>
      </article>
    </main></body></html>
    """
    document = design_document_from_html(
        html, "https://fixture.invalid/", captured_at=CAPTURE_TIME
    )
    assert _footer_sections(document) == []
    owner = _owning_section(document, "By Independent Author")
    assert owner.semantic_role != "footer"
    assert any(p.css_selector == "#story" for p in owner.provenance)
    owners = [
        section
        for section in document.pages[0].sections
        if any("By Independent Author" in str(element.value) for element in section.content)
    ]
    assert len(owners) == 1


def test_isolated_article_local_byline_is_rescued_alongside_a_genuine_site_footer() -> None:
    html = """
    <html><body>
      <main>
        <article id="story">
          <h2>A studio update</h2>
          <p>Our team finished the new community project.</p>
          <footer><p>By Independent Author</p></footer>
        </article>
      </main>
      <footer id="site-footer"><p>Agency copyright</p></footer>
    </body></html>
    """
    document = design_document_from_html(
        html, "https://fixture.invalid/", captured_at=CAPTURE_TIME
    )
    footers = _footer_sections(document)
    assert len(footers) == 1
    assert any(p.css_selector == "#site-footer" for p in footers[0].provenance)
    owner = _owning_section(document, "By Independent Author")
    assert owner is not footers[0]
    assert any(p.css_selector == "#story" for p in owner.provenance)


def test_blockquote_citation_already_captured_is_not_duplicated_by_the_rescue() -> None:
    """The rescue only fires for text the extractor never captured anywhere.

    A testimonial's `<footer>` citation is already read into the raw
    `blockquotes`/`headings` content by `migration/sections.py`, so the
    rescue in `prepare_static_sections` must see it as already-captured text
    and do nothing — never appending a second copy alongside the one the
    normal pipeline already produced.
    """

    html = """
    <html><body><main>
      <section id="testimonials">
        <h2>Client stories</h2>
        <blockquote><p>Distinct experience number 0.</p>
        <footer>Unique author 0</footer></blockquote>
        <blockquote><p>Distinct experience number 1.</p>
        <footer>Unique author 1</footer></blockquote>
      </section>
    </main></body></html>
    """
    document = design_document_from_html(
        html, "https://fixture.invalid/", captured_at=CAPTURE_TIME
    )
    sections = document.pages[0].sections
    assert _footer_sections(document) == []
    for marker in ("Unique author 0", "Unique author 1"):
        occurrences = sum(
            1
            for section in sections
            for element in section.content
            if marker in str(element.value)
        )
        assert occurrences == 1, f"{marker} must appear exactly once"
