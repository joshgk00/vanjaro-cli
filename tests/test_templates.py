"""Tests for vanjaro templates commands (VanjaroAI endpoints)."""

from __future__ import annotations

import json

import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

LIST_URL = f"{BASE_URL}/API/VanjaroAI/AITemplate/List"
GET_URL = f"{BASE_URL}/API/VanjaroAI/AITemplate/Get"
APPLY_URL = f"{BASE_URL}/API/VanjaroAI/AITemplate/Apply"

SAMPLE_TEMPLATES = [
    {"name": "Default", "type": "Standard", "isSystem": True, "hasSvg": True},
    {"name": "Home", "type": "Standard", "isSystem": True, "hasSvg": True},
]

SAMPLE_TEMPLATE_DETAIL = {
    "name": "Default",
    "type": "Standard",
    "isSystem": True,
    "svg": "<svg></svg>",
    "contentJSON": [
        {"type": "globalblockwrapper", "name": "Global: Header", "attributes": {}, "components": []},
        {"type": "section", "components": []},
        {"type": "globalblockwrapper", "name": "Global: Footer", "attributes": {}},
    ],
    "styleJSON": [{"selectors": [".hero"], "style": {"color": "red"}}],
}


@responses.activate
def test_templates_list(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        LIST_URL,
        json={"total": 2, "templates": SAMPLE_TEMPLATES},
        status=200,
    )

    result = runner.invoke(cli, ["templates", "list"])

    assert result.exit_code == 0
    assert "Default" in result.output
    assert "Home" in result.output


@responses.activate
def test_templates_list_json(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        LIST_URL,
        json={"total": 2, "templates": SAMPLE_TEMPLATES},
        status=200,
    )

    result = runner.invoke(cli, ["templates", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 2
    assert data[0]["name"] == "Default"
    assert data[1]["name"] == "Home"


@responses.activate
def test_templates_list_empty(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        LIST_URL,
        json={"total": 0, "templates": []},
        status=200,
    )

    result = runner.invoke(cli, ["templates", "list"])

    assert result.exit_code == 0
    assert "No templates found." in result.output


@responses.activate
def test_templates_get(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        GET_URL,
        json=SAMPLE_TEMPLATE_DETAIL,
        status=200,
    )

    result = runner.invoke(cli, ["templates", "get", "Default"])

    assert result.exit_code == 0
    assert "Default" in result.output
    assert "Standard" in result.output
    assert "Components: 3" in result.output


@responses.activate
def test_templates_get_json(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        GET_URL,
        json=SAMPLE_TEMPLATE_DETAIL,
        status=200,
    )

    result = runner.invoke(cli, ["templates", "get", "Default", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "Default"
    assert len(data["content_json"]) == 3
    assert len(data["style_json"]) == 1


@responses.activate
def test_templates_get_to_file(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(
        responses.GET,
        GET_URL,
        json=SAMPLE_TEMPLATE_DETAIL,
        status=200,
    )
    output_file = tmp_path / "template.json"

    result = runner.invoke(cli, ["templates", "get", "Default", "--output", str(output_file)])

    assert result.exit_code == 0
    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert data["name"] == "Default"
    assert len(data["content_json"]) == 3
    assert "Template written to" in result.output


@responses.activate
def test_templates_apply(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        APPLY_URL,
        json={"status": "ok"},
        status=200,
    )

    result = runner.invoke(cli, ["templates", "apply", "34", "--template", "Default", "--force"])

    assert result.exit_code == 0
    assert "Template 'Default' applied to page 34" in result.output

    post_call = [c for c in responses.calls if "AITemplate/Apply" in c.request.url][0]
    sent_body = json.loads(post_call.request.body)
    assert sent_body["pageId"] == 34
    assert sent_body["templateName"] == "Default"


@responses.activate
def test_templates_apply_json(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        APPLY_URL,
        json={"status": "ok"},
        status=200,
    )

    result = runner.invoke(cli, ["templates", "apply", "34", "--template", "Default", "--force", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "applied"
    assert data["page_id"] == 34
    assert data["template_name"] == "Default"


def test_templates_apply_abort(runner, mock_config):
    result = runner.invoke(cli, ["templates", "apply", "34", "--template", "Default"], input="n\n")
    assert result.exit_code != 0


@responses.activate
def test_templates_api_error(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        LIST_URL,
        json={"Message": "Unauthorized"},
        status=401,
    )

    result = runner.invoke(cli, ["templates", "list"])

    assert result.exit_code == 1
