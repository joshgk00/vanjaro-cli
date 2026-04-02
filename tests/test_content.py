"""Tests for vanjaro content commands (VanjaroAI endpoints)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

GET_PAGE_URL = f"{BASE_URL}/API/VanjaroAI/AIPage/Get"
UPDATE_PAGE_URL = f"{BASE_URL}/API/VanjaroAI/AIPage/Update"
PUBLISH_PAGE_URL = f"{BASE_URL}/API/VanjaroAI/AIPage/Publish"

SAMPLE_COMPONENTS = [{"type": "text", "content": "Hello world", "attributes": {}}]
SAMPLE_STYLES = [{"selectors": [".hero"], "style": {"color": "red"}}]

SAMPLE_API_RESPONSE = {
    "pageId": 10,
    "tabId": 10,
    "contentJSON": json.dumps(SAMPLE_COMPONENTS),
    "styleJSON": json.dumps(SAMPLE_STYLES),
    "content": "<p>Hello world</p>",
    "style": ".hero { color: red; }",
    "version": 3,
    "isPublished": True,
    "locale": "en-US",
}


@responses.activate
def test_content_get(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_API_RESPONSE, status=200)

    result = runner.invoke(cli, ["content", "get", "10"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["page_id"] == 10
    assert data["locale"] == "en-US"
    assert data["version"] == 3
    assert data["is_published"] is True
    assert len(data["components"]) == 1
    assert data["components"][0]["type"] == "text"


@responses.activate
def test_content_get_sends_correct_params(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_API_RESPONSE, status=200)

    runner.invoke(cli, ["content", "get", "10", "--locale", "fr-FR"])

    api_call = [c for c in responses.calls if "AIPage/Get" in c.request.url][0]
    assert api_call.request.params["pageId"] == "10"
    assert api_call.request.params["locale"] == "fr-FR"
    assert api_call.request.params["includeDraft"] == "true"


@responses.activate
def test_content_get_published_only(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_API_RESPONSE, status=200)

    runner.invoke(cli, ["content", "get", "10", "--published"])

    api_call = [c for c in responses.calls if "AIPage/Get" in c.request.url][0]
    assert api_call.request.params["includeDraft"] == "false"


@responses.activate
def test_content_get_to_file(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_API_RESPONSE, status=200)
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
    locale_response = {**SAMPLE_API_RESPONSE, "locale": "fr-FR"}
    responses.add(responses.GET, GET_PAGE_URL, json=locale_response, status=200)

    result = runner.invoke(cli, ["content", "get", "10", "--locale", "fr-FR"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["locale"] == "fr-FR"


@responses.activate
def test_content_update_from_file(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(
        responses.POST,
        UPDATE_PAGE_URL,
        json={"pageId": 10, "version": 4},
        status=200,
    )

    content_file = tmp_path / "content.json"
    content_file.write_text(json.dumps({
        "components": SAMPLE_COMPONENTS,
        "styles": SAMPLE_STYLES,
    }))

    result = runner.invoke(cli, ["content", "update", "10", "--file", str(content_file)])

    assert result.exit_code == 0
    assert "Content updated for page 10" in result.output
    assert "version 4" in result.output

    post_call = [c for c in responses.calls if "AIPage/Update" in c.request.url][0]
    sent_body = json.loads(post_call.request.body)
    assert sent_body["pageId"] == 10
    assert sent_body["locale"] == "en-US"
    # ContentJSON should be a JSON string, not a raw object
    parsed_components = json.loads(sent_body["contentJSON"])
    assert len(parsed_components) == 1


@responses.activate
def test_content_update_with_version(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(
        responses.POST,
        UPDATE_PAGE_URL,
        json={"pageId": 10, "version": 5},
        status=200,
    )

    content_file = tmp_path / "content.json"
    content_file.write_text(json.dumps({"components": [], "styles": []}))

    result = runner.invoke(cli, ["content", "update", "10", "--file", str(content_file), "--version", "4"])

    assert result.exit_code == 0

    post_call = [c for c in responses.calls if "AIPage/Update" in c.request.url][0]
    sent_body = json.loads(post_call.request.body)
    assert sent_body["expectedVersion"] == 4


@responses.activate
def test_content_update_json_output(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(
        responses.POST,
        UPDATE_PAGE_URL,
        json={"pageId": 10, "version": 4},
        status=200,
    )

    content_file = tmp_path / "content.json"
    content_file.write_text(json.dumps({"components": SAMPLE_COMPONENTS, "styles": SAMPLE_STYLES}))

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
def test_content_get_null_response(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=None, status=200)

    result = runner.invoke(cli, ["content", "get", "5"])

    assert result.exit_code == 1


@responses.activate
def test_content_publish(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        PUBLISH_PAGE_URL,
        json={"pageId": 10, "isPublished": True},
        status=200,
    )

    result = runner.invoke(cli, ["content", "publish", "10"])

    assert result.exit_code == 0
    assert "Page 10 published" in result.output


@responses.activate
def test_content_publish_json(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        PUBLISH_PAGE_URL,
        json={"pageId": 10, "isPublished": True},
        status=200,
    )

    result = runner.invoke(cli, ["content", "publish", "10", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "published"
    assert data["page_id"] == 10


@responses.activate
def test_content_publish_sends_locale(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, PUBLISH_PAGE_URL, json={}, status=200)

    runner.invoke(cli, ["content", "publish", "10", "--locale", "fr-FR"])

    post_call = [c for c in responses.calls if "AIPage/Publish" in c.request.url][0]
    sent_body = json.loads(post_call.request.body)
    assert sent_body["pageId"] == 10
    assert sent_body["locale"] == "fr-FR"
