"""Tests for the public Design Document v1 model contract."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from vanjaro_cli.design.models import DesignDocument


def make_design_document_data() -> dict:
    """Return a complete relationship-aware Design Document fixture."""

    provenance = {
        "source_kind": "live_html",
        "method": "rendered",
        "source_url": "https://example.com/",
        "css_selector": "main > section:nth-child(1)",
        "viewport": "desktop",
    }
    return {
        "schema_version": "1.0",
        "source": {
            "kind": "live_html",
            "identifier": "https://example.com/",
            "captured_at": "2026-07-16T12:00:00Z",
            "adapter_version": "1.0",
        },
        "tokens": {
            "colors": {
                "brand-primary": {
                    "value": "#123456",
                    "provenance": [provenance],
                }
            },
            "typography": [
                {
                    "role": "heading",
                    "font_family": "Inter",
                    "font_size": "48px",
                    "font_weight": 700,
                    "provenance": [provenance],
                }
            ],
        },
        "assets": [
            {
                "id": "asset-service-one",
                "kind": "image",
                "role": "editorial",
                "source_url": "https://example.com/service-one.jpg",
                "width": 800,
                "height": 600,
                "provenance": [provenance],
            }
        ],
        "pages": [
            {
                "id": "home",
                "source_reference": "https://example.com/",
                "title": "Home",
                "slug": "",
                "sections": [
                    {
                        "id": "home.services",
                        "order": 0,
                        "semantic_role": "feature_cards",
                        "role_confidence": 0.92,
                        "candidate_roles": [
                            {"role": "feature_cards", "score": 0.92},
                            {"role": "gallery", "score": 0.41},
                        ],
                        "layout": {
                            "kind": "grid",
                            "contained": True,
                            "columns": 3,
                            "media_position": "top",
                            "alignment": "left",
                            "full_bleed": False,
                        },
                        "content": [
                            {
                                "id": "element-21",
                                "kind": "image",
                                "role": "card_media",
                                "asset_id": "asset-service-one",
                                "group_id": "home.services.cards",
                                "order": 0,
                                "provenance": [provenance],
                                "confidence": 0.99,
                            },
                            {
                                "id": "element-22",
                                "kind": "heading",
                                "role": "card_title",
                                "value": "Service One",
                                "attributes": {"heading_level": 3},
                                "group_id": "home.services.cards",
                                "order": 1,
                                "provenance": [provenance],
                                "confidence": 0.98,
                            },
                        ],
                        "groups": [
                            {
                                "id": "home.services.cards",
                                "kind": "card",
                                "items": [
                                    {
                                        "id": "home.services.card.1",
                                        "fields": {
                                            "media": "element-21",
                                            "title": "element-22",
                                        },
                                    }
                                ],
                                "provenance": [provenance],
                            }
                        ],
                        "style": {
                            "observations": [
                                {
                                    "property": "background_color",
                                    "value": "#ffffff",
                                    "provenance": [provenance],
                                }
                            ],
                            "raw": {"clip-path": "polygon(0 0,100% 0,100% 90%,0 100%)"},
                        },
                        "responsive": [
                            {
                                "breakpoint": "mobile",
                                "viewport": {"width": 390, "height": 844},
                                "status": "observed",
                                "layout_changes": {"columns": 1},
                                "provenance": [provenance],
                            }
                        ],
                        "decorative_layers": [],
                        "interactions": [],
                        "provenance": [provenance],
                    }
                ],
                "breakpoints": ["desktop", "mobile"],
                "navigation_visibility": "visible",
                "seo": {"title": "Example home"},
                "provenance": [provenance],
            }
        ],
        "warnings": [],
        "analysis": {
            "section_confidence_mean": 0.92,
            "unsupported_traits": ["clip-path"],
        },
    }


def test_design_document_round_trips_without_data_loss() -> None:
    data = make_design_document_data()

    document = DesignDocument.model_validate(data)
    round_tripped = DesignDocument.model_validate(document.model_dump(mode="json"))

    assert round_tripped == document
    assert round_tripped.pages[0].sections[0].groups[0].items[0].fields == {
        "media": "element-21",
        "title": "element-22",
    }


def test_design_document_rejects_unknown_fields() -> None:
    data = make_design_document_data()
    data["future_field"] = "not-yet-supported"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DesignDocument.model_validate(data)


def test_design_document_rejects_dangling_group_reference_with_path() -> None:
    data = make_design_document_data()
    data["pages"][0]["sections"][0]["groups"][0]["items"][0]["fields"][
        "title"
    ] = "missing-element"

    with pytest.raises(ValidationError) as exc_info:
        DesignDocument.model_validate(data)

    message = str(exc_info.value)
    assert "pages[0].sections[0].groups[0].items[0].fields['title']" in message
    assert "missing-element" in message


def test_design_document_rejects_duplicate_ids_with_both_paths() -> None:
    data = make_design_document_data()
    duplicate = deepcopy(data["pages"][0]["sections"][0]["content"][0])
    duplicate["role"] = "duplicate_media"
    duplicate["order"] = 2
    data["pages"][0]["sections"][0]["content"].append(duplicate)

    with pytest.raises(ValidationError) as exc_info:
        DesignDocument.model_validate(data)

    message = str(exc_info.value)
    assert "duplicate id 'element-21'" in message
    assert "content[0].id" in message
    assert "content[2].id" in message


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("analysis", "section_confidence_mean"), 1.01),
        (("pages", 0, "sections", 0, "role_confidence"), -0.01),
        (("pages", 0, "sections", 0, "content", 0, "confidence"), 2),
    ],
)
def test_design_document_rejects_invalid_confidence_ranges(
    path: tuple[str | int, ...], value: float
) -> None:
    data = make_design_document_data()
    current = data
    for component in path[:-1]:
        current = current[component]
    current[path[-1]] = value

    with pytest.raises(ValidationError):
        DesignDocument.model_validate(data)


def test_design_document_rejects_unknown_enum_values() -> None:
    data = make_design_document_data()
    data["pages"][0]["sections"][0]["layout"]["kind"] = "masonry_magic"

    with pytest.raises(ValidationError, match="Input should be"):
        DesignDocument.model_validate(data)

