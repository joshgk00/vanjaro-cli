"""The project footer keeps the design's columns, band colour, and bottom strip."""

from __future__ import annotations

from datetime import datetime, timezone

from vanjaro_cli.design.models import (
    AssetKind,
    AssetRecord,
    AssetRole,
    BoundingBox,
    ContentElement,
    ContentKind,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    LayoutKind,
    LayoutObservation,
    NavigationVisibility,
    ObservationMethod,
    Page,
    Provenance,
    Section,
    SourceKind,
    StyleObservation,
    StyleProperty,
    StyleSet,
)
from vanjaro_cli.portal.global_blocks import compose_project_global_blocks
from vanjaro_cli.portal.global_footer import footer_builder_content

TEAL = "#103030"
YELLOW = "#fdbb2c"
LONG_BLURB = "We teach music to children of every age and ability. " * 3


def _provenance(bounds: BoundingBox | None) -> list[Provenance]:
    if bounds is None:
        return []
    return [Provenance(source_kind=SourceKind.FIGMA, method=ObservationMethod.API, bounds=bounds)]


def _element(
    key: str,
    order: int,
    kind: ContentKind,
    value: str | None,
    at: tuple[float, float, float, float] | None,
    *,
    size: float | None = 14,
    href: str | None = None,
    asset_id: str | None = None,
) -> ContentElement:
    attributes: dict = {}
    if size is not None:
        attributes["font_size"] = size
    if href is not None:
        attributes["href"] = href
    return ContentElement(
        id=key, order=order, kind=kind, role="body", value=value, asset_id=asset_id,
        attributes=attributes,
        provenance=_provenance(BoundingBox(x=at[0], y=at[1], width=at[2], height=at[3]) if at else None),
        confidence=1,
    )


def _section(
    content: list[ContentElement],
    *,
    bands: list[dict] | None = None,
    style: StyleSet | None = None,
) -> Section:
    return Section(
        id="home.footer", order=0, semantic_role="footer", role_confidence=1,
        candidate_roles=[], layout=LayoutObservation(kind=LayoutKind.FREEFORM, contained=False),
        content=content, groups=[], style=style or StyleSet(), responsive=[],
        decorative_layers=[], interactions=[], provenance=[],
        metadata={"background_bands": bands} if bands else {},
    )


def _bands(bar: bool = True) -> list[dict]:
    bands = [{
        "role": "base", "color": TEAL, "node_id": "1:1",
        "bounds": {"x": 0, "y": 700, "width": 1440, "height": 360},
    }]
    if bar:
        bands.append({
            "role": "bottom_bar", "color": YELLOW, "node_id": "1:2",
            "bounds": {"x": 0, "y": 1060, "width": 1440, "height": 50},
        })
    return bands


def _kts_like_footer(**overrides: object) -> Section:
    """Brand blurb, two link columns, contact lines, and a legal strip."""

    content = [
        _element("blurb", 0, ContentKind.TEXT, LONG_BLURB, (100, 760, 420, 76), size=16),
        _element("cta", 1, ContentKind.BUTTON, "SCHEDULE A CALL", (120, 860, 150, 15), href="/contact", size=16),
        _element("links-title", 2, ContentKind.HEADING, "Quick Links", (700, 760, 130, 19), size=16),
        _element("nav-home", 3, ContentKind.TEXT, "Home", (700, 800, 40, 13)),
        _element("about", 4, ContentKind.BUTTON, "About Us", (700, 828, 60, 13), href="/about"),
        _element("more-title", 5, ContentKind.TEXT, "Other Links", (930, 760, 130, 19), size=16),
        _element("terms", 6, ContentKind.TEXT, "Terms & Conditions", (930, 800, 125, 13)),
        _element("email-label", 7, ContentKind.TEXT, "EMAIL ADDRESS", (1180, 760, 108, 15), size=16),
        _element("email", 8, ContentKind.TEXT, "hello@example.com", (1180, 788, 120, 13)),
        _element("legal", 9, ContentKind.TEXT, "All rights reserved", (600, 1075, 160, 22), size=18),
    ]
    return _section(content, bands=_bands(), **overrides)


def _entries(column: dict) -> list[tuple[str, str]]:
    return [(entry["kind"], entry.get("text", "")) for entry in column["entries"]]


