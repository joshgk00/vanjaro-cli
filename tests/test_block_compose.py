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
    # image_5_src is absorbed by image slot expansion, not overflow
    assert unused == ["heading_2"]


def test_check_overflow_absorbs_excess_list_items():
    overrides = {f"list-item_{i}": f"Link {i}" for i in range(1, 8)}
    unused = check_overflow(FOOTER_TEMPLATE, overrides)

    # list-item_4..7 are absorbed by list slot expansion, not dropped
    assert unused == []


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


# ---------------------------------------------------------------------------
# expand_text_slots
# ---------------------------------------------------------------------------


def make_two_text_template() -> dict:
    return {
        "name": "Rich Text Block",
        "category": "Content",
        "template": {
            "type": "section",
            "attributes": {"id": "tpl-s1"},
            "components": [
                {
                    "type": "column",
                    "attributes": {"id": "tpl-c1"},
                    "components": [
                        {"type": "heading", "attributes": {"id": "tpl-h1"}, "content": ""},
                        {"type": "text", "attributes": {"id": "tpl-t1"}, "content": ""},
                        {"type": "text", "attributes": {"id": "tpl-t2"}, "content": ""},
                    ],
                }
            ],
        },
    }


def test_apply_overrides_expands_text_slots_for_long_content():
    overrides = {f"text_{n}": f"Paragraph {n}" for n in range(1, 6)}
    overrides["heading_1"] = "Post Title"

    result = apply_overrides(make_two_text_template(), overrides)

    column = result["template"]["components"][0]
    texts = [c for c in column["components"] if c["type"] == "text"]
    assert [t["content"] for t in texts] == [f"Paragraph {n}" for n in range(1, 6)]


def test_expanded_clones_get_unique_ids():
    overrides = {f"text_{n}": f"P{n}" for n in range(1, 5)}

    result = apply_overrides(make_two_text_template(), overrides)

    column = result["template"]["components"][0]
    ids = [c["attributes"]["id"] for c in column["components"] if c["type"] == "text"]
    assert len(ids) == len(set(ids)) == 4


def test_no_expansion_when_overrides_fit():
    template = make_two_text_template()

    result = apply_overrides(template, {"text_1": "Only one"})

    column = result["template"]["components"][0]
    texts = [c for c in column["components"] if c["type"] == "text"]
    assert len(texts) == 2


def test_check_overflow_ignores_absorbable_text_keys():
    overrides = {"text_5": "Deep paragraph", "image_9_src": "/nope.jpg", "button_7": "x"}

    overflow = check_overflow(make_two_text_template(), overrides)

    # text and image keys are absorbed by slot expansion; buttons are not
    assert overflow == ["button_7"]


# ---------------------------------------------------------------------------
# expand_image_slots
# ---------------------------------------------------------------------------


def make_one_image_template() -> dict:
    return {
        "name": "Gallery (1-up)",
        "category": "Cards",
        "template": {
            "type": "section",
            "attributes": {"id": "tpl-g-s1"},
            "components": [
                {
                    "type": "column",
                    "attributes": {"id": "tpl-g-c1"},
                    "components": [
                        {"type": "image", "attributes": {"id": "tpl-g-i1", "src": "", "alt": ""}},
                    ],
                }
            ],
        },
    }


def test_image_slots_expand_by_cloning():
    overrides = {f"image_{n}_src": f"/img/{n}.jpg" for n in range(1, 5)}

    result = apply_overrides(make_one_image_template(), overrides)

    column = result["template"]["components"][0]
    images = [c for c in column["components"] if c["type"] == "image"]
    assert [i["attributes"]["src"] for i in images] == [f"/img/{n}.jpg" for n in range(1, 5)]
    ids = [i["attributes"]["id"] for i in images]
    assert len(set(ids)) == 4


def test_imageless_template_gains_image_components():
    """Rich Text Block has no image slots — page imagery must not be dropped."""
    overrides = {
        "heading_1": "Post Title",
        "text_1": "Body",
        "image_1_src": "/img/featured.jpg",
        "image_1_alt": "Featured",
    }

    result = apply_overrides(make_two_text_template(), overrides)

    column = result["template"]["components"][0]
    images = [c for c in column["components"] if c["type"] == "image"]
    assert len(images) == 1
    assert images[0]["attributes"]["src"] == "/img/featured.jpg"
    assert images[0]["attributes"]["alt"] == "Featured"
    # A lone featured image floats right of the body instead of stranding
    # full-width at the end of the article.
    assert "float:right" in images[0]["attributes"]["style"]
    assert column["components"].index(images[0]) < len(column["components"]) - 1


def test_multiple_synthesized_images_append_without_float():
    overrides = {
        "heading_1": "Gallery",
        "text_1": "Body",
        "image_1_src": "/img/1.jpg",
        "image_2_src": "/img/2.jpg",
        "image_3_src": "/img/3.jpg",
    }

    result = apply_overrides(make_two_text_template(), overrides)

    column = result["template"]["components"][0]
    images = [c for c in column["components"] if c["type"] == "image"]
    assert len(images) == 3
    assert all("style" not in i["attributes"] for i in images)


