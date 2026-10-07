"""The Trust Badge Hero template (RT-21): a hero with two buttons and a row of trust badges.

The real quality-hc.com hero carries an eyebrow line, a heading, a row of three
linked review badges and two buttons. The only hero templates held one button
and one image, so the plan blocked with "field 'action' has 2 values but owns 1
physical slots; field 'media' has 3 values but owns 1 physical slots".
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from vanjaro_cli.design.global_plan import split_global_sections
from vanjaro_cli.design.html_adapter import design_document_from_html
from vanjaro_cli.design.matcher import match_section
from vanjaro_cli.design.models import (
    Alignment,
    BreakpointName,
    ContentElement,
    ContentKind,
    EvidenceStatus,
    LayoutKind,
    LayoutObservation,
    MediaPosition,
    ResponsiveObservation,
    Section,
    StyleSet,
    Viewport,
)
from vanjaro_cli.design.physical_contract import validate_physical_contract
from vanjaro_cli.design.planner import plan_design_document
from vanjaro_cli.design.template_catalog import load_template_catalog
from vanjaro_cli.utils.block_compose import apply_overrides

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = PROJECT_ROOT / "artifacts" / "block-templates" / "Heroes" / "trust-badge-hero.json"
VALIDATOR_SCRIPT = (
    PROJECT_ROOT / ".agents" / "skills" / "block-template-author" / "scripts" / "validate_template.py"
)
REAL_PAGE = PROJECT_ROOT / "tests" / "fixtures" / "real-sources" / "quality-hc-home-real.html"
BADGE_HERO = "Heroes/trust-badge-hero"
CATALOG = load_template_catalog(PROJECT_ROOT / "artifacts" / "block-templates")


def _template() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def _entry(template_id: str):
    return next(entry for entry in CATALOG if entry.template_id == template_id)


def _walk(node: dict):
    yield node
    for child in node.get("components", []):
        yield from _walk(child)


def _types(root: dict) -> list[str]:
    return [node["type"] for node in _walk(root)]


def _overrides(*, badges: int, buttons: int = 2) -> dict[str, str]:
    values = {"heading_1": "Eyebrow", "heading_2": "Title", "text_1": "Body"}
    for index in range(1, 4):
        filled = index <= badges
        values[f"image_{index}_src"] = f"badge-{index}.svg" if filled else ""
        values[f"image_{index}_alt"] = f"Badge {index}" if filled else ""
        values[f"image_{index}_href"] = f"https://example.com/{index}" if filled else ""
    for index in range(1, 3):
        filled = index <= buttons
        values[f"button_{index}"] = f"Button {index}" if filled else ""
        values[f"button_{index}_href"] = f"https://example.com/b{index}" if filled else ""
    return values


def test_native_validator_passes_on_the_repository_template() -> None:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR_SCRIPT), str(TEMPLATE_PATH)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASSED" in result.stdout


def test_the_template_declares_two_actions_and_three_badges_as_editable_fields() -> None:
    capabilities = _entry(BADGE_HERO).capabilities

    assert capabilities.fields == {
        "eyebrow": "optional",
        "title": "required",
        "body": "optional",
        "action": "optional",
        "media": "required",
    }
    assert capabilities.physical_fields["action"].slots == ("button_1", "button_2")
    assert capabilities.physical_fields["action"].slots_per_owner == 2
    assert capabilities.physical_fields["media"].slots == ("image_1_src", "image_2_src", "image_3_src")
    assert capabilities.physical_fields["media"].slots_per_owner == 3
    assert capabilities.native_component_ratio == 1.0


def test_the_physical_contract_matches_the_executable_tree_exactly() -> None:
    data = _template()

    assert validate_physical_contract(data["template"], _entry(BADGE_HERO).capabilities) == ()


def test_every_slot_is_native_vanjaro_and_there_is_no_custom_code() -> None:
    types = set(_types(_template()["template"]))

    assert types <= {"section", "grid", "row", "column", "heading", "text", "button", "image", "spacer"}


def test_three_badges_and_two_buttons_fill_every_slot() -> None:
    composed = apply_overrides(_template(), _overrides(badges=3))["template"]

    types = _types(composed)
    assert types.count("image") == 3
    assert types.count("button") == 2
    buttons = [node for node in _walk(composed) if node["type"] == "button"]
    assert [node["content"] for node in buttons] == ["Button 1", "Button 2"]
    assert [node["attributes"]["href"] for node in buttons] == [
        "https://example.com/b1",
        "https://example.com/b2",
    ]
    links = [node for node in _walk(composed) if node["type"] == "link"]
    assert [node["attributes"]["href"] for node in links] == [f"https://example.com/{i}" for i in (1, 2, 3)]


def test_unused_badges_and_buttons_are_removed_not_left_as_placeholders() -> None:
    composed = apply_overrides(_template(), _overrides(badges=2, buttons=1))["template"]

    types = _types(composed)
    assert types.count("image") == 2
    assert types.count("button") == 1
    contents = [node.get("content") for node in _walk(composed)]
    assert "Learn More" not in contents
    assert "https://placehold.co/185x57" not in json.dumps(composed)


def test_a_hero_with_no_badges_loses_the_whole_badge_row() -> None:
    composed = apply_overrides(_template(), _overrides(badges=0))["template"]

    assert "image" not in _types(composed)
    column = next(node for node in _walk(composed) if node["type"] == "column")
    assert [child["type"] for child in column["components"]] == ["heading", "heading", "text", "button", "button"]


def _hero_section(
    *roles: str,
    section_id: str = "hero-1",
    layout_kind: LayoutKind = LayoutKind.SPLIT,
    columns: int = 2,
    media_position: MediaPosition | None = MediaPosition.RIGHT,
    alignment: Alignment | None = Alignment.LEFT,
    stacked_media_position: str | None = None,
) -> Section:
    kinds = {"title": ContentKind.HEADING, "action": ContentKind.BUTTON, "media": ContentKind.IMAGE}
    content = [
        ContentElement(
            id=f"{section_id}-{index}",
            kind=next((kind for word, kind in kinds.items() if word in role), ContentKind.TEXT),
            role=role,
            value=f"{role} value",
            order=index,
            provenance=[],
            confidence=1.0,
        )
        for index, role in enumerate(roles, 1)
    ]
    return Section(
        id=section_id,
        order=1,
        semantic_role="hero",
        role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(
            kind=layout_kind,
            contained=True,
            columns=columns,
            media_position=media_position,
            alignment=alignment,
        ),
        content=content,
        groups=[],
        style=StyleSet(),
        responsive=[
            ResponsiveObservation(
                breakpoint=BreakpointName.MOBILE,
                viewport=Viewport(width=390, height=844),
                status=EvidenceStatus.INFERRED,
                layout_changes={"columns": 1, "media_position": stacked_media_position},
            )
        ]
        if stacked_media_position
        else [],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )


def test_a_plain_split_hero_still_picks_split_hero() -> None:
    section = _hero_section("section_title", "body", "primary_action", "hero_media")

    best = match_section(section, CATALOG).selected_candidate

    assert best.template_id == "Heroes/split-hero"


def test_a_plain_hero_whose_picture_stacks_on_top_on_mobile_still_picks_split_hero() -> None:
    """The html-dnn-services benchmark hero: one picture, one button, and an
    inferred mobile layout that puts the picture on top. A badge row that also
    listed `top` won this section and shrank a team photo into a badge slot."""

    section = _hero_section(
        "section_title",
        "body",
        "primary_action",
        "hero_media",
        media_position=MediaPosition.LEFT,
        stacked_media_position="top",
    )

    best = match_section(section, CATALOG).selected_candidate

    assert best.template_id == "Heroes/split-hero"


def test_a_left_aligned_hero_with_no_picture_keeps_centered_hero() -> None:
    """The html-elementor-studio benchmark hero: title, body and one button, no
    picture. Left alignment fits the badge hero better than the centered one, but
    the badge row is the template's whole point, so a section with no picture
    must not move to it."""

    section = _hero_section(
        "section_title",
        "body",
        "primary_action",
        layout_kind=LayoutKind.STACK,
        columns=1,
        media_position=None,
    )

    best = match_section(section, CATALOG).selected_candidate

    assert best.template_id == "Heroes/centered-hero"


def test_a_tie_with_an_older_hero_goes_to_the_older_hero() -> None:
    """A hero with a title and one background picture, and no observed alignment,
    fits the badge hero exactly as well as the centered hero, and the matcher breaks
    ties by template ID. This template's ID sorts after every older hero on purpose,
    so it only wins where it fits strictly better; otherwise a background photo
    would land in a badge slot."""

    section = _hero_section(
        "section_title",
        "background_media",
        layout_kind=LayoutKind.STACK,
        columns=1,
        media_position=None,
        alignment=None,
    )

    candidates = {candidate.template_id: candidate for candidate in match_section(section, CATALOG, top_k=len(CATALOG)).candidates}

    assert candidates[BADGE_HERO].score == candidates["Heroes/centered-hero"].score
    assert match_section(section, CATALOG).selected_candidate.template_id == "Heroes/centered-hero"
    assert BADGE_HERO > "Heroes/split-hero" > "Heroes/photo-band" > "Heroes/centered-hero"


def test_two_buttons_and_three_badges_score_badge_hero_without_a_capacity_shortfall() -> None:
    section = _hero_section(
        "eyebrow",
        "section_title",
        "primary_action",
        "primary_action",
        "hero_media",
        "hero_media",
        "hero_media",
    )

    candidates = {candidate.template_id: candidate for candidate in match_section(section, CATALOG, top_k=len(CATALOG)).candidates}

    assert candidates[BADGE_HERO].missing_requirements == ()
    assert candidates["Heroes/split-hero"].missing_requirements
    assert match_section(section, CATALOG).selected_candidate.template_id == BADGE_HERO


def test_a_third_action_still_overflows_the_template() -> None:
    section = _hero_section(
        "section_title",
        "primary_action",
        "primary_action",
        "primary_action",
        "hero_media",
    )

    candidates = {candidate.template_id: candidate for candidate in match_section(section, CATALOG, top_k=len(CATALOG)).candidates}

    assert any(
        "action needs 3 slots, template owns 2" in item
        for item in candidates[BADGE_HERO].missing_requirements
    )


@pytest.fixture(scope="module")
def real_plan():
    document = design_document_from_html(REAL_PAGE.read_text(encoding="utf-8"), "https://quality-hc.com/")
    resolved = document.model_copy(
        update={
            "assets": [
                asset.model_copy(update={"local_path": f"sources/live-html-1/assets/{asset.id}.svg"})
                for asset in document.assets
            ]
        }
    )
    body_document, _, _ = split_global_sections(resolved)
    return plan_design_document(body_document)


def test_the_real_quality_hc_hero_matches_badge_hero_with_nothing_blocking(real_plan) -> None:
    hero = next(entry for entry in real_plan.entries if entry.source_section_id == "home.section.2")

    assert hero.template_id == BADGE_HERO
    assert not hero.match.blocking
    assert hero.simplifications == ()


def test_the_real_hero_binds_both_buttons_all_three_badges_and_the_eyebrow(real_plan) -> None:
    hero = next(entry for entry in real_plan.entries if entry.source_section_id == "home.section.2")
    bindings = {binding.slot: binding for binding in hero.bindings}

    assert bindings["button_1"].value == "Schedule Service"
    assert bindings["button_2"].value == "Call Now"
    assert bindings["button_2_href"].value == "tel:9183934577"
    assert [bindings[f"image_{index}_alt"].value for index in (1, 2, 3)] == [
        "Google Reviews Badge",
        "Facebook Reviews Badge",
        "Better Business Bureau Reviews Badge",
    ]
    assert all(bindings[f"image_{index}_href"].value.startswith("https://") for index in (1, 2, 3))
    assert bindings["heading_1"].semantic_field == "eyebrow"
    assert bindings["heading_2"].semantic_field == "title"
    assert hero.clear_slots == ("text_1",)


def test_the_real_page_no_longer_loses_its_eyebrow_and_has_no_blocker(real_plan) -> None:
    assert real_plan.summary.blocking_count == 0
    assert real_plan.summary.native_component_ratio >= 0.9
    assert real_plan.summary.editable_content_coverage >= 0.756
