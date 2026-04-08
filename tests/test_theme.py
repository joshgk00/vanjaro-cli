"""Tests for vanjaro theme commands."""

from __future__ import annotations

import json

import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

GET_URL = f"{BASE_URL}/API/VanjaroAI/AIDesign/GetSettings"
SAVE_URL = f"{BASE_URL}/API/VanjaroAI/AIDesign/SaveCategory"
RESET_URL = f"{BASE_URL}/API/VanjaroAI/AIDesign/ResetSettings"
CSS_SAVE_URL = f"{BASE_URL}/API/CustomCSS/stylesheet/save"
PORTAL_CSS_URL = f"{BASE_URL}/Portals/0/portal.css"

# ThemeBuilder endpoints (same as the Vanjaro editor UI)
TB_GET_FONTS_URL = f"{BASE_URL}/API/ThemeBuilder/Settings/GetFonts"
TB_UPDATE_FONT_URL = f"{BASE_URL}/API/ThemeBuilder/Settings/UpdateFont"
TB_SAVE_URL = f"{BASE_URL}/API/ThemeBuilder/Settings/Save"

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
    responses.add(responses.GET, GET_URL, json=SAMPLE_SETTINGS, status=200)
    responses.add(responses.POST, SAVE_URL, json=SAMPLE_SETTINGS, status=200)

    result = runner.invoke(cli, ["theme", "set", "--guid", "color-1", "--value", "#ff0000"])

    assert result.exit_code == 0
    assert "Updated color-1" in result.output

    post_call = [c for c in responses.calls if "SaveCategory" in c.request.url][0]
    sent = json.loads(post_call.request.body)
    assert sent["categoryGuid"] == "cat-1"
    assert len(sent["themeEditorValues"]) == 1
    assert sent["themeEditorValues"][0]["guid"] == "color-1"
    assert sent["themeEditorValues"][0]["value"] == "#ff0000"
    assert sent["themeEditorValues"][0]["css"] == ""


@responses.activate
def test_theme_set_by_variable(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_SETTINGS, status=200)
    responses.add(responses.POST, SAVE_URL, json=SAMPLE_SETTINGS, status=200)

    result = runner.invoke(cli, ["theme", "set", "--variable", "@brand-primary", "--value", "#00ff00"])

    assert result.exit_code == 0

    post_call = [c for c in responses.calls if "SaveCategory" in c.request.url][0]
    sent = json.loads(post_call.request.body)
    assert sent["themeEditorValues"][0]["guid"] == "color-1"
    assert sent["themeEditorValues"][0]["value"] == "#00ff00"


@responses.activate
def test_theme_set_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_SETTINGS, status=200)
    responses.add(responses.POST, SAVE_URL, json=SAMPLE_SETTINGS, status=200)

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
    responses.add(responses.GET, GET_URL, json=SAMPLE_SETTINGS, status=200)
    responses.add(responses.POST, SAVE_URL, json=SAMPLE_SETTINGS, status=200)
    responses.add(responses.POST, SAVE_URL, json=SAMPLE_SETTINGS, status=200)

    bulk_file = tmp_path / "theme.json"
    bulk_file.write_text(json.dumps([
        {"guid": "color-1", "value": "#ff0000"},
        {"guid": "size-1", "value": "18"},
    ]))

    result = runner.invoke(cli, ["theme", "set-bulk", str(bulk_file)])

    assert result.exit_code == 0
    assert "Updated 2 theme controls" in result.output

    post_calls = [c for c in responses.calls if "SaveCategory" in c.request.url]
    assert len(post_calls) == 2

    first = json.loads(post_calls[0].request.body)
    second = json.loads(post_calls[1].request.body)
    payloads = {payload["categoryGuid"]: payload for payload in (first, second)}

    assert payloads["cat-1"]["themeEditorValues"][0]["guid"] == "color-1"
    assert payloads["cat-1"]["themeEditorValues"][0]["value"] == "#ff0000"

    typography_values = {item["guid"]: item["value"] for item in payloads["cat-2"]["themeEditorValues"]}
    assert typography_values["font-1"] == "Open Sans"
    assert typography_values["size-1"] == "18"


@responses.activate
def test_theme_set_bulk_wrapper_format(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_SETTINGS, status=200)
    responses.add(responses.POST, SAVE_URL, json=SAMPLE_SETTINGS, status=200)

    bulk_file = tmp_path / "theme.json"
    bulk_file.write_text(json.dumps({"controls": [
        {"guid": "color-1", "value": "#ff0000"},
    ]}))

    result = runner.invoke(cli, ["theme", "set-bulk", str(bulk_file)])

    assert result.exit_code == 0
    assert "Updated 1 theme controls" in result.output