def test_empty_image_src_overrides_do_not_expand():
    result = apply_overrides(make_two_text_template(), {"image_1_src": "", "text_1": "x"})

    column = result["template"]["components"][0]
    assert not [c for c in column["components"] if c["type"] == "image"]


def test_check_overflow_ignores_absorbable_image_keys():
    overrides = {"image_3_src": "/img/3.jpg", "image_3_alt": "x", "button_9": "Nope"}

    overflow = check_overflow(make_one_image_template(), overrides)

    assert overflow == ["button_9"]


# ---------------------------------------------------------------------------
# expand_column_units
# ---------------------------------------------------------------------------


def make_image_grid_template() -> dict:
    return {
        "name": "Gallery (2-up)",
        "category": "Cards",
        "template": {
            "type": "section",
            "attributes": {"id": "tpl-ig-s1"},
            "components": [{
                "type": "row",
                "attributes": {"id": "tpl-ig-r1"},
                "components": [
                    {
                        "type": "column",
                        "attributes": {"id": "tpl-ig-c1"},
                        "components": [
                            {"type": "image", "attributes": {"id": "tpl-ig-i1", "src": "", "alt": ""}},
                        ],
                    },
                    {
                        "type": "column",
                        "attributes": {"id": "tpl-ig-c2"},
                        "components": [
                            {"type": "image", "attributes": {"id": "tpl-ig-i2", "src": "", "alt": ""}},
                        ],
                    },
                ],
            }],
        },
    }


def _cards_row(composed: dict) -> list[dict]:
    return composed["template"]["components"][0]["components"][0]["components"]


def test_card_overflow_clones_column_units():
    overrides = {}
    for n in range(1, 6):
        overrides[f"heading_{n}"] = f"Card {n}"
        overrides[f"text_{n}"] = f"Description {n}."

    composed = apply_overrides(CARDS_TEMPLATE, overrides)

    row = _cards_row(composed)
    assert len(row) == 5
    assert all(col["type"] == "column" for col in row)
    for index, column in enumerate(row, start=1):
        assert column["components"][0]["content"] == f"Card {index}"
        assert column["components"][1]["content"] == f"Description {index}."


def test_cloned_column_units_get_unique_ids():
    overrides = {f"heading_{n}": f"Card {n}" for n in range(1, 6)}

    composed = apply_overrides(CARDS_TEMPLATE, overrides)

    row = _cards_row(composed)
    all_ids = []
    for column in row:
        all_ids.append(column["attributes"]["id"])
        all_ids.extend(c["attributes"]["id"] for c in column["components"])
    assert len(all_ids) == len(set(all_ids))


def test_image_grid_overflow_clones_columns_not_leaves():
    overrides = {f"image_{n}_src": f"/img/{n}.jpg" for n in range(1, 7)}

    composed = apply_overrides(make_image_grid_template(), overrides)

    row = composed["template"]["components"][0]["components"]
    assert len(row) == 6
    for index, column in enumerate(row, start=1):
        images = [c for c in column["components"] if c["type"] == "image"]
        assert len(images) == 1
        assert images[0]["attributes"]["src"] == f"/img/{index}.jpg"


def test_no_unit_expansion_when_overrides_fit():
    overrides = {"heading_1": "One", "heading_2": "Two", "text_1": "A", "text_2": "B"}

    composed = apply_overrides(CARDS_TEMPLATE, overrides)

    assert len(_cards_row(composed)) == 2


def test_empty_override_values_do_not_trigger_unit_expansion():
    overrides = {"heading_1": "One", "heading_5": "", "text_9": ""}

    composed = apply_overrides(CARDS_TEMPLATE, overrides)

    assert len(_cards_row(composed)) == 2


def test_unit_expansion_does_not_mutate_original():
    template = make_image_grid_template()
    overrides = {f"image_{n}_src": f"/img/{n}.jpg" for n in range(1, 5)}

    apply_overrides(template, overrides)

    assert len(template["template"]["components"][0]["components"]) == 2


# ---------------------------------------------------------------------------
# expand_list_slots
# ---------------------------------------------------------------------------


def test_list_slots_expand_by_cloning():
    overrides = {f"list-item_{n}": f"Feature {n}" for n in range(1, 7)}

    result = apply_overrides(FOOTER_TEMPLATE, overrides)

    list_comp = result["template"]["components"][0]["components"][0]["components"][0]["components"][1]
    items = list_comp["components"]
    assert [i["content"] for i in items] == [f"Feature {n}" for n in range(1, 7)]
    ids = [i["attributes"]["id"] for i in items]
    assert len(ids) == len(set(ids)) == 6