def _walk(value: object) -> list[dict]:
    found: list[dict] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.get("components", []):
            found.extend(_walk(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk(child))
    return found


def _classes(component: dict) -> list[str]:
    return [item["name"] for item in component.get("classes", [])]


def _compose(section: Section, assets: list[AssetRecord] | None = None) -> dict:
    document = DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.FIGMA, identifier="figma-file",
            captured_at=datetime(2026, 10, 6, tzinfo=timezone.utc), adapter_version="test",
        ),
        tokens=DesignTokens(), assets=assets or [],
        pages=[Page(
            id="home", source_reference="frame", title="Home", slug="home", sections=[section],
            breakpoints=[], navigation_visibility=NavigationVisibility.VISIBLE, provenance=[],
        )],
        warnings=[], analysis=DesignAnalysis(section_confidence_mean=1, unsupported_traits=[]),
    )
    plan = {"entries": [{
        "id": "global-footer", "kind": "footer", "status": "ready",
        "source_section_id": section.id, "name": "project / Site Footer",
        "category": "Agency - project",
    }]}
    return compose_project_global_blocks(document, plan, project_id="project")[0]


# -- columns --


def test_elements_are_grouped_into_columns_by_where_they_sit():
    content = footer_builder_content(_kts_like_footer(), {})

    assert [_entries(column) for column in content["columns"]] == [
        [("paragraph", LONG_BLURB.strip()), ("link", "SCHEDULE A CALL")],
        [("heading", "Quick Links"), ("text", "Home"), ("link", "About Us")],
        [("heading", "Other Links"), ("text", "Terms & Conditions")],
        [("heading", "EMAIL ADDRESS"), ("text", "hello@example.com")],
    ]


def test_a_short_line_set_larger_than_its_column_body_is_a_heading():
    content = footer_builder_content(_kts_like_footer(), {})

    kinds = {entry["text"]: entry["kind"] for column in content["columns"] for entry in column["entries"]}

    assert kinds["Other Links"] == "heading"
    assert kinds["EMAIL ADDRESS"] == "heading"
    assert kinds["Terms & Conditions"] == "text"


def test_a_lone_larger_line_in_a_column_with_no_body_text_stays_text():
    section = _section([_element("only", 0, ContentKind.TEXT, "Call us", (100, 100, 80, 15), size=16)])

    content = footer_builder_content(section, {})

    assert _entries(content["columns"][0]) == [("text", "Call us")]


def test_a_link_keeps_its_destination_and_an_unsafe_one_becomes_text():
    section = _section([
        _element("ok", 0, ContentKind.LINK, "Contact", (100, 100, 80, 14), href="/contact"),
        _element("bad", 1, ContentKind.LINK, "Run", (100, 130, 80, 14), href="javascript:alert(1)"),
        _element("none", 2, ContentKind.BUTTON, "Soon", (100, 160, 80, 14)),
    ])

    entries = footer_builder_content(section, {})["columns"][0]["entries"]

    assert entries[0] == {"kind": "link", "text": "Contact", "href": "/contact"}
    assert entries[1] == {"kind": "text", "text": "Run"}
    assert entries[2] == {"kind": "text", "text": "Soon"}


def test_multi_line_text_is_collapsed_to_one_line():
    section = _section([_element("address", 0, ContentKind.TEXT, "12 Main St\nSpringfield", (100, 100, 150, 30))])

    entries = footer_builder_content(section, {})["columns"][0]["entries"]

    assert entries == [{"kind": "text", "text": "12 Main St Springfield"}]


def test_an_image_in_a_column_is_kept_with_its_alt_text():
    logo = AssetRecord(
        id="logo", kind=AssetKind.IMAGE, role=AssetRole.EDITORIAL,
        source_url="/Portals/2/logo.png", alt_text="Studio logo", provenance=[],
    )
    section = _section([
        _element("logo-el", 0, ContentKind.IMAGE, None, (100, 100, 160, 130), size=None, asset_id="logo"),
        _element("blurb", 1, ContentKind.TEXT, "Music for everyone", (100, 250, 160, 20)),
    ])

    entries = footer_builder_content(section, {"logo": logo})["columns"][0]["entries"]

    assert entries[0] == {"kind": "image", "src": "/Portals/2/logo.png", "alt": "Studio logo"}


