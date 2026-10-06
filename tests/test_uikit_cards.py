"""Card extraction for UIkit markup: wrapped buttons, untitled linked cards, logo strips (RT-19)."""

from __future__ import annotations

from vanjaro_cli.design.html_adapter import design_document_from_html

URL = "https://site.example/"
INTRO = '<div class="uk-section-default"><div class="uk-section"><h2>Intro</h2><p>Some words here.</p></div></div>'


def _document(section_body: str):
    html = (
        f"<html><body><main>{INTRO}"
        f'<div class="uk-section-default"><div class="uk-section"><div class="uk-container">'
        f"{section_body}</div></div></div></main></body></html>"
    )
    return design_document_from_html(html, URL).pages[0].sections[1]


def _values(section, kind: str, role: str | None = None) -> list[str]:
    return [
        e.value for e in section.content
        if e.kind.value == kind and (role is None or e.role == role) and e.value
    ]


def _service_cards() -> str:
    cell = (
        '<div><div class="el-item"><a class="uk-panel" href="/s/{n}"><img src="/i/{n}.jpg" alt="">'
        '<h3 class="el-title">Service {n}</h3><div class="el-content"><p>About service {n}.</p></div>'
        '<div class="el-link uk-button uk-button-text">View Service</div></a></div></div>'
    )
    return '<div class="uk-grid">' + "".join(cell.format(n=n) for n in range(3)) + "</div>"


def test_a_button_drawn_inside_a_card_link_is_the_cards_action_with_the_links_destination() -> None:
    section = _document(_service_cards())

    actions = [e for e in section.content if e.role == "primary_action"]

    assert [(a.value, a.attributes["href"]) for a in actions] == [
        ("View Service", "/s/0"), ("View Service", "/s/1"), ("View Service", "/s/2"),
    ]


def test_the_button_label_is_not_also_body_copy() -> None:
    section = _document(_service_cards())

    assert "View Service" not in _values(section, "text")
    assert _values(section, "text", "card_body") == [f"About service {n}." for n in range(3)]


def test_a_linked_card_with_no_heading_takes_its_first_line_as_title_and_links_through() -> None:
    cell = (
        '<div><a href="/go/{n}"><img src="/i/{n}.jpg" alt=""><div class="uk-panel">'
        "<p>Title {n}</p><p>Detail {n}</p></div></a></div>"
    )
    section = _document('<div class="uk-grid">' + "".join(cell.format(n=n) for n in range(3)) + "</div>")

    item = section.groups[0].items[0]

    assert {"title", "media", "body", "action"} <= set(item.fields)
    assert _values(section, "heading", "card_title") == ["Title 0", "Title 1", "Title 2"]
    assert [e.attributes["href"] for e in section.content if e.role == "primary_action"] == [
        "/go/0", "/go/1", "/go/2",
    ]


def test_a_logo_strip_below_the_cards_does_not_become_more_cards() -> None:
    cards = "".join(
        f'<div><div class="el-item"><img src="/c/{n}.svg" alt=""><h3>Reason {n}</h3><p>Because {n}.</p></div></div>'
        for n in range(3)
    )
    logos = "".join(
        f'<div><div class="el-item"><a href="/l"><img src="/l/{n}.png" alt=""></a></div></div>' for n in range(7)
    )
    section = _document(f'<div class="uk-grid">{cards}</div><div class="uk-grid">{logos}</div>')

    assert len(section.groups[0].items) == 3
    assert all("title" in item.fields for item in section.groups[0].items)
