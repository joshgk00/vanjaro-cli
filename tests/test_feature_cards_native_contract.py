"""Native-conformance contract for the Feature Cards (3-up) authoring template.

Covers the defect fixed here: the authored section heading (``tpl-fc3-h0``)
used to sit directly under the root ``section`` with no ``head-style-N``
preset, which fails the repository's native block-template validator. The
fix moved it into a dedicated full-width title row (section > grid > row >
column > heading) ahead of the unchanged three-card row, in the same
container, and gave it ``head-style-2``.

These tests load the real template file and drive the real composition path
(``vanjaro_cli.utils.block_compose``) and the real native validator script
(via subprocess, exactly as documented in the skill), so a regression here
cannot slip past a mock.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from vanjaro_cli.design.physical_contract import primary_slots
from vanjaro_cli.utils.block_compose import apply_overrides, check_overflow, enumerate_slots, find_template

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = PROJECT_ROOT / "artifacts" / "block-templates" / "Cards" / "feature-cards-3up.json"
VALIDATOR_SCRIPT = (
    PROJECT_ROOT / ".agents" / "skills" / "block-template-author" / "scripts" / "validate_template.py"
)


def _run_validator(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR_SCRIPT), str(path)],
        capture_output=True,
        text=True,
    )


def _walk(node: dict, ancestors: tuple[dict, ...] = ()):
    yield node, ancestors
    for child in node.get("components", []):
        yield from _walk(child, ancestors + (node,))


def _load_template() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def _column_of(template_root: dict, node_id: str) -> str:
    """Return the id of the nearest ancestor column that owns ``node_id``."""
    for node, ancestors in _walk(template_root):
        if node.get("attributes", {}).get("id") == node_id:
            column = next(a for a in reversed(ancestors) if a.get("type") == "column")
            return column["attributes"]["id"]
    raise AssertionError(f"{node_id} not found in composed tree")


# ---------------------------------------------------------------------------
# Native validator, run for real
# ---------------------------------------------------------------------------


def test_native_validator_passes_on_the_repository_template() -> None:
    result = _run_validator(TEMPLATE_PATH)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASSED" in result.stdout


# ---------------------------------------------------------------------------
# Structural repair: heading in standard hierarchy, still owns section_title
# ---------------------------------------------------------------------------


def test_section_heading_sits_under_column_row_grid_with_required_preset() -> None:
    data = _load_template()
    section = data["template"]

    heading, ancestors = next(
        (node, ancestors)
        for node, ancestors in _walk(section)
        if node.get("attributes", {}).get("id") == "tpl-fc3-h0"
    )

    ancestor_types = [a["type"] for a in ancestors]
    # section -> grid -> row -> column, immediately above the heading.
    assert ancestor_types[-4:] == ["section", "grid", "row", "column"]

    column = ancestors[-1]
    column_classes = [c["name"] for c in column["classes"]]
    assert "col-12" in column_classes

    heading_classes = [c["name"] for c in heading["classes"]]
    assert "vj-heading" in heading_classes
    assert any(name.startswith("head-style-") for name in heading_classes)
    # Original content/id/other classes retained verbatim.
    assert heading["content"] == "Section heading"
    assert "text-center" in heading_classes
    assert "mb-4" in heading_classes


def test_section_heading_still_owns_heading_1_via_capabilities_and_composition() -> None:
    data = _load_template()

    contract = data["capabilities"]["physical_fields"]["section_title"]
    assert contract["slots"] == ["heading_1"]
    assert contract["owner"] == "section"

    order = [slot["key"] for slot in primary_slots(data["template"])]
    assert order[0] == "heading_1"

    slots = {slot["key"]: slot for slot in enumerate_slots(data["template"])}
    assert slots["heading_1"]["value"] == "Section heading"
    # Item headings remain heading_2..4, per the existing capabilities map.
    assert data["capabilities"]["physical_fields"]["item.title"]["slots"] == [
        "heading_2",
        "heading_3",
        "heading_4",
    ]


def test_all_authored_ids_are_unique() -> None:
    data = _load_template()
    ids = [node.get("attributes", {}).get("id") for node, _ in _walk(data["template"])]
    assert all(ids)
    assert len(ids) == len(set(ids))


def test_card_row_and_card_components_are_unchanged() -> None:
    """The fix must not touch card content, ordering, or the cards row."""
    data = _load_template()
    grid = data["template"]["components"][0]
    assert grid["type"] == "grid"
    # Title row first, then the original three-card row, same container.
    assert [row["type"] for row in grid["components"]] == ["row", "row"]
    cards_row = grid["components"][1]
    assert cards_row["attributes"]["id"] == "tpl-fc3-r1"
    assert [c["name"] for c in cards_row["classes"]] == ["row", "g-4", "text-center"]

    columns = cards_row["components"]
    assert [c["attributes"]["id"] for c in columns] == ["tpl-fc3-c1", "tpl-fc3-c2", "tpl-fc3-c3"]
    for index, column in enumerate(columns, start=1):
        child_types = [c["type"] for c in column["components"]]
        assert child_types == ["image", "icon", "heading", "text", "button"]
        heading = column["components"][2]
        assert heading["content"] == f"Feature {['One', 'Two', 'Three'][index - 1]}"
        assert heading["attributes"]["id"] == f"tpl-fc3-h{index}"


# ---------------------------------------------------------------------------
# Real composition: three distinct cards + native validation of the result
# ---------------------------------------------------------------------------


def test_three_card_composition_has_correct_native_values_and_ancestry(tmp_path: Path) -> None:
    template = find_template("Feature Cards (3-up)")
    overrides = {
        "heading_1": "Why choose us",
        "heading_2": "Card A title", "text_1": "Card A body",
        "button_1": "Card A CTA", "button_1_href": "/a",
        "image_1_src": "/assets/a.jpg", "image_1_href": "/work/a",
        "heading_3": "Card B title", "text_2": "Card B body",
        "button_2": "Card B CTA", "button_2_href": "/b",
        "image_2_src": "/assets/b.jpg", "image_2_href": "/work/b",
        "heading_4": "Card C title", "text_3": "Card C body",
        "button_3": "Card C CTA", "button_3_href": "/c",
        "image_3_src": "/assets/c.jpg", "image_3_href": "/work/c",
    }
    assert check_overflow(template, overrides) == []
    composed = apply_overrides(template, overrides)

    section_heading = next(
        node for node, _ in _walk(composed["template"])
        if node.get("attributes", {}).get("id") == "tpl-fc3-h0"
    )
    assert section_heading["content"] == "Why choose us"

    expected = {
        "tpl-fc3-c1": ("Card A title", "Card A body", "Card A CTA", "/a", "/assets/a.jpg", "/work/a"),
        "tpl-fc3-c2": ("Card B title", "Card B body", "Card B CTA", "/b", "/assets/b.jpg", "/work/b"),
        "tpl-fc3-c3": ("Card C title", "Card C body", "Card C CTA", "/c", "/assets/c.jpg", "/work/c"),
    }
    for column_id, (title, body, button_label, href, image_src, image_href) in expected.items():
        column = next(
            node for node, _ in _walk(composed["template"])
            if node.get("attributes", {}).get("id") == column_id
        )
        by_type = {c["type"]: c for c in column["components"] if c["type"] != "link"}
        assert by_type["heading"]["content"] == title
        assert by_type["text"]["content"] == body
        assert by_type["button"]["content"] == button_label
        assert by_type["button"]["attributes"]["href"] == href

        # Image ancestry: wrapped in its own native clickable link, still
        # inside this card's column, with the right destination.
        link = next(c for c in column["components"] if c["type"] == "link")
        image = link["components"][0]
        assert image["type"] == "image"
        assert image["attributes"]["src"] == image_src
        assert link["attributes"]["href"] == image_href
        assert _column_of(composed["template"], image["attributes"]["id"]) == column_id
        assert _column_of(composed["template"], by_type["button"]["attributes"]["id"]) == column_id

    composed_path = tmp_path / "feature-cards-3up-composed.json"
    composed_path.write_text(json.dumps(composed), encoding="utf-8")
    result = _run_validator(composed_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASSED" in result.stdout


# ---------------------------------------------------------------------------
# Real composition: five cards through column-unit expansion
# ---------------------------------------------------------------------------


def test_five_card_composition_keeps_one_section_heading_and_validates(tmp_path: Path) -> None:
    template = find_template("Feature Cards (3-up)")
    overrides = {"heading_1": "Section title"}
    for i in range(1, 6):
        overrides[f"heading_{i + 1}"] = f"Card {i} title"
        overrides[f"text_{i}"] = f"Card {i} body"
        overrides[f"button_{i}"] = f"Card {i} CTA"
        overrides[f"button_{i}_href"] = f"/card-{i}"
        overrides[f"image_{i}_src"] = f"/assets/card-{i}.jpg"

    assert check_overflow(template, overrides) == []
    composed = apply_overrides(template, overrides)

    all_nodes = list(_walk(composed["template"]))
    ids = [node.get("attributes", {}).get("id") for node, _ in all_nodes]
    assert all(ids)
    assert len(ids) == len(set(ids))

    headings = [node for node, _ in all_nodes if node.get("type") == "heading"]
    assert len(headings) == 6
    assert headings[0]["attributes"]["id"] == "tpl-fc3-h0"
    assert headings[0]["content"] == "Section title"

    grid = composed["template"]["components"][0]
    assert grid["components"][0]["attributes"]["id"] == "tpl-fc3-r0"
    assert [c["type"] for c in grid["components"][0]["components"][0]["components"]] == ["heading"]

    cards_row = grid["components"][1]
    columns = cards_row["components"]
    assert len(columns) == 5
    for index, column in enumerate(columns, start=1):
        child_types = [c["type"] for c in column["components"]]
        assert child_types == ["image", "icon", "heading", "text", "button"]
        assert column["components"][2]["content"] == f"Card {index} title"
        assert column["components"][3]["content"] == f"Card {index} body"
        assert column["components"][4]["content"] == f"Card {index} CTA"
        assert column["components"][4]["attributes"]["href"] == f"/card-{index}"
        assert column["components"][0]["attributes"]["src"] == f"/assets/card-{index}.jpg"

    composed_path = tmp_path / "feature-cards-3up-five-cards.json"
    composed_path.write_text(json.dumps(composed), encoding="utf-8")
    result = _run_validator(composed_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASSED" in result.stdout


# ---------------------------------------------------------------------------
# Clearing the section title must not remove or shift the cards
# ---------------------------------------------------------------------------


def test_clearing_section_title_removes_only_the_title_row() -> None:
    template = find_template("Feature Cards (3-up)")
    composed = apply_overrides(template, {"heading_1": ""})

    grid = composed["template"]["components"][0]
    assert [row["type"] for row in grid["components"]] == ["row"]
    remaining_row = grid["components"][0]
    assert remaining_row["attributes"]["id"] == "tpl-fc3-r1"

    columns = remaining_row["components"]
    assert [c["attributes"]["id"] for c in columns] == ["tpl-fc3-c1", "tpl-fc3-c2", "tpl-fc3-c3"]
    for index, column in enumerate(columns, start=1):
        heading = next(c for c in column["components"] if c["type"] == "heading")
        assert heading["content"] == f"Feature {['One', 'Two', 'Three'][index - 1]}"

    ids = [node.get("attributes", {}).get("id") for node, _ in _walk(composed["template"])]
    assert "tpl-fc3-h0" not in ids
    assert "tpl-fc3-r0" not in ids
    assert "tpl-fc3-c0" not in ids
