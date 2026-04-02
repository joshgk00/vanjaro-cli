"""Tests for vanjaro blocks commands."""

from __future__ import annotations

import json

import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

LIST_URL = f"{BASE_URL}/API/VanjaroAI/AIBlock/List"
GET_URL = f"{BASE_URL}/API/VanjaroAI/AIBlock/Get"
PAGE_GET_URL = f"{BASE_URL}/API/VanjaroAI/AIPage/Get"
PAGE_UPDATE_URL = f"{BASE_URL}/API/VanjaroAI/AIPage/Update"

SAMPLE_BLOCKS = {
    "pageId": 34,
    "version": 3,
    "total": 2,
    "blocks": [
        {
            "componentId": "hdr1",
            "guid": "guid-header",
            "blockTypeGuid": "bt-guid",
            "type": "globalblockwrapper",
            "name": "Global: Header",
            "childCount": 0,
        },
        {
            "componentId": "ftr1",
            "guid": "guid-footer",
            "blockTypeGuid": "bt-guid",
            "type": "globalblockwrapper",
            "name": "Global: Footer",
            "childCount": 0,
        },
    ],
}

SAMPLE_BLOCK_DETAIL = {
    "pageId": 34,
    "version": 3,
    "componentId": "hdr1",
    "guid": "guid-header",
    "blockTypeGuid": "bt-guid",
    "type": "globalblockwrapper",
    "name": "Global: Header",
    "contentJSON": {"type": "globalblockwrapper", "attributes": {"id": "hdr1"}},
    "styleJSON": [],
}

SAMPLE_PAGE_CONTENT = {
    "contentJSON": json.dumps([
        {"type": "section", "attributes": {"id": "s1"}, "components": [
            {"type": "text", "content": "Hello", "attributes": {"id": "t1"}},
        ]},
    ]),
    "styleJSON": json.dumps([]),
    "version": 3,
}


@responses.activate
def test_blocks_list(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json=SAMPLE_BLOCKS, status=200)

    result = runner.invoke(cli, ["blocks", "list", "34"])

    assert result.exit_code == 0
    assert "Global: Header" in result.output
    assert "Global: Footer" in result.output


