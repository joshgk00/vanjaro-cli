"""Tests for vanjaro migrate assemble-page."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.commands.migrate_assemble_cmd import assemble_page
from vanjaro_cli.migration.overrides import crawl_content_to_overrides

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


# -- crawl_content_to_overrides --


def test_crawl_section_maps_first_heading_paragraph_button():
    content = {
        "headings": ["Welcome to VGRT", "Subtitle"],
        "paragraphs": ["Lead paragraph.", "Second paragraph."],
        "buttons": [{"text": "Get Started", "href": "/signup"}],
    }

    overrides = crawl_content_to_overrides(content)

    assert overrides["heading_1"] == "Welcome to VGRT"
    assert overrides["heading_2"] == "Subtitle"
    assert overrides["text_1"] == "Lead paragraph."
    assert overrides["text_2"] == "Second paragraph."
    assert overrides["button_1"] == "Get Started"
    assert overrides["button_1_href"] == "/signup"


def test_crawl_section_handles_missing_keys():
    overrides = crawl_content_to_overrides({})
    assert overrides == {}


def test_crawl_section_maps_images():
    content = {
        "images": [
            {"src": "https://example.com/hero.jpg", "alt": "Hero image"},
            {"src": "https://example.com/logo.png", "alt": "Company logo"},
        ],
    }

    overrides = crawl_content_to_overrides(content)

    assert overrides["image_1_src"] == "https://example.com/hero.jpg"
    assert overrides["image_1_alt"] == "Hero image"
    assert overrides["image_2_src"] == "https://example.com/logo.png"
    assert overrides["image_2_alt"] == "Company logo"


def test_crawl_section_skips_non_dict_images():
    content = {
        "images": ["not-a-dict", {"src": "https://example.com/ok.jpg", "alt": "Valid"}],
    }

    overrides = crawl_content_to_overrides(content)

    assert "image_1_src" not in overrides
    assert overrides["image_2_src"] == "https://example.com/ok.jpg"
    assert overrides["image_2_alt"] == "Valid"


def test_crawl_section_image_missing_alt():
    content = {
        "images": [{"src": "https://example.com/no-alt.jpg"}],
    }

    overrides = crawl_content_to_overrides(content)

    assert overrides["image_1_src"] == "https://example.com/no-alt.jpg"
    assert "image_1_alt" not in overrides


def test_crawl_section_maps_list_items():
    content = {
        "list_items": ["Home", "About", "Services", "Contact"],
    }

    overrides = crawl_content_to_overrides(content)

    assert overrides["list-item_1"] == "Home"
    assert overrides["list-item_2"] == "About"
    assert overrides["list-item_3"] == "Services"
    assert overrides["list-item_4"] == "Contact"


def test_crawl_section_skips_non_string_list_items():
    content = {
        "list_items": [None, "Valid", 42, "Also Valid"],
    }

    overrides = crawl_content_to_overrides(content)

    assert "list-item_1" not in overrides
    assert overrides["list-item_2"] == "Valid"
    assert "list-item_3" not in overrides
    assert overrides["list-item_4"] == "Also Valid"


def test_crawl_section_ignores_non_string_entries():
    content = {
        "headings": [None, "Only this one"],
        "buttons": ["not-a-dict", {"text": 42, "href": "/ok"}],
    }

    overrides = crawl_content_to_overrides(content)

    assert overrides["heading_2"] == "Only this one"
    assert "heading_1" not in overrides
    assert overrides["button_2_href"] == "/ok"
    assert "button_2" not in overrides


def test_crawl_section_maps_blockquotes_after_paragraphs():
    content = {
        "paragraphs": ["Intro paragraph."],
        "blockquotes": [
            {"text": "This product changed our workflow.", "citation": "Jane Smith"},
            {"text": "Support was incredible.", "citation": "John Doe"},
        ],
    }

    overrides = crawl_content_to_overrides(content)

    assert overrides["text_1"] == "Intro paragraph."
    assert overrides["text_2"] == "This product changed our workflow."
    assert overrides["text_3"] == "Support was incredible."


def test_crawl_section_maps_blockquotes_with_no_paragraphs():
    content = {
        "blockquotes": [{"text": "Great team.", "citation": ""}],
    }

    overrides = crawl_content_to_overrides(content)

    assert overrides["text_1"] == "Great team."


def test_crawl_section_skips_blockquote_already_in_paragraphs():
    """A section-specific rescope (see _rescope_testimonial) sometimes copies
    the quote into paragraphs before this mapping runs; the same quote text
    must not also be pulled from blockquotes, or it ships twice."""
    content = {
        "paragraphs": ["Great team.", "Second quote."],
        "blockquotes": [
            {"text": "Great team.", "citation": "Jane Smith"},
            {"text": "Second quote.", "citation": "John Doe"},
            {"text": "Only here.", "citation": "Alex Johnson"},
        ],
    }

    overrides = crawl_content_to_overrides(content)

    assert overrides["text_1"] == "Great team."
    assert overrides["text_2"] == "Second quote."
    assert overrides["text_3"] == "Only here."
    assert "text_4" not in overrides


def test_crawl_section_skips_non_dict_and_textless_blockquotes():
    """The crawler always emits blockquotes as {text, citation} dicts; guard
    against malformed entries the same way headings/buttons/images do."""
    content = {
        "blockquotes": ["not-a-dict", {"citation": "No text here"}, {"text": "Valid quote."}],
    }

    overrides = crawl_content_to_overrides(content)

    assert overrides["text_1"] == "Valid quote."
    assert "text_2" not in overrides


def test_crawl_section_blockquotes_respect_index_offset():
    content = {
        "paragraphs": ["Caption."],
        "blockquotes": [{"text": "Quote."}],
    }

    overrides = crawl_content_to_overrides(content, index_offset=1)

    assert overrides["text_2"] == "Caption."
    assert overrides["text_3"] == "Quote."


# -- CLI: Mode A (raw component trees) --


def test_assemble_mode_a_two_raw_sections(runner, tmp_path, write_json):
    section_one = write_json(tmp_path / "section-1-hero.json", _raw_section("s1", "First"))
    section_two = write_json(tmp_path / "section-2-cards.json", _raw_section("s2", "Second"))
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


def test_assemble_mode_b_template_reference(runner, tmp_path, monkeypatch, write_json):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = write_json(
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


def test_assemble_crawler_shape_maps_content_to_overrides(runner, tmp_path, monkeypatch, write_json):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = write_json(
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


def test_assemble_glob_expansion_sorts_lexically(runner, tmp_path, write_json):
    # Deliberately write in reverse order
    write_json(tmp_path / "section-2-cards.json", _raw_section("s2", "Two"))
    write_json(tmp_path / "section-1-hero.json", _raw_section("s1", "One"))
    write_json(tmp_path / "section-3-cta.json", _raw_section("s3", "Three"))

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


def test_assemble_glob_deduplicates_with_explicit_path(runner, tmp_path, write_json):
    section_one = write_json(tmp_path / "section-1.json", _raw_section("s1", "One"))
    write_json(tmp_path / "section-2.json", _raw_section("s2", "Two"))
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


def test_assemble_missing_template_reports_source_file(runner, tmp_path, monkeypatch, write_json):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = write_json(
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


def test_assemble_section_with_neither_components_nor_template_errors(runner, tmp_path, write_json):
    bad_file = write_json(tmp_path / "empty.json", {"foo": "bar"})
    output_file = tmp_path / "home.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(bad_file), "--output", str(output_file)],
    )

    assert result.exit_code != 0
    assert "empty.json" in result.output


# -- --json output shape --


def test_assemble_json_output_shape(runner, tmp_path, write_json):
    section_one = write_json(tmp_path / "a.json", _raw_section("s1", "First"))
    section_two = write_json(tmp_path / "b.json", _raw_section("s2", "Second"))
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


def test_assemble_expands_excess_list_items(runner, tmp_path, monkeypatch, write_json):
    """List items beyond the template's slot count ship via list expansion."""
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, FOOTER_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = write_json(
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
    assert "exceed template" not in result.output
    data = json.loads(output_file.read_text())
    assert len(data["components"]) == 1
    rendered = json.dumps(data)
    for item in ("Services", "Portfolio", "Contact"):
        assert item in rendered


RICH_TEXT_TEMPLATE = {
    "name": "Rich Text Block",
    "category": "Content",
    "description": "Heading plus body paragraphs",
    "template": {
        "type": "section",
        "attributes": {"id": "tpl-rt-s1"},
        "components": [{
            "type": "column",
            "attributes": {"id": "tpl-rt-c1"},
            "components": [
                {"type": "heading", "tagName": "h2", "content": "Heading Text", "attributes": {"id": "tpl-rt-h1"}},
                {"type": "text", "content": "Paragraph of text content.", "attributes": {"id": "tpl-rt-t1"}},
                {"type": "text", "content": "Paragraph of text content.", "attributes": {"id": "tpl-rt-t2"}},
            ],
        }],
    },
    "styles": [],
}


def test_assemble_expands_excess_headings(runner, tmp_path, monkeypatch, write_json):
    """Headings beyond the template's slot count ship via heading expansion.

    Quality-hc regression: Rich Text Block content sections carried a heading
    per subsection ("Find Comfort in The Home Promise Club!") and every
    heading past heading_1 was dropped, while paragraph overflow was absorbed.
    """
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, RICH_TEXT_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = write_json(
        tmp_path / "content.json",
        {
            "type": "content",
            "template": "Rich Text Block",
            "content": {
                "headings": ["The Home Promise Club", "Find Comfort in The Home Promise Club!"],
                "paragraphs": ["Intro.", "Lead-in.", "Perk one.", "Perk two."],
                "buttons": [],
                "list_items": [],
            },
        },
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(section_file), "--output", str(output_file)],
    )

    assert result.exit_code == 0, result.output
    assert "exceed template" not in result.output
    rendered = json.dumps(json.loads(output_file.read_text()))
    assert "Find Comfort in The Home Promise Club!" in rendered
    for paragraph in ("Intro.", "Lead-in.", "Perk one.", "Perk two."):
        assert paragraph in rendered


