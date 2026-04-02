"""Tests for vanjaro pages commands."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, make_page_item, make_page_detail, mock_homepage

GET_PAGES_URL = f"{BASE_URL}/API/Vanjaro/Page/GetPages"
DETAIL_URL = f"{BASE_URL}/API/PersonaBar/Pages/GetPageDetails"
SAVE_URL = f"{BASE_URL}/API/Pages/Pages/SavePageDetails"
DELETE_URL = f"{BASE_URL}/API/Pages/Pages/DeletePage"
COPY_URL = f"{BASE_URL}/API/PersonaBar/Pages/CopyPage"


@responses.activate
def test_pages_list(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        GET_PAGES_URL,
        json=[make_page_item(1, "Home"), make_page_item(2, "About")],
        status=200,
    )

    result = runner.invoke(cli, ["pages", "list"])

    assert result.exit_code == 0
    assert "Home" in result.output
    assert "About" in result.output


@responses.activate
def test_pages_list_parses_ids(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        GET_PAGES_URL,
        json=[make_page_item(21, "Home"), make_page_item(34, "About")],
        status=200,
    )

    result = runner.invoke(cli, ["pages", "list", "--json"])

    data = json.loads(result.output)
    assert data[0]["id"] == 21
    assert data[0]["name"] == "Home"
    assert data[1]["id"] == 34
    assert data[1]["name"] == "About"


@responses.activate
def test_pages_list_parses_child_levels(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        GET_PAGES_URL,
        json=[
            make_page_item(1, "Parent"),
            make_page_item(2, "Child", level=1),
            make_page_item(3, "Grandchild", level=2),
        ],
        status=200,
    )

    result = runner.invoke(cli, ["pages", "list", "--json"])

    data = json.loads(result.output)
    assert data[0]["level"] == 0
    assert data[1]["level"] == 1
    assert data[1]["name"] == "Child"
    assert data[2]["level"] == 2


@responses.activate
def test_pages_list_filters_select_page_placeholder(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        GET_PAGES_URL,
        json=[
            {"Text": "Select Page", "Value": 0, "Url": None},
            make_page_item(1, "Home"),
        ],
        status=200,
    )

    result = runner.invoke(cli, ["pages", "list", "--json"])

    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["name"] == "Home"


@responses.activate
def test_pages_list_with_keyword_filter(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        GET_PAGES_URL,
        json=[make_page_item(1, "Home"), make_page_item(2, "About")],
        status=200,
    )

    result = runner.invoke(cli, ["pages", "list", "--keyword", "about"])

    assert result.exit_code == 0
    assert "About" in result.output
    assert "Home" not in result.output


@responses.activate
def test_pages_list_empty(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_PAGES_URL, json=[], status=200)

    result = runner.invoke(cli, ["pages", "list"])

    assert result.exit_code == 0
    assert "No pages found" in result.output


@responses.activate
def test_pages_get(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        DETAIL_URL,
        json={"page": make_page_detail(42, "Contact", "/contact")},
        status=200,
    )

    result = runner.invoke(cli, ["pages", "get", "42"])

    assert result.exit_code == 0
    assert "Contact" in result.output
    assert "42" in result.output


@responses.activate
def test_pages_get_json(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        DETAIL_URL,
        json={"page": make_page_detail(42, "Contact", "/contact")},
        status=200,
    )

    result = runner.invoke(cli, ["pages", "get", "42", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == 42
    assert data["name"] == "Contact"


@responses.activate
def test_pages_create(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        SAVE_URL,
        json={"page": make_page_detail(99, "New Page", "/new-page")},
        status=200,
    )

    result = runner.invoke(cli, ["pages", "create", "--title", "New Page"])

    assert result.exit_code == 0
    assert "Created page 'New Page' (ID: 99)" in result.output


@responses.activate
def test_pages_create_sends_correct_payload(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, SAVE_URL, json={"page": make_page_detail(99, "Blog")}, status=200)

    runner.invoke(cli, ["pages", "create", "--title", "Blog", "--hidden"])

    post_call = [c for c in responses.calls if "SavePageDetails" in c.request.url][0]
    sent_body = json.loads(post_call.request.body)
    assert sent_body["name"] == "Blog"
    assert sent_body["title"] == "Blog"
    assert sent_body["includeInMenu"] is False


@responses.activate
def test_pages_create_json(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        SAVE_URL,
        json={"page": make_page_detail(99, "Blog", "/blog")},
        status=200,
    )

    result = runner.invoke(cli, ["pages", "create", "--title", "Blog", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "created"


@responses.activate
def test_pages_delete_with_force(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, DELETE_URL, json={}, status=200)

    result = runner.invoke(cli, ["pages", "delete", "5", "--force"])

    assert result.exit_code == 0
    assert "Deleted page 5" in result.output


@responses.activate
def test_pages_delete_prompts_without_force(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, DELETE_URL, json={}, status=200)

    result = runner.invoke(cli, ["pages", "delete", "5"], input="y\n")

    assert result.exit_code == 0


@responses.activate
def test_pages_delete_abort(runner, mock_config):
    result = runner.invoke(cli, ["pages", "delete", "5"], input="n\n")
    assert result.exit_code != 0


@responses.activate
def test_pages_copy(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        COPY_URL,
        json={"page": make_page_detail(100, "Home Copy", "/home-copy")},
        status=200,
    )

    result = runner.invoke(cli, ["pages", "copy", "1"])

    assert result.exit_code == 0
    assert "Copied page 1 -> new ID: 100" in result.output


@responses.activate
def test_pages_settings_view(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        DETAIL_URL,
        json={"page": make_page_detail(1, "Home", "/home")},
        status=200,
    )

    result = runner.invoke(cli, ["pages", "settings", "1"])

    assert result.exit_code == 0
    assert "Home" in result.output


@responses.activate
def test_pages_settings_update(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        DETAIL_URL,
        json={"page": make_page_detail(1, "Home", "/home")},
        status=200,
    )
    responses.add(responses.POST, SAVE_URL, json={}, status=200)

    result = runner.invoke(cli, ["pages", "settings", "1", "--title", "Homepage"])

    assert result.exit_code == 0
    assert "Updated settings for page 1" in result.output

    post_call = [c for c in responses.calls if "SavePageDetails" in c.request.url][0]
    sent_body = json.loads(post_call.request.body)
    assert sent_body["title"] == "Homepage"


@responses.activate
def test_pages_api_error_surfaces(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        GET_PAGES_URL,
        json={"Message": "Portal not found"},
        status=404,
    )

    result = runner.invoke(cli, ["pages", "list"])

    assert result.exit_code == 1
