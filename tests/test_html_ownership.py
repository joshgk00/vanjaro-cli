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
    assert [item["layout_changes"] for item in section["responsive"]] == [
        {"columns": 2},
        {"columns": 1},
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
