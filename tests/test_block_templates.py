"""Tests for vanjaro blocks templates command."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.cli import cli


def _create_template(
    templates_dir: Path,
    category: str,
    filename: str,
    name: str,
    description: str,
) -> Path:
    """Create a template JSON file in the given category subdirectory."""
    category_dir = templates_dir / category
    category_dir.mkdir(parents=True, exist_ok=True)
    template_file = category_dir / filename
    template_file.write_text(json.dumps({
        "name": name,
        "category": category,
        "description": description,
        "template": {"type": "section", "components": []},
        "styles": [],
    }))
    return template_file


# -- list --


def test_block_templates_list(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "block-templates"
    _create_template(templates_dir, "Heroes", "centered-hero.json", "Centered Hero", "A centered hero section")
    _create_template(templates_dir, "Cards", "feature-cards.json", "Feature Cards", "Three feature cards")
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, ["blocks", "templates"])

    assert result.exit_code == 0
    assert "Centered Hero" in result.output
    assert "Feature Cards" in result.output
    assert "Heroes" in result.output
    assert "Cards" in result.output


def test_block_templates_list_json(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "block-templates"
    _create_template(templates_dir, "Heroes", "centered-hero.json", "Centered Hero", "A centered hero section")
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, ["blocks", "templates", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["name"] == "Centered Hero"
    assert data[0]["category"] == "Heroes"
    assert data[0]["description"] == "A centered hero section"
    assert data[0]["file"] == "Heroes/centered-hero.json"


# -- category filter --


def test_block_templates_filter_by_category(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "block-templates"
    _create_template(templates_dir, "Heroes", "centered-hero.json", "Centered Hero", "A hero section")
    _create_template(templates_dir, "Cards", "feature-cards.json", "Feature Cards", "Three cards")
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, ["blocks", "templates", "--category", "Heroes"])

    assert result.exit_code == 0
    assert "Centered Hero" in result.output
    assert "Feature Cards" not in result.output


def test_block_templates_category_case_insensitive(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "block-templates"
    _create_template(templates_dir, "Heroes", "hero.json", "Hero Banner", "A hero banner")
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, ["blocks", "templates", "--category", "heroes"])

    assert result.exit_code == 0
    assert "Hero Banner" in result.output


# -- empty / missing --


def test_block_templates_empty_directory(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "block-templates"
    templates_dir.mkdir()
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, ["blocks", "templates"])

    assert result.exit_code == 0
    assert "No block templates found." in result.output


def test_block_templates_empty_with_category_filter(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "block-templates"
    _create_template(templates_dir, "Heroes", "hero.json", "Hero", "A hero")
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, ["blocks", "templates", "--category", "NonExistent"])

    assert result.exit_code == 0
    assert "No block templates found in category 'NonExistent'." in result.output


def test_block_templates_missing_directory(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(tmp_path / "nonexistent"))

    result = runner.invoke(cli, ["blocks", "templates"])

    assert result.exit_code == 0
    assert "No block templates found." in result.output


# -- edge cases --


def test_block_templates_skips_invalid_json(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "block-templates"
    _create_template(templates_dir, "Heroes", "good.json", "Good Template", "Valid template")
    bad_file = templates_dir / "Heroes" / "bad.json"
    bad_file.write_text("not valid json {{{")
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, ["blocks", "templates"])

    assert result.exit_code == 0
    assert "Good Template" in result.output


def test_block_templates_json_includes_file_path(runner, tmp_path, monkeypatch):
    templates_dir = tmp_path / "block-templates"
    _create_template(templates_dir, "CTAs", "cta-banner.json", "CTA Banner", "A call to action")
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(cli, ["blocks", "templates", "--json"])

    data = json.loads(result.output)
    assert data[0]["file"] == "CTAs/cta-banner.json"
