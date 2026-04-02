"""vanjaro assets commands for managing files and folders via VanjaroAI API."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client, output_result, print_table
from vanjaro_cli.models.asset import AssetFile, AssetFolder

LIST_FOLDERS = "/API/VanjaroAI/AIAsset/ListFolders"
LIST_FILES = "/API/VanjaroAI/AIAsset/ListFiles"
UPLOAD = "/API/VanjaroAI/AIAsset/Upload"
DELETE = "/API/VanjaroAI/AIAsset/Delete"


@click.group()
def assets() -> None:
    """Manage asset files and folders."""


@assets.command("folders")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_folders(as_json: bool) -> None:
    """List all asset folders."""
    client, _ = get_client()

    try:
        response = client.get(LIST_FOLDERS)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    raw = response.json()
    folder_list = [AssetFolder.from_api(f) for f in raw]

    if as_json:
        click.echo(json.dumps([f.model_dump(by_alias=False) for f in folder_list], indent=2))
    else:
        if not folder_list:
            click.echo("No folders found.")
            return
        print_table(
            ["folder_id", "path", "name"],
            [f.to_row() for f in folder_list],
        )


@assets.command("list")
@click.option("--folder", "folder_id", type=int, default=None, help="Folder ID to list files from.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_files(folder_id: int | None, as_json: bool) -> None:
    """List files in a folder."""
    if folder_id is not None and folder_id < 0:
        exit_error("Folder ID must be a non-negative integer.", as_json)

    client, _ = get_client()

    params: dict[str, int] = {}
    if folder_id is not None:
        params["folderId"] = folder_id

    try:
        response = client.get(LIST_FILES, params=params)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    raw = response.json()
    file_list = [AssetFile.from_api(f) for f in raw]

    if as_json:
        click.echo(json.dumps([f.model_dump(by_alias=False) for f in file_list], indent=2))
    else:
        if not file_list:
            click.echo("No files found.")
            return
        print_table(
            ["file_id", "file_name", "folder_path", "size", "content_type"],
            [f.to_row() for f in file_list],
        )


@assets.command("upload")
@click.argument("file_path", type=click.Path())
@click.option("--folder", "folder", default=None, help="Folder path to upload into (e.g. 'Images/').")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def upload_file(file_path: str, folder: str | None, as_json: bool) -> None:
    """Upload a local file to the asset library."""
    local_path = Path(file_path)
    if not local_path.exists():
        exit_error(f"File not found: {file_path}", as_json)

    file_content = base64.b64encode(local_path.read_bytes()).decode("ascii")
    payload = {
        "fileName": local_path.name,
        "folderPath": folder or "",
        "fileContent": file_content,
    }

    client, _ = get_client()

    try:
        response = client.post(UPLOAD, json=payload)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    if as_json:
        click.echo(json.dumps(response.json(), indent=2))
    else:
        output_result(
            as_json,
            status="uploaded",
            human_message=f"Uploaded {local_path.name} to {folder or 'root'}.",
        )


@assets.command("delete")
@click.argument("file_id", type=int)
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def delete_file(file_id: int, force: bool, as_json: bool) -> None:
    """Delete a file by ID."""
    if file_id < 1:
        exit_error("File ID must be a positive integer.", as_json)

    if not force:
        click.confirm(f"Delete file {file_id}?", abort=True)

    client, _ = get_client()

    try:
        client.post(DELETE, json={"fileId": file_id})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="deleted",
        human_message=f"Deleted file {file_id}.",
        file_id=file_id,
    )