def test_assemble_warns_dropped_paragraphs_when_template_has_no_text_slot(
    runner, tmp_path, monkeypatch, write_json
):
    """A template with no text component cannot absorb paragraphs — they must
    warn on stderr as dropped keys, never vanish silently."""
    logo_bar = {
        "name": "Logo Bar",
        "category": "Content",
        "description": "Heading plus logos, no body text",
        "template": {
            "type": "section",
            "attributes": {"id": "tpl-lb-s1"},
            "components": [
                {"type": "heading", "tagName": "h2", "content": "Trusted By", "attributes": {"id": "tpl-lb-h1"}},
            ],
        },
        "styles": [],
    }
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, logo_bar)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = write_json(
        tmp_path / "logos.json",
        {
            "type": "gallery",
            "template": "Logo Bar",
            "content": {
                "headings": ["Trusted By"],
                "paragraphs": ["Orphan paragraph."],
                "buttons": [],
                "list_items": [],
            },
        },
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(section_file), "--output", str(output_file)],
    )

    assert result.exit_code == 0, result.output
    assert "exceed template" in result.output
    assert "text_1" in result.output
    assert "Orphan paragraph." not in output_file.read_text()


def test_assemble_no_warning_when_content_fits(runner, tmp_path, monkeypatch, write_json):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, FOOTER_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = write_json(
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


def test_assemble_wraps_with_header_and_footer_when_guids_provided(runner, tmp_path, write_json):
    section_file = write_json(
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


def test_assemble_wraps_only_header_when_footer_guid_omitted(runner, tmp_path, write_json):
    section_file = write_json(
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


def test_assemble_does_not_wrap_when_no_guids_provided(runner, tmp_path, write_json):
    """Existing callers that don't opt in to wrapping must keep the old shape."""
    section_file = write_json(
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


def test_assemble_wrapper_ids_are_unique(runner, tmp_path, write_json):
    """Header and footer wrappers must get distinct auto-generated ids."""
    section_file = write_json(
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


def test_assemble_applies_section_background_from_content(runner, tmp_path, monkeypatch, write_json):
    """Crawled background colors land as inline style on the composed section."""
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = write_json(
        tmp_path / "band.json",
        {
            "type": "cta",
            "template": "Centered Hero",
            "content": {
                "headings": ["Get started today!"],
                "background_color": "#640f0d",
            },
        },
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(section_file), "--output", str(output_file)],
    )

    assert result.exit_code == 0, result.output
    section = json.loads(output_file.read_text())["components"][0]
    style = section["attributes"]["style"]
    assert "background-color:#640f0d;" in style
    # Dark band with no explicit text color gets readable white text
    assert "color:#ffffff;" in style


def test_assemble_light_background_keeps_default_text_color(runner, tmp_path, monkeypatch, write_json):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = write_json(
        tmp_path / "light.json",
        {
            "type": "content",
            "template": "Centered Hero",
            "content": {
                "headings": ["Bright Section"],
                "background_color": "#e8e8e8",
            },
        },
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(section_file), "--output", str(output_file)],
    )

    assert result.exit_code == 0, result.output
    style = json.loads(output_file.read_text())["components"][0]["attributes"]["style"]
    assert "background-color:#e8e8e8;" in style
    assert "color:" not in style.replace("background-color:", "")


def test_assemble_background_image_and_rgb_dark_color(runner, tmp_path, monkeypatch, write_json):
    """Rendered-crawl rgb() colors and background images carry into the style."""
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = write_json(
        tmp_path / "band.json",
        {
            "type": "content",
            "template": "Centered Hero",
            "content": {
                "headings": ["Each Website Includes"],
                "background_color": "rgb(100, 15, 13)",
                "background_image": "https://source.test/blueprint.jpg",
            },
        },
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(section_file), "--output", str(output_file)],
    )

    assert result.exit_code == 0, result.output
    style = json.loads(output_file.read_text())["components"][0]["attributes"]["style"]
    assert "background-color:rgb(100, 15, 13);" in style
    assert "background-image:url(https://source.test/blueprint.jpg);" in style
    assert "background-size:cover" in style
    # rgb() dark band still gets auto-white text
    assert "color:#ffffff;" in style


def test_assemble_promotes_background_role_image_over_decorative_overlay(
    runner, tmp_path, monkeypatch, write_json
):
    """A hero/cta background-role photo becomes the band background, not an inline <img>."""
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = write_json(
        tmp_path / "section-1-cta.json",
        {
            "type": "cta",
            "template": "Centered Hero",
            "content": {
                "paragraphs": ["Crafting Total Comfort"],
                "images": [
                    {"src": "https://source.test/team-photo-1920w.jpg", "alt": "", "role": "background"}
                ],
                "buttons": [{"text": "Request a Quote", "href": "https://source.test/quote"}],
                "background_image": "https://source.test/bg-slant-1920w.png",
            },
        },
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(section_file), "--output", str(output_file)],
    )

    assert result.exit_code == 0, result.output
    section = json.loads(output_file.read_text())["components"][0]
    style = section["attributes"]["style"]
    assert "background-image:url(https://source.test/team-photo-1920w.jpg);" in style
    assert "bg-slant" not in style
    # The photo must not also render as an inline/floating <img>
    assert "team-photo" not in json.dumps(section["components"])


def test_crawler_sections_blank_unfilled_placeholder_slots(runner, tmp_path, monkeypatch, write_json):
    """Template placeholder copy must not leak when crawled content lacks a slot."""
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = write_json(
        tmp_path / "banner.json",
        {
            "type": "hero",
            "template": "Centered Hero",
            "content": {
                "background_image": "https://src.test/banner.jpg",
            },
        },
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(section_file), "--output", str(output_file)],
    )

    assert result.exit_code == 0, result.output
    rendered = json.dumps(json.loads(output_file.read_text()))
    for placeholder in ("Your Headline Here", "Get Started", "Hero heading"):
        assert placeholder not in rendered


