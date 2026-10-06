"""Regression tests from a real live site: quality-hc.com (WordPress, YOOtheme).

Card sections on that page were classified as image galleries and planned onto
the Gallery templates, which hold an image per tile and nothing else, so every
card title, body and button was dropped (RT-17).

Two fixtures, with different provenance:

- ``quality-hc-card-sections.design-document.json`` is two real sections cut
  from the analyzed project's design document, unchanged. It is the evidence
  that an already-analyzed project is repaired by re-planning alone.
- ``quality-hc-home.html`` is a RECONSTRUCTION of the page's markup rebuilt from
  that design document's text, links and image URLs. The analyzed workspace did
  not keep the fetched HTML, so the real DOM was not available. It reproduces
  the original classification (every card section came out as a gallery), but
  nesting and class names are an educated guess at YOOtheme's output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vanjaro_cli.design.html_adapter import design_document_from_html
from vanjaro_cli.design.models import DesignDocument
from vanjaro_cli.design.planner import plan_design_document

FIXTURES = Path(__file__).parent / "fixtures" / "real-sources"
SOURCE_URL = "https://quality-hc.com/"


def _plan_for_html(html: str):
    return plan_design_document(design_document_from_html(html, SOURCE_URL))


def _plan_for_real_sections():
    document = DesignDocument.model_validate_json(
        (FIXTURES / "quality-hc-card-sections.design-document.json").read_text(encoding="utf-8")
    )
    return plan_design_document(document)


def _entries_by_section(plan) -> dict[str, object]:
    return {entry.source_section_id: entry for entry in plan.entries}


def test_real_card_sections_are_planned_onto_a_card_template_not_a_gallery() -> None:
    plan = _plan_for_real_sections()

    assert [entry.template_id for entry in plan.entries] == [
        "Cards/feature-cards-3up",
        "Cards/feature-cards-3up",
    ]


def test_real_card_sections_keep_every_title_body_media_and_action() -> None:
    entries = _entries_by_section(_plan_for_real_sections())

    fields = {binding.semantic_field for binding in entries["home.section.5"].bindings}
    assert {"item.title", "item.body", "item.media", "item.action"} <= fields
    for section_id, source_value_count in (("home.section.5", 24), ("home.section.6", 9)):
        bound = {binding.source_element_ids[0] for binding in entries[section_id].bindings}
        assert len(bound) == source_value_count, section_id


def test_real_card_sections_report_no_dropped_content() -> None:
    plan = _plan_for_real_sections()

    assert plan.summary.editable_content_coverage == 1.0
    for entry in plan.entries:
        assert not [warning for warning in entry.warnings if "not editable" in warning], entry.warnings


def test_real_card_sections_no_longer_report_a_doubled_item_prefix() -> None:
    for entry in _plan_for_real_sections().entries:
        assert not [warning for warning in entry.warnings if "item.item_" in warning]


@pytest.fixture(scope="module")
def reconstructed_html() -> str:
    return (FIXTURES / "quality-hc-home.html").read_text(encoding="utf-8")


def test_reconstructed_page_extracts_card_sections_instead_of_galleries(reconstructed_html: str) -> None:
    document = design_document_from_html(reconstructed_html, SOURCE_URL)

    roles = [section.semantic_role for section in document.pages[0].sections]

    assert "gallery" not in roles
    assert roles.count("feature_cards") == 4


def test_reconstructed_card_items_each_own_a_title_and_media(reconstructed_html: str) -> None:
    document = design_document_from_html(reconstructed_html, SOURCE_URL)

    card_sections = [s for s in document.pages[0].sections if s.semantic_role == "feature_cards"]
    for section in card_sections:
        for item in section.groups[0].items:
            assert {"title", "media"} <= set(item.fields), (section.id, item.id, item.fields)


def test_reconstructed_linked_cards_keep_their_destination(reconstructed_html: str) -> None:
    document = design_document_from_html(reconstructed_html, SOURCE_URL)

    linked = next(s for s in document.pages[0].sections if s.id == "home.section.4")

    assert all("action" in item.fields for item in linked.groups[0].items)


def test_reconstructed_badge_band_with_buttons_is_not_a_gallery(reconstructed_html: str) -> None:
    document = design_document_from_html(reconstructed_html, SOURCE_URL)

    hero = next(s for s in document.pages[0].sections if s.id == "home.section.2")

    assert hero.semantic_role == "hero"
    assert not hero.groups


def test_reconstructed_page_plans_every_card_section_on_a_card_template(reconstructed_html: str) -> None:
    entries = _entries_by_section(_plan_for_html(reconstructed_html))

    for section_id in ("home.section.4", "home.section.5", "home.section.6", "home.section.7"):
        assert entries[section_id].template_id.startswith("Cards/feature-cards"), section_id
        assert not [w for w in entries[section_id].warnings if "not editable" in w]
