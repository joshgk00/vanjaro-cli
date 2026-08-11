"""Contract tests for the shared agency semantic vocabulary."""

from __future__ import annotations

from vanjaro_cli.design.semantics import (
    binding_field_aliases,
    item_capability_aliases,
    normalize_semantic_name,
    section_capability_aliases,
    semantic_slot_types,
)


def test_semantic_normalization_is_stable_across_source_naming_styles() -> None:
    assert normalize_semantic_name("Card Title") == "card_title"
    assert normalize_semantic_name("item.card-title") == "item_card_title"
    assert normalize_semantic_name("  Background Media  ") == "background_media"


def test_binding_aliases_preserve_field_scope_and_known_synonyms() -> None:
    assert binding_field_aliases("item.title") == (
        "title", "heading", "name", "question", "label",
    )
    assert "image" in binding_field_aliases("background_media")
    assert binding_field_aliases("item.client_code") == ("client_code",)


def test_slot_preferences_are_centralized_and_unknown_fields_are_explicit() -> None:
    assert semantic_slot_types("item.media") == ("image",)
    assert semantic_slot_types("background_media") == ("section",)
    assert semantic_slot_types("item.client_code") is None


def test_observed_roles_map_to_capability_fields_without_source_branching() -> None:
    assert item_capability_aliases("person-media") == ("item.media",)
    assert item_capability_aliases("stat value") == ("item.value",)
    assert section_capability_aliases("hero_media") == ("media",)
    assert section_capability_aliases("contact item") == ("contact_items",)
    assert section_capability_aliases("client code") == ("client_code",)


def test_a_subheading_reaches_the_field_that_already_accepts_it() -> None:
    """The two tables disagreed: binding has always accepted a `subheading` for a
    `subtitle` field, while matching did not know the word — so a section
    carrying one scored as though no template could hold it."""

    assert "subheading" in binding_field_aliases("subtitle")
    assert section_capability_aliases("subheading") == ("subtitle",)

