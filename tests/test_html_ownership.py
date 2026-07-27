"""Focused contracts for static HTML semantic ownership recovery."""

from __future__ import annotations

from vanjaro_cli.design.html_ownership import enrich_section_from_static_dom
from vanjaro_cli.design.html_primitives import register_asset


def _provenance() -> dict:
    return {
        "source_kind": "live_html",
        "method": "static",
        "source_url": "https://agency.example/",
        "css_selector": "#services",
    }


def _section_from_html(static_html: str, *, role: str) -> dict:
    section = {
        "id": f"home.section.{role}",
        "semantic_role": role,
        "layout": {},
        "content": [],
        "groups": [],
        "responsive": [],
    }
    enrich_section_from_static_dom(
        section,
        static_html,
        source_url="https://agency.example/",
        assets={},
        provenance=_provenance(),
    )
    return section


def _responsive_changes(section: dict, breakpoint: str) -> dict:
    for entry in section["responsive"]:
        if entry["breakpoint"] == breakpoint:
            return entry["layout_changes"]
    return {}


def test_card_ownership_preserves_item_fields_assets_and_responsive_evidence() -> None:
    static_html = """
    <section id='services'>
      <h2>Services</h2>
      <article><img src='/one.jpg' alt='One'><h3>Strategy</h3><p>Plan the work.</p></article>
      <article><img src='/two.jpg' alt='Two'><h3>Design</h3><p>Shape the experience.</p></article>
      <article><img src='/three.jpg' alt='Three'><h3>Build</h3><p>Ship the site.</p></article>
    </section>
    """
    section = {
        "id": "home.section.2",
        "semantic_role": "feature_cards",
        "layout": {},
        "content": [],
        "groups": [],
        "responsive": [],
    }
    assets: dict = {}

    enrich_section_from_static_dom(
        section,
        static_html,
        source_url="https://agency.example/",
        assets=assets,
        provenance=_provenance(),
    )

    group = section["groups"][0]
    assert group["kind"] == "card"
    assert len(group["items"]) == 3
    assert all(set(item["fields"]) == {"media", "title", "body"} for item in group["items"])
    assert len(assets) == 3
    assert section["layout"] == {
        "kind": "grid",
        "contained": True,
        "columns": 3,
        "media_position": "top",
        "alignment": "left",
        "full_bleed": False,
    }
    assert [item["breakpoint"] for item in section["responsive"]] == ["tablet", "mobile"]
    # Column collapse is structural; alignment is derived independently from
    # utility classes, so mobile carries both (VF-203).
    assert [item["layout_changes"] for item in section["responsive"]] == [
        {"columns": 2},
        {"columns": 1, "alignment": "left"},
    ]


def test_navigation_ownership_keeps_link_labels_and_destinations() -> None:
    section = {
        "id": "home.section.1",
        "semantic_role": "navigation",
        "layout": {},
        "content": [],
        "groups": [],
        "responsive": [],
    }

    enrich_section_from_static_dom(
        section,
        """<header><a class='brand' href='/'>Agency</a><nav>
          <a href='/work'>Work</a><a href='/contact'>Contact</a>
        </nav></header>""",
        source_url="https://agency.example/",
        assets={},
        provenance=_provenance(),
    )

    values = {element["role"]: element for element in section["content"] if element["role"] == "brand"}
    assert values["brand"]["value"] == "Agency"
    group = section["groups"][0]
    labels = {
        element["value"]: element["attributes"]["href"]
        for element in section["content"]
        if element["role"] == "navigation_item"
    }
    assert labels == {"Work": "/work", "Contact": "/contact"}
    assert len(group["items"]) == 2
    assert section["layout"]["kind"] == "flex"


def test_asset_registration_is_deterministic_and_enriches_existing_record() -> None:
    assets: dict = {}
    first = register_asset(assets, source_url="https://agency.example/image.jpg")
    second = register_asset(
        assets,
        source_url="https://agency.example/image.jpg",
        alt_text="Editorial image",
        provenance=[_provenance()],
    )

    assert first == second
    assert len(assets) == 1
    assert assets[first]["alt_text"] == "Editorial image"
    assert assets[first]["provenance"] == [_provenance()]


def test_centering_utility_class_yields_center_alignment() -> None:
    section = _section_from_html(
        '<section class="container text-center"><h2>Ready?</h2>'
        '<a class="btn btn-dark" href="/contact">Start</a></section>',
        role="contact",
    )

    assert _responsive_changes(section, "mobile")["alignment"] == "center"


def test_absent_centering_utility_yields_left_alignment() -> None:
    section = _section_from_html(
        '<section class="container"><h2>Start a conversation</h2>'
        "<p>Share your timeline.</p></section>",
        role="contact",
    )

    # Absence of a centering utility is evidence, not missing evidence: the
    # section inherits the document default.
    assert _responsive_changes(section, "mobile")["alignment"] == "left"


def test_styled_button_yields_full_width_action_on_mobile() -> None:
    section = _section_from_html(
        '<section class="container"><h2>Ready?</h2>'
        '<a class="btn btn-primary" href="/x">Go</a></section>',
        role="rich_text",
    )

    assert _responsive_changes(section, "mobile")["button_width"] == "100%"


def test_bare_anchor_in_a_cta_section_counts_as_an_action() -> None:
    section = _section_from_html(
        '<div id="cta-module"><h2>Bring calm.</h2>'
        '<a href="/contact">Book an introduction</a></div>',
        role="cta",
    )

    assert _responsive_changes(section, "mobile")["button_width"] == "100%"


def test_section_without_any_action_omits_button_width() -> None:
    section = _section_from_html(
        '<section class="container"><h2>About</h2><p>Copy.</p></section>',
        role="rich_text",
    )

    assert "button_width" not in _responsive_changes(section, "mobile")


def test_navigation_keeps_its_collapse_rule_without_alignment() -> None:
    section = _section_from_html(
        '<header class="navbar navbar-expand-lg"><a class="navbar-brand" href="/">B</a>'
        '<nav><a href="#a">A</a></nav></header>',
        role="navigation",
    )
    changes = _responsive_changes(section, "mobile")

    assert changes["navigation"] == "collapsed"
    assert "alignment" not in changes