@responses.activate
def test_blocks_list_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json=SAMPLE_BLOCKS, status=200)

    result = runner.invoke(cli, ["blocks", "list", "34", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["page_id"] == 34
    assert data["total"] == 2
    assert len(data["blocks"]) == 2
    assert data["blocks"][0]["component_id"] == "hdr1"


@responses.activate
def test_blocks_list_empty(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json={"pageId": 34, "version": 1, "total": 0, "blocks": []}, status=200)

    result = runner.invoke(cli, ["blocks", "list", "34"])

    assert result.exit_code == 0
    assert "No blocks found" in result.output


@responses.activate
def test_blocks_get(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_BLOCK_DETAIL, status=200)

    result = runner.invoke(cli, ["blocks", "get", "34", "hdr1"])

    assert result.exit_code == 0
    assert "hdr1" in result.output
    assert "globalblockwrapper" in result.output


@responses.activate
def test_blocks_get_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_BLOCK_DETAIL, status=200)

    result = runner.invoke(cli, ["blocks", "get", "34", "hdr1", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["component_id"] == "hdr1"
    assert data["type"] == "globalblockwrapper"
    assert "content_json" in data


@responses.activate
def test_blocks_get_to_file(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_BLOCK_DETAIL, status=200)
    output_file = tmp_path / "block.json"

    result = runner.invoke(cli, ["blocks", "get", "34", "hdr1", "--output", str(output_file)])

    assert result.exit_code == 0
    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert data["component_id"] == "hdr1"


@responses.activate
def test_blocks_tree(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, PAGE_GET_URL, json=SAMPLE_PAGE_CONTENT, status=200)

    result = runner.invoke(cli, ["blocks", "tree", "34"])

    assert result.exit_code == 0
    assert "section [s1]" in result.output
    assert "  text [t1]" in result.output


@responses.activate
def test_blocks_tree_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, PAGE_GET_URL, json=SAMPLE_PAGE_CONTENT, status=200)

    result = runner.invoke(cli, ["blocks", "tree", "34", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 2
    assert data[0]["type"] == "section"
    assert data[0]["depth"] == 0
    assert data[1]["type"] == "text"
    assert data[1]["depth"] == 1


@responses.activate
def test_blocks_add(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, PAGE_GET_URL, json=SAMPLE_PAGE_CONTENT, status=200)
    responses.add(responses.POST, PAGE_UPDATE_URL, json={"pageId": 34, "version": 4}, status=200)

    result = runner.invoke(cli, ["blocks", "add", "34", "--type", "text", "--content", "New paragraph"])

    assert result.exit_code == 0
    assert "Added text" in result.output
    assert "version 4" in result.output

    post_call = [c for c in responses.calls if "AIPage/Update" in c.request.url][0]
    sent = json.loads(post_call.request.body)
    components = json.loads(sent["contentJSON"])
    assert len(components) == 2
    assert components[1]["type"] == "text"
    assert components[1]["content"] == "New paragraph"


@responses.activate
def test_blocks_add_into_parent(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, PAGE_GET_URL, json=SAMPLE_PAGE_CONTENT, status=200)
    responses.add(responses.POST, PAGE_UPDATE_URL, json={"pageId": 34, "version": 4}, status=200)

    result = runner.invoke(cli, ["blocks", "add", "34", "--type", "heading", "--content", "Title", "--parent", "s1"])

    assert result.exit_code == 0

    post_call = [c for c in responses.calls if "AIPage/Update" in c.request.url][0]
    sent = json.loads(post_call.request.body)
    components = json.loads(sent["contentJSON"])
    section = components[0]
    assert len(section["components"]) == 2
    assert section["components"][1]["type"] == "heading"


@responses.activate
def test_blocks_add_with_classes(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, PAGE_GET_URL, json=SAMPLE_PAGE_CONTENT, status=200)
    responses.add(responses.POST, PAGE_UPDATE_URL, json={"pageId": 34, "version": 4}, status=200)

    result = runner.invoke(cli, ["blocks", "add", "34", "--type", "text", "--classes", "vj-text,text-dark"])

    assert result.exit_code == 0

    post_call = [c for c in responses.calls if "AIPage/Update" in c.request.url][0]
    sent = json.loads(post_call.request.body)
    components = json.loads(sent["contentJSON"])
    new_comp = components[1]
    assert len(new_comp["classes"]) == 2
    assert new_comp["classes"][0]["name"] == "vj-text"


@responses.activate
def test_blocks_add_parent_not_found(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, PAGE_GET_URL, json=SAMPLE_PAGE_CONTENT, status=200)

    result = runner.invoke(cli, ["blocks", "add", "34", "--type", "text", "--parent", "nonexistent"])

    assert result.exit_code == 1


@responses.activate
def test_blocks_add_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, PAGE_GET_URL, json=SAMPLE_PAGE_CONTENT, status=200)
    responses.add(responses.POST, PAGE_UPDATE_URL, json={"pageId": 34, "version": 4}, status=200)

    result = runner.invoke(cli, ["blocks", "add", "34", "--type", "section", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "added"
    assert data["page_id"] == 34


@responses.activate
def test_blocks_remove_with_force(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, PAGE_GET_URL, json=SAMPLE_PAGE_CONTENT, status=200)
    responses.add(responses.POST, PAGE_UPDATE_URL, json={"pageId": 34, "version": 4}, status=200)

    result = runner.invoke(cli, ["blocks", "remove", "34", "t1", "--force"])

    assert result.exit_code == 0
    assert "Removed t1" in result.output

    post_call = [c for c in responses.calls if "AIPage/Update" in c.request.url][0]
    sent = json.loads(post_call.request.body)
    components = json.loads(sent["contentJSON"])
    section = components[0]
    assert len(section["components"]) == 0


@responses.activate
def test_blocks_remove_prompts_without_force(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, PAGE_GET_URL, json=SAMPLE_PAGE_CONTENT, status=200)
    responses.add(responses.POST, PAGE_UPDATE_URL, json={"pageId": 34, "version": 4}, status=200)

    result = runner.invoke(cli, ["blocks", "remove", "34", "t1"], input="y\n")

    assert result.exit_code == 0


def test_blocks_remove_abort(runner, mock_config):
    result = runner.invoke(cli, ["blocks", "remove", "34", "t1"], input="n\n")
    assert result.exit_code != 0


@responses.activate
def test_blocks_remove_not_found(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, PAGE_GET_URL, json=SAMPLE_PAGE_CONTENT, status=200)

    result = runner.invoke(cli, ["blocks", "remove", "34", "nonexistent", "--force"])

    assert result.exit_code == 1


@responses.activate
def test_blocks_remove_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, PAGE_GET_URL, json=SAMPLE_PAGE_CONTENT, status=200)
    responses.add(responses.POST, PAGE_UPDATE_URL, json={"pageId": 34, "version": 4}, status=200)

    result = runner.invoke(cli, ["blocks", "remove", "34", "t1", "--force", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "removed"
    assert data["component_id"] == "t1"


@responses.activate
def test_blocks_api_error(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json={"Message": "Not found"}, status=404)

    result = runner.invoke(cli, ["blocks", "list", "999"])

    assert result.exit_code == 1