@responses.activate
def test_theme_set_bulk_groups_multiple_updates_in_same_category(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_SETTINGS, status=200)
    responses.add(responses.POST, SAVE_URL, json=SAMPLE_SETTINGS, status=200)

    bulk_file = tmp_path / "theme.json"
    bulk_file.write_text(json.dumps([
        {"guid": "font-1", "value": "Roboto"},
        {"guid": "size-1", "value": "18"},
    ]))

    result = runner.invoke(cli, ["theme", "set-bulk", str(bulk_file)])

    assert result.exit_code == 0

    post_calls = [c for c in responses.calls if "SaveCategory" in c.request.url]
    assert len(post_calls) == 1
    sent = json.loads(post_calls[0].request.body)
    assert sent["categoryGuid"] == "cat-2"
    typography_values = {item["guid"]: item["value"] for item in sent["themeEditorValues"]}
    assert typography_values["font-1"] == "Roboto"
    assert typography_values["size-1"] == "18"


@responses.activate
def test_theme_set_unknown_control(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_SETTINGS, status=200)

    result = runner.invoke(cli, ["theme", "set", "--guid", "missing", "--value", "#ff0000"])

    assert result.exit_code == 1
    assert "Control not found" in result.output


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


GFONTS_URL = "https://fonts.googleapis.com/css2?family=Raleway:wght@400&display=swap"
SAMPLE_FONT_CSS = "@font-face { font-family: 'Raleway'; src: url('raleway.woff2') format('woff2'); }"

# ThemeBuilder returns PascalCase keys
TB_EXISTING_FONTS = [
    {"Guid": "aaa-111", "Name": "Open Sans", "Family": "Open Sans, sans-serif", "Css": ""},
    {"Guid": "bbb-222", "Name": "Roboto", "Family": "Roboto, sans-serif", "Css": ""},
]


def _mock_font_list():
    """Mock the ThemeBuilder GetFonts call (uses hardcoded Custom category GUID)."""
    responses.add(responses.GET, TB_GET_FONTS_URL, json=TB_EXISTING_FONTS, status=200)


@responses.activate
def test_theme_register_font_with_css(runner, mock_config):
    mock_homepage()
    _mock_font_list()
    responses.add(responses.POST, TB_UPDATE_FONT_URL, json={"IsSuccess": True, "Data": {"Fonts": TB_EXISTING_FONTS}}, status=200)
    responses.add(responses.POST, TB_SAVE_URL, json={"IsSuccess": True}, status=200)

    result = runner.invoke(cli, [
        "theme", "register-font",
        "--name", "Raleway",
        "--family", "Raleway, sans-serif",
        "--css", SAMPLE_FONT_CSS,
    ])

    assert result.exit_code == 0
    assert "Font 'Raleway' registered" in result.output

    post_call = [c for c in responses.calls if "UpdateFont" in c.request.url][0]
    sent = json.loads(post_call.request.body)
    assert sent["Css"] == SAMPLE_FONT_CSS
    assert sent["Name"] == "Raleway"
    assert sent["Family"] == "Raleway, sans-serif"
    assert sent["Guid"] == ""
    assert "Guid=be134fd2-3a3d-4460-8ee9-2953722a5ab2" in post_call.request.url

    save_call = [c for c in responses.calls if "Settings/Save" in c.request.url][0]
    assert "Guid=be134fd2" in save_call.request.url


@responses.activate
def test_theme_register_font_with_import_url_fetches_css(runner, mock_config):
    """--import-url fetches CSS from the URL and sends it via ThemeBuilder."""
    mock_homepage()
    responses.add(responses.GET, GFONTS_URL, body=SAMPLE_FONT_CSS, status=200)
    _mock_font_list()
    responses.add(responses.POST, TB_UPDATE_FONT_URL, json={"IsSuccess": True, "Data": {"Fonts": TB_EXISTING_FONTS}}, status=200)
    responses.add(responses.POST, TB_SAVE_URL, json={"IsSuccess": True}, status=200)

    result = runner.invoke(cli, [
        "theme", "register-font",
        "--name", "Raleway",
        "--family", "Raleway, sans-serif",
        "--import-url", GFONTS_URL,
    ])

    assert result.exit_code == 0
    assert "Font 'Raleway' registered" in result.output

    post_call = [c for c in responses.calls if "UpdateFont" in c.request.url][0]
    sent = json.loads(post_call.request.body)
    assert sent["Css"] == SAMPLE_FONT_CSS


@responses.activate
def test_theme_register_font_import_url_fetch_failure(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GFONTS_URL, status=503)

    result = runner.invoke(cli, [
        "theme", "register-font",
        "--name", "Raleway",
        "--family", "Raleway, sans-serif",
        "--import-url", GFONTS_URL,
    ])

    assert result.exit_code == 1
    assert "Failed to fetch font CSS" in result.output


def test_theme_register_font_no_source(runner, mock_config):
    """Without --import-url or --css, register-font exits with an error."""
    result = runner.invoke(cli, [
        "theme", "register-font",
        "--name", "Raleway",
        "--family", "Raleway, sans-serif",
    ])

    assert result.exit_code == 1
    assert "import-url" in result.output or "css" in result.output