def test_cloned_column_units_do_not_leak_placeholder_copy(runner, tmp_path, monkeypatch, write_json):
    """Slots in cloned column units must be blanked when overrides don't fill them."""
    cards_template = {
        "name": "Feature Cards",
        "category": "Cards",
        "description": "Two feature cards",
        "template": {
            "type": "section",
            "attributes": {"id": "tpl-fc-s1"},
            "components": [{
                "type": "row",
                "attributes": {"id": "tpl-fc-r1"},
                "components": [
                    {
                        "type": "column", "attributes": {"id": "tpl-fc-c1"},
                        "components": [
                            {"type": "heading", "content": "Project Title", "attributes": {"id": "tpl-fc-h1"}},
                            {"type": "image", "attributes": {"id": "tpl-fc-i1", "src": "", "alt": ""}},
                        ],
                    },
                    {
                        "type": "column", "attributes": {"id": "tpl-fc-c2"},
                        "components": [
                            {"type": "heading", "content": "Project Title", "attributes": {"id": "tpl-fc-h2"}},
                            {"type": "image", "attributes": {"id": "tpl-fc-i2", "src": "", "alt": ""}},
                        ],
                    },
                ],
            }],
        },
        "styles": [],
    }
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, cards_template)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    # 5 images but only 2 headings: 3 cloned columns gain placeholder headings
    section_file = write_json(
        tmp_path / "cards.json",
        {
            "type": "gallery",
            "template": "Feature Cards",
            "content": {
                "headings": ["One", "Two"],
                "images": [{"src": f"/img/{n}.jpg", "alt": ""} for n in range(1, 6)],
            },
        },
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(section_file), "--output", str(output_file)],
    )

    assert result.exit_code == 0, result.output
    rendered = json.loads(output_file.read_text())
    row = rendered["components"][0]["components"][0]
    assert len(row["components"]) == 5
    assert "Project Title" not in json.dumps(rendered)


