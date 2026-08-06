"""Focused tests for the agency-project responsive global header."""

from __future__ import annotations

from datetime import datetime, timezone

from vanjaro_cli.design.models import (
    AssetKind,
    AssetRecord,
    AssetRole,
    ContentElement,
    ContentKind,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    LayoutKind,
    LayoutObservation,
    NavigationVisibility,
    Page,
    Section,
    SourceKind,
    StyleSet,
)
from vanjaro_cli.portal.global_blocks import compose_project_global_blocks
from vanjaro_cli.portal.global_header import build_project_header


def _element(
    key: str,
    order: int,
    kind: ContentKind,
    value: str | None,
    *,
    role: str = "body",
    asset_id: str | None = None,
    attributes: dict | None = None,
) -> ContentElement:
    return ContentElement(
        id=key,
        order=order,
        kind=kind,
        role=role,
        value=value,
        asset_id=asset_id,
        attributes=attributes or {},
        provenance=[],
        confidence=1,
    )


def _section(content: list[ContentElement]) -> Section:
    return Section(
        id="home.header",
        order=0,
        semantic_role="navigation",
        role_confidence=1,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.FLEX, contained=True),
        content=content,
        groups=[],
        style=StyleSet(),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )


def _asset(key: str, source: str, *, alt: str = "") -> AssetRecord:
    return AssetRecord(
        id=key,
        kind=AssetKind.IMAGE,
        role=AssetRole.EDITORIAL,
        source_url=source,
        alt_text=alt,
        provenance=[],
    )


def _document(section: Section, assets: list[AssetRecord]) -> DesignDocument:
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.FIGMA,
            identifier="figma-file",
            captured_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
            adapter_version="test",
        ),
        tokens=DesignTokens(),
        assets=assets,
        pages=[
            Page(
                id="home",
                source_reference="figma-frame",
                title="Home",
                slug="home",
                sections=[section],
                breakpoints=[],
                navigation_visibility=NavigationVisibility.VISIBLE,
                provenance=[],
            )
        ],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1, unsupported_traits=[]),
    )


