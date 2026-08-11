"""Focused contracts for static HTML boundary and relationship recovery."""

from __future__ import annotations

from bs4 import BeautifulSoup

from vanjaro_cli.design.html_boundaries import (
    append_missing_video_sections,
    enrich_faq_relationships,
    prepare_static_sections,
    static_boundary_candidates,
    static_role,
)


def test_static_boundaries_require_stable_navigation_and_preserve_order() -> None:
    html = """
    <html><body>
      <nav><a href='/ignored'>Incidental</a></nav>
      <header id='site-header'><nav>
        <a href='/'>Home</a><a href='/about'>About</a>
      </nav></header>
      <main>
        <section id='hero'><h1>Welcome</h1></section>
        <section id='stats'><ul><li><strong>10</strong><span>Clients</span></li>
          <li><strong>20</strong><span>Projects</span></li></ul></section>
      </main>
    </body></html>
    """

    assert [tag.get("id") for tag in static_boundary_candidates(html)] == [
        "site-header",
        "hero",
        "stats",
    ]


def test_prepare_static_sections_attaches_navigation_roles_and_provenance() -> None:
    html = """
    <header id='header'><nav><a href='/'>Home</a><a href='/work'>Work</a></nav></header>
    <main>
      <section id='hero'><h1>Build better sites</h1><p>Agency introduction</p></section>
      <section id='testimonials'><blockquote>Excellent work</blockquote></section>
    </main>
    """
    legacy = [
        {"type": "hero", "content": {"headings": ["Build better sites"], "paragraphs": ["Agency introduction"]}},
        {"type": "testimonial", "content": {"paragraphs": ["Excellent work"]}},
    ]

    prepared = prepare_static_sections(html, legacy)

    assert [section["_static_role"] for section in prepared] == [
        "navigation",
        "hero",
        "testimonials",
    ]
    assert [section["_static_selector"] for section in prepared] == [
        "#header",
        "#hero",
        "#testimonials",
    ]


def test_faq_and_media_only_relationship_repair_is_source_faithful() -> None:
    html = """
    <section id='faq'>
      <details><summary>Question one?</summary><p>Answer one.</p></details>
      <details><summary>Question two?</summary><p>Answer two.</p></details>
    </section>
    <section><video><source src='/media/intro.mp4'></video></section>
    <section><iframe src='https://www.youtube.com/embed/example'></iframe></section>
    """
    sections = [{
        "type": "faq",
        "content": {"headings": ["FAQ"], "paragraphs": []},
    }]

    enrich_faq_relationships(html, sections)
    append_missing_video_sections(html, "https://agency.example/home", sections)

    assert sections[0]["content"]["headings"] == [
        "FAQ",
        "Question one?",
        "Question two?",
    ]
    assert sections[0]["content"]["paragraphs"] == ["Answer one.", "Answer two."]
    assert sections[1]["content"]["videos"] == [
        {"type": "native", "src": "https://agency.example/media/intro.mp4"},
        {"type": "embed", "src": "https://www.youtube.com/embed/example"},
    ]


def _role(markup: str, index: int = 2) -> str:
    element = BeautifulSoup(markup, "html.parser").find(["section", "div"])
    return static_role(element, index)


def test_one_pull_quote_beside_photographs_is_not_testimonials() -> None:
    """A page carrying a single quote among six photographs read as a quote grid
    and lost the photographs, the copy and every link. `_classify_section` has
    always required quotes to be the point; this rule used to override it."""

    role = _role(
        "<section><h2>Lighting</h2>"
        "<blockquote><h3>A line worth quoting</h3><footer><cite>A Poet</cite></footer></blockquote>"
        "<img src='/one.jpg'><img src='/two.jpg'><p>Copy about lighting.</p></section>"
    )

    assert role != "testimonials"


def test_several_quotes_are_still_testimonials() -> None:
    """The guard must not swallow the real thing: a wall of quotes is what the
    role is for, pictures or no pictures."""

    role = _role(
        "<section><h2>What clients say</h2>"
        "<blockquote>First.</blockquote><blockquote>Second.</blockquote>"
        "<img src='/portrait.jpg'></section>"
    )

    assert role == "testimonials"


def test_a_lone_quote_with_nothing_competing_is_testimonials() -> None:
    """One quote and no imagery is a quote section, which is the other half of
    the rule `_classify_section` has always applied."""

    role = _role("<section><h2>Praise</h2><blockquote>The only quote.</blockquote></section>")

    assert role == "testimonials"


def test_a_section_that_calls_itself_a_testimonial_is_believed() -> None:
    """The author's own word outranks the inference, however much else is on the
    page."""

    role = _role(
        "<section class='testimonial-band'><h2>Voices</h2>"
        "<blockquote>Only one.</blockquote><img src='/a.jpg'><img src='/b.jpg'></section>"
    )

    assert role == "testimonials"
