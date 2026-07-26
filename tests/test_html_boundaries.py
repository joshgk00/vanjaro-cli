"""Focused contracts for static HTML boundary and relationship recovery."""

from __future__ import annotations

from vanjaro_cli.design.html_boundaries import (
    append_missing_video_sections,
    enrich_faq_relationships,
    prepare_static_sections,
    static_boundary_candidates,
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
