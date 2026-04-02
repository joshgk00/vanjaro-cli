"""Tests for vanjaro modules commands."""

from __future__ import annotations

import json

import responses

from vanjaro_cli.cli import cli
from vanjaro_cli.commands.modules_cmd import modules
from tests.conftest import BASE_URL, make_page_detail, mock_homepage

if "modules" not in [c.name for c in cli.commands.values()]:
    cli.add_command(modules)

BASE_URL = BASE_URL
DETAIL_URL = f"{BASE_URL}/API/PersonaBar/Pages/GetPageDetails"

SAMPLE_MODULES = [
    {
        "id": 354,
        "title": "",
        "friendlyName": "HTML",
        "editContentUrl": "http://vanjarocli.local/Home/ctl/Edit/mid/354?popUp=true",
        "editSettingUrl": "http://vanjarocli.local/Home/ctl/Module/ModuleId/354?popUp=true",
    },
    {
        "id": 355,
        "title": "Home Banner",
        "friendlyName": "HTML",
        "editContentUrl": "http://vanjarocli.local/Home/ctl/Edit/mid/355?popUp=true",
        "editSettingUrl": "http://vanjarocli.local/Home/ctl/Module/ModuleId/355?popUp=true",
    },
]


def make_page_detail_with_modules(
    tab_id: int = 21,
    name: str = "Home",
    module_list: list | None = None,
) -> dict:
    """Build a page detail response that includes a modules array."""
    detail = make_page_detail(tab_id=tab_id, name=name)
    detail["modules"] = module_list if module_list is not None else []
    return detail


@responses.activate
def test_modules_list(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        DETAIL_URL,
        json={"page": make_page_detail_with_modules(21, "Home", SAMPLE_MODULES)},
        status=200,
    )

    result = runner.invoke(cli, ["modules", "list", "21"])

    assert result.exit_code == 0
    assert "Page 21 modules:" in result.output
    assert "354" in result.output
    assert "355" in result.output
    assert "Home Banner" in result.output
    assert "HTML" in result.output


@responses.activate
def test_modules_list_json(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        DETAIL_URL,
        json={"page": make_page_detail_with_modules(21, "Home", SAMPLE_MODULES)},
        status=200,
    )

    result = runner.invoke(cli, ["modules", "list", "21", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 2
    assert data[0]["id"] == 354
    assert data[0]["friendlyName"] == "HTML"
    assert data[1]["id"] == 355
    assert data[1]["title"] == "Home Banner"


@responses.activate
def test_modules_list_empty(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        DETAIL_URL,
        json={"page": make_page_detail_with_modules(34, "About")},
        status=200,
    )

    result = runner.invoke(cli, ["modules", "list", "34"])

    assert result.exit_code == 0
    assert "No modules on page 34." in result.output


@responses.activate
def test_modules_api_error(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.GET,
        DETAIL_URL,
        json={"Message": "Page not found"},
        status=404,
    )

    result = runner.invoke(cli, ["modules", "list", "999"])

    assert result.exit_code == 1
