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
    assert sent["base64Content"] == expected_content


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


@responses.activate
def test_assets_folders_empty(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, FOLDERS_URL, json=[], status=200)

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


def _make_upload_dir(tmp_path, filenames=("hero.jpg", "photo.png", "icon.svg")):
    """Create a temp directory with a few supported asset files."""
    source = tmp_path / "assets"
    source.mkdir()
    for name in filenames:
        (source / name).write_bytes(f"bytes-for-{name}".encode("ascii"))
    return source


def _upload_response(file_id: int, name: str, folder: str = "Images/") -> dict:
    return {
        "fileId": file_id,
        "fileName": name,
        "url": f"/Portals/0/{folder}{name}",
    }


@responses.activate
def test_assets_upload_dir_happy_path(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, UPLOAD_URL, json=_upload_response(10, "hero.jpg"), status=200)
    responses.add(responses.POST, UPLOAD_URL, json=_upload_response(11, "icon.svg"), status=200)
    responses.add(responses.POST, UPLOAD_URL, json=_upload_response(12, "photo.png"), status=200)

    source = _make_upload_dir(tmp_path)

    result = runner.invoke(cli, ["assets", "upload-dir", str(source)])

    assert result.exit_code == 0, result.output
    assert "Uploaded 3 of 3" in result.output

    manifest = json.loads((source / "manifest.json").read_text())
    assert len(manifest) == 3
    by_name = {entry["local_file"]: entry for entry in manifest}
    assert by_name["hero.jpg"]["uploaded"] is True
    assert by_name["hero.jpg"]["vanjaro_file_id"] == 10
    assert by_name["hero.jpg"]["vanjaro_url"] == "/Portals/0/Images/hero.jpg"
    assert by_name["hero.jpg"]["content_type"] == "image/jpeg"
    assert by_name["hero.jpg"]["source_url"] is None
    assert by_name["icon.svg"]["content_type"] == "image/svg+xml"
    assert by_name["photo.png"]["content_type"] == "image/png"

    upload_calls = [call for call in responses.calls if call.request.url == UPLOAD_URL]
    assert len(upload_calls) == 3
    sent = json.loads(upload_calls[0].request.body)
    assert sent["folderPath"] == "Images/"
    assert sent["fileName"] in {"hero.jpg", "photo.png", "icon.svg"}
    assert base64.b64decode(sent["base64Content"]).startswith(b"bytes-for-")


@responses.activate
def test_assets_upload_dir_skip_existing(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, UPLOAD_URL, json=_upload_response(21, "icon.svg"), status=200)
    responses.add(responses.POST, UPLOAD_URL, json=_upload_response(22, "photo.png"), status=200)

    source = _make_upload_dir(tmp_path)
    manifest_path = source / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "source_url": "https://example.com/hero.jpg",
                    "local_file": "hero.jpg",
                    "filename": "hero.jpg",
                    "size_bytes": 13,
                    "content_type": "image/jpeg",
                    "vanjaro_url": "/Portals/0/Images/hero.jpg",
                    "vanjaro_file_id": 99,
                    "uploaded": True,
                }
            ]
        )
    )

    result = runner.invoke(cli, ["assets", "upload-dir", str(source), "--skip-existing"])

    assert result.exit_code == 0, result.output

    upload_calls = [call for call in responses.calls if call.request.url == UPLOAD_URL]
    assert len(upload_calls) == 2
    sent_names = {json.loads(call.request.body)["fileName"] for call in upload_calls}
    assert sent_names == {"icon.svg", "photo.png"}

    manifest = json.loads(manifest_path.read_text())
    by_name = {entry["local_file"]: entry for entry in manifest}
    assert by_name["hero.jpg"]["source_url"] == "https://example.com/hero.jpg"
    assert by_name["hero.jpg"]["vanjaro_file_id"] == 99
    assert by_name["icon.svg"]["uploaded"] is True
    assert by_name["photo.png"]["uploaded"] is True


