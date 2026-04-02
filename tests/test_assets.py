"""Tests for vanjaro assets commands."""

from __future__ import annotations

import base64
import json

import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

FOLDERS_URL = f"{BASE_URL}/API/VanjaroAI/AIAsset/ListFolders"
FILES_URL = f"{BASE_URL}/API/VanjaroAI/AIAsset/ListFiles"
UPLOAD_URL = f"{BASE_URL}/API/VanjaroAI/AIAsset/Upload"
DELETE_URL = f"{BASE_URL}/API/VanjaroAI/AIAsset/Delete"

SAMPLE_FOLDERS = [
    {"folderId": 36, "folderPath": "", "displayName": ""},
    {"folderId": 37, "folderPath": "Images/", "displayName": "Images"},
]

SAMPLE_FILES = [
    {
        "fileId": 127,
        "fileName": "background_header.gif",
        "folderPath": "Images/",
        "relativePath": "Images/background_header.gif",
        "url": "/Portals/0/Images/background_header.gif?ver=2026",
        "extension": "gif",
        "size": 4922,
        "width": 1089,
        "height": 254,
        "contentType": "image/gif",
        "lastModified": "2026-04-02T08:10:50.873",
    }
]


@responses.activate
def test_assets_folders(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, FOLDERS_URL, json=SAMPLE_FOLDERS, status=200)

    result = runner.invoke(cli, ["assets", "folders"])

    assert result.exit_code == 0
    assert "Images" in result.output
    assert "36" in result.output
    assert "37" in result.output


@responses.activate
def test_assets_folders_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, FOLDERS_URL, json=SAMPLE_FOLDERS, status=200)

    result = runner.invoke(cli, ["assets", "folders", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 2
    assert data[0]["folder_id"] == 36
    assert data[1]["folder_path"] == "Images/"


@responses.activate
def test_assets_list(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, FILES_URL, json=SAMPLE_FILES, status=200)

    result = runner.invoke(cli, ["assets", "list"])

    assert result.exit_code == 0
    assert "background_header.gif" in result.output
    assert "127" in result.output


@responses.activate
def test_assets_list_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, FILES_URL, json=SAMPLE_FILES, status=200)

    result = runner.invoke(cli, ["assets", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["file_id"] == 127
    assert data[0]["file_name"] == "background_header.gif"
    assert data[0]["content_type"] == "image/gif"


@responses.activate
def test_assets_list_with_folder(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, FILES_URL, json=SAMPLE_FILES, status=200)

    result = runner.invoke(cli, ["assets", "list", "--folder", "37"])

    assert result.exit_code == 0

    request = responses.calls[-1].request
    assert "folderId=37" in request.url


@responses.activate
def test_assets_list_empty(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, FILES_URL, json=[], status=200)

    result = runner.invoke(cli, ["assets", "list"])

    assert result.exit_code == 0
    assert "No files found" in result.output


@responses.activate
def test_assets_upload(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, UPLOAD_URL, json={"status": "ok"}, status=200)

    test_file = tmp_path / "photo.jpg"
    test_file.write_bytes(b"fake-image-bytes")

    result = runner.invoke(cli, ["assets", "upload", str(test_file)])

    assert result.exit_code == 0
    assert "Uploaded" in result.output

    request = responses.calls[-1].request
    sent = json.loads(request.body)
    assert sent["fileName"] == "photo.jpg"
    assert sent["folderPath"] == ""
    expected_content = base64.b64encode(b"fake-image-bytes").decode("ascii")
    assert sent["fileContent"] == expected_content


@responses.activate
def test_assets_upload_with_folder(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, UPLOAD_URL, json={"status": "ok"}, status=200)

    test_file = tmp_path / "photo.jpg"
    test_file.write_bytes(b"fake-image-bytes")

    result = runner.invoke(cli, ["assets", "upload", str(test_file), "--folder", "Images/"])

    assert result.exit_code == 0

    request = responses.calls[-1].request
    sent = json.loads(request.body)
    assert sent["folderPath"] == "Images/"


@responses.activate
def test_assets_upload_json(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, UPLOAD_URL, json={"fileId": 200, "fileName": "photo.jpg"}, status=200)

    test_file = tmp_path / "photo.jpg"
    test_file.write_bytes(b"fake-image-bytes")

    result = runner.invoke(cli, ["assets", "upload", str(test_file), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["fileId"] == 200


def test_assets_upload_file_not_found(runner, mock_config):
    result = runner.invoke(cli, ["assets", "upload", "/nonexistent/file.jpg"])

    assert result.exit_code != 0
    assert "File not found" in result.output


def test_assets_folders_empty(runner, mock_config):
    import responses as resp_lib
    with resp_lib.RequestsMock() as rsps:
        from tests.conftest import mock_homepage as mh, BASE_URL
        mh(rsps)
        rsps.add(resp_lib.GET, f"{BASE_URL}/API/VanjaroAI/AIAsset/ListFolders", json=[], status=200)
        result = runner.invoke(cli, ["assets", "folders"])

    assert result.exit_code == 0
    assert "No folders found" in result.output


@responses.activate
def test_assets_delete_with_force(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, DELETE_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(cli, ["assets", "delete", "127", "--force"])

    assert result.exit_code == 0
    assert "Deleted file 127" in result.output

    request = responses.calls[-1].request
    sent = json.loads(request.body)
    assert sent["fileId"] == 127


@responses.activate
def test_assets_delete_prompts_without_force(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, DELETE_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(cli, ["assets", "delete", "127"], input="y\n")

    assert result.exit_code == 0


def test_assets_delete_abort(runner, mock_config):
    result = runner.invoke(cli, ["assets", "delete", "127"], input="n\n")

    assert result.exit_code != 0


@responses.activate
def test_assets_api_error(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, FILES_URL, json={"Message": "Not found"}, status=404)

    result = runner.invoke(cli, ["assets", "list"])

    assert result.exit_code == 1