def test_without_positions_the_footer_falls_back_to_one_flat_list():
    section = _section([
        _element("a", 0, ContentKind.HEADING, "Links", None),
        _element("b", 1, ContentKind.TEXT, "Home", None),
    ])

    content = footer_builder_content(section, {})

    assert "columns" not in content
    assert content["headings"] == ["Links"]
    assert content["list_items"] == ["Home"]


# -- colours and strip --


def test_the_base_band_colour_and_the_bottom_bar_come_from_the_design():
    content = footer_builder_content(_kts_like_footer(), {})

    assert content["background_color"] == TEAL
    assert content["bottom_bar"] == {
        "background_color": YELLOW,
        "entries": [{"kind": "text", "text": "All rights reserved"}],
    }
    legal = [e["text"] for column in content["columns"] for e in column["entries"]]
    assert "All rights reserved" not in legal


def test_with_no_bottom_bar_everything_stays_in_the_columns():
    section = _section(
        [_element("legal", 0, ContentKind.TEXT, "All rights reserved", (600, 1075, 160, 22))],
        bands=_bands(bar=False),
    )

    content = footer_builder_content(section, {})

    assert "bottom_bar" not in content
    assert _entries(content["columns"][0]) == [("text", "All rights reserved")]


def test_a_source_style_background_is_used_when_no_band_was_recorded():
    style = StyleSet(observations=[
        StyleObservation(property=StyleProperty.BACKGROUND_COLOR, value="rgb(16, 48, 48)"),
    ])
    section = _section([_element("a", 0, ContentKind.TEXT, "Home", (100, 100, 40, 14))], style=style)

    assert footer_builder_content(section, {})["background_color"] == "#103030"


def test_a_transparent_source_background_is_ignored():
    style = StyleSet(observations=[
        StyleObservation(property=StyleProperty.BACKGROUND_COLOR, value="rgba(0, 0, 0, 0)"),
    ])
    section = _section([_element("a", 0, ContentKind.TEXT, "Home", (100, 100, 40, 14))], style=style)

    assert "background_color" not in footer_builder_content(section, {})


# -- the composed global block --


def test_the_composed_footer_has_four_columns_a_teal_band_and_a_yellow_strip():
    block = _compose(_kts_like_footer())

    nodes = _walk(block["components"])
    columns = [node for node in nodes if node.get("type") == "column"]
    sections = [node for node in nodes if node.get("type") == "section"]
    styles = [node["attributes"].get("style", "") for node in sections]

    assert len(sections) == 2
    assert len([c for c in columns if "col-md-3" in _classes(c)]) == 4
    assert f"background-color:{TEAL}" in styles[0]
    assert f"background-color:{YELLOW}" in styles[1]
    assert "bg-light" not in block["html"]
    assert "All rights reserved" in block["html"]


def test_text_on_a_dark_band_is_forced_light_and_the_light_strip_is_not():
    block = _compose(_kts_like_footer())

    main, strip = [node for node in _walk(block["components"]) if node.get("type") == "section"]
    main_text = [n for n in _walk(main) if n.get("type") in {"heading", "text", "link"}]
    strip_text = [n for n in _walk(strip) if n.get("type") in {"heading", "text", "link"}]

    assert main_text and all("text-white" in _classes(n) for n in main_text)
    assert strip_text and not any("text-white" in _classes(n) for n in strip_text)


def test_the_composed_footer_links_keep_their_destinations():
    block = _compose(_kts_like_footer())

    hrefs = {
        node["content"]: node["attributes"]["href"]
        for node in _walk(block["components"]) if node.get("type") == "link"
    }

    assert hrefs == {"SCHEDULE A CALL": "/contact", "About Us": "/about"}


def test_a_footer_without_a_band_keeps_the_light_fallback_class():
    section = _section([_element("a", 0, ContentKind.TEXT, "Home", (100, 100, 40, 14))])

    block = _compose(section)

    assert "bg-light" in block["html"]
    assert "text-white" not in block["html"]


def test_composing_the_same_footer_twice_is_identical():
    assert _compose(_kts_like_footer()) == _compose(_kts_like_footer())
