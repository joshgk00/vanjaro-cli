"""Tests for vanjaro branding commands."""

from __future__ import annotations

import json

import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

GET_URL = f"{BASE_URL}/API/VanjaroAI/AIBranding/GetBranding"
UPDATE_URL = f"{BASE_URL}/API/VanjaroAI/AIBranding/UpdateBranding"

SAMPLE_BRANDING = {
    "siteName": "My Website",
    "description": "",
    "keywords": "",
    "footerText": "Copyright [year] by My Website",
    "logo": {
        "fileId": 134,
        "fileName": "logo.png",
        "folderPath": "Images/",
        "relativePath": "Images/logo.png",
        "url": "/Portals/0/Images/logo.png?ver=abc",
        "extension": "png",
        "size": 2651,
        "width": 167,
        "height": 62,
        "contentType": "image/png",
        "lastModified": "2026-04-02T08:10:50.967",
    },
}

SAMPLE_BRANDING_NO_LOGO = {
    "siteName": "My Website",
    "description": "A test site",
    "keywords": "",
    "footerText": "Copyright [year] by My Website",
    "logo": None,
}


@responses.activate
def test_branding_get(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_BRANDING, status=200)

    result = runner.invoke(cli, ["branding", "get"])

    assert result.exit_code == 0
    assert "Site Name:   My Website" in result.output
    assert "Description: " in result.output
    assert "Footer:      Copyright [year] by My Website" in result.output
    assert "Logo:        logo.png (167x62, Images/)" in result.output


@responses.activate
def test_branding_get_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_BRANDING, status=200)

    result = runner.invoke(cli, ["branding", "get", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["site_name"] == "My Website"
    assert data["footer_text"] == "Copyright [year] by My Website"
    assert data["logo"]["fileName"] == "logo.png"


@responses.activate
def test_branding_get_no_logo(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_BRANDING_NO_LOGO, status=200)

    result = runner.invoke(cli, ["branding", "get"])

    assert result.exit_code == 0
    assert "Logo:        (none)" in result.output


@responses.activate
def test_branding_update(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, UPDATE_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(cli, ["branding", "update", "--site-name", "New Name"])

    assert result.exit_code == 0
    assert "Branding updated" in result.output


@responses.activate
def test_branding_update_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, UPDATE_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(cli, ["branding", "update", "--site-name", "New Name", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "updated"
    assert data["siteName"] == "New Name"


@responses.activate
def test_branding_update_sends_only_changed_fields(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, UPDATE_URL, json={"status": "ok"}, status=200)

    runner.invoke(cli, ["branding", "update", "--footer-text", "New footer"])

    post_call = [c for c in responses.calls if "UpdateBranding" in c.request.url][0]
    sent = json.loads(post_call.request.body)
    assert sent == {"footerText": "New footer"}
    assert "siteName" not in sent
    assert "description" not in sent


@responses.activate
def test_branding_update_no_flags_shows_current(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_BRANDING, status=200)

    result = runner.invoke(cli, ["branding", "update"])

    assert result.exit_code == 0
    assert "Site Name:   My Website" in result.output
    assert "Footer:      Copyright [year] by My Website" in result.output


@responses.activate
def test_branding_api_error(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json={"Message": "Unauthorized"}, status=401)

    result = runner.invoke(cli, ["branding", "get"])

    assert result.exit_code == 1