def test_listless_template_gains_synthesized_list():
    """Checklist content fed to a template with no list must not be dropped."""
    overrides = {
        "heading_1": "Each Website Includes",
        "text_1": "Intro",
        "list-item_1": "Hosting for your website",
        "list-item_2": "Professional design",
        "list-item_3": "Mobile-friendly website",
    }

    result = apply_overrides(make_two_text_template(), overrides)

    column = result["template"]["components"][0]
    lists = [c for c in column["components"] if c["type"] == "list"]
    assert len(lists) == 1
    assert [i["content"] for i in lists[0]["components"]] == [
        "Hosting for your website", "Professional design", "Mobile-friendly website",
    ]


def test_empty_list_item_overrides_do_not_synthesize():
    result = apply_overrides(make_two_text_template(), {"list-item_1": "", "text_1": "x"})

    column = result["template"]["components"][0]
    assert not [c for c in column["components"] if c["type"] == "list"]


def test_check_overflow_absorbs_card_unit_overflow():
    overrides = {f"heading_{n}": f"Card {n}" for n in range(1, 6)}
    overrides["button_9"] = "No home for this"

    overflow = check_overflow(CARDS_TEMPLATE, overrides)

    # heading_3..5 land in cloned columns; the cards carry no buttons anywhere
    assert overflow == ["button_9"]


# ---------------------------------------------------------------------------
# apply_section_background — band/text contrast
# ---------------------------------------------------------------------------


def test_low_contrast_captured_text_flips_to_readable():
    """Gray text captured onto an olive band (same luminance) flips to white."""
    from vanjaro_cli.utils.block_compose import apply_section_background

    section = {}
    apply_section_background(
        section, {"background_color": "rgb(106, 103, 71)", "text_color": "rgb(102, 102, 102)"}
    )

    style = section["attributes"]["style"]
    assert "background-color:rgb(106, 103, 71);" in style
    assert "color:#ffffff;" in style


def test_low_contrast_on_light_band_flips_to_dark():
    from vanjaro_cli.utils.block_compose import apply_section_background

    section = {}
    apply_section_background(section, {"background_color": "#f5f5f5", "text_color": "#eeeeee"})

    assert "color:#111111;" in section["attributes"]["style"]


def test_good_contrast_captured_text_is_kept():
    from vanjaro_cli.utils.block_compose import apply_section_background

    section = {}
    apply_section_background(section, {"background_color": "#1a1a1a", "text_color": "#eeeeee"})

    assert "color:#eeeeee;" in section["attributes"]["style"]


def test_light_band_without_captured_text_stays_default():
    from vanjaro_cli.utils.block_compose import apply_section_background

    section = {}
    apply_section_background(section, {"background_color": "#ffffff"})

    # only background-color is set — no standalone text color directive
    assert section["attributes"]["style"].count("color:") == 1


# ---------------------------------------------------------------------------
# _balance_card_rows — even per-row column counts
# ---------------------------------------------------------------------------


def _grid_template(n_cards: int) -> dict:
    cols = [
        {
            "type": "column",
            "classes": [{"name": "col-md-4", "active": False}],
            "attributes": {"id": f"c{i}"},
            "components": [{"type": "image", "tagName": "img",
                           "attributes": {"id": f"i{i}", "src": "", "alt": ""}}],
        }
        for i in range(1, n_cards + 1)
    ]
    return {
        "name": "Grid", "category": "Cards",
        "template": {"type": "section", "attributes": {"id": "s1"},
                     "components": [{"type": "row", "attributes": {"id": "r1"}, "components": cols}]},
        "styles": [],
    }


def _md_widths(template: dict) -> list[str]:
    widths = []
    def walk(c):
        if c.get("type") == "column":
            widths.extend(cl["name"] for cl in c.get("classes", []) if cl["name"].startswith("col-md"))
        for ch in c.get("components", []):
            walk(ch)
    walk(template["template"])
    return widths


def test_four_card_row_balances_to_four_across():
    composed = apply_overrides(_grid_template(4), {f"image_{i}_src": f"/{i}.jpg" for i in range(1, 5)})
    assert _md_widths(composed) == ["col-md-3"] * 4


def test_six_card_row_stays_three_across():
    composed = apply_overrides(_grid_template(6), {f"image_{i}_src": f"/{i}.jpg" for i in range(1, 7)})
    assert _md_widths(composed) == ["col-md-4"] * 6


def test_seven_cards_fall_back_to_three_across():
    composed = apply_overrides(_grid_template(7), {f"image_{i}_src": f"/{i}.jpg" for i in range(1, 8)})
    assert _md_widths(composed) == ["col-md-4"] * 7


def test_small_grid_is_left_untouched():
    composed = apply_overrides(_grid_template(3), {f"image_{i}_src": f"/{i}.jpg" for i in range(1, 4)})
    # 3 columns < 4 — below the rebalance threshold, template default kept
    assert _md_widths(composed) == ["col-md-4"] * 3