# --- Global dedup stub resolution (--global-guids) ---


def _dedup_stub(key: str) -> dict:
    return {
        "global_key": key,
        "original_backup": {"type": "cta", "template": "CTA Strip", "content": {}},
        "components": [
            {
                "type": "globalblockwrapper",
                "name": "Global: CTA",
                "content": "",
                "attributes": {
                    "data-block-type": "global",
                    "data-guid": "{{global:%s}}" % key,
                    "id": "abc12",
                },
                "components": [],
            }
        ],
    }


def test_assemble_resolves_global_placeholder_from_manifest(runner, tmp_path, write_json):
    stub_file = write_json(tmp_path / "section-001-cta.json", _dedup_stub("global-cta"))
    manifest = write_json(tmp_path / "guids.json", {"global-cta": "real-guid-123"})
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        [
            "--sections", str(stub_file),
            "--output", str(output_file),
            "--global-guids", str(manifest),
        ],
    )

    assert result.exit_code == 0, result.output
    components = json.loads(output_file.read_text())["components"]
    assert len(components) == 1
    wrapper = components[0]
    assert wrapper["type"] == "globalblockwrapper"
    assert wrapper["attributes"]["data-guid"] == "real-guid-123"
    # Helper keys must never reach the assembled output.
    assert "global_key" not in wrapper
    assert "original_backup" not in wrapper
    assert "original_backup" not in output_file.read_text()