@responses.activate
def test_theme_register_font_already_exists(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, TB_GET_FONTS_URL, json=[
        {"Guid": "aaa-111", "Name": "Raleway", "Family": "Raleway, sans-serif", "Css": ""},
    ], status=200)

    result = runner.invoke(cli, [
        "theme", "register-font",
        "--name", "Raleway",
        "--family", "Raleway, sans-serif",
        "--css", SAMPLE_FONT_CSS,
    ])

    assert result.exit_code == 0
    assert "already registered" in result.output


@responses.activate
def test_theme_list_fonts(runner, mock_config):
    mock_homepage()
    _mock_font_list()

    result = runner.invoke(cli, ["theme", "list-fonts"])

    assert result.exit_code == 0
    assert "2 available fonts" in result.output
    assert "Open Sans" in result.output
    assert "Roboto" in result.output


@responses.activate
def test_theme_list_fonts_json(runner, mock_config):
    mock_homepage()
    _mock_font_list()

    result = runner.invoke(cli, ["theme", "list-fonts", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["total"] == 2
    assert data["fonts"][0]["Name"] == "Open Sans"
    assert data["fonts"][1]["Name"] == "Roboto"


@responses.activate
def test_theme_list_fonts_empty(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, TB_GET_FONTS_URL, json=[], status=200)

    result = runner.invoke(cli, ["theme", "list-fonts"])

    assert result.exit_code == 0
    assert "No fonts registered" in result.output


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


# ------------------------------------------------------------------
# CSS subcommand tests
# ------------------------------------------------------------------

SAMPLE_CSS = ".card-hover { transform: translateY(-4px); }\n"
CSS_SAVE_RESPONSE = {"Errors": {}, "IsSuccess": True, "HasErrors": False, "Message": None}


@responses.activate
def test_css_get_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, PORTAL_CSS_URL, body=SAMPLE_CSS, status=200)

    result = runner.invoke(cli, ["theme", "css", "get", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert ".card-hover" in data["css"]
    assert data["length"] > 0


@responses.activate
def test_css_get_human(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, PORTAL_CSS_URL, body=SAMPLE_CSS, status=200)

    result = runner.invoke(cli, ["theme", "css", "get"])

    assert result.exit_code == 0
    assert ".card-hover" in result.output


@responses.activate
def test_css_get_empty(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, PORTAL_CSS_URL, status=404)

    result = runner.invoke(cli, ["theme", "css", "get"])

    assert result.exit_code == 0
    assert "No custom CSS defined" in result.output


@responses.activate
def test_css_get_output_file(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.GET, PORTAL_CSS_URL, body=SAMPLE_CSS, status=200)

    out_file = tmp_path / "portal.css"
    result = runner.invoke(cli, ["theme", "css", "get", "--output", str(out_file), "--json"])

    assert result.exit_code == 0
    assert out_file.read_text() == SAMPLE_CSS


@responses.activate
def test_css_update(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, CSS_SAVE_URL, json=CSS_SAVE_RESPONSE, status=200)

    css_file = tmp_path / "styles.css"
    css_file.write_text(SAMPLE_CSS)

    result = runner.invoke(cli, ["theme", "css", "update", "--file", str(css_file), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "updated"

    post_call = [c for c in responses.calls if "CustomCSS" in c.request.url][0]
    sent_body = json.loads(post_call.request.body)
    assert ".card-hover" in sent_body


@responses.activate
def test_css_update_server_error(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, CSS_SAVE_URL, json={**CSS_SAVE_RESPONSE, "IsSuccess": False}, status=200)

    css_file = tmp_path / "styles.css"
    css_file.write_text(SAMPLE_CSS)

    result = runner.invoke(cli, ["theme", "css", "update", "--file", str(css_file), "--json"])

    assert result.exit_code == 1
    assert "rejected" in result.output


@responses.activate
def test_css_append(runner, mock_config, tmp_path):
    mock_homepage()
    existing_css = ".existing { color: red; }\n"
    append_css = ".new-class { color: blue; }\n"

    responses.add(responses.GET, PORTAL_CSS_URL, body=existing_css, status=200)
    responses.add(responses.POST, CSS_SAVE_URL, json=CSS_SAVE_RESPONSE, status=200)

    css_file = tmp_path / "append.css"
    css_file.write_text(append_css)

    result = runner.invoke(cli, ["theme", "css", "append", "--file", str(css_file), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "updated"

    post_call = [c for c in responses.calls if "CustomCSS" in c.request.url][0]
    sent_body = json.loads(post_call.request.body)
    assert ".existing" in sent_body
    assert ".new-class" in sent_body


@responses.activate
def test_css_append_to_empty(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.GET, PORTAL_CSS_URL, status=404)
    responses.add(responses.POST, CSS_SAVE_URL, json=CSS_SAVE_RESPONSE, status=200)

    css_file = tmp_path / "first.css"
    css_file.write_text(SAMPLE_CSS)

    result = runner.invoke(cli, ["theme", "css", "append", "--file", str(css_file), "--json"])

    assert result.exit_code == 0
    post_call = [c for c in responses.calls if "CustomCSS" in c.request.url][0]
    sent_body = json.loads(post_call.request.body)
    assert ".card-hover" in sent_body
