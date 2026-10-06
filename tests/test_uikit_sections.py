"""UIkit / YOOtheme page-builder vocabulary: sections, bands, twins, headings (RT-19)."""

from __future__ import annotations

from bs4 import BeautifulSoup

from vanjaro_cli.design.html_adapter import design_document_from_html
from vanjaro_cli.design.html_boundaries import static_boundary_candidates, static_role
from vanjaro_cli.migration.sections import extract_sections, normalize_text_blocks
from vanjaro_cli.migration.uikit import (
    authored_sections,
    is_hidden_at_desktop,
    is_uikit_section,
    normalize_accordions,
)

URL = "https://site.example/"
FILLER = "Plain sentence with enough words to count as body copy for a band. "


def _page(*sections: str, header: str = "") -> str:
    return f"<html><body>{header}<main>{''.join(sections)}</main></body></html>"


def _section(inner: str, classes: str = "uk-section-default") -> str:
    return f'<div class="{classes}"><div class="uk-section"><div class="uk-container">{inner}</div></div></div>'


def _text_section(title: str) -> str:
    return _section(f"<h2>{title}</h2><p>{FILLER * 2}</p>")


def _main(html: str):
    return BeautifulSoup(html, "html.parser").find("main")


def test_section_class_tokens_are_matched_whole() -> None:
    soup = BeautifulSoup(
        '<div class="uk-section"></div><div class="uk-section-primary"></div>'
        '<div class="uk-sectional"></div><div class="my-uk-section"></div>',
        "html.parser",
    )
    assert [is_uikit_section(div) for div in soup.find_all("div")] == [True, True, False, False]


def test_each_section_is_one_boundary_and_the_wrapper_pair_is_not_two() -> None:
    html = _page(_text_section("Alpha"), _text_section("Beta"), _text_section("Gamma"))

    texts = [tag.get_text(" ", strip=True) for tag in static_boundary_candidates(html)]

    assert len(texts) == 3
    assert texts[0].startswith("Alpha") and texts[2].startswith("Gamma")


def test_extraction_reads_the_same_sections_without_merging_them() -> None:
    html = _page(_text_section("Alpha"), _text_section("Beta"), _text_section("Gamma"))

    sections = extract_sections(html, URL)

    assert [section["content"]["headings"] for section in sections] == [["Alpha"], ["Beta"], ["Gamma"]]


def test_a_page_with_one_uikit_section_keeps_the_generic_path() -> None:
    assert authored_sections(_main(_page(_text_section("Only"))), require_page_share=True) == []


def test_content_outside_the_sections_keeps_the_generic_path() -> None:
    loose = f"<div><h2>Loose</h2><p>{FILLER * 20}</p></div>"
    main = _main(_page(_text_section("A"), _text_section("B"), loose))

    assert authored_sections(main, require_page_share=True) == []


def test_desktop_hidden_twin_is_not_a_second_section() -> None:
    twin = _section(f"<h2>Mobile twin</h2><p>{FILLER}</p>", "uk-hidden@m uk-section-primary")
    html = _page(_text_section("Desktop"), twin, _text_section("After"))

    texts = [tag.get_text(" ", strip=True) for tag in static_boundary_candidates(html)]

    assert not any(text.startswith("Mobile twin") for text in texts)
    assert is_hidden_at_desktop(BeautifulSoup(twin, "html.parser").find("div"))


def test_header_chosen_is_the_one_shown_on_a_desktop() -> None:
    mobile = '<header class="uk-hidden@m"><nav><a href="/">Home</a><a href="/m">Menu</a></nav></header>'
    desktop = (
        '<header class="uk-visible@m"><nav><a href="/a">Alpha</a><a href="/b">Beta</a>'
        '<a href="/c">Gamma</a></nav></header>'
    )
    html = _page(_text_section("A"), _text_section("B"), header=mobile + desktop)

    header = static_boundary_candidates(html)[0]

    assert "Alpha" in header.get_text()


def test_a_page_with_only_a_mobile_header_still_has_a_header() -> None:
    mobile = '<header class="uk-hidden@m"><nav><a href="/">Home</a><a href="/m">Menu</a></nav></header>'
    html = _page(_text_section("A"), _text_section("B"), header=mobile)

    assert static_boundary_candidates(html)[0].name == "header"


def _stacked_parts() -> str:
    return _section(
        f"<h2>Reviews</h2><p>{FILLER}</p>"
        f"<h2>Services</h2><p>{FILLER}</p>"
        f"<h2>Questions</h2><p>{FILLER}</p>"
    )