def test_assemble_errors_when_global_placeholder_has_no_manifest_entry(runner, tmp_path, write_json):
    stub_file = write_json(tmp_path / "section-001-cta.json", _dedup_stub("global-cta"))
    manifest = write_json(tmp_path / "guids.json", {"some-other-key": "guid"})
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        [
            "--sections", str(stub_file),
            "--output", str(output_file),
            "--global-guids", str(manifest),
        ],
    )

    assert result.exit_code != 0
    assert "global-cta" in result.output
    assert not output_file.exists()


# -- assemble --theme-palette (band colors -> theme classes) --


def test_assemble_theme_palette_maps_band_to_bg_class(runner, tmp_path, monkeypatch, write_json):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    palette_file = write_json(
        tmp_path / "palette.json", {"primary": "#00aa55", "light": "#f8f9fa"}
    )
    section_file = write_json(
        tmp_path / "band.json",
        {
            "type": "cta",
            "template": "Centered Hero",
            "content": {"headings": ["Hello"], "background_color": "#00aa55"},
        },
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        [
            "--sections", str(section_file),
            "--output", str(output_file),
            "--theme-palette", str(palette_file),
        ],
    )

    assert result.exit_code == 0, result.output
    section = json.loads(output_file.read_text())["components"][0]
    class_names = [c["name"] for c in section.get("classes", [])]
    assert "bg-primary" in class_names
    assert "text-light" in class_names
    assert "style" not in section["attributes"]


