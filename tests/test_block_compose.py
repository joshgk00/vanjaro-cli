"""Tests for vanjaro blocks compose command and block_compose utility."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vanjaro_cli.cli import cli
from vanjaro_cli.utils.block_compose import (
    TemplateNotFoundError,
    apply_overrides,
    check_overflow,
    enumerate_slots,
    find_template,
)

HERO_TEMPLATE = {
    "name": "Centered Hero",
    "category": "Heroes",
    "description": "Full-width hero with centered heading, subtext, and CTA button",
    "template": {
        "type": "section",
        "attributes": {"id": "tpl-hero-s1"},
        "components": [{
            "type": "grid",
            "attributes": {"id": "tpl-hero-g1"},
            "components": [{
                "type": "row",
                "attributes": {"id": "tpl-hero-r1"},
                "components": [{
                    "type": "column",
                    "attributes": {"id": "tpl-hero-c1"},
                    "components": [
                        {"type": "heading", "tagName": "h1", "content": "Your Headline Here", "attributes": {"id": "tpl-hero-h1"}},
                        {"type": "text", "content": "Supporting text goes here.", "attributes": {"id": "tpl-hero-t1"}},
                        {"type": "button", "tagName": "a", "content": "Get Started", "attributes": {"id": "tpl-hero-b1", "href": "#"}},
                    ],
                }],
            }],
        }],
    },
    "styles": [],
}

CARDS_TEMPLATE = {
    "name": "Feature Cards",
    "category": "Cards",
    "description": "Three feature cards",
    "template": {
        "type": "section",
        "attributes": {"id": "tpl-fc-s1"},
        "components": [{
            "type": "grid",
            "attributes": {"id": "tpl-fc-g1"},
            "components": [{
                "type": "row",
                "attributes": {"id": "tpl-fc-r1"},
                "components": [
                    {
                        "type": "column", "attributes": {"id": "tpl-fc-c1"},
                        "components": [
                            {"type": "heading", "tagName": "h3", "content": "Card One", "attributes": {"id": "tpl-fc-h1"}},
                            {"type": "text", "content": "Description one.", "attributes": {"id": "tpl-fc-t1"}},
                        ],
                    },
                    {
                        "type": "column", "attributes": {"id": "tpl-fc-c2"},
                        "components": [
                            {"type": "heading", "tagName": "h3", "content": "Card Two", "attributes": {"id": "tpl-fc-h2"}},
                            {"type": "text", "content": "Description two.", "attributes": {"id": "tpl-fc-t2"}},
                        ],
                    },
                ],
            }],
        }],
    },
    "styles": [],
}


def _write_template(templates_dir: Path, template: dict) -> None:
    """Write a template file to the templates directory."""
    category_dir = templates_dir / template["category"]
    category_dir.mkdir(parents=True, exist_ok=True)
    filename = template["name"].lower().replace(" ", "-") + ".json"
    (category_dir / filename).write_text(json.dumps(template))


# -- enumerate_slots --


def test_enumerate_slots_hero():
    slots = enumerate_slots(HERO_TEMPLATE["template"])

    assert len(slots) == 4
    assert slots[0] == {"key": "heading_1", "type": "heading", "field": "content", "value": "Your Headline Here"}
    assert slots[1] == {"key": "text_1", "type": "text", "field": "content", "value": "Supporting text goes here."}
    assert slots[2] == {"key": "button_1", "type": "button", "field": "content", "value": "Get Started"}
    assert slots[3] == {"key": "button_1_href", "type": "button", "field": "attributes.href", "value": "#"}


def test_enumerate_slots_multiple_of_same_type():
    slots = enumerate_slots(CARDS_TEMPLATE["template"])

    heading_slots = [s for s in slots if s["type"] == "heading"]
    assert len(heading_slots) == 2
    assert heading_slots[0]["key"] == "heading_1"
    assert heading_slots[0]["value"] == "Card One"
    assert heading_slots[1]["key"] == "heading_2"
    assert heading_slots[1]["value"] == "Card Two"


def test_enumerate_slots_empty_template():
    slots = enumerate_slots({"type": "section", "components": []})
    assert slots == []


# -- apply_overrides --


def test_apply_overrides_content():
    composed = apply_overrides(HERO_TEMPLATE, {"heading_1": "Welcome to VGRT"})

    heading = composed["template"]["components"][0]["components"][0]["components"][0]["components"][0]
    assert heading["content"] == "Welcome to VGRT"


def test_apply_overrides_button_href():
    composed = apply_overrides(HERO_TEMPLATE, {"button_1_href": "/contact"})

    button = composed["template"]["components"][0]["components"][0]["components"][0]["components"][2]
    assert button["attributes"]["href"] == "/contact"


def test_apply_overrides_multiple():
    overrides = {
        "heading_1": "New Heading",
        "text_1": "New description.",
        "button_1": "Click Here",
        "button_1_href": "/go",
    }
    composed = apply_overrides(HERO_TEMPLATE, overrides)

    col = composed["template"]["components"][0]["components"][0]["components"][0]["components"]
    assert col[0]["content"] == "New Heading"
    assert col[1]["content"] == "New description."
    assert col[2]["content"] == "Click Here"
    assert col[2]["attributes"]["href"] == "/go"


def test_apply_overrides_does_not_mutate_original():
    original_heading = HERO_TEMPLATE["template"]["components"][0]["components"][0]["components"][0]["components"][0]["content"]
    apply_overrides(HERO_TEMPLATE, {"heading_1": "Changed"})

    current_heading = HERO_TEMPLATE["template"]["components"][0]["components"][0]["components"][0]["components"][0]["content"]
    assert current_heading == original_heading


def test_apply_overrides_ignores_unknown_keys():
    composed = apply_overrides(HERO_TEMPLATE, {"nonexistent_1": "ignored"})
    assert composed["name"] == "Centered Hero"


def test_apply_overrides_preserves_metadata():
    composed = apply_overrides(HERO_TEMPLATE, {"heading_1": "New"})

    assert composed["name"] == "Centered Hero"
    assert composed["category"] == "Heroes"
    assert composed["description"] == HERO_TEMPLATE["description"]
    assert composed["styles"] == []


def test_apply_overrides_cards_second_heading():
    composed = apply_overrides(CARDS_TEMPLATE, {"heading_2": "Updated Card Two"})

    row = composed["template"]["components"][0]["components"][0]["components"]
    col1_heading = row[0]["components"][0]
    col2_heading = row[1]["components"][0]
    assert col1_heading["content"] == "Card One"
    assert col2_heading["content"] == "Updated Card Two"


# -- find_template --


def test_find_template(tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = find_template("Centered Hero")

    assert result["name"] == "Centered Hero"


def test_find_template_case_insensitive(tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = find_template("centered hero")

    assert result["name"] == "Centered Hero"


def test_find_template_not_found(tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    with pytest.raises(TemplateNotFoundError) as exc_info:
        find_template("Nonexistent")

    assert "Nonexistent" in str(exc_info.value)
    assert "Centered Hero" in str(exc_info.value)


def test_find_template_missing_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(tmp_path / "missing"))

    with pytest.raises(TemplateNotFoundError) as exc_info:
        find_template("Anything")

    assert exc_info.value.available == []


# -- CLI: blocks compose --list-slots --


def test_compose_list_slots(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, ["blocks", "compose", "Centered Hero", "--list-slots"])

    assert result.exit_code == 0
    assert "heading_1" in result.output
    assert "text_1" in result.output
    assert "button_1" in result.output
    assert "button_1_href" in result.output


def test_compose_list_slots_json(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, ["blocks", "compose", "Centered Hero", "--list-slots", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 4
    keys = [s["key"] for s in data]
    assert "heading_1" in keys
    assert "button_1_href" in keys


# -- CLI: blocks compose (default) --


def test_compose_with_set(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, [
        "blocks", "compose", "Centered Hero",
        "--set", "heading_1=Welcome to VGRT",
        "--set", "button_1=Learn More",
    ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "Centered Hero"
    col = data["template"]["components"][0]["components"][0]["components"][0]["components"]
    assert col[0]["content"] == "Welcome to VGRT"
    assert col[2]["content"] == "Learn More"


def test_compose_with_overrides_file(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    overrides_file = tmp_path / "overrides.json"
    overrides_file.write_text(json.dumps({"heading_1": "From File", "text_1": "File text."}))

    result = runner.invoke(cli, [
        "blocks", "compose", "Centered Hero",
        "--overrides", str(overrides_file),
    ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    col = data["template"]["components"][0]["components"][0]["components"][0]["components"]
    assert col[0]["content"] == "From File"
    assert col[1]["content"] == "File text."


def test_compose_set_overrides_merge_with_file(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    overrides_file = tmp_path / "overrides.json"
    overrides_file.write_text(json.dumps({"heading_1": "From File"}))

    result = runner.invoke(cli, [
        "blocks", "compose", "Centered Hero",
        "--overrides", str(overrides_file),
        "--set", "text_1=From CLI",
    ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    col = data["template"]["components"][0]["components"][0]["components"][0]["components"]
    assert col[0]["content"] == "From File"
    assert col[1]["content"] == "From CLI"


def test_compose_output_to_file(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    output_file = tmp_path / "composed.json"

    result = runner.invoke(cli, [
        "blocks", "compose", "Centered Hero",
        "--set", "heading_1=File Output",
        "--output", str(output_file),
    ])

    assert result.exit_code == 0
    assert "Composed" in result.output
    assert "1 override" in result.output

    written = json.loads(output_file.read_text())
    col = written["template"]["components"][0]["components"][0]["components"][0]["components"]
    assert col[0]["content"] == "File Output"


def test_compose_json_status_envelope(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, [
        "blocks", "compose", "Centered Hero",
        "--set", "heading_1=JSON Mode",
        "--json",
    ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "composed"
    assert data["template_name"] == "Centered Hero"
    assert data["overrides_applied"] == 1
    assert data["result"]["name"] == "Centered Hero"


def test_compose_template_not_found(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, ["blocks", "compose", "Nonexistent"])

    assert result.exit_code == 1
    assert "not found" in result.output


def test_compose_invalid_set_format(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, [
        "blocks", "compose", "Centered Hero",
        "--set", "no-equals-sign",
    ])

    assert result.exit_code == 1
    assert "key=value" in result.output


def test_compose_no_overrides_outputs_original(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, ["blocks", "compose", "Centered Hero"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    col = data["template"]["components"][0]["components"][0]["components"][0]["components"]
    assert col[0]["content"] == "Your Headline Here"


# -- list-item support --

FOOTER_TEMPLATE = {
    "name": "Footer Links",
    "category": "Navigation",
    "description": "Simple footer with list items",
    "template": {
        "type": "section",
        "attributes": {"id": "tpl-foot-s1"},
        "components": [{
            "type": "grid",
            "attributes": {"id": "tpl-foot-g1"},
            "components": [{
                "type": "row",
                "attributes": {"id": "tpl-foot-r1"},
                "components": [{
                    "type": "column",
                    "attributes": {"id": "tpl-foot-c1"},
                    "components": [
                        {"type": "heading", "tagName": "h5", "content": "Quick Links", "attributes": {"id": "tpl-foot-h1"}},
                        {
                            "type": "list",
                            "attributes": {"id": "tpl-foot-l1"},
                            "components": [
                                {"type": "list-item", "content": "Home", "attributes": {"id": "tpl-foot-li1"}},
                                {"type": "list-item", "content": "About", "attributes": {"id": "tpl-foot-li2"}},
                                {"type": "list-item", "content": "Contact", "attributes": {"id": "tpl-foot-li3"}},
                            ],
                        },
                    ],
                }],
            }],
        }],
    },
    "styles": [],
}


def test_enumerate_slots_includes_list_items():
    slots = enumerate_slots(FOOTER_TEMPLATE["template"])

    list_item_slots = [s for s in slots if s["type"] == "list-item"]
    assert len(list_item_slots) == 3
    assert list_item_slots[0] == {"key": "list-item_1", "type": "list-item", "field": "content", "value": "Home"}
    assert list_item_slots[1]["key"] == "list-item_2"
    assert list_item_slots[2]["key"] == "list-item_3"


def test_apply_overrides_list_item_content():
    composed = apply_overrides(FOOTER_TEMPLATE, {"list-item_1": "Portfolio", "list-item_3": "Blog"})

    list_comp = composed["template"]["components"][0]["components"][0]["components"][0]["components"][1]
    items = list_comp["components"]
    assert items[0]["content"] == "Portfolio"
    assert items[1]["content"] == "About"
    assert items[2]["content"] == "Blog"


def test_apply_overrides_list_item_does_not_mutate_original():
    original = FOOTER_TEMPLATE["template"]["components"][0]["components"][0]["components"][0]["components"][1]["components"][0]["content"]
    apply_overrides(FOOTER_TEMPLATE, {"list-item_1": "Changed"})

    current = FOOTER_TEMPLATE["template"]["components"][0]["components"][0]["components"][0]["components"][1]["components"][0]["content"]
    assert current == original


# -- check_overflow --


def test_check_overflow_returns_empty_when_all_match():
    unused = check_overflow(HERO_TEMPLATE, {"heading_1": "Hello", "text_1": "World"})
    assert unused == []


def test_check_overflow_returns_unmatched_keys():
    unused = check_overflow(HERO_TEMPLATE, {
        "heading_1": "Hello",
        "heading_2": "Dropped",
        "image_5_src": "also-dropped.jpg",
    })
    assert unused == ["heading_2", "image_5_src"]


def test_check_overflow_with_footer_excess_items():
    overrides = {f"list-item_{i}": f"Link {i}" for i in range(1, 8)}
    unused = check_overflow(FOOTER_TEMPLATE, overrides)

    assert "list-item_1" not in unused
    assert "list-item_3" not in unused
    assert "list-item_4" in unused
    assert "list-item_7" in unused
    assert len(unused) == 4


def test_check_overflow_empty_overrides():
    unused = check_overflow(HERO_TEMPLATE, {})
    assert unused == []


# -- CLI: compose overflow warning --


def test_compose_warns_on_overflow(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, [
        "blocks", "compose", "Centered Hero",
        "--set", "heading_1=OK",
        "--set", "heading_99=Dropped",
    ])

    assert result.exit_code == 0
    assert "heading_99" in result.output
