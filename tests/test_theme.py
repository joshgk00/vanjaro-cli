"""Tests for vanjaro theme commands."""

from __future__ import annotations

import json

import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

GET_URL = f"{BASE_URL}/API/VanjaroAI/AIDesign/GetSettings"
UPDATE_URL = f"{BASE_URL}/API/VanjaroAI/AIDesign/UpdateSettings"
FONT_URL = f"{BASE_URL}/API/VanjaroAI/AIDesign/RegisterFont"
RESET_URL = f"{BASE_URL}/API/VanjaroAI/AIDesign/ResetSettings"

SAMPLE_CONTROLS = [
    {
        "guid": "color-1",
        "title": "Primary Color",
        "type": "Color Picker",
        "lessVariable": "@brand-primary",
        "currentValue": "#336699",
        "defaultValue": "#007bff",
        "category": "Colors",
        "categoryGuid": "cat-1",
    },
    {
        "guid": "font-1",
        "title": "Body Font",
        "type": "Fonts",
        "lessVariable": "@font-family-base",
        "currentValue": "Open Sans",
        "defaultValue": "Open Sans",
        "category": "Typography",
        "categoryGuid": "cat-2",
    },
    {
        "guid": "size-1",
        "title": "Base Font Size",
        "type": "Slider",
        "lessVariable": "@font-size-base",
        "currentValue": "16",
        "defaultValue": "14",
        "category": "Typography",
        "categoryGuid": "cat-2",
        "rangeMin": 10,
        "rangeMax": 24,
        "increment": 1,
        "suffix": "px",
    },
]

SAMPLE_SETTINGS = {
    "themeName": "Basic",
    "controls": SAMPLE_CONTROLS,
    "availableFonts": [
        {"name": "Open Sans", "value": "Open Sans, sans-serif"},
        {"name": "Roboto", "value": "Roboto, sans-serif"},
    ],
}


@responses.activate
def test_theme_get(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_SETTINGS, status=200)

    result = runner.invoke(cli, ["theme", "get"])

    assert result.exit_code == 0
    assert "Theme: Basic" in result.output
    assert "Primary Color" in result.output
    assert "Body Font" in result.output