def _walk(value: object) -> list[dict]:
    result: list[dict] = []
    if isinstance(value, dict):
        result.append(value)
        for child in value.get("components", []):
            result.extend(_walk(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(_walk(child))
    return result


def _class_names(component: dict) -> list[str]:
    return [
        item["name"] if isinstance(item, dict) else item
        for item in component.get("classes", [])
    ]


def test_header_preserves_explicit_logo_and_observed_desktop_labels() -> None:
    logo = _asset("logo", "/Portals/2/logo.svg", alt="Keys to Success logo")
    section = _section(
        [
            _element(
                "logo-element",
                0,
                ContentKind.IMAGE,
                None,
                role="site_logo",
                asset_id=logo.id,
                attributes={"href": "/", "alt": "Designer logo"},
            ),
            _element(
                "home",
                1,
                ContentKind.LINK,
                "Home",
                attributes={"href": "/home"},
            ),
            _element("studio", 2, ContentKind.TEXT, "The Studio"),
            _element(
                "contact",
                3,
                ContentKind.BUTTON,
                "Contact Us",
                role="primary_action",
                attributes={"href": "/contact"},
            ),
        ]
    )

    built = build_project_header(section, {logo.id: logo}, brand_text="Keys to Success")
    nodes = _walk(built["components"])

    image = next(node for node in nodes if node.get("type") == "image")
    assert image["attributes"]["src"] == "/Portals/2/logo.svg"
    assert image["attributes"]["alt"] == "Designer logo"
    brand = next(node for node in nodes if node["attributes"].get("id") == "agency-header-brand")
    assert brand["tagName"] == "a"
    assert brand["attributes"]["href"] == "/"
    assert [node.get("content") for node in nodes if node.get("content")] == [
        "Home",
        "The Studio",
        "Contact Us",
    ]
    assert built["warnings"] == []


def test_header_ignores_unrelated_raster_and_uses_accessible_brand_text() -> None:
    photo = _asset("photo", "/Portals/2/studio.jpg", alt="Student at a piano")
    section = _section(
        [
            _element(
                "editorial-photo",
                0,
                ContentKind.IMAGE,
                None,
                role="editorial_media",
                asset_id=photo.id,
            ),
            _element("home", 1, ContentKind.TEXT, "Home"),
        ]
    )

    built = build_project_header(section, {photo.id: photo}, brand_text="Keys to Success")
    nodes = _walk(built["components"])

    assert not any(node.get("type") == "image" for node in nodes)
    brand_text = next(
        node for node in nodes if node["attributes"].get("id") == "agency-header-brand-text"
    )
    assert brand_text["content"] == "Keys to Success"
    assert "no explicit usable logo asset" in built["warnings"][0]


def test_unavailable_explicit_figma_logo_reports_reason_and_falls_back() -> None:
    unresolved_logo = AssetRecord(
        id="figma-logo",
        kind=AssetKind.SVG,
        role=AssetRole.DECORATIVE,
        missing_reason="Vector export URL was not supplied",
        alt_text="Keys to Success logo",
        provenance=[],
    )
    section = _section(
        [
            _element(
                "logo-element",
                0,
                ContentKind.IMAGE,
                None,
                role="site_logo",
                asset_id=unresolved_logo.id,
            )
        ]
    )

    built = build_project_header(
        section,
        {unresolved_logo.id: unresolved_logo},
        brand_text="Keys to Success",
    )
    nodes = _walk(built["components"])

    assert not any(node.get("type") == "image" for node in nodes)
    assert "Vector export URL was not supplied" in built["warnings"][0]
    assert "Keys to Success" in built["warnings"][0]


def test_header_has_standard_mobile_collapse_and_never_fabricates_hrefs() -> None:
    section = _section(
        [
            _element("home", 0, ContentKind.TEXT, "Home"),
            _element(
                "register",
                1,
                ContentKind.BUTTON,
                "Register Now!",
                role="primary_action",
            ),
            _element(
                "contact",
                2,
                ContentKind.BUTTON,
                "Contact Us",
                role="primary_action",
                attributes={"href": "/contact"},
            ),
        ]
    )

    built = build_project_header(section, {}, brand_text="Keys to Success")
    nodes = _walk(built["components"])
    navbar = next(node for node in nodes if "navbar" in _class_names(node))
    toggler = next(node for node in nodes if "navbar-toggler" in _class_names(node))
    collapse = next(node for node in nodes if "navbar-collapse" in _class_names(node))
    unresolved = next(node for node in nodes if node.get("content") == "Register Now!")
    contact = next(node for node in nodes if node.get("content") == "Contact Us")

    assert "navbar-expand-lg" in _class_names(navbar)
    assert "navbar-light" in _class_names(navbar)
    assert "flex-lg-nowrap" in _class_names(navbar)
    assert toggler["tagName"] == "button"
    assert toggler["attributes"]["data-bs-toggle"] == "collapse"
    assert toggler["attributes"]["data-bs-target"] == f"#{collapse['attributes']['id']}"
    assert toggler["attributes"]["aria-controls"] == collapse["attributes"]["id"]
    assert unresolved["tagName"] == "span"
    assert unresolved["attributes"]["data-agency-missing-url"] == "true"
    assert "href" not in unresolved["attributes"]
    assert contact["attributes"]["href"] == "/contact"
    assert any("1 header action(s)" in warning for warning in built["warnings"])


def test_header_honors_observed_href_even_when_adapter_classified_label_as_text() -> None:
    section = _section(
        [
            _element(
                "studio",
                0,
                ContentKind.TEXT,
                "The Studio",
                attributes={"href": "/studio"},
            )
        ]
    )

    built = build_project_header(section, {}, brand_text="Keys to Success")
    label = next(
        node for node in _walk(built["components"])
        if node.get("content") == "The Studio"
    )

    assert label["type"] == "link"
    assert label["tagName"] == "a"
    assert label["attributes"]["href"] == "/studio"


def test_integrated_header_output_is_deterministic_and_rewrites_collapse_ids() -> None:
    section = _section(
        [
            _element("home-link", 0, ContentKind.LINK, "Home", attributes={"href": "/"}),
        ]
    )
    document = _document(section, [])
    plan = {
        "entries": [
            {
                "id": "global-header",
                "kind": "header",
                "status": "ready",
                "source_section_id": section.id,
                "name": "project / Site Header",
                "category": "Agency - project",
            }
        ]
    }

    first = compose_project_global_blocks(
        document, plan, project_id="keys-to-success-agency-project"
    )
    second = compose_project_global_blocks(
        document, plan, project_id="keys-to-success-agency-project"
    )
    nodes = _walk(first[0]["components"])
    toggler = next(node for node in nodes if "navbar-toggler" in _class_names(node))
    collapse = next(node for node in nodes if "navbar-collapse" in _class_names(node))

    assert first == second
    assert first[0]["html"] == second[0]["html"]
    assert toggler["attributes"]["data-bs-target"] == f"#{collapse['attributes']['id']}"
    assert toggler["attributes"]["aria-controls"] == collapse["attributes"]["id"]
    assert "Keys To Success" in first[0]["html"]
    assert "no explicit usable logo asset" in first[0]["warnings"][0]


def test_a_global_block_carries_the_design_section_id_not_the_block_key() -> None:
    """`data-agency-section` is how the measurer pairs a rendered element with
    the section the design described. Stamping the block key made the nav
    unpairable, so a correctly rendering nav read as absent and scored zero."""

    section = _section(
        [_element("home-link", 0, ContentKind.LINK, "Home", attributes={"href": "/"})]
    )
    document = _document(section, [])
    plan = {
        "entries": [
            {
                "id": "global-header",
                "kind": "header",
                "status": "ready",
                "source_section_id": section.id,
                "name": "project / Site Header",
                "category": "Agency - project",
            }
        ]
    }

    built = compose_project_global_blocks(document, plan, project_id="project")
    markers = {
        node.get("attributes", {}).get("data-agency-section")
        for node in _walk(built[0]["components"])
    }
    pages = {
        node.get("attributes", {}).get("data-agency-page")
        for node in _walk(built[0]["components"])
    }

    assert markers == {section.id}
    assert "global-header" not in markers
    # The block key still records where the section lives.
    assert pages == {"global:global-header"}