@responses.activate
def test_assets_upload_dir_dry_run_makes_no_calls(runner, mock_config, tmp_path):
    mock_homepage()
    # Register the upload URL but assert_all_requests_are_fired=False (default in @responses.activate)
    # We'll simply not add any upload mocks and confirm the test still succeeds because no call is made.
    source = _make_upload_dir(tmp_path)

    result = runner.invoke(cli, ["assets", "upload-dir", str(source), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert "hero.jpg" in result.output
    assert "photo.png" in result.output
    assert "icon.svg" in result.output

    upload_calls = [call for call in responses.calls if call.request.url == UPLOAD_URL]
    assert upload_calls == []

    # Dry run must not create a manifest file
    assert not (source / "manifest.json").exists()


def test_assets_upload_dir_directory_not_found(runner, mock_config, tmp_path):
    missing = tmp_path / "does-not-exist"

    result = runner.invoke(cli, ["assets", "upload-dir", str(missing)])

    assert result.exit_code != 0
    assert "Directory not found" in result.output


@responses.activate
def test_assets_upload_dir_partial_failure(runner, mock_config, tmp_path):
    mock_homepage()
    # Order is sorted: hero.jpg -> icon.svg -> photo.png
    responses.add(responses.POST, UPLOAD_URL, json=_upload_response(30, "hero.jpg"), status=200)
    responses.add(responses.POST, UPLOAD_URL, json={"Message": "boom"}, status=500)
    responses.add(responses.POST, UPLOAD_URL, json=_upload_response(32, "photo.png"), status=200)

    source = _make_upload_dir(tmp_path)

    result = runner.invoke(cli, ["assets", "upload-dir", str(source)])

    assert result.exit_code == 0, result.output
    assert "Uploaded 2 of 3" in result.output
    assert "failed: 1" in result.output
    assert "Failed to upload icon.svg" in result.output

    manifest = json.loads((source / "manifest.json").read_text())
    by_name = {entry["local_file"]: entry for entry in manifest}
    assert by_name["hero.jpg"]["uploaded"] is True
    assert by_name["hero.jpg"]["vanjaro_file_id"] == 30
    assert by_name["photo.png"]["uploaded"] is True
    assert by_name["photo.png"]["vanjaro_file_id"] == 32
    assert by_name["icon.svg"]["uploaded"] is False
    assert by_name["icon.svg"]["vanjaro_file_id"] is None


@responses.activate
def test_assets_upload_dir_json_output(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, UPLOAD_URL, json=_upload_response(40, "hero.jpg"), status=200)
    responses.add(responses.POST, UPLOAD_URL, json=_upload_response(41, "icon.svg"), status=200)
    responses.add(responses.POST, UPLOAD_URL, json=_upload_response(42, "photo.png"), status=200)

    source = _make_upload_dir(tmp_path)

    result = runner.invoke(cli, ["assets", "upload-dir", str(source), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["total"] == 3
    assert data["uploaded"] == 3
    assert data["skipped"] == 0
    assert data["failed"] == 0
    assert data["manifest"].endswith("manifest.json")


@responses.activate
def test_assets_upload_dir_custom_manifest_and_folder(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, UPLOAD_URL, json=_upload_response(50, "hero.jpg"), status=200)

    source = tmp_path / "source"
    source.mkdir()
    (source / "hero.jpg").write_bytes(b"hero-bytes")

    manifest_path = tmp_path / "manifest.json"

    result = runner.invoke(
        cli,
        [
            "assets",
            "upload-dir",
            str(source),
            "--folder",
            "Images/Migration/",
            "--manifest",
            str(manifest_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert manifest_path.exists()

    sent = json.loads(responses.calls[-1].request.body)
    assert sent["folderPath"] == "Images/Migration/"


def test_assets_upload_dir_invalid_manifest(runner, mock_config, tmp_path):
    source = _make_upload_dir(tmp_path)
    (source / "manifest.json").write_text("{ not json")

    result = runner.invoke(cli, ["assets", "upload-dir", str(source)])

    assert result.exit_code != 0
    assert "Invalid manifest" in result.output
