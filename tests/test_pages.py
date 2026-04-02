"""Tests for vanjaro pages commands."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, make_page

SEARCH_URL = f"{BASE_URL}/API/PersonaBar/Pages/SearchPages"
DETAIL_URL = f"{BASE_URL}/API/PersonaBar/Pages/GetPageDetails"
SAVE_URL = f"{BASE_URL}/API/PersonaBar/Pages/SavePageDetails"
DELETE_URL = f"{BASE_URL}/API/PersonaBar/Pages/DeletePage"
COPY_URL = f"{BASE_URL}/API/PersonaBar/Pages/CopyPage"
CSRF_URL = f"{BASE_URL}/API/PersonaBar/Security/GetAntiForgeryToken"


@responses.activate
def test_pages_list(runner, mock_config):
    responses.add(
        responses.GET,
        SEARCH_URL,
        json={"pages": [make_page(1, "Home", "/home"), make_page(2, "About", "/about")]},
        status=200,
    )

    result = runner.invoke(cli, ["pages", "list"])

    assert result.exit_code == 0
    assert "Home" in result.output
    assert "About" in result.output


@responses.activate
def test_pages_list_json(runner, mock_config):
    responses.add(
        responses.GET,
        SEARCH_URL,
        json={"pages": [make_page(1, "Home")]},
        status=200,
    )

    result = runner.invoke(cli, ["pages", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["name"] == "Home"


@responses.activate
def test_pages_list_empty(runner, mock_config):
    responses.add(responses.GET, SEARCH_URL, json={"pages": []}, status=200)

    result = runner.invoke(cli, ["pages", "list"])

    assert result.exit_code == 0
    assert "No pages found" in result.output


@responses.activate
def test_pages_get(runner, mock_config):
    responses.add(
        responses.GET,
        DETAIL_URL,
        json={"page": make_page(42, "Contact", "/contact")},
        status=200,
    )

    result = runner.invoke(cli, ["pages", "get", "42"])

    assert result.exit_code == 0
    assert "Contact" in result.output
    assert "42" in result.output


@responses.activate
def test_pages_get_json(runner, mock_config):
    responses.add(
        responses.GET,
        DETAIL_URL,
        json={"page": make_page(42, "Contact", "/contact")},
        status=200,
    )

    result = runner.invoke(cli, ["pages", "get", "42", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == 42
    assert data["name"] == "Contact"


@responses.activate
def test_pages_create(runner, mock_config):
    responses.add(responses.GET, CSRF_URL, json={"token": "csrf-abc"}, status=200)
    responses.add(
        responses.POST,
        SAVE_URL,
        json={"page": make_page(99, "New Page", "/new-page")},
        status=200,
    )

    result = runner.invoke(cli, ["pages", "create", "--title", "New Page"])

    assert result.exit_code == 0
    assert "New Page" in result.output or "99" in result.output


@responses.activate
def test_pages_create_json(runner, mock_config):
    responses.add(responses.GET, CSRF_URL, json={"token": "csrf-abc"}, status=200)
    responses.add(
        responses.POST,
        SAVE_URL,
        json={"page": make_page(99, "Blog", "/blog")},
        status=200,
    )

    result = runner.invoke(cli, ["pages", "create", "--title", "Blog", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "created"


@responses.activate
def test_pages_delete_with_force(runner, mock_config):
    responses.add(responses.GET, CSRF_URL, json={"token": "csrf-abc"}, status=200)
    responses.add(responses.POST, DELETE_URL, json={}, status=200)

    result = runner.invoke(cli, ["pages", "delete", "5", "--force"])

    assert result.exit_code == 0
    assert "Deleted" in result.output or "5" in result.output


@responses.activate
def test_pages_delete_prompts_without_force(runner, mock_config):
    responses.add(responses.GET, CSRF_URL, json={"token": "csrf-abc"}, status=200)
    responses.add(responses.POST, DELETE_URL, json={}, status=200)

    # Simulate user typing "y" at the confirmation prompt
    result = runner.invoke(cli, ["pages", "delete", "5"], input="y\n")

    assert result.exit_code == 0


@responses.activate
def test_pages_delete_abort(runner, mock_config):
    result = runner.invoke(cli, ["pages", "delete", "5"], input="n\n")
    assert result.exit_code != 0


@responses.activate
def test_pages_copy(runner, mock_config):
    responses.add(responses.GET, CSRF_URL, json={"token": "csrf-abc"}, status=200)
    responses.add(
        responses.POST,
        COPY_URL,
        json={"page": make_page(100, "Home Copy", "/home-copy")},
        status=200,
    )

    result = runner.invoke(cli, ["pages", "copy", "1"])

    assert result.exit_code == 0
    assert "100" in result.output or "Copy" in result.output


@responses.activate
def test_pages_settings_view(runner, mock_config):
    responses.add(
        responses.GET,
        DETAIL_URL,
        json={"page": make_page(1, "Home", "/home")},
        status=200,
    )

    result = runner.invoke(cli, ["pages", "settings", "1"])

    assert result.exit_code == 0
    assert "Home" in result.output


@responses.activate
def test_pages_settings_update(runner, mock_config):
    responses.add(
        responses.GET,
        DETAIL_URL,
        json={"page": make_page(1, "Home", "/home")},
        status=200,
    )
    responses.add(responses.GET, CSRF_URL, json={"token": "csrf-abc"}, status=200)
    responses.add(responses.POST, SAVE_URL, json={}, status=200)

    result = runner.invoke(cli, ["pages", "settings", "1", "--title", "Homepage"])

    assert result.exit_code == 0
    assert "Updated" in result.output or "1" in result.output


@responses.activate
def test_pages_api_error_surfaces(runner, mock_config):
    responses.add(
        responses.GET,
        SEARCH_URL,
        json={"Message": "Portal not found"},
        status=404,
    )

    result = runner.invoke(cli, ["pages", "list"])

    assert result.exit_code == 1
