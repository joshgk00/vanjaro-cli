"""Tests for vanjaro blocks scaffold command."""

from __future__ import annotations

import json

from vanjaro_cli.cli import cli


def test_scaffold_hero(runner, mock_config):
    result = runner.invoke(cli, ["blocks", "scaffold", "--sections", "hero"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "components" in data
    assert len(data["components"]) == 1
    section = data["components"][0]
    assert section["type"] == "section"


def test_scaffold_multiple_sections(runner, mock_config):
    result = runner.invoke(cli, ["blocks", "scaffold", "--sections", "hero-simple,content,cta"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data["components"]) == 3


def test_scaffold_all_section_types(runner, mock_config):
    all_sections = "hero,hero-simple,content,cards-3,testimonials,bio,checklist,cta,form,features-4,program"
    result = runner.invoke(cli, ["blocks", "scaffold", "--sections", all_sections])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data["components"]) == 11


def test_scaffold_output_to_file(runner, mock_config, tmp_path):
    output_file = tmp_path / "layout.json"
    result = runner.invoke(cli, ["blocks", "scaffold", "--sections", "hero,cta", "--output", str(output_file)])

    assert result.exit_code == 0
    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert len(data["components"]) == 2
    assert "Layout written to" in result.output


def test_scaffold_unknown_section(runner, mock_config):
    result = runner.invoke(cli, ["blocks", "scaffold", "--sections", "nonexistent"])

    assert result.exit_code == 1
    assert "Unknown section type" in result.output


def test_scaffold_hero_has_two_columns(runner, mock_config):
    result = runner.invoke(cli, ["blocks", "scaffold", "--sections", "hero"])

    data = json.loads(result.output)
    section = data["components"][0]
    grid = section["components"][0]
    row = grid["components"][0]
    assert len(row["components"]) == 2


def test_scaffold_cards_has_three_columns(runner, mock_config):
    result = runner.invoke(cli, ["blocks", "scaffold", "--sections", "cards-3"])

    data = json.loads(result.output)
    section = data["components"][0]
    grid = section["components"][0]
    rows = grid["components"]
    card_row = [r for r in rows if len(r.get("components", [])) == 3][0]
    assert len(card_row["components"]) == 3


def test_scaffold_features_has_four_columns(runner, mock_config):
    result = runner.invoke(cli, ["blocks", "scaffold", "--sections", "features-4"])

    data = json.loads(result.output)
    section = data["components"][0]
    grid = section["components"][0]
    rows = grid["components"]
    feature_row = [r for r in rows if len(r.get("components", [])) == 4][0]
    assert len(feature_row["components"]) == 4


def test_scaffold_components_have_unique_ids(runner, mock_config):
    result = runner.invoke(cli, ["blocks", "scaffold", "--sections", "hero,content,cta"])

    data = json.loads(result.output)

    def collect_ids(components):
        ids = set()
        for comp in components:
            comp_id = comp.get("attributes", {}).get("id", "")
            if comp_id:
                ids.add(comp_id)
            ids.update(collect_ids(comp.get("components", [])))
        return ids

    all_ids = collect_ids(data["components"])
    assert len(all_ids) > 10


def test_scaffold_output_is_content_update_compatible(runner, mock_config):
    """The output shape should work with `content update --file`."""
    result = runner.invoke(cli, ["blocks", "scaffold", "--sections", "hero"])

    data = json.loads(result.output)
    assert "components" in data
    assert "styles" in data
    assert isinstance(data["components"], list)
    assert isinstance(data["styles"], list)
