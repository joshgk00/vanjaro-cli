"""Tests for vanjaro content commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

GET_PAGE_URL = f"{BASE_URL}/API/Vanjaro/Page/Get"
SAVE_PAGE_URL = f"{BASE_URL}/API/Vanjaro/Page/Save"

SAMPLE_CONTENT = {
    "components": [
        {"type": "text", "content": "Hello world", "attributes": {}}
    ],
    "styles": [{"selectors": [".hero"], "style": {"color": "red"}}],
}


@responses.activate
def test_content_get(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_CONTENT, status=200)

    result = runner.invoke(cli, ["content", "get", "10"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["page_id"] == 10
    assert data["locale"] == "en-US"
    assert len(data["components"]) == 1
    assert data["components"][0]["type"] == "text"


@responses.activate
def test_content_get_sends_correct_params(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_CONTENT, status=200)

    runner.invoke(cli, ["content", "get", "10", "--locale", "fr-FR"])

    api_call = [c for c in responses.calls if "Page/Get" in c.request.url][0]
    assert api_call.request.params["tabid"] == "10"
    assert api_call.request.params["locale"] == "fr-FR"


@responses.activate
def test_content_get_to_file(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_CONTENT, status=200)
    output_file = tmp_path / "content.json"

    result = runner.invoke(cli, ["content", "get", "10", "--output", str(output_file)])

    assert result.exit_code == 0
    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert data["page_id"] == 10
    assert len(data["components"]) == 1


@responses.activate
def test_content_get_locale(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_CONTENT, status=200)

    result = runner.invoke(cli, ["content", "get", "10", "--locale", "fr-FR"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["locale"] == "fr-FR"


@responses.activate
def test_content_update_from_file(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, SAVE_PAGE_URL, json={"success": True}, status=200)

    content_file = tmp_path / "content.json"
    content_file.write_text(json.dumps(SAMPLE_CONTENT))

    result = runner.invoke(cli, ["content", "update", "10", "--file", str(content_file)])

    assert result.exit_code == 0
    assert "Content updated for page 10" in result.output

    post_call = [c for c in responses.calls if "Page/Save" in c.request.url][0]
    sent_body = json.loads(post_call.request.body)
    assert sent_body["pageId"] == 10
    assert sent_body["locale"] == "en-US"
    assert len(sent_body["components"]) == 1


@responses.activate
def test_content_update_json_output(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, SAVE_PAGE_URL, json={"success": True}, status=200)

    content_file = tmp_path / "content.json"
    content_file.write_text(json.dumps(SAMPLE_CONTENT))

    result = runner.invoke(cli, ["content", "update", "10", "--file", str(content_file), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "updated"
    assert data["page_id"] == 10


@responses.activate
def test_content_update_no_input(runner, mock_config):
    result = runner.invoke(cli, ["content", "update", "10"])
    assert result.exit_code != 0


@responses.activate
def test_content_update_invalid_json(runner, mock_config, tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not json at all {{{")

    result = runner.invoke(cli, ["content", "update", "10", "--file", str(bad_file)])

    assert result.exit_code == 1


@responses.activate
def test_content_get_api_error(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json={"Message": "Page not found"}, status=404)

    result = runner.invoke(cli, ["content", "get", "999"])

    assert result.exit_code == 1


@responses.activate
def test_content_get_blockdata_format(runner, mock_config):
    """Vanjaro sometimes wraps GrapesJS data under 'BlockData'."""
    mock_homepage()
    wrapped = {
        "BlockData": {
            "components": [{"type": "section", "content": "Section"}],
            "styles": [],
        }
    }
    responses.add(responses.GET, GET_PAGE_URL, json=wrapped, status=200)

    result = runner.invoke(cli, ["content", "get", "5"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data["components"], list)
    assert data["components"][0]["type"] == "section"