def test_a_section_stacking_headed_parts_is_split_into_them() -> None:
    html = _page(_text_section("Intro"), _stacked_parts())

    sections = extract_sections(html, URL)

    assert [section["content"]["headings"] for section in sections] == [
        ["Intro"], ["Reviews"], ["Services"], ["Questions"],
    ]
    boundaries = [tag.get_text(" ", strip=True) for tag in static_boundary_candidates(html)]
    assert [text.split(" ")[0] for text in boundaries] == ["Intro", "Reviews", "Services", "Questions"]


def test_split_bands_carry_no_id_of_the_section_they_came_from() -> None:
    html = _page(
        _text_section("Intro"),
        _stacked_parts().replace('class="uk-section-default"', 'id="one" class="uk-section-default"'),
    )

    bands = [tag for tag in static_boundary_candidates(html) if "Reviews" in tag.get_text()]

    assert bands and all(band.get("id") is None for band in bands)


def test_columns_of_one_grid_row_are_not_split_into_stacked_sections() -> None:
    columns = (
        '<div class="uk-grid"><div class="uk-width-1-2@m">'
        f"<h2>Left</h2><p>{FILLER}</p></div>"
        f'<div class="uk-width-1-2@m"><h2>Right</h2><p>{FILLER}</p></div></div>'
    )

    sections = extract_sections(_page(_text_section("Intro"), _section(columns)), URL)

    assert len(sections) == 2


def test_repeated_item_headings_are_not_section_parts() -> None:
    cards = "".join(
        f'<div class="uk-grid"><div class="el-item"><h2>Card {n}</h2><p>{FILLER}</p></div></div>'
        for n in range(4)
    )

    sections = extract_sections(_page(_text_section("Intro"), _section(cards)), URL)

    assert len(sections) == 2


def test_a_part_with_no_body_of_its_own_prevents_the_split() -> None:
    thin = _section(f"<h2>Reviews</h2><p>{FILLER}</p><h2>Empty</h2>")

    assert len(extract_sections(_page(_text_section("Intro"), thin), URL)) == 2


def test_a_div_styled_as_a_heading_by_uikit_class_becomes_one() -> None:
    soup = BeautifulSoup('<div class="el-title uk-h3">Card title</div><div class="x">Plain</div>', "html.parser")

    normalize_text_blocks(soup)

    assert [tag.name for tag in soup.find_all(True)] == ["h3", "p"]


def test_the_larger_uikit_style_makes_the_title_and_the_smaller_one_the_kicker() -> None:
    section = _section(
        f'<h2 class="uk-h4">Kicker</h2><h3 class="uk-h1">Big title</h3><p>{FILLER}</p>'
        f'<a href="/x" class="uk-button">Go</a>'
    )
    document = design_document_from_html(_page(_text_section("Intro"), section), URL)

    roles = {e.role: e.value for e in document.pages[0].sections[1].content if e.kind.value == "heading"}

    assert roles["section_title"] == "Big title"
    assert roles["eyebrow"] == "Kicker"


def test_accordion_is_read_as_details_and_the_section_as_a_faq() -> None:
    items = "".join(
        f'<div class="el-item"><a class="uk-accordion-title" href="">Question {n}?</a>'
        f'<div class="uk-accordion-content"><p>Answer {n}.</p></div></div>'
        for n in range(4)
    )
    accordion = f'<div uk-accordion="collapsible: true;">{items}</div>'
    soup = BeautifulSoup(accordion, "html.parser")
    normalize_accordions(soup)
    assert len(soup.find_all("details")) == 4 and len(soup.find_all("summary")) == 4

    sections = extract_sections(_page(_text_section("Intro"), _section(f"<h2>FAQs</h2>{accordion}")), URL)

    assert sections[1]["type"] == "faq"


def test_a_carousel_dot_list_is_not_a_content_list() -> None:
    dots = '<ul class="uk-dotnav"><li></li><li></li></ul>'
    section = BeautifulSoup(f'<div><img src="/a.jpg">{dots}<p>{FILLER}</p></div>', "html.parser").div
    listed = BeautifulSoup('<div><img src="/a.jpg"><ul><li>One</li></ul></div>', "html.parser").div

    assert static_role(section, 3) != "split_feature"
    assert static_role(listed, 3) == "split_feature"


def test_a_row_of_linked_cards_is_not_a_navigation_bar() -> None:
    cards = "".join(f'<a href="/{n}"><img src="/{n}.jpg">Card {n}</a>' for n in range(3))
    links = "".join(f'<a href="/{n}">Link {n}</a>' for n in range(3))

    assert static_role(BeautifulSoup(f"<div>{cards}</div>", "html.parser").div, 3) != "navigation"
    assert static_role(BeautifulSoup(f"<div>{links}</div>", "html.parser").div, 3) == "navigation"