@responses.activate
def test_theme_get_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_SETTINGS, status=200)

    result = runner.invoke(cli, ["theme", "get", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["theme_name"] == "Basic"
    assert data["total"] == 3
    assert len(data["controls"]) == 3
    assert data["controls"][0]["guid"] == "color-1"


@responses.activate
def test_theme_get_filter_category(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_SETTINGS, status=200)

    result = runner.invoke(cli, ["theme", "get", "--category", "typography"])

    assert result.exit_code == 0
    assert "Body Font" in result.output
    assert "Primary Color" not in result.output


@responses.activate
def test_theme_get_modified_only(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_SETTINGS, status=200)

    result = runner.invoke(cli, ["theme", "get", "--modified"])

    assert result.exit_code == 0
    assert "Primary Color" in result.output
    assert "Base Font Size" in result.output
    assert "Body Font" not in result.output


@responses.activate
def test_theme_set(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, UPDATE_URL, json=SAMPLE_SETTINGS, status=200)

    result = runner.invoke(cli, ["theme", "set", "--guid", "color-1", "--value", "#ff0000"])

    assert result.exit_code == 0
    assert "Updated color-1" in result.output

    post_call = [c for c in responses.calls if "UpdateSettings" in c.request.url][0]
    sent = json.loads(post_call.request.body)
    assert len(sent["controls"]) == 1
    assert sent["controls"][0]["guid"] == "color-1"
    assert sent["controls"][0]["value"] == "#ff0000"


@responses.activate
def test_theme_set_by_variable(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, UPDATE_URL, json=SAMPLE_SETTINGS, status=200)

    result = runner.invoke(cli, ["theme", "set", "--variable", "@brand-primary", "--value", "#00ff00"])

    assert result.exit_code == 0

    post_call = [c for c in responses.calls if "UpdateSettings" in c.request.url][0]
    sent = json.loads(post_call.request.body)
    assert sent["controls"][0]["lessVariable"] == "@brand-primary"


@responses.activate
def test_theme_set_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, UPDATE_URL, json=SAMPLE_SETTINGS, status=200)

    result = runner.invoke(cli, ["theme", "set", "--guid", "color-1", "--value", "#ff0000", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "updated"


def test_theme_set_no_identifier(runner, mock_config):
    result = runner.invoke(cli, ["theme", "set", "--value", "#ff0000"])

    assert result.exit_code == 1
    assert "guid" in result.output or "variable" in result.output


@responses.activate
def test_theme_set_bulk(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, UPDATE_URL, json=SAMPLE_SETTINGS, status=200)

    bulk_file = tmp_path / "theme.json"
    bulk_file.write_text(json.dumps([
        {"guid": "color-1", "value": "#ff0000"},
        {"guid": "size-1", "value": "18"},
    ]))

    result = runner.invoke(cli, ["theme", "set-bulk", str(bulk_file)])

    assert result.exit_code == 0
    assert "Updated 2 theme controls" in result.output

    post_call = [c for c in responses.calls if "UpdateSettings" in c.request.url][0]
    sent = json.loads(post_call.request.body)
    assert len(sent["controls"]) == 2


@responses.activate
def test_theme_set_bulk_wrapper_format(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, UPDATE_URL, json=SAMPLE_SETTINGS, status=200)

    bulk_file = tmp_path / "theme.json"
    bulk_file.write_text(json.dumps({"controls": [
        {"guid": "color-1", "value": "#ff0000"},
    ]}))

    result = runner.invoke(cli, ["theme", "set-bulk", str(bulk_file)])

    assert result.exit_code == 0
    assert "Updated 1 theme controls" in result.output


def test_theme_set_bulk_invalid_json(runner, mock_config, tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not valid json {{")

    result = runner.invoke(cli, ["theme", "set-bulk", str(bad_file)])

    assert result.exit_code == 1


def test_theme_set_bulk_missing_value(runner, mock_config, tmp_path):
    bad_file = tmp_path / "missing.json"
    bad_file.write_text(json.dumps([{"guid": "color-1"}]))

    result = runner.invoke(cli, ["theme", "set-bulk", str(bad_file)])

    assert result.exit_code == 1
    assert "value" in result.output


@responses.activate
def test_theme_register_font(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        FONT_URL,
        json={"registered": True, "name": "Raleway", "family": "Raleway, sans-serif", "alreadyExists": False},
        status=200,
    )

    result = runner.invoke(cli, ["theme", "register-font", "--name", "Raleway", "--family", "Raleway, sans-serif"])

    assert result.exit_code == 0
    assert "Font 'Raleway' registered" in result.output


@responses.activate
def test_theme_register_font_already_exists(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        FONT_URL,
        json={"registered": True, "name": "Raleway", "family": "Raleway", "alreadyExists": True},
        status=200,
    )

    result = runner.invoke(cli, ["theme", "register-font", "--name", "Raleway", "--family", "Raleway"])

    assert result.exit_code == 0
    assert "already registered" in result.output


@responses.activate
def test_theme_reset_with_force(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, RESET_URL, json=SAMPLE_SETTINGS, status=200)

    result = runner.invoke(cli, ["theme", "reset", "--force"])

    assert result.exit_code == 0
    assert "reset to defaults" in result.output


def test_theme_reset_abort(runner, mock_config):
    result = runner.invoke(cli, ["theme", "reset"], input="n\n")

    assert result.exit_code != 0


@responses.activate
def test_theme_api_error(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json={"Message": "Failed to read design settings"}, status=500)

    result = runner.invoke(cli, ["theme", "get"])

    assert result.exit_code == 1