def test_assemble_theme_palette_unmatched_color_lands_in_styles(runner, tmp_path, monkeypatch, write_json):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    palette_file = write_json(tmp_path / "palette.json", {"primary": "#00aa55"})
    section_file = write_json(
        tmp_path / "band.json",
        {
            "type": "content",
            "template": "Centered Hero",
            "content": {"headings": ["Hello"], "background_color": "#7b1fa2"},
        },
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        [
            "--sections", str(section_file),
            "--output", str(output_file),
            "--theme-palette", str(palette_file),
        ],
    )

    assert result.exit_code == 0, result.output
    result_json = json.loads(output_file.read_text())
    section = result_json["components"][0]
    section_id = section["attributes"]["id"]
    assert "style" not in section["attributes"]
    def _targets(rule: dict) -> bool:
        first = (rule.get("selectors") or [None])[0]
        return isinstance(first, dict) and first.get("name") == section_id

    band_rules = [
        rule for rule in result_json["styles"]
        if _targets(rule) and "background-color" in rule.get("style", {})
    ]
    assert len(band_rules) == 1
    assert band_rules[0]["style"]["background-color"] == "#7b1fa2"


def test_assemble_without_palette_keeps_inline_style(runner, tmp_path, monkeypatch, write_json):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = write_json(
        tmp_path / "band.json",
        {
            "type": "cta",
            "template": "Centered Hero",
            "content": {"headings": ["Hello"], "background_color": "#00aa55"},
        },
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        ["--sections", str(section_file), "--output", str(output_file)],
    )

    assert result.exit_code == 0, result.output
    section = json.loads(output_file.read_text())["components"][0]
    assert "background-color:#00aa55;" in section["attributes"]["style"]
    assert "classes" not in section


def test_assemble_bad_palette_file_errors(runner, tmp_path, monkeypatch, write_json):
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, HERO_TEMPLATE)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    section_file = write_json(
        tmp_path / "band.json",
        {"type": "cta", "template": "Centered Hero", "content": {"headings": ["Hi"]}},
    )
    output_file = tmp_path / "out.json"

    result = runner.invoke(
        assemble_page,
        [
            "--sections", str(section_file),
            "--output", str(output_file),
            "--theme-palette", str(tmp_path / "missing.json"),
        ],
    )

    assert result.exit_code != 0
    assert "Cannot read palette file" in result.output


def test_crawl_section_index_offset_shifts_headings_and_text_only():
    """Gallery-shaped templates lead with a section-title heading/text pair,
    so per-item headings/texts shift by one while images stay put."""
    content = {
        "headings": ["Card A", "Card B"],
        "paragraphs": ["First caption.", "Second caption."],
        "images": [
            {"src": "/a.jpg", "alt": "A"},
            {"src": "/b.jpg", "alt": "B"},
        ],
    }

    overrides = crawl_content_to_overrides(content, index_offset=1)

    assert "heading_1" not in overrides
    assert overrides["heading_2"] == "Card A"
    assert overrides["heading_3"] == "Card B"
    assert "text_1" not in overrides
    assert overrides["text_2"] == "First caption."
    assert overrides["image_1_src"] == "/a.jpg"
    assert overrides["image_2_src"] == "/b.jpg"
