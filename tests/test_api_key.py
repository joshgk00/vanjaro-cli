"""Tests for vanjaro api-key commands."""

from __future__ import annotations

import json

import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, FAKE_API_KEY, mock_homepage

GENERATE_URL = f"{BASE_URL}/API/VanjaroAI/AIApiKey/Generate"
REVOKE_URL = f"{BASE_URL}/API/VanjaroAI/AIApiKey/Revoke"
STATUS_URL = f"{BASE_URL}/API/VanjaroAI/AIApiKey/Status"


@responses.activate
def test_api_key_generate(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        GENERATE_URL,
        json={"apiKey": "new-api-key-abc123", "message": "API key generated."},
        status=200,
    )

    result = runner.invoke(cli, ["api-key", "generate"])

    assert result.exit_code == 0
    assert "API key generated and saved to config" in result.output


@responses.activate
def test_api_key_generate_saves_to_config(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        GENERATE_URL,
        json={"apiKey": "new-key-xyz", "message": "OK"},
        status=200,
    )

    result = runner.invoke(cli, ["api-key", "generate"])

    assert result.exit_code == 0

    saved = json.loads(mock_config.read_text())
    default_profile = saved["profiles"]["default"]
    assert default_profile["api_key"] == "new-key-xyz"


@responses.activate
def test_api_key_generate_json(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        GENERATE_URL,
        json={"apiKey": "new-key-json", "message": "Generated."},
        status=200,
    )

    result = runner.invoke(cli, ["api-key", "generate", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["api_key"] == "new-key-json"


@responses.activate
def test_api_key_generate_server_error(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        GENERATE_URL,
        json={"Message": "Access denied"},
        status=403,
    )

    result = runner.invoke(cli, ["api-key", "generate"])

    assert result.exit_code == 1


@responses.activate
def test_api_key_revoke(runner, mock_config_with_api_key):
    mock_homepage()
    responses.add(
        responses.POST,
        REVOKE_URL,
        json={"message": "API key revoked."},
        status=200,
    )

    result = runner.invoke(cli, ["api-key", "revoke"])

    assert result.exit_code == 0
    assert "API key revoked" in result.output

    saved = json.loads(mock_config_with_api_key.read_text())
    default_profile = saved["profiles"]["default"]
    assert default_profile["api_key"] is None


@responses.activate
def test_api_key_revoke_json(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        REVOKE_URL,
        json={"message": "Revoked."},
        status=200,
    )

    result = runner.invoke(cli, ["api-key", "revoke", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"


@responses.activate
def test_api_key_status_both_configured(runner, mock_config_with_api_key):
    mock_homepage()
    responses.add(
        responses.GET,
        STATUS_URL,
        json={"isConfigured": True, "message": "Configured."},
        status=200,
    )

    result = runner.invoke(cli, ["api-key", "status"])

    assert result.exit_code == 0
    assert "API key configured" in result.output
    assert "API key in config" in result.output


@responses.activate
def test_api_key_status_json(runner, mock_config_with_api_key):
    mock_homepage()
    responses.add(
        responses.GET,
        STATUS_URL,
        json={"isConfigured": True, "message": "OK"},
        status=200,
    )

    result = runner.invoke(cli, ["api-key", "status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["server_configured"] is True
    assert data["local_configured"] is True


@responses.activate
def test_api_key_status_not_configured(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        STATUS_URL,
        json={"isConfigured": False, "message": "Not configured."},
        status=200,
    )

    result = runner.invoke(cli, ["api-key", "status"])

    assert result.exit_code == 0
    assert "No API key configured" in result.output
    assert "No API key in config" in result.output


def test_api_key_set(runner, mock_config):
    result = runner.invoke(cli, ["api-key", "set", "manual-key-123"])

    assert result.exit_code == 0
    assert "API key saved to config" in result.output

    saved = json.loads(mock_config.read_text())
    default_profile = saved["profiles"]["default"]
    assert default_profile["api_key"] == "manual-key-123"


@responses.activate
def test_api_key_sends_header(runner, mock_config_with_api_key):
    """Verify that the X-Api-Key header is sent when an API key is configured."""
    mock_homepage()
    responses.add(
        responses.GET,
        STATUS_URL,
        json={"isConfigured": True, "message": "OK"},
        status=200,
    )

    runner.invoke(cli, ["api-key", "status"])

    api_call = [c for c in responses.calls if "AIApiKey" in c.request.url][0]
    assert api_call.request.headers.get("X-Api-Key") == FAKE_API_KEY
