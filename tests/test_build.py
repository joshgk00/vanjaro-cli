"""Tests for the build command (create page + apply template)."""

from __future__ import annotations

import json

import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

CREATE_URL = f"{BASE_URL}/API/VanjaroAI/AIPage/Create"
APPLY_URL = f"{BASE_URL}/API/VanjaroAI/AITemplate/Apply"


@responses.activate
def test_build_creates_page_and_applies_template(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        CREATE_URL,
        json={"pageId": 99, "name": "About Us", "version": 1, "path": "/AboutUs"},
        status=201,
    )
    responses.add(
        responses.POST,
        APPLY_URL,
        json={"status": "ok"},
        status=200,
    )

    result = runner.invoke(cli, ["build", "--title", "About Us", "--template", "Default"])

    assert result.exit_code == 0
    assert "Created page 'About Us' (ID: 99) with template 'Default'." in result.output

    create_call = [c for c in responses.calls if "AIPage/Create" in c.request.url][0]
    create_body = json.loads(create_call.request.body)
    assert create_body["title"] == "About Us"
    assert create_body["name"] == "About Us"
    assert create_body["includeInMenu"] is True

    apply_call = [c for c in responses.calls if "AITemplate/Apply" in c.request.url][0]
    apply_body = json.loads(apply_call.request.body)
    assert apply_body["pageId"] == 99
    assert apply_body["templateName"] == "Default"


@responses.activate
def test_build_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, CREATE_URL, json={"pageId": 99, "name": "About Us"}, status=201)
    responses.add(responses.POST, APPLY_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(cli, ["build", "--title", "About Us", "--template", "Default", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "created"
    assert data["page_id"] == 99
    assert data["title"] == "About Us"
    assert data["template"] == "Default"


@responses.activate
def test_build_with_parent(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, CREATE_URL, json={"pageId": 100, "name": "Child Page"}, status=201)
    responses.add(responses.POST, APPLY_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(
        cli, ["build", "--title", "Child Page", "--template", "Default", "--parent", "42"]
    )

    assert result.exit_code == 0

    create_call = [c for c in responses.calls if "AIPage/Create" in c.request.url][0]
    create_body = json.loads(create_call.request.body)
    assert create_body["parentId"] == 42


@responses.activate
def test_build_template_fail_warns(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, CREATE_URL, json={"pageId": 99, "name": "About Us"}, status=201)
    responses.add(responses.POST, APPLY_URL, json={"Message": "Template not found"}, status=404)

    result = runner.invoke(cli, ["build", "--title", "About Us", "--template", "Missing"])

    assert result.exit_code == 0
    assert "Warning" in result.output
    assert "About Us" in result.output
    assert "ID: 99" in result.output


@responses.activate
def test_build_page_fail(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, CREATE_URL, json={"Message": "Unauthorized"}, status=401)

    result = runner.invoke(cli, ["build", "--title", "About Us", "--template", "Default"])

    assert result.exit_code == 1
