"""Contracts for routing header composition through navigation templates."""

from __future__ import annotations

from vanjaro_cli.design.models import (
    ContentElement,
    ContentKind,
    LayoutKind,
    LayoutObservation,
    RepeatGroup,
    RepeatGroupItem,
    RepeatGroupKind,
    Section,
    StyleSet,
)
from vanjaro_cli.portal.global_header_matching import compose_header_block
from vanjaro_cli.utils.grapesjs import render_components


_NAV_LABELS = ("Work", "Services", "About", "Contact")


def _element(
    key: str,
    order: int,
    role: str,
    value: str,
    *,
    group_id: str | None = None,
    href: str | None = None,
) -> ContentElement:
    return ContentElement(
        id=key,
        order=order,
        kind=ContentKind.LINK,
        role=role,
        value=value,
        asset_id=None,
        group_id=group_id,
        attributes={"href": href} if href else {},
        provenance=[],
        confidence=1,
    )


def _navigation_section(*, with_group: bool = True) -> Section:
    content = [_element("brand", 1, "brand", "Northstar", href="/")]
    items: list[RepeatGroupItem] = []
    for index, label in enumerate(_NAV_LABELS, start=1):
        key = f"nav-{index}"
        content.append(
            _element(
                key,
                index,
                "navigation_item",
                label,
                group_id="nav-links" if with_group else None,
                href=f"#{label.casefold()}",
            )
        )
        items.append(RepeatGroupItem(id=f"nav-item-{index}", fields={"label": key}))
    groups = (
        [
            RepeatGroup(
                id="nav-links",
                kind=RepeatGroupKind.NAVIGATION_ITEM,
                items=items,
                provenance=[],
            )
        ]
        if with_group
        else []
    )
    return Section(
        id="home.header",
        order=0,
        semantic_role="navigation",
        role_confidence=1,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.FLEX, contained=True),
        content=content,
        groups=groups,
        style=StyleSet(),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )


def test_matched_navigation_template_composes_the_header() -> None:
    built = compose_header_block(_navigation_section(), {}, brand_text="Northstar")

    assert built["composition_path"] == "template"
    assert built["template_id"].startswith("Navigation/navbar")
    html = render_components(built["components"])
    assert "Northstar" in html
    for label in _NAV_LABELS:
        assert f">{label}<" in html
        assert f'href="#{label.casefold()}"' in html


def test_template_composition_never_ships_template_placeholder_copy() -> None:
    # The navbar template ships six sample links; a four-item source must not
    # leak the two it does not fill.
    html = render_components(
        compose_header_block(_navigation_section(), {}, brand_text="Northstar")["components"]
    )

    assert "Team" not in html
    assert "Home" not in html


def test_unbindable_header_falls_back_to_the_bespoke_composer() -> None:
    # No repeat group means the navbar's required item field cannot bind.
    built = compose_header_block(
        _navigation_section(with_group=False), {}, brand_text="Northstar"
    )

    assert built["composition_path"] == "composer"
    assert built["template_id"] is None
    assert "Northstar" in render_components(built["components"])


def test_an_empty_navigation_catalog_falls_back_to_the_composer() -> None:
    built = compose_header_block(
        _navigation_section(), {}, brand_text="Northstar", catalog=[]
    )

    assert built["composition_path"] == "composer"


def test_matched_header_keeps_the_native_bootstrap_collapse_control() -> None:
    html = render_components(
        compose_header_block(_navigation_section(), {}, brand_text="Northstar")["components"]
    )

    assert 'data-bs-toggle="collapse"' in html
    assert 'aria-label="Toggle navigation"' in html
