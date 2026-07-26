"""Maintainable Bootstrap/Vanjaro header composition for agency projects.

The project pipeline needs to preserve designer-owned labels and branding even
when the source does not provide working destinations yet.  This builder uses
only normal GrapesJS components and Bootstrap 5 navbar utilities: links are
created only for observed ``href`` values, while unresolved actions remain
visible, editable text with an explicit ownership marker.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from vanjaro_cli.design.models import AssetRecord, ContentElement, ContentKind, Section


_LOGO_TERMS = ("logo", "brand")
HEADER_COMPOSER_CONTRACT_VERSION = "1.1"


def build_project_header(
    section: Section,
    assets: Mapping[str, AssetRecord],
    *,
    brand_text: str,
) -> dict[str, Any]:
    """Compose a responsive, source-faithful project header.

    Bootstrap owns the responsive behavior.  No project CSS or copied source
    scripts are required, which keeps the result portable between Vanjaro
    portals and editable through normal GrapesJS components.
    """

    brand_text = brand_text.strip()
    if not brand_text:
        raise ValueError("project header requires non-empty accessible brand text")
    logo, logo_warning = _logo(section, assets, brand_text)
    nav_items, unresolved = _navigation_items(section)
    collapse_id = "agency-header-collapse"

    navbar_children: list[dict[str, Any]] = []
    if logo is not None:
        navbar_children.append(logo)
    else:
        navbar_children.append(_brand_text_component(brand_text))
    navbar_children.extend(
        [
            _component(
                "default",
                tag_name="button",
                classes=["navbar-toggler"],
                attributes={
                    "id": "agency-header-toggler",
                    "type": "button",
                    "data-bs-toggle": "collapse",
                    "data-bs-target": f"#{collapse_id}",
                    "aria-controls": collapse_id,
                    "aria-expanded": "false",
                    "aria-label": "Toggle navigation",
                },
                children=[
                    _component(
                        "default",
                        tag_name="span",
                        classes=["navbar-toggler-icon"],
                        attributes={"id": "agency-header-toggler-icon"},
                    )
                ],
            ),
            _component(
                "default",
                classes=[
                    "collapse",
                    "navbar-collapse",
                    "justify-content-lg-end",
                ],
                attributes={"id": collapse_id},
                children=[
                    _component(
                        "default",
                        tag_name="ul",
                        classes=[
                            "navbar-nav",
                            "align-items-lg-center",
                            "flex-lg-nowrap",
                            "gap-lg-2",
                            "small",
                        ],
                        attributes={"id": "agency-header-nav"},
                        children=nav_items,
                    )
                ],
            ),
        ]
    )

    root = _component(
        "section",
        classes=["vj-section", "py-2"],
        attributes={"id": "agency-header-section"},
        children=[
            _component(
                "grid",
                classes=["container"],
                attributes={"id": "agency-header-container"},
                children=[
                    _component(
                        "default",
                        tag_name="nav",
                        classes=[
                            "navbar",
                            "navbar-light",
                            "navbar-expand-lg",
                            "flex-lg-nowrap",
                            "w-100",
                            "p-0",
                        ],
                        attributes={
                            "id": "agency-header-navbar",
                            "aria-label": "Primary navigation",
                        },
                        children=navbar_children,
                    )
                ],
            )
        ],
    )
    warnings: list[str] = []
    if logo_warning:
        warnings.append(f"{logo_warning}; rendered accessible brand text {brand_text!r}")
    elif logo is None:
        unavailable = _unavailable_decorative_summary(section, assets)
        context = f"; {unavailable}" if unavailable else ""
        warnings.append(
            f"header had no explicit usable logo asset{context}; rendered accessible "
            f"brand text {brand_text!r}"
        )
    if unresolved:
        warnings.append(
            f"{unresolved} header action(s) had no source URL and were "
            "rendered as non-link text"
        )
    return {"components": [root], "styles": [], "warnings": warnings}


def _logo(
    section: Section,
    assets: Mapping[str, AssetRecord],
    brand_text: str,
) -> tuple[dict[str, Any] | None, str | None]:
    image_elements = [
        element
        for element in sorted(section.content, key=lambda value: (value.order, value.id))
        if (
            element.kind == ContentKind.IMAGE
            and element.asset_id
            and _is_logo_element(element)
        )
    ]
    for element in image_elements:
        asset = assets.get(str(element.asset_id))
        if asset is None:
            continue
        src = _asset_source(asset)
        if not src:
            if _is_logo_element(element):
                return None, _missing_logo_warning(asset)
            continue
        return _logo_component(
            src,
            _asset_alt(element, asset) or brand_text,
            _href(element),
        ), None

    # Some adapters retain a flattened logo as a decorative asset.  Only use
    # it when the source explicitly calls it a logo/brand; arbitrary decorative
    # vectors must never be promoted into site branding.
    for layer in sorted(section.decorative_layers, key=lambda value: (value.order, value.id)):
        if not layer.asset_id:
            continue
        asset = assets.get(layer.asset_id)
        if asset is None or not _is_logo_asset(asset, layer.id, layer.kind):
            continue
        src = _asset_source(asset)
        if not src:
            return None, _missing_logo_warning(asset)
        return _logo_component(src, asset.alt_text or brand_text, None), None
    return None, None


def _logo_component(src: str, alt: str, href: str | None) -> dict[str, Any]:
    image = _component(
        "image",
        classes=["vj-image", "img-fluid", "header-logo"],
        attributes={"id": "agency-header-logo", "src": src, "alt": alt},
    )
    if href:
        return _component(
            "link",
            tag_name="a",
            classes=["navbar-brand", "me-2", "flex-shrink-0"],
            attributes={"id": "agency-header-brand", "href": href},
            children=[image],
        )
    return _component(
        "default",
        classes=["navbar-brand", "me-2", "flex-shrink-0"],
        attributes={"id": "agency-header-brand"},
        children=[image],
    )


def _brand_text_component(text: str) -> dict[str, Any]:
    return _component(
        "default",
        classes=["navbar-brand", "me-2", "flex-shrink-0"],
        attributes={"id": "agency-header-brand"},
        children=[
            _component(
                "text",
                tag_name="span",
                content=text,
                classes=[
                    "vj-text",
                    "paragraph-style-1",
                    "fw-semibold",
                ],
                attributes={"id": "agency-header-brand-text"},
            )
        ],
    )


def _navigation_items(section: Section) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    unresolved = 0
    for element in sorted(section.content, key=lambda value: (value.order, value.id)):
        if element.kind == ContentKind.IMAGE:
            continue
        text = _element_text(element)
        if not text:
            continue
        href = _href(element)
        is_action = element.kind == ContentKind.BUTTON or "action" in element.role.casefold()
        item_classes = ["nav-item"]
        child_classes = ["nav-link", "text-nowrap"]
        if is_action and href:
            child_classes = [
                "btn", "btn-sm", "btn-primary", "button-style-1",
                "text-nowrap", "ms-lg-1",
            ]

        child_attributes: dict[str, Any] = {
            "id": f"agency-header-label-{len(items) + 1}",
        }
        is_link_candidate = element.kind in {ContentKind.BUTTON, ContentKind.LINK} or is_action
        if href:
            child_attributes["href"] = href
            target = element.attributes.get("target")
            if isinstance(target, str) and target.strip():
                child_attributes["target"] = target.strip()
            child = _component(
                "link",
                tag_name="a",
                content=text,
                classes=child_classes,
                attributes=child_attributes,
            )
        else:
            if is_action:
                child_classes = [
                    "btn",
                    "btn-sm",
                    "btn-primary",
                    "button-style-1",
                    "text-nowrap",
                    "ms-lg-1",
                    "disabled",
                ]
                child_attributes["aria-disabled"] = "true"
            if is_link_candidate:
                unresolved += 1
                child_attributes["data-agency-missing-url"] = "true"
            child = _component(
                "default",
                tag_name="span",
                content=text,
                classes=child_classes,
                attributes=child_attributes,
            )
        items.append(
            _component(
                "default",
                tag_name="li",
                classes=item_classes,
                attributes={"id": f"agency-header-item-{len(items) + 1}"},
                children=[child],
            )
        )
    return items, unresolved


def _component(
    component_type: str,
    *,
    classes: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
    content: str | None = None,
    children: list[dict[str, Any]] | None = None,
    tag_name: str | None = None,
) -> dict[str, Any]:
    component: dict[str, Any] = {
        "type": component_type,
        "attributes": dict(attributes or {}),
    }
    if classes:
        component["classes"] = [
            {"name": name, "active": False}
            for name in classes
        ]
    if tag_name:
        component["tagName"] = tag_name
    if content is not None:
        component["content"] = content
    if children is not None:
        component["components"] = children
    return component


def _asset_source(asset: AssetRecord) -> str | None:
    for value in (asset.source_url, asset.local_path):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _missing_logo_warning(asset: AssetRecord) -> str:
    reason = f": {asset.missing_reason}" if asset.missing_reason else ""
    return f"header logo asset {asset.id!r} has no usable source{reason}"


def _asset_alt(element: ContentElement, asset: AssetRecord) -> str:
    value = element.attributes.get("alt")
    if isinstance(value, str):
        return value.strip()
    return (asset.alt_text or "").strip()


def _href(element: ContentElement) -> str | None:
    value = element.attributes.get("href")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _element_text(element: ContentElement) -> str:
    return element.value.strip() if isinstance(element.value, str) else ""


def _is_logo_element(element: ContentElement) -> bool:
    evidence = " ".join(
        str(value)
        for value in (
            element.role,
            element.attributes.get("figma_node_name", ""),
            element.attributes.get("alt", ""),
        )
    ).casefold()
    return any(term in evidence for term in _LOGO_TERMS)


def _is_logo_asset(asset: AssetRecord, layer_id: str, layer_kind: str) -> bool:
    evidence = " ".join(
        [
            asset.alt_text or "",
            layer_id,
            layer_kind,
            *(str(value) for value in asset.metadata.values()),
        ]
    ).casefold()
    return any(term in evidence for term in _LOGO_TERMS)


def _unavailable_decorative_summary(
    section: Section,
    assets: Mapping[str, AssetRecord],
) -> str | None:
    unavailable: list[AssetRecord] = []
    seen: set[str] = set()
    for layer in section.decorative_layers:
        if not layer.asset_id or layer.asset_id in seen:
            continue
        seen.add(layer.asset_id)
        asset = assets.get(layer.asset_id)
        if asset is not None and not _asset_source(asset) and asset.missing_reason:
            unavailable.append(asset)
    if not unavailable:
        return None
    reasons = sorted({str(asset.missing_reason) for asset in unavailable})
    reason_text = "; ".join(reasons)
    return (
        f"{len(unavailable)} associated decorative asset(s) were unavailable "
        f"({reason_text})"
    )


__all__ = ["HEADER_COMPOSER_CONTRACT_VERSION", "build_project_header"]
