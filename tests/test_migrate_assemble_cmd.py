"""Tests for vanjaro migrate assemble-page."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.commands.migrate_assemble_cmd import (
    _crawl_section_to_overrides,
    assemble_page,
)

HERO_TEMPLATE = {
    "name": "Centered Hero",
    "category": "Heroes",
    "description": "Full-width hero with centered heading, subtext, and CTA button",
    "template": {
        "type": "section",
        "attributes": {"id": "tpl-hero-s1"},
        "components": [
            {
                "type": "heading",
                "tagName": "h1",
                "content": "Your Headline Here",
                "attributes": {"id": "tpl-hero-h1"},
            },
            {
                "type": "text",
                "content": "Supporting text goes here.",
                "attributes": {"id": "tpl-hero-t1"},
            },
            {
                "type": "button",
                "tagName": "a",
                "content": "Get Started",
                "attributes": {"id": "tpl-hero-b1", "href": "#"},
            },
        ],
    },
    "styles": [{"selectors": [".hero"], "style": {"padding": "2rem"}}],
}


def _write_template(templates_dir: Path, template: dict) -> None:
    category_dir = templates_dir / template["category"]
    category_dir.mkdir(parents=True, exist_ok=True)
    filename = template["name"].lower().replace(" ", "-") + ".json"
    (category_dir / filename).write_text(json.dumps(template))


def _write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def _raw_section(section_id: str, heading_text: str) -> dict:
    return {
        "type": "section",
        "attributes": {"id": section_id},
        "components": [
            {
                "type": "heading",
                "tagName": "h2",
                "content": heading_text,
                "attributes": {"id": f"{section_id}-h"},
            },
        ],
    }


# -- _crawl_section_to_overrides --


def test_crawl_section_maps_first_heading_paragraph_button():
    content = {
        "headings": ["Welcome to VGRT", "Subtitle"],
        "paragraphs": ["Lead paragraph.", "Second paragraph."],
        "buttons": [{"text": "Get Started", "href": "/signup"}],
    }

    overrides = _crawl_section_to_overrides(content)

    assert overrides["heading_1"] == "Welcome to VGRT"
    assert overrides["heading_2"] == "Subtitle"
    assert overrides["text_1"] == "Lead paragraph."
    assert overrides["text_2"] == "Second paragraph."
    assert overrides["button_1"] == "Get Started"
    assert overrides["button_1_href"] == "/signup"


def test_crawl_section_handles_missing_keys():
    overrides = _crawl_section_to_overrides({})
    assert overrides == {}


def test_crawl_section_maps_images():
    content = {
        "images": [
            {"src": "https://example.com/hero.jpg", "alt": "Hero image"},
            {"src": "https://example.com/logo.png", "alt": "Company logo"},
        ],
    }

    overrides = _crawl_section_to_overrides(content)

    assert overrides["image_1_src"] == "https://example.com/hero.jpg"
    assert overrides["image_1_alt"] == "Hero image"
    assert overrides["image_2_src"] == "https://example.com/logo.png"
    assert overrides["image_2_alt"] == "Company logo"


def test_crawl_section_skips_non_dict_images():
    content = {
        "images": ["not-a-dict", {"src": "https://example.com/ok.jpg", "alt": "Valid"}],
    }

    overrides = _crawl_section_to_overrides(content)

    assert "image_1_src" not in overrides
    assert overrides["image_2_src"] == "https://example.com/ok.jpg"
    assert overrides["image_2_alt"] == "Valid"


def test_crawl_section_image_missing_alt():
    content = {
        "images": [{"src": "https://example.com/no-alt.jpg"}],
    }

    overrides = _crawl_section_to_overrides(content)

    assert overrides["image_1_src"] == "https://example.com/no-alt.jpg"
    assert "image_1_alt" not in overrides


def test_crawl_section_maps_list_items():
    content = {
        "list_items": ["Home", "About", "Services", "Contact"],
    }

    overrides = _crawl_section_to_overrides(content)

    assert overrides["list-item_1"] == "Home"
    assert overrides["list-item_2"] == "About"
    assert overrides["list-item_3"] == "Services"
    assert overrides["list-item_4"] == "Contact"


def test_crawl_section_skips_non_string_list_items():
    content = {
        "list_items": [None, "Valid", 42, "Also Valid"],
    }

    overrides = _crawl_section_to_overrides(content)

    assert "list-item_1" not in overrides
    assert overrides["list-item_2"] == "Valid"
    assert "list-item_3" not in overrides
    assert overrides["list-item_4"] == "Also Valid"


def test_crawl_section_ignores_non_string_entries():
    content = {
        "headings": [None, "Only this one"],
        "buttons": ["not-a-dict", {"text": 42, "href": "/ok"}],
    }

    overrides = _crawl_section_to_overrides(content)

    assert overrides["heading_2"] == "Only this one"
    assert "heading_1" not in overrides
    assert overrides["button_2_href"] == "/ok"
    assert "button_2" not in overrides


# -- CLI: Mode A (raw component trees) --


def test_assemble_mode_a_two_raw_sections(runner, tmp_path):
    section_one = _write_json(tmp_path / "section-1-hero.json", _raw_section("s1", "First"))
    section_two = _write_json(tmp_path / "section-2-cards.json", _raw_section("s2", "Second"))
    output_file = tmp_path / "home.json"

    result = runner.invoke(
        assemble_page,
        [
            "--sections", str(section_one),
            "--sections", str(section_two),
            "--output", str(output_file),
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(output_file.read_text())
    assert len(data["components"]) == 2
    assert data["components"][0]["attributes"]["id"] == "s1"
    assert data["components"][1]["attributes"]["id"] == "s2"
    assert data["styles"] == []


# -- CLI: Mode B (template reference + explicit overrides) --


def test_assemble_mode_b_template_reference(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = _write_json(
        tmp_path / "hero.json",
        {
            "template": "Centered Hero",
            "overrides": {"heading_1": "Welcome Home", "button_1_href": "/start"},
        },
    )
    output_file = tmp_path / "home.json"

    result = runner.invoke(
        assemble_page,
        [
            "--sections", str(section_file),
            "--output", str(output_file),
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(output_file.read_text())
    assert len(data["components"]) == 1
    section = data["components"][0]
    assert section["type"] == "section"
    assert section["components"][0]["content"] == "Welcome Home"
    assert section["components"][2]["attributes"]["href"] == "/start"
    # Styles from the composed template are carried up
    assert data["styles"] == HERO_TEMPLATE["styles"]


# -- CLI: crawler shape (template + content) --


def test_assemble_crawler_shape_maps_content_to_overrides(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = _write_json(
        tmp_path / "crawled.json",
        {
            "type": "hero",
            "template": "Centered Hero",
            "content": {
                "headings": ["Crawled Heading"],
                "paragraphs": ["Crawled body text."],
                "buttons": [{"text": "Go", "href": "/go"}],
            },
        },
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(section_file), "--output", str(output_file)],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(output_file.read_text())
    section = data["components"][0]
    assert section["components"][0]["content"] == "Crawled Heading"
    assert section["components"][1]["content"] == "Crawled body text."
    assert section["components"][2]["content"] == "Go"
    assert section["components"][2]["attributes"]["href"] == "/go"


# -- Glob expansion / ordering --


def test_assemble_glob_expansion_sorts_lexically(runner, tmp_path):
    # Deliberately write in reverse order
    _write_json(tmp_path / "section-2-cards.json", _raw_section("s2", "Two"))
    _write_json(tmp_path / "section-1-hero.json", _raw_section("s1", "One"))
    _write_json(tmp_path / "section-3-cta.json", _raw_section("s3", "Three"))

    output_file = tmp_path / "home.json"
    pattern = str(tmp_path / "section-*.json")

    result = runner.invoke(
        assemble_page,
        ["--sections", pattern, "--output", str(output_file)],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(output_file.read_text())
    ids = [c["attributes"]["id"] for c in data["components"]]
    assert ids == ["s1", "s2", "s3"]


def test_assemble_glob_deduplicates_with_explicit_path(runner, tmp_path):
    section_one = _write_json(tmp_path / "section-1.json", _raw_section("s1", "One"))
    _write_json(tmp_path / "section-2.json", _raw_section("s2", "Two"))
    output_file = tmp_path / "home.json"
    pattern = str(tmp_path / "section-*.json")

    result = runner.invoke(
        assemble_page,
        [
            "--sections", str(section_one),
            "--sections", pattern,
            "--output", str(output_file),
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(output_file.read_text())
    ids = [c["attributes"]["id"] for c in data["components"]]
    assert ids == ["s1", "s2"]


# -- Error paths --


def test_assemble_missing_file_reports_clear_error(runner, tmp_path):
    output_file = tmp_path / "home.json"
    missing = tmp_path / "nope.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(missing), "--output", str(output_file)],
    )

    assert result.exit_code != 0
    assert "not found" in result.output.lower()
    assert "nope.json" in result.output


def test_assemble_glob_no_matches_errors(runner, tmp_path):
    output_file = tmp_path / "home.json"
    pattern = str(tmp_path / "does-not-exist-*.json")

    result = runner.invoke(
        assemble_page,
        ["--sections", pattern, "--output", str(output_file)],
    )

    assert result.exit_code != 0
    assert "No files matched" in result.output or "no files matched" in result.output.lower()


def test_assemble_invalid_json_reports_file(runner, tmp_path):
    bad_file = tmp_path / "broken.json"
    bad_file.write_text("{not json")
    output_file = tmp_path / "home.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(bad_file), "--output", str(output_file)],
    )

    assert result.exit_code != 0
    assert "broken.json" in result.output
    assert "Invalid JSON" in result.output or "invalid json" in result.output.lower()


def test_assemble_missing_template_reports_source_file(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = _write_json(
        tmp_path / "bad-template.json",
        {"template": "Nonexistent Template", "overrides": {}},
    )
    output_file = tmp_path / "home.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(section_file), "--output", str(output_file)],
    )

    assert result.exit_code != 0
    assert "Nonexistent Template" in result.output
    assert "bad-template.json" in result.output


def test_assemble_section_with_neither_components_nor_template_errors(runner, tmp_path):
    bad_file = _write_json(tmp_path / "empty.json", {"foo": "bar"})
    output_file = tmp_path / "home.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(bad_file), "--output", str(output_file)],
    )

    assert result.exit_code != 0
    assert "empty.json" in result.output


# -- --json output shape --


def test_assemble_json_output_shape(runner, tmp_path):
    section_one = _write_json(tmp_path / "a.json", _raw_section("s1", "First"))
    section_two = _write_json(tmp_path / "b.json", _raw_section("s2", "Second"))
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        [
            "--sections", str(section_one),
            "--sections", str(section_two),
            "--output", str(output_file),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["sections"] == 2
    assert payload["components"] == 2
    assert payload["output"].endswith("out.json")


# -- overflow warning --

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
                        {"type": "heading", "tagName": "h5", "content": "Links", "attributes": {"id": "tpl-foot-h1"}},
                        {
                            "type": "list",
                            "attributes": {"id": "tpl-foot-l1"},
                            "components": [
                                {"type": "list-item", "content": "Home", "attributes": {"id": "tpl-foot-li1"}},
                                {"type": "list-item", "content": "About", "attributes": {"id": "tpl-foot-li2"}},
                            ],
                        },
                    ],
                }],
            }],
        }],
    },
    "styles": [],
}


def test_assemble_warns_on_overflow(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, FOOTER_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = _write_json(
        tmp_path / "footer.json",
        {
            "type": "footer",
            "template": "Footer Links",
            "content": {
                "headings": ["Quick Links"],
                "paragraphs": [],
                "buttons": [],
                "list_items": ["Home", "About", "Services", "Portfolio", "Contact"],
            },
        },
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(section_file), "--output", str(output_file)],
    )

    assert result.exit_code == 0, result.output
    assert "list-item_3" in result.output or "list-item_3" in (result.stderr or "")
    data = json.loads(output_file.read_text())
    assert len(data["components"]) == 1


def test_assemble_no_warning_when_content_fits(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, FOOTER_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = _write_json(
        tmp_path / "footer.json",
        {
            "type": "footer",
            "template": "Footer Links",
            "content": {
                "headings": ["Links"],
                "paragraphs": [],
                "buttons": [],
                "list_items": ["Home", "About"],
            },
        },
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(section_file), "--output", str(output_file)],
    )

    assert result.exit_code == 0, result.output
    assert "dropped" not in result.output.lower()
    assert "Warning" not in result.output


# --- Global block wrapping ---


def test_assemble_wraps_with_header_and_footer_when_guids_provided(runner, tmp_path):
    section_file = _write_json(
        tmp_path / "sections" / "s.json",
        _raw_section("s1", "Hello"),
    )
    output_file = tmp_path / "wrapped.json"

    result = runner.invoke(
        assemble_page,
        [
            "--sections", str(section_file),
            "--output", str(output_file),
            "--header-block-guid", "20020077-89f8-468f-a488-017421ce5a0b",
            "--footer-block-guid", "fe37ff48-2c99-4201-85fc-913cac94914d",
        ],
    )

    assert result.exit_code == 0, result.output
    content = json.loads(output_file.read_text())
    components = content["components"]
    assert len(components) == 3
    assert components[0]["type"] == "globalblockwrapper"
    assert components[0]["name"] == "Global: Header"
    assert components[0]["attributes"]["data-guid"] == "20020077-89f8-468f-a488-017421ce5a0b"
    assert components[0]["attributes"]["data-block-type"] == "global"
    assert components[1]["type"] == "section"  # the real page section stays in the middle
    assert components[2]["type"] == "globalblockwrapper"
    assert components[2]["name"] == "Global: Footer"
    assert components[2]["attributes"]["data-guid"] == "fe37ff48-2c99-4201-85fc-913cac94914d"


def test_assemble_wraps_only_header_when_footer_guid_omitted(runner, tmp_path):
    section_file = _write_json(
        tmp_path / "sections" / "s.json",
        _raw_section("s1", "Hello"),
    )
    output_file = tmp_path / "header-only.json"

    result = runner.invoke(
        assemble_page,
        [
            "--sections", str(section_file),
            "--output", str(output_file),
            "--header-block-guid", "abc",
        ],
    )

    assert result.exit_code == 0
    components = json.loads(output_file.read_text())["components"]
    assert len(components) == 2
    assert components[0]["type"] == "globalblockwrapper"
    assert components[1]["type"] == "section"


def test_assemble_does_not_wrap_when_no_guids_provided(runner, tmp_path):
    """Existing callers that don't opt in to wrapping must keep the old shape."""
    section_file = _write_json(
        tmp_path / "sections" / "s.json",
        _raw_section("s1", "Hello"),
    )
    output_file = tmp_path / "unwrapped.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(section_file), "--output", str(output_file)],
    )

    assert result.exit_code == 0
    components = json.loads(output_file.read_text())["components"]
    assert len(components) == 1
    assert components[0]["type"] == "section"
    assert not any(c.get("type") == "globalblockwrapper" for c in components)


def test_assemble_wrapper_ids_are_unique(runner, tmp_path):
    """Header and footer wrappers must get distinct auto-generated ids."""
    section_file = _write_json(
        tmp_path / "sections" / "s.json",
        _raw_section("s1", "Hello"),
    )
    output_file = tmp_path / "wrapped.json"

    runner.invoke(
        assemble_page,
        [
            "--sections", str(section_file),
            "--output", str(output_file),
            "--header-block-guid", "h",
            "--footer-block-guid", "f",
        ],
    )

    components = json.loads(output_file.read_text())["components"]
    header_id = components[0]["attributes"]["id"]
    footer_id = components[2]["attributes"]["id"]
    assert header_id != footer_id
    assert header_id
    assert footer_id
