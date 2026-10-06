"""The real quality-hc.com home page (YOOtheme Pro), trimmed but not reconstructed (RT-19).

``quality-hc-home-real.html`` is the fetched page with scripts, styles, srcsets
and inline styles removed and the footer and menu cut short. Markup, class names
and nesting are the site's own.

Before: no section boundaries were found, a mobile twin of the hero arrived as a
second section, the About section was lost, and reviews, services and the FAQ
arrived as one section. Re-planned, editable coverage was 0.42 with 4 blockers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vanjaro_cli.design.global_plan import split_global_sections
from vanjaro_cli.design.html_adapter import design_document_from_html
from vanjaro_cli.design.planner import plan_design_document

FIXTURE = Path(__file__).parent / "fixtures" / "real-sources" / "quality-hc-home-real.html"
URL = "https://quality-hc.com/"


@pytest.fixture(scope="module")
def document():
    return design_document_from_html(FIXTURE.read_text(encoding="utf-8"), URL)


@pytest.fixture(scope="module")
def plan(document):
    body_document, _, _ = split_global_sections(document)
    return plan_design_document(body_document)


def test_every_page_section_is_its_own_section_in_page_order(document) -> None:
    leading = [
        next((e.value for e in s.content if e.kind.value == "heading" and e.value), "")
        for s in document.pages[0].sections
    ]

    expected = [
        "It’s Not Just Our Name",
        "Schedule Same-Day Service",
        "About Quality",
        "Our Professional Services",
        "Why Choose Quality",
        "The Home Promise Club",
    ]
    positions = [next(i for i, text in enumerate(leading) if text.startswith(prefix)) for prefix in expected]
    assert positions == sorted(positions)


def test_reviews_services_and_faq_are_three_sections_not_one(document) -> None:
    roles_by_title = {
        next((e.value for e in s.content if e.value and e.role in {"section_title", "eyebrow"}), ""): s.semantic_role
        for s in document.pages[0].sections
    }

    assert any("Our Company Reviews" in title or "Generation of Quality" in title for title in roles_by_title)
    assert any(title.startswith("Our Core HVAC Services") for title in roles_by_title)
    assert any(title.startswith("FAQs") for title in roles_by_title)
    assert roles_by_title[next(t for t in roles_by_title if t.startswith("FAQs"))] == "faq"


def test_the_mobile_twin_of_the_hero_is_not_a_second_hero(document) -> None:
    texts = [e.value for s in document.pages[0].sections for e in s.content if e.value]

    assert not any("#1 Plumbing" in text for text in texts)
    assert sum(1 for s in document.pages[0].sections if s.semantic_role == "hero") == 1


def test_the_header_is_the_desktop_header_with_the_real_menu(document) -> None:
    header = document.pages[0].sections[0]

    assert header.semantic_role == "navigation"
    assert len([e for e in header.content if e.role == "navigation_item"]) > 5


def test_the_about_section_keeps_its_heading_copy_and_button(document) -> None:
    about = next(s for s in document.pages[0].sections if any("About Quality" in (e.value or "") for e in s.content))
    values = [e.value for e in about.content if e.value]

    assert "The Cornerstone of Quality" in values
    assert "About Our Company" in values
    assert sum(1 for e in about.content if e.role == "body") == 3


def test_card_sections_keep_titles_text_and_actions(document) -> None:
    services = next(s for s in document.pages[0].sections if s.semantic_role == "feature_cards" and len(s.groups[0].items) == 6)

    for item in services.groups[0].items:
        assert {"title", "body", "media", "action"} <= set(item.fields)


def test_the_page_plans_with_fewer_blockers_more_editable_content_and_native_templates(plan) -> None:
    summary = plan.summary

    assert summary.editable_content_coverage > 0.5
    assert summary.blocking_count <= 3
    assert summary.native_component_ratio == 1.0


def test_no_template_that_is_not_native_is_chosen(plan) -> None:
    assert "Cards/class-photo-cards-4up" not in {entry.template_id for entry in plan.entries}
