"""Coverage for deterministic hero/CTA title selection (see figma_text_roles.py).

Confirms the fix for a diagnosed regression in
``figma_adapter._refine_section_content``: when font metadata is absent or
tied across a section's text candidates, the adapter used to rank by string
length, so a long ``Body`` paragraph could replace an explicitly named
``Headline`` as the section title. Every scenario here goes through the
public ``analyze_figma_document`` entry point rather than calling the
private selection helper directly, so the coverage exercises the same path
a real Figma export takes.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from vanjaro_cli.design.figma_adapter import analyze_figma_document
from vanjaro_cli.design.models import ContentKind
from vanjaro_cli.design.planner import plan_design_document
from vanjaro_cli.design.template_catalog import load_template_catalog

CAPTURED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
CORPUS_SOURCE = (
    Path(__file__).parent
    / "fixtures/design-benchmarks/cases/figma-freeform-nonprofit/source.json"
)


def _minimal_file(children: list[dict]) -> dict:
    return {
        "name": "Text Roles Fixture",
        "document": {
            "id": "0:0", "type": "DOCUMENT", "children": [{
                "id": "1:0", "type": "CANVAS", "name": "Pages", "children": [{
                    "id": "1:1", "type": "FRAME", "name": "Home Desktop",
                    "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1000, "height": 1600},
                    "children": children,
                }],
            }],
        },
    }


def _text(node_id: str, name: str, characters: str, *, x=80, y=100, w=500, h=60, font_size=None) -> dict:
    node: dict = {
        "id": node_id, "type": "TEXT", "name": name, "characters": characters,
        "absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": h},
    }
    if font_size is not None:
        node["style"] = {"fontSize": font_size}
    return node


def _text_no_bounds(node_id: str, name: str, characters: str) -> dict:
    return {"id": node_id, "type": "TEXT", "name": name, "characters": characters}


def _group(node_id: str, name: str, children: list[dict], *, x=0, y=0, w=1000, h=400) -> dict:
    return {
        "id": node_id, "type": "GROUP", "name": name,
        "absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": h},
        "children": children,
    }


def _hero_section(document, role="hero"):
    return next(s for s in document.pages[0].sections if s.semantic_role == role)


@pytest.mark.parametrize("reorder", [False, True])
def test_absent_font_longer_body_does_not_replace_explicit_headline(reorder):
    headline = _text("h1", "Headline", "Clean water for every neighborhood.", x=80, y=100)
    body = _text(
        "h2", "Body",
        "Every year our volunteer teams test, restore, and protect the creeks "
        "and rivers that run through this city, working block by block.",
        x=80, y=220,
    )
    assert len(body["characters"]) > len(headline["characters"])
    children = [body, headline] if reorder else [headline, body]
    payload = _minimal_file([_group("hero-1", "Hero", children)])

    document = analyze_figma_document(payload, file_key="text-roles-absent-font")
    section = _hero_section(document)
    titles = [e for e in section.content if e.role == "section_title"]
    assert len(titles) == 1
    assert titles[0].value == headline["characters"]
    assert any(e.role == "body" and e.value == body["characters"] for e in section.content)


def test_equal_nonzero_font_sizes_honor_explicit_headline_name():
    headline = _text("h1", "Headline", "Roots run deep here.", x=80, y=100, font_size=28)
    body = _text(
        "h2", "Body",
        "This program has spent a decade rebuilding the wetlands one volunteer weekend at a time.",
        x=80, y=220, font_size=28,
    )
    payload = _minimal_file([_group("hero-1", "Hero", [headline, body])])

    document = analyze_figma_document(payload, file_key="text-roles-equal-font")
    section = _hero_section(document)
    titles = [e for e in section.content if e.role == "section_title"]
    assert len(titles) == 1
    assert titles[0].value == headline["characters"]


def test_strong_font_hierarchy_still_wins_over_position_and_length():
    dominant = _text("t1", "Line 1", "Big.", x=80, y=300, font_size=54)
    minor_a = _text("t2", "Line 2", "A much longer supporting line of copy underneath it.", x=80, y=60, font_size=16)
    minor_b = _text("t3", "Line 3", "Another short line.", x=80, y=180, font_size=16)
    payload = _minimal_file([_group("hero-1", "Hero", [minor_a, minor_b, dominant])])

    document = analyze_figma_document(payload, file_key="text-roles-strong-typography")
    section = _hero_section(document)
    titles = [e for e in section.content if e.role == "section_title"]
    assert len(titles) == 1
    assert titles[0].value == dominant["characters"]


def test_nameless_missing_font_falls_back_to_geometric_reading_order():
    lower_longer = _text("t1", "Layer 1", "A much longer paragraph of body copy placed lower on the page.", x=80, y=400)
    topmost_shorter = _text("t2", "Layer 2", "Top line.", x=80, y=40)
    # Document order deliberately does not match reading order so the test
    # only passes if geometry, not list position, drives the choice.
    payload = _minimal_file([_group("hero-1", "Hero", [lower_longer, topmost_shorter])])

    document = analyze_figma_document(payload, file_key="text-roles-nameless-geometry")
    section = _hero_section(document)
    titles = [e for e in section.content if e.role == "section_title"]
    assert len(titles) == 1
    assert titles[0].value == topmost_shorter["characters"]


def test_missing_geometry_falls_back_to_deterministic_document_order():
    first_longer = _text_no_bounds("t1", "Layer 1", "A noticeably longer line of unlabeled copy that appears first.")
    second_shorter = _text_no_bounds("t2", "Layer 2", "Second line.")
    payload = _minimal_file([_group("hero-1", "Hero", [first_longer, second_shorter])])

    document = analyze_figma_document(payload, file_key="text-roles-missing-geometry")
    section = _hero_section(document)
    titles = [e for e in section.content if e.role == "section_title"]
    assert len(titles) == 1
    assert titles[0].value == first_longer["characters"]

    # Deterministic, not order-coincidental: swapping document order swaps the pick.
    payload_swapped = _minimal_file([_group("hero-1", "Hero", [second_shorter, first_longer])])
    document_swapped = analyze_figma_document(payload_swapped, file_key="text-roles-missing-geometry-swapped")
    section_swapped = _hero_section(document_swapped)
    titles_swapped = [e for e in section_swapped.content if e.role == "section_title"]
    assert titles_swapped[0].value == second_shorter["characters"]


def test_explicit_subtitle_and_eyebrow_names_do_not_steal_title_without_fonts():
    headline = _text("h1", "Headline", "Every child deserves music.", x=80, y=100)
    subtitle = _text(
        "h2", "Subtitle",
        "A much longer subtitle line that would win on length alone if the fix regressed.",
        x=80, y=200,
    )
    body = _text("h3", "Body", "Our mobile studio brings classes to your neighborhood every week.", x=80, y=280)
    payload = _minimal_file([_group("cta-1", "Call to action", [headline, subtitle, body])])

    document = analyze_figma_document(payload, file_key="text-roles-subtitle-eyebrow")
    section = _hero_section(document, role="call_to_action")
    titles = [e for e in section.content if e.role == "section_title"]
    assert len(titles) == 1
    assert titles[0].value == headline["characters"]
    assert not any(e.value == subtitle["characters"] and e.role == "section_title" for e in section.content)


def test_video_feature_eyebrow_and_action_are_distinguished_from_title_by_font():
    eyebrow = _text("v1", "Eyebrow", "Featured story", x=80, y=60, font_size=30)
    title = _text("v2", "Heading", "Watch the river come back to life.", x=80, y=140, font_size=36)
    body = _text("v3", "Body", "A short film following one summer of restoration work.", x=80, y=260, font_size=16)
    action = _text("v4", "Action", "Watch now", x=80, y=340)
    payload = _minimal_file([_group("video-1", "Video feature", [eyebrow, title, body, action])])

    document = analyze_figma_document(payload, file_key="text-roles-video-feature")
    section = _hero_section(document, role="video_feature")
    by_role = {e.role: e for e in section.content if e.value in {eyebrow["characters"], title["characters"], body["characters"], action["characters"]}}
    assert by_role["section_title"].value == title["characters"]
    assert by_role["eyebrow"].value == eyebrow["characters"]
    assert by_role["body"].value == body["characters"]
    action_element = next(e for e in section.content if e.value == action["characters"])
    assert action_element.kind == ContentKind.BUTTON
    assert action_element.role == "primary_action"


def test_analyze_figma_document_never_mutates_the_source_payload():
    headline = _text("h1", "Headline", "Healthy rivers. Strong communities.", x=80, y=100)
    body = _text("h2", "Body", "Local volunteers restore the waterways that connect us to this place.", x=80, y=220)
    payload = _minimal_file([_group("hero-1", "Hero", [headline, body])])
    before = deepcopy(payload)

    analyze_figma_document(payload, file_key="text-roles-source-unchanged")

    assert payload == before


def test_headline_and_body_reach_corresponding_native_template_slots():
    """Exercise the real matcher/planner pipeline, not just the adapter."""

    source = json.loads(CORPUS_SOURCE.read_text(encoding="utf-8"))
    document = analyze_figma_document(source, file_key="figma-freeform-nonprofit", captured_at=CAPTURED_AT)

    hero = next(s for s in document.pages[0].sections if s.semantic_role == "hero")
    headline = next(e for e in hero.content if e.role == "section_title")
    body = next(e for e in hero.content if e.role == "body")
    assert headline.value == "Healthy rivers. Strong communities."
    assert body.value == "Local volunteers restore the waterways that connect us."

    # Model the asset-migration step that a live run performs before
    # composition, matching the pattern used by the committed end-to-end
    # pipeline test, so the hero is eligible for native composition instead
    # of blocking on an unresolved remote asset.
    migrated_assets = [
        asset.model_copy(update={"local_path": f"/Portals/0/e2e/text-roles/{asset.id}.bin", "missing_reason": None})
        for asset in document.assets
    ]
    document = document.model_copy(update={"assets": migrated_assets})

    plan = plan_design_document(document, catalog=load_template_catalog())
    hero_entry = next(entry for entry in plan.entries if entry.source_section_id == hero.id)
    assert hero_entry.match.blocking is False

    bindings = {binding.slot: binding.value for binding in hero_entry.bindings}
    heading_slots = {slot: value for slot, value in bindings.items() if slot.startswith("heading")}
    text_slots = {slot: value for slot, value in bindings.items() if slot.startswith("text")}
    assert headline.value in heading_slots.values()
    assert body.value in text_slots.values()
