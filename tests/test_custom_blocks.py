"""Tests for vanjaro custom-blocks commands (core Vanjaro Block API)."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

LIST_URL = f"{BASE_URL}/API/Vanjaro/Block/GetAllCustomBlock"
ADD_URL = f"{BASE_URL}/API/Vanjaro/Block/AddCustomBlock"
DELETE_URL = f"{BASE_URL}/API/Vanjaro/Block/DeleteCustomBlock"

SAMPLE_BLOCKS = [
    {
        "ScreenshotPath": None,
        "IsGlobal": False,
        "ID": 1,
        "Guid": "abc12345-6789-0000-1111-222233334444",
        "PortalID": 0,
        "Name": "Hero Banner",
        "Category": "heroes",
        "ContentJSON": '[{"type": "section", "components": []}]',
        "StyleJSON": "[]",
        "IsLibrary": False,
        "CreatedBy": 1,
        "CreatedOn": "2026-04-08T12:00:00Z",
        "UpdatedBy": 1,
        "UpdatedOn": "2026-04-08T12:00:00Z",
    },
    {
        "ScreenshotPath": None,
        "IsGlobal": False,
        "ID": 2,
        "Guid": "def67890-1234-5555-6666-777788889999",
        "PortalID": 0,
        "Name": "Feature Cards",
        "Category": "content",
        "ContentJSON": '[{"type": "section", "components": [{"type": "heading"}]}]',
        "StyleJSON": '[{"selectors": [".card"], "style": {"padding": "1rem"}}]',
        "IsLibrary": False,
        "CreatedBy": 1,
        "CreatedOn": "2026-04-08T12:00:00Z",
        "UpdatedBy": 1,
        "UpdatedOn": "2026-04-08T12:00:00Z",
    },
]

SAMPLE_BLOCK_FILE = {
    "contentJSON": [{"type": "section", "components": [{"type": "heading", "content": "CTA"}]}],
    "styleJSON": [{"selectors": [".cta"], "style": {"background": "#C75B8E"}}],
}


def _parse_form_body(request) -> dict[str, str]:
    """Parse a form-encoded request body into a dict."""
    parsed = parse_qs(request.body, keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items()}


# -- list --


@responses.activate
def test_custom_blocks_list(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json=SAMPLE_BLOCKS, status=200)

    result = runner.invoke(cli, ["custom-blocks", "list"])

    assert result.exit_code == 0
    assert "Hero Banner" in result.output
    assert "Feature Cards" in result.output
    assert "heroes" in result.output


@responses.activate
def test_custom_blocks_list_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json=SAMPLE_BLOCKS, status=200)

    result = runner.invoke(cli, ["custom-blocks", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 2
    assert data[0]["name"] == "Hero Banner"
    assert data[0]["guid"] == "abc12345-6789-0000-1111-222233334444"
    assert data[0]["content_json"][0]["type"] == "section"
    assert data[1]["style_json"][0]["selectors"] == [".card"]


@responses.activate
def test_custom_blocks_list_empty(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json=[], status=200)

    result = runner.invoke(cli, ["custom-blocks", "list"])

    assert result.exit_code == 0
    assert "No custom blocks found." in result.output


# -- create --


@responses.activate
def test_custom_blocks_create(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, ADD_URL, json={"Status": "Success", "Guid": None}, status=200)
    # GUID lookup after create
    responses.add(responses.GET, LIST_URL, json=[{
        "ID": 5, "Guid": "new-guid-1234", "Name": "CTA Block", "Category": "cta",
        "ContentJSON": "[]", "StyleJSON": "[]",
    }], status=200)

    block_file = tmp_path / "cta.json"
    block_file.write_text(json.dumps(SAMPLE_BLOCK_FILE))

    result = runner.invoke(cli, [
        "custom-blocks", "create",
        "--name", "CTA Block",
        "--category", "cta",
        "--file", str(block_file),
    ])

    assert result.exit_code == 0
    assert "Created custom block 'CTA Block'" in result.output
    assert "new-guid-1234" in result.output

    # Verify form-encoded body was sent
    form_body = _parse_form_body(responses.calls[1].request)
    assert form_body["Name"] == "CTA Block"
    assert form_body["Category"] == "cta"
    assert form_body["IsGlobal"] == "false"
    assert form_body["Html"] == ""
    content = json.loads(form_body["ContentJSON"])
    assert content[0]["type"] == "section"


@responses.activate
def test_custom_blocks_create_json(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, ADD_URL, json={"Status": "Success", "Guid": None}, status=200)
    responses.add(responses.GET, LIST_URL, json=[{
        "ID": 5, "Guid": "new-guid-5678", "Name": "Test Block", "Category": "general",
        "ContentJSON": "[]", "StyleJSON": "[]",
    }], status=200)

    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps(SAMPLE_BLOCK_FILE))

    result = runner.invoke(cli, [
        "custom-blocks", "create",
        "--name", "Test Block",
        "--file", str(block_file),
        "--json",
    ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "created"
    assert data["name"] == "Test Block"
    assert data["guid"] == "new-guid-5678"
    assert data["category"] == "general"


@responses.activate
def test_custom_blocks_create_duplicate_name(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, ADD_URL, json={"Status": "Exist"}, status=200)

    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps({"contentJSON": [], "styleJSON": []}))

    result = runner.invoke(cli, [
        "custom-blocks", "create",
        "--name", "Hero Banner",
        "--file", str(block_file),
    ])

    assert result.exit_code == 1
    assert "already exists" in result.output


@responses.activate
def test_custom_blocks_create_scaffold_format(runner, mock_config, tmp_path):
    """Accepts scaffold output format with components/styles keys."""
    mock_homepage()
    responses.add(responses.POST, ADD_URL, json={"Status": "Success", "Guid": None}, status=200)
    responses.add(responses.GET, LIST_URL, json=[{
        "ID": 6, "Guid": "scaffold-guid", "Name": "Scaffolded", "Category": "general",
        "ContentJSON": "[]", "StyleJSON": "[]",
    }], status=200)

    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps({
        "components": [{"type": "section", "components": []}],
        "styles": [],
    }))

    result = runner.invoke(cli, [
        "custom-blocks", "create",
        "--name", "Scaffolded",
        "--file", str(block_file),
    ])

    assert result.exit_code == 0
    form_body = _parse_form_body(responses.calls[1].request)
    assert json.loads(form_body["ContentJSON"]) == [{"type": "section", "components": []}]


def test_custom_blocks_create_invalid_json_file(runner, mock_config, tmp_path):
    block_file = tmp_path / "bad.json"
    block_file.write_text("not json {{{")

    result = runner.invoke(cli, [
        "custom-blocks", "create",
        "--name", "Bad Block",
        "--file", str(block_file),
    ])

    assert result.exit_code == 1


def test_custom_blocks_create_missing_name(runner, mock_config, tmp_path):
    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps({"contentJSON": []}))

    result = runner.invoke(cli, ["custom-blocks", "create", "--file", str(block_file)])

    assert result.exit_code != 0


# -- delete --


@responses.activate
def test_custom_blocks_delete_with_force(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, DELETE_URL, json={"Status": "Success"}, status=200)

    result = runner.invoke(cli, ["custom-blocks", "delete", "abc12345-guid", "--force"])

    assert result.exit_code == 0
    assert "deleted" in result.output

    # Verify GUID was passed as query param
    assert "CustomBlockGuid=abc12345-guid" in responses.calls[-1].request.url


@responses.activate
def test_custom_blocks_delete_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, DELETE_URL, json={"Status": "Success"}, status=200)

    result = runner.invoke(cli, ["custom-blocks", "delete", "abc12345-guid", "--force", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "deleted"
    assert data["guid"] == "abc12345-guid"


def test_custom_blocks_delete_abort(runner, mock_config):
    result = runner.invoke(cli, ["custom-blocks", "delete", "abc12345-guid"], input="n\n")

    assert result.exit_code != 0
