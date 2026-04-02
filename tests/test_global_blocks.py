"""Tests for vanjaro global-blocks commands (VanjaroAI endpoints)."""

from __future__ import annotations

import json

import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

LIST_URL = f"{BASE_URL}/API/VanjaroAI/AIGlobalBlock/List"
GET_URL = f"{BASE_URL}/API/VanjaroAI/AIGlobalBlock/Get"
UPDATE_URL = f"{BASE_URL}/API/VanjaroAI/AIGlobalBlock/Update"
PUBLISH_URL = f"{BASE_URL}/API/VanjaroAI/AIGlobalBlock/Publish"
DELETE_URL = f"{BASE_URL}/API/VanjaroAI/AIGlobalBlock/Delete"

SAMPLE_BLOCKS = [
    {
        "id": 1,
        "guid": "20020077-89f8-468f-a488-017421ce5a0b",
        "name": "Header",
        "category": "site",
        "isPublished": True,
        "version": 1,
        "updatedOn": "2026-04-02T12:16:35.05Z",
    },
    {
        "id": 2,
        "guid": "fe37ff48-2c99-4201-85fc-913cac94914d",
        "name": "Footer",
        "category": "site",
        "isPublished": True,
        "version": 1,
        "updatedOn": "2026-04-02T12:16:35.087Z",
    },
]

SAMPLE_BLOCK_DETAIL = {
    "id": 1,
    "guid": "20020077-89f8-468f-a488-017421ce5a0b",
    "name": "Header",
    "category": "site",
    "version": 1,
    "isPublished": True,
    "contentJSON": [{"type": "section", "components": []}],
    "styleJSON": [{"selectors": [".header"], "style": {"color": "blue"}}],
}


@responses.activate
def test_global_blocks_list(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json={"total": 2, "blocks": SAMPLE_BLOCKS}, status=200)

    result = runner.invoke(cli, ["global-blocks", "list"])

    assert result.exit_code == 0
    assert "Header" in result.output
    assert "Footer" in result.output


@responses.activate
def test_global_blocks_list_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json={"total": 2, "blocks": SAMPLE_BLOCKS}, status=200)

    result = runner.invoke(cli, ["global-blocks", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 2
    assert data[0]["name"] == "Header"
    assert data[0]["is_published"] is True
    assert data[1]["guid"] == "fe37ff48-2c99-4201-85fc-913cac94914d"


@responses.activate
def test_global_blocks_list_empty(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json={"total": 0, "blocks": []}, status=200)

    result = runner.invoke(cli, ["global-blocks", "list"])

    assert result.exit_code == 0
    assert "No global blocks found." in result.output


@responses.activate
def test_global_blocks_get(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_BLOCK_DETAIL, status=200)

    result = runner.invoke(cli, ["global-blocks", "get", "20020077-89f8-468f-a488-017421ce5a0b"])

    assert result.exit_code == 0
    assert "Header" in result.output
    assert "20020077-89f8-468f-a488-017421ce5a0b" in result.output
    assert "site" in result.output


@responses.activate
def test_global_blocks_get_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_BLOCK_DETAIL, status=200)

    result = runner.invoke(cli, ["global-blocks", "get", "20020077-89f8-468f-a488-017421ce5a0b", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "Header"
    assert data["guid"] == "20020077-89f8-468f-a488-017421ce5a0b"
    assert len(data["content_json"]) == 1
    assert data["content_json"][0]["type"] == "section"


@responses.activate
def test_global_blocks_get_to_file(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_BLOCK_DETAIL, status=200)
    output_file = tmp_path / "block.json"

    result = runner.invoke(cli, ["global-blocks", "get", "20020077-89f8-468f-a488-017421ce5a0b", "--output", str(output_file)])

    assert result.exit_code == 0
    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert data["name"] == "Header"
    assert "Block written to" in result.output


@responses.activate
def test_global_blocks_get_not_found(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json={"Message": "Block not found"}, status=404)

    result = runner.invoke(cli, ["global-blocks", "get", "nonexistent-guid"])

    assert result.exit_code == 1


@responses.activate
def test_global_blocks_api_error(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json={"Message": "Internal server error"}, status=500)

    result = runner.invoke(cli, ["global-blocks", "list"])

    assert result.exit_code == 1


@responses.activate
def test_global_blocks_update(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, UPDATE_URL, json={"status": "ok"}, status=200)

    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps({
        "content_json": [{"type": "section", "components": []}],
        "style_json": [{"selectors": [".header"], "style": {"color": "red"}}],
    }))

    result = runner.invoke(cli, [
        "global-blocks", "update", "20020077-89f8-468f-a488-017421ce5a0b",
        "--file", str(block_file),
    ])

    assert result.exit_code == 0
    assert "updated" in result.output

    request_body = json.loads(responses.calls[-1].request.body)
    assert request_body["guid"] == "20020077-89f8-468f-a488-017421ce5a0b"
    assert request_body["contentJSON"] == [{"type": "section", "components": []}]
    assert request_body["styleJSON"] == [{"selectors": [".header"], "style": {"color": "red"}}]


@responses.activate
def test_global_blocks_update_json(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, UPDATE_URL, json={"status": "ok"}, status=200)

    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps({
        "contentJSON": [{"type": "div"}],
        "styleJSON": [],
    }))

    result = runner.invoke(cli, [
        "global-blocks", "update", "20020077-89f8-468f-a488-017421ce5a0b",
        "--file", str(block_file), "--json",
    ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "updated"
    assert data["guid"] == "20020077-89f8-468f-a488-017421ce5a0b"


@responses.activate
def test_global_blocks_publish(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, PUBLISH_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(cli, ["global-blocks", "publish", "20020077-89f8-468f-a488-017421ce5a0b"])

    assert result.exit_code == 0
    assert "published" in result.output

    request_body = json.loads(responses.calls[-1].request.body)
    assert request_body["guid"] == "20020077-89f8-468f-a488-017421ce5a0b"


@responses.activate
def test_global_blocks_publish_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, PUBLISH_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(cli, ["global-blocks", "publish", "20020077-89f8-468f-a488-017421ce5a0b", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["guid"] == "20020077-89f8-468f-a488-017421ce5a0b"


@responses.activate
def test_global_blocks_delete_with_force(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, DELETE_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(cli, ["global-blocks", "delete", "20020077-89f8-468f-a488-017421ce5a0b", "--force"])

    assert result.exit_code == 0
    assert "deleted" in result.output

    request_body = json.loads(responses.calls[-1].request.body)
    assert request_body["guid"] == "20020077-89f8-468f-a488-017421ce5a0b"


def test_global_blocks_delete_abort(runner, mock_config):
    result = runner.invoke(cli, ["global-blocks", "delete", "20020077-89f8-468f-a488-017421ce5a0b"], input="n\n")

    assert result.exit_code != 0


@responses.activate
def test_global_blocks_delete_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, DELETE_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(cli, ["global-blocks", "delete", "20020077-89f8-468f-a488-017421ce5a0b", "--force", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "deleted"
    assert data["guid"] == "20020077-89f8-468f-a488-017421ce5a0b"
