"""Tests for vanjaro blocks build-library command."""

from __future__ import annotations

import json
from pathlib import Path

import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

CUSTOM_ADD_URL = f"{BASE_URL}/API/Vanjaro/Block/AddCustomBlock"
CUSTOM_LIST_URL = f"{BASE_URL}/API/Vanjaro/Block/GetAllCustomBlock"
GLOBAL_CREATE_URL = f"{BASE_URL}/API/VanjaroAI/AIGlobalBlock/Create"

HERO_TEMPLATE = {
    "name": "Centered Hero",
    "category": "Heroes",
    "description": "A hero section",
    "template": {
        "type": "section",
        "attributes": {"id": "tpl-s1"},
        "components": [{
            "type": "grid",
            "attributes": {"id": "tpl-g1"},
            "components": [{
                "type": "row",
                "attributes": {"id": "tpl-r1"},
                "components": [{
                    "type": "column",
                    "attributes": {"id": "tpl-c1"},
                    "components": [
                        {"type": "heading", "tagName": "h1", "content": "Placeholder", "attributes": {"id": "tpl-h1"}},
                        {"type": "text", "content": "Placeholder text.", "attributes": {"id": "tpl-t1"}},
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
    "description": "Feature cards",
    "template": {
        "type": "section",
        "attributes": {"id": "tpl-s1"},
        "components": [{
            "type": "grid",
            "attributes": {"id": "tpl-g1"},
            "components": [{
                "type": "row",
                "attributes": {"id": "tpl-r1"},
                "components": [
                    {"type": "column", "attributes": {"id": "tpl-c1"}, "components": [
                        {"type": "heading", "tagName": "h3", "content": "Card One", "attributes": {"id": "tpl-h1"}},
                    ]},
                    {"type": "column", "attributes": {"id": "tpl-c2"}, "components": [
                        {"type": "heading", "tagName": "h3", "content": "Card Two", "attributes": {"id": "tpl-h2"}},
                    ]},
                ],
            }],
        }],
    },
    "styles": [],
}


def _setup_templates(tmp_path: Path) -> Path:
    """Write test templates and return the templates directory."""
    templates_dir = tmp_path / "templates"
    for tpl in (HERO_TEMPLATE, CARDS_TEMPLATE):
        cat_dir = templates_dir / tpl["category"]
        cat_dir.mkdir(parents=True, exist_ok=True)
        filename = tpl["name"].lower().replace(" ", "-") + ".json"
        (cat_dir / filename).write_text(json.dumps(tpl))
    return templates_dir


def _write_plan(tmp_path: Path, plan: list) -> Path:
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan))
    return plan_file


# -- dry run --


def test_build_library_dry_run(runner, tmp_path, monkeypatch):
    templates_dir = _setup_templates(tmp_path)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    plan_file = _write_plan(tmp_path, [
        {"template": "Centered Hero", "name": "Site Hero", "overrides": {"heading_1": "Welcome"}},
        {"template": "Feature Cards", "name": "Site Cards", "type": "custom"},
    ])

    result = runner.invoke(cli, ["blocks", "build-library", "--plan", str(plan_file), "--dry-run"])

    assert result.exit_code == 0
    assert "DRY   Site Hero" in result.output
    assert "DRY   Site Cards" in result.output
    assert "1 override" in result.output
    assert "2 block(s) would be created" in result.output


def test_build_library_dry_run_json(runner, tmp_path, monkeypatch):
    templates_dir = _setup_templates(tmp_path)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    plan_file = _write_plan(tmp_path, [
        {"template": "Centered Hero", "name": "Site Hero"},
    ])

    result = runner.invoke(cli, ["blocks", "build-library", "--plan", str(plan_file), "--dry-run", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert len(data["results"]) == 1
    assert data["results"][0]["status"] == "dry_run"
    assert data["results"][0]["template"] == "Centered Hero"
    assert data["summary"]["total"] == 1


# -- output-dir --


def test_build_library_output_dir(runner, tmp_path, monkeypatch):
    templates_dir = _setup_templates(tmp_path)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    output_dir = tmp_path / "output"
    plan_file = _write_plan(tmp_path, [
        {"template": "Centered Hero", "name": "Site Hero", "overrides": {"heading_1": "Custom Heading"}},
    ])

    result = runner.invoke(cli, [
        "blocks", "build-library",
        "--plan", str(plan_file),
        "--output-dir", str(output_dir),
    ])

    assert result.exit_code == 0
    assert "WROTE" in result.output
    assert "1 file(s)" in result.output

    written_file = output_dir / "site-hero.json"
    assert written_file.exists()
    composed = json.loads(written_file.read_text())
    heading = composed["template"]["components"][0]["components"][0]["components"][0]["components"][0]
    assert heading["content"] == "Custom Heading"


def test_build_library_output_dir_multiple(runner, tmp_path, monkeypatch):
    templates_dir = _setup_templates(tmp_path)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    output_dir = tmp_path / "output"
    plan_file = _write_plan(tmp_path, [
        {"template": "Centered Hero", "name": "Site Hero"},
        {"template": "Feature Cards", "name": "Site Cards"},
    ])

    result = runner.invoke(cli, [
        "blocks", "build-library",
        "--plan", str(plan_file),
        "--output-dir", str(output_dir),
    ])

    assert result.exit_code == 0
    assert (output_dir / "site-hero.json").exists()
    assert (output_dir / "site-cards.json").exists()


# -- register custom blocks --


@responses.activate
def test_build_library_register_custom(runner, mock_config, tmp_path, monkeypatch):
    templates_dir = _setup_templates(tmp_path)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    mock_homepage()
    responses.add(responses.POST, CUSTOM_ADD_URL, json={"Status": "Success"}, status=200)
    responses.add(responses.GET, CUSTOM_LIST_URL, json=[
        {"ID": 1, "Guid": "aaa-bbb-ccc", "Name": "Site Hero", "Category": "Heroes", "ContentJSON": "[]", "StyleJSON": "[]"},
    ], status=200)

    plan_file = _write_plan(tmp_path, [
        {"template": "Centered Hero", "name": "Site Hero", "overrides": {"heading_1": "Welcome"}},
    ])

    result = runner.invoke(cli, ["blocks", "build-library", "--plan", str(plan_file)])

    assert result.exit_code == 0
    assert "OK    Site Hero" in result.output
    assert "aaa-bbb-" in result.output
    assert "Created 1/1" in result.output


@responses.activate
def test_build_library_register_custom_json(runner, mock_config, tmp_path, monkeypatch):
    templates_dir = _setup_templates(tmp_path)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    mock_homepage()
    responses.add(responses.POST, CUSTOM_ADD_URL, json={"Status": "Success"}, status=200)
    responses.add(responses.GET, CUSTOM_LIST_URL, json=[
        {"ID": 1, "Guid": "guid-123", "Name": "Site Hero", "Category": "Heroes", "ContentJSON": "[]", "StyleJSON": "[]"},
    ], status=200)

    plan_file = _write_plan(tmp_path, [
        {"template": "Centered Hero", "name": "Site Hero"},
    ])

    result = runner.invoke(cli, ["blocks", "build-library", "--plan", str(plan_file), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["results"][0]["status"] == "created"
    assert data["results"][0]["guid"] == "guid-123"
    assert data["summary"]["created"] == 1


# -- register global blocks --


@responses.activate
def test_build_library_register_global(runner, mock_config, tmp_path, monkeypatch):
    templates_dir = _setup_templates(tmp_path)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    mock_homepage()
    responses.add(responses.POST, GLOBAL_CREATE_URL, json={"guid": "global-guid-456"}, status=200)

    plan_file = _write_plan(tmp_path, [
        {"template": "Centered Hero", "name": "Global Hero", "type": "global"},
    ])

    result = runner.invoke(cli, ["blocks", "build-library", "--plan", str(plan_file)])

    assert result.exit_code == 0
    assert "OK    Global Hero" in result.output
    assert "global-g" in result.output


@responses.activate
def test_build_library_sends_correct_payloads(runner, mock_config, tmp_path, monkeypatch):
    """Verify the API receives correct content and category."""
    templates_dir = _setup_templates(tmp_path)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    mock_homepage()
    responses.add(responses.POST, CUSTOM_ADD_URL, json={"Status": "Success"}, status=200)
    responses.add(responses.GET, CUSTOM_LIST_URL, json=[
        {"ID": 1, "Guid": "g1", "Name": "My Block", "Category": "mycategory", "ContentJSON": "[]", "StyleJSON": "[]"},
    ], status=200)

    plan_file = _write_plan(tmp_path, [
        {"template": "Centered Hero", "name": "My Block", "category": "mycategory", "overrides": {"heading_1": "Custom"}},
    ])

    result = runner.invoke(cli, ["blocks", "build-library", "--plan", str(plan_file)])

    assert result.exit_code == 0
    # Verify form body
    from urllib.parse import parse_qs
    add_request = responses.calls[1].request
    form = {k: v[0] for k, v in parse_qs(add_request.body, keep_blank_values=True).items()}
    assert form["Name"] == "My Block"
    assert form["Category"] == "mycategory"
    content = json.loads(form["ContentJSON"])
    heading = content[0]["components"][0]["components"][0]["components"][0]["components"][0]
    assert heading["content"] == "Custom"


# -- category defaults --


def test_build_library_category_defaults_from_template(runner, tmp_path, monkeypatch):
    templates_dir = _setup_templates(tmp_path)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    output_dir = tmp_path / "output"
    plan_file = _write_plan(tmp_path, [
        {"template": "Centered Hero", "name": "No Category Specified"},
    ])

    result = runner.invoke(cli, [
        "blocks", "build-library",
        "--plan", str(plan_file),
        "--dry-run",
    ])

    assert result.exit_code == 0
    assert "No Category Specified" in result.output


# -- error handling --


@responses.activate
def test_build_library_partial_failure(runner, mock_config, tmp_path, monkeypatch):
    templates_dir = _setup_templates(tmp_path)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    mock_homepage()
    # First block succeeds
    responses.add(responses.POST, CUSTOM_ADD_URL, json={"Status": "Success"}, status=200)
    responses.add(responses.GET, CUSTOM_LIST_URL, json=[
        {"ID": 1, "Guid": "ok-guid", "Name": "Good Block", "Category": "Heroes", "ContentJSON": "[]", "StyleJSON": "[]"},
    ], status=200)
    # Second block fails (duplicate)
    responses.add(responses.POST, CUSTOM_ADD_URL, json={"Status": "Exist"}, status=200)

    plan_file = _write_plan(tmp_path, [
        {"template": "Centered Hero", "name": "Good Block"},
        {"template": "Feature Cards", "name": "Duplicate Block"},
    ])

    result = runner.invoke(cli, ["blocks", "build-library", "--plan", str(plan_file)])

    assert result.exit_code == 1
    assert "OK    Good Block" in result.output
    assert "FAIL  Duplicate Block" in result.output
    assert "1 failed" in result.output


def test_build_library_template_not_found(runner, tmp_path, monkeypatch):
    templates_dir = _setup_templates(tmp_path)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    plan_file = _write_plan(tmp_path, [
        {"template": "Nonexistent", "name": "Bad Block"},
    ])

    result = runner.invoke(cli, ["blocks", "build-library", "--plan", str(plan_file), "--dry-run"])

    assert result.exit_code == 1
    assert "SKIP  Bad Block" in result.output


def test_build_library_invalid_plan_missing_fields(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(tmp_path))

    plan_file = _write_plan(tmp_path, [{"template": "Hero"}])

    result = runner.invoke(cli, ["blocks", "build-library", "--plan", str(plan_file), "--dry-run"])

    assert result.exit_code == 1
    assert "missing required field 'name'" in result.output


def test_build_library_invalid_plan_bad_type(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(tmp_path))

    plan_file = _write_plan(tmp_path, [
        {"template": "Hero", "name": "Test", "type": "invalid"},
    ])

    result = runner.invoke(cli, ["blocks", "build-library", "--plan", str(plan_file), "--dry-run"])

    assert result.exit_code == 1
    assert "'type' must be 'custom' or 'global'" in result.output


def test_build_library_invalid_json_plan(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(tmp_path))

    plan_file = tmp_path / "bad.json"
    plan_file.write_text("not json {{{")

    result = runner.invoke(cli, ["blocks", "build-library", "--plan", str(plan_file)])

    assert result.exit_code == 1
    assert "Cannot read plan file" in result.output


def test_build_library_plan_not_array(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(tmp_path))

    plan_file = _write_plan(tmp_path, {"not": "an array"})

    result = runner.invoke(cli, ["blocks", "build-library", "--plan", str(plan_file)])

    assert result.exit_code == 1
    assert "JSON array" in result.output


# -- empty plan --


def test_build_library_empty_plan(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(tmp_path))

    plan_file = _write_plan(tmp_path, [])

    result = runner.invoke(cli, ["blocks", "build-library", "--plan", str(plan_file)])

    assert result.exit_code == 0
    assert "nothing to do" in result.output


def test_build_library_empty_plan_json(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(tmp_path))

    plan_file = _write_plan(tmp_path, [])

    result = runner.invoke(cli, ["blocks", "build-library", "--plan", str(plan_file), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["summary"]["total"] == 0
