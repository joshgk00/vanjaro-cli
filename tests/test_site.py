"""Tests for vanjaro site commands (VanjaroAI endpoints)."""

from __future__ import annotations

import json

import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

ANALYZE_URL = f"{BASE_URL}/API/VanjaroAI/AISiteAnalysis/Analyze"
HEALTH_URL = f"{BASE_URL}/API/VanjaroAI/AIHealth/Check"

SAMPLE_ANALYZE_RESPONSE = {
    "site": {
        "name": "My Website",
        "description": "",
        "theme": "Basic",
        "url": "vanjarocli.local",
    },
    "pages": [
        {
            "id": 21,
            "name": "Home",
            "path": "/Home",
            "isPublished": False,
            "blockCount": 0,
            "hasCustomStyles": False,
        },
        {
            "id": 34,
            "name": "About Us",
            "path": "/AboutUs",
            "isPublished": True,
            "blockCount": 2,
            "hasCustomStyles": True,
        },
    ],
    "globalBlocks": [
        {"id": 2, "guid": "fe37ff48-guid", "name": "Footer", "usedOnPages": 2},
        {"id": 1, "guid": "20020077-guid", "name": "Header", "usedOnPages": 1},
    ],
    "designSummary": {
        "themeName": "Basic",
        "customizedControls": 0,
        "totalControls": 838,
    },
    "assets": {
        "totalFiles": 14,
        "totalFolders": 2,
        "totalSizeMB": 0.07,
    },
    "branding": {
        "hasLogo": True,
        "hasFavicon": False,
    },
}

SAMPLE_HEALTH_RESPONSE = {
    "status": "ok",
    "dnnVersion": "9.10.2",
    "vanjaroVersion": "1.6.0.0",
    "userId": 1,
    "userName": "host",
    "portalId": 0,
    "timestamp": "2026-04-02T19:30:00Z",
}


@responses.activate
def test_site_info(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, ANALYZE_URL, json=SAMPLE_ANALYZE_RESPONSE, status=200)

    result = runner.invoke(cli, ["site", "info"])

    assert result.exit_code == 0
    assert "Site: My Website" in result.output
    assert "Theme: Basic" in result.output
    assert "URL: vanjarocli.local" in result.output
    assert "logo yes" in result.output
    assert "favicon no" in result.output


@responses.activate
def test_site_info_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, ANALYZE_URL, json=SAMPLE_ANALYZE_RESPONSE, status=200)

    result = runner.invoke(cli, ["site", "info", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["site"]["name"] == "My Website"
    assert data["site"]["theme"] == "Basic"
    assert len(data["pages"]) == 2
    assert len(data["global_blocks"]) == 2
    assert data["assets"]["totalFiles"] == 14
    assert data["branding"]["hasLogo"] is True


@responses.activate
def test_site_info_shows_page_count(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, ANALYZE_URL, json=SAMPLE_ANALYZE_RESPONSE, status=200)

    result = runner.invoke(cli, ["site", "info"])

    assert result.exit_code == 0
    assert "Pages: 2 (1 published)" in result.output
    assert "Global Blocks: 2 (Footer, Header)" in result.output


@responses.activate
def test_site_health(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, HEALTH_URL, json=SAMPLE_HEALTH_RESPONSE, status=200)

    result = runner.invoke(cli, ["site", "health"])

    assert result.exit_code == 0
    assert "Status:  ok" in result.output
    assert "DNN:     9.10.2" in result.output
    assert "Vanjaro: 1.6.0.0" in result.output
    assert "User:    host (ID: 1)" in result.output
    assert "Portal:  0" in result.output


@responses.activate
def test_site_health_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, HEALTH_URL, json=SAMPLE_HEALTH_RESPONSE, status=200)

    result = runner.invoke(cli, ["site", "health", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["dnn_version"] == "9.10.2"
    assert data["vanjaro_version"] == "1.6.0.0"
    assert data["user_id"] == 1
    assert data["user_name"] == "host"


@responses.activate
def test_site_api_error(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        ANALYZE_URL,
        json={"Message": "Internal server error"},
        status=500,
    )

    result = runner.invoke(cli, ["site", "info"])

    assert result.exit_code == 1


@responses.activate
def test_site_health_api_error(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        HEALTH_URL,
        json={"Message": "Service unavailable"},
        status=503,
    )

    result = runner.invoke(cli, ["site", "health"])

    assert result.exit_code == 1
