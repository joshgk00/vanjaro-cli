"""Source-neutral semantic vocabulary for matching and template binding.

This module is deliberately free of source, template, and portal I/O.  Figma,
HTML, and image adapters may emit different observed roles, but matching and
binding resolve them through one audited vocabulary.
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Final


def normalize_semantic_name(value: str) -> str:
    """Normalize a role or field name without changing its semantic scope."""

    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


_BINDING_FIELD_ALIASES: Final = MappingProxyType({
    "section_title": ("section_title", "title", "heading", "name"),
    "section_body": ("section_body", "body", "text", "description", "excerpt"),
    "title": ("title", "heading", "name", "question", "label"),
    "subtitle": ("subtitle", "subheading", "kicker"),
    "body": ("body", "text", "description", "answer", "excerpt", "quote", "role"),
    "media": ("media", "image", "photo", "logo", "video"),
    "background_media": ("background_media", "background_image", "media", "image", "photo"),
    "icon": ("icon", "media", "image"),
    "action": ("action", "button", "link", "cta"),
    "brand": ("brand", "logo", "wordmark", "site_name"),
    "navigation_item": ("navigation_item", "label", "link", "action", "title"),
    "features": ("features", "feature", "list", "items"),
    "contact_items": ("contact_items", "contact", "list", "items"),
    "links": ("links", "link", "navigation_item", "items"),
    "question": ("question", "title", "heading"),
    "answer": ("answer", "body", "text"),
    "value": ("value", "stat", "number", "price"),
    "price": ("price", "value", "stat", "number"),
    "label": ("label", "title", "name"),
    "role": ("role", "meta", "body", "text"),
    "meta": ("meta", "role", "tag", "category"),
    "tag": ("tag", "meta", "category"),
    "quote": ("quote", "body", "text"),
    "author": ("author", "title", "name"),
    "eyebrow": ("eyebrow", "subtitle", "kicker"),
    "action_title": ("action_title", "title", "heading"),
    "action_body": ("action_body", "body", "text"),
    "contact_title": ("contact_title", "title", "heading"),
    "form": ("form", "form_placeholder"),
})

_SEMANTIC_SLOT_TYPES: Final = MappingProxyType({
    "section_title": ("heading",),
    "section_body": ("text",),
    "title": ("heading", "text"),
    "subtitle": ("heading", "text"),
    "body": ("text", "heading"),
    "media": ("image",),
    "background_media": ("section",),
    "icon": ("image",),
    "action": ("button", "link"),
    "brand": ("heading", "text", "image"),
    "navigation_item": ("link", "button", "text"),
    "features": ("list-item", "text"),
    "contact_items": ("list-item", "text"),
    "links": ("list-item", "link", "text"),
    "question": ("heading", "button", "text"),
    "answer": ("text",),
    "value": ("heading", "text"),
    "price": ("heading", "text"),
    "label": ("text", "heading"),
    "role": ("text",),
    "meta": ("text",),
    "tag": ("text",),
    "quote": ("text",),
    "author": ("heading", "text"),
    "eyebrow": ("heading", "text"),
    "action_title": ("heading", "text"),
    "action_body": ("text", "heading"),
    "contact_title": ("heading", "text"),
    "form": ("form",),
})

_ITEM_CAPABILITY_ALIASES: Final = MappingProxyType({
    "title": ("item.title",),
    "card_title": ("item.title",),
    "step_title": ("item.title", "item.label"),
    "body": ("item.body",),
    "card_body": ("item.body",),
    "media": ("item.media", "item.icon"),
    "card_media": ("item.media", "item.icon"),
    "person_media": ("item.media",),
    "wordmark": ("item.media",),
    "logo_wordmark": ("item.media",),
    "icon": ("item.icon", "item.media"),
    "quote": ("item.quote",),
    "testimonial_quote": ("item.quote",),
    "author": ("item.author",),
    "role": ("item.role",),
    "value": ("item.value",),
    "stat_value": ("item.value",),
    "step_number": ("item.value",),
    "label": ("item.label", "item.navigation_item"),
    "navigation_item": ("item.navigation_item", "item.action"),
    "stat_label": ("item.label",),
    "features": ("item.features",),
    "action": ("item.action",),
    "primary_action": ("item.action",),
    "tag": ("item.tag", "item.meta"),
    "eyebrow": ("item.tag", "item.meta"),
})

_SECTION_CAPABILITY_ALIASES: Final = MappingProxyType({
    "section_title": ("section_title", "title"),
    "title": ("title", "section_title"),
    "subtitle": ("subtitle",),
    "body": ("body", "section_body"),
    "section_body": ("section_body", "body"),
    "primary_action": ("action",),
    "action": ("action",),
    "hero_media": ("media",),
    "section_media": ("media",),
    "author_media": ("media",),
    "media": ("media",),
    "background_media": ("background_media", "media"),
    "eyebrow": ("eyebrow",),
    "testimonial_quote": ("body",),
    "author": ("title",),
    "brand": ("brand", "brand.title", "title"),
    "contact_item": ("contact_items",),
})


def _leaf(field: str) -> str:
    return normalize_semantic_name(field.rsplit(".", 1)[-1])


def binding_field_aliases(field: str) -> tuple[str, ...]:
    """Return observed element roles accepted by one template field."""

    leaf = _leaf(field)
    return _BINDING_FIELD_ALIASES.get(leaf, (leaf,))


def semantic_slot_types(field: str) -> tuple[str, ...] | None:
    """Return preferred physical GrapesJS slot types for a semantic field."""

    return _SEMANTIC_SLOT_TYPES.get(_leaf(field))


def item_capability_aliases(role: str) -> tuple[str, ...]:
    """Map an observed repeat-item role to supported capability fields."""

    normalized = normalize_semantic_name(role)
    return _ITEM_CAPABILITY_ALIASES.get(normalized, (f"item.{normalized}",))


def section_capability_aliases(role: str) -> tuple[str, ...]:
    """Map an observed section-owned role to supported capability fields."""

    normalized = normalize_semantic_name(role)
    return _SECTION_CAPABILITY_ALIASES.get(normalized, (normalized,))


__all__ = [
    "binding_field_aliases",
    "item_capability_aliases",
    "normalize_semantic_name",
    "section_capability_aliases",
    "semantic_slot_types",
]
