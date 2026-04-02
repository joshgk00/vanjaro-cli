"""Tests for vanjaro content commands."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL

GET_CONTENT_URL = f"{BASE_URL}/API/Vanjaro/Page/GetPageContent"
UPDATE_CONTENT_URL = f"{BASE_URL}/API/Vanjaro/Page/UpdatePageContent"
PUBLISH_URL = f"{BASE_URL}/API/Vanjaro/Page/PublishPage"
CSRF_URL = f"{BASE_URL}/API/PersonaBar/Security/GetAntiForgeryToken"

SAMPLE_CONTENT = {
    "components": [
        {"type": "text", "content": "Hello world", "attributes": {}}
    ],
    "styles": [{"selectors": [".hero"], "style": {"color": "red"}}],
}


@responses.activate
def test_content_get(runner, mock_config):
    responses.add(responses.GET, GET_CONTENT_URL, json=SAMPLE_CONTENT, status=200)

    result = runner.invoke(cli, ["content", "get", "10"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "components" in data
    assert data["page_id"] == 10


@responses.activate
def test_content_get_to_file(runner, mock_config, tmp_path):
    responses.add(responses.GET, GET_CONTENT_URL, json=SAMPLE_CONTENT, status=200)
    output_file = tmp_path / "content.json"

    result = runner.invoke(cli, ["content", "get", "10", "--output", str(output_file)])

    assert result.exit_code == 0
    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert "components" in data


@responses.activate
def test_content_get_locale(runner, mock_config):
    responses.add(responses.GET, GET_CONTENT_URL, json=SAMPLE_CONTENT, status=200)

    result = runner.invoke(cli, ["content", "get", "10", "--locale", "fr-FR"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["locale"] == "fr-FR"


@responses.activate
def test_content_update_from_file(runner, mock_config, tmp_path):
    responses.add(responses.GET, CSRF_URL, json={"token": "csrf-abc"}, status=200)
    responses.add(responses.POST, UPDATE_CONTENT_URL, json={"success": True}, status=200)

    content_file = tmp_path / "content.json"
    content_file.write_text(json.dumps(SAMPLE_CONTENT))

    result = runner.invoke(cli, ["content", "update", "10", "--file", str(content_file)])

    assert result.exit_code == 0
    assert "updated" in result.output.lower()


@responses.activate
def test_content_update_json_output(runner, mock_config, tmp_path):
    responses.add(responses.GET, CSRF_URL, json={"token": "csrf-abc"}, status=200)
    responses.add(responses.POST, UPDATE_CONTENT_URL, json={"success": True}, status=200)

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
def test_content_publish(runner, mock_config):
    responses.add(responses.GET, CSRF_URL, json={"token": "csrf-abc"}, status=200)
    responses.add(responses.POST, PUBLISH_URL, json={"success": True}, status=200)

    result = runner.invoke(cli, ["content", "publish", "10"])

    assert result.exit_code == 0
    assert "published" in result.output.lower()


@responses.activate
def test_content_publish_json(runner, mock_config):
    responses.add(responses.GET, CSRF_URL, json={"token": "csrf-abc"}, status=200)
    responses.add(responses.POST, PUBLISH_URL, json={"success": True}, status=200)

    result = runner.invoke(cli, ["content", "publish", "10", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "published"
    assert data["page_id"] == 10


@responses.activate
def test_content_get_api_error(runner, mock_config):
    responses.add(responses.GET, GET_CONTENT_URL, json={"Message": "Page not found"}, status=404)

    result = runner.invoke(cli, ["content", "get", "999"])

    assert result.exit_code == 1


@responses.activate
def test_content_get_blockdata_format(runner, mock_config):
    """Vanjaro sometimes wraps GrapesJS data under 'BlockData'."""
    wrapped = {
        "BlockData": {
            "components": [{"type": "section", "content": "Section"}],
            "styles": [],
        }
    }
    responses.add(responses.GET, GET_CONTENT_URL, json=wrapped, status=200)

    result = runner.invoke(cli, ["content", "get", "5"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data["components"], list)
