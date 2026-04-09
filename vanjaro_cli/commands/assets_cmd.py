"""vanjaro assets commands for managing files and folders via VanjaroAI API."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client, output_result, print_table
from vanjaro_cli.models.asset import AssetFile, AssetFolder

LIST_FOLDERS = "/API/VanjaroAI/AIAsset/ListFolders"
LIST_FILES = "/API/VanjaroAI/AIAsset/ListFiles"
UPLOAD = "/API/VanjaroAI/AIAsset/Upload"
DELETE = "/API/VanjaroAI/AIAsset/Delete"

SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".mp4",
    ".webm",
    ".pdf",
}

_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".pdf": "application/pdf",
}


def _guess_content_type(filename: str) -> str:
    """Map a filename's extension to a MIME type."""
    return _CONTENT_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


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


def _scan_directory(directory: Path) -> list[Path]:
    """Return sorted list of supported media files under the directory (recursive)."""
    found = [
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(found)


def _load_manifest(manifest_path: Path, as_json: bool) -> list[dict[str, Any]]:
    """Load an existing manifest file, or return an empty list if missing."""
    if not manifest_path.exists():
        return []
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        exit_error(
            f"Invalid manifest at {manifest_path}; delete it to start fresh.",
            as_json,
        )
    if not isinstance(raw, list):
        exit_error(
            f"Invalid manifest at {manifest_path}; expected a JSON list.",
            as_json,
        )
    return raw


def _save_manifest(manifest_path: Path, entries: list[dict[str, Any]]) -> None:
    """Write the manifest to disk."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _find_entry(entries: list[dict[str, Any]], local_file: str) -> dict[str, Any] | None:
    """Find an existing manifest entry matching a relative local file path."""
    for entry in entries:
        if entry.get("local_file") == local_file:
            return entry
    return None


def _build_entry(local_file: str, filename: str, size_bytes: int) -> dict[str, Any]:
    """Create a fresh manifest entry for a local file."""
    return {
        "source_url": None,
        "local_file": local_file,
        "filename": filename,
        "size_bytes": size_bytes,
        "content_type": _guess_content_type(filename),
        "vanjaro_url": None,
        "vanjaro_file_id": None,
        "uploaded": False,
    }


@assets.command("upload-dir")
@click.argument("directory", type=click.Path())
@click.option("--folder", "folder", default="Images/", help="Vanjaro folder to upload into.")
@click.option("--manifest", "manifest", default=None, help="Manifest file path (default: {directory}/manifest.json).")
@click.option("--dry-run", "dry_run", is_flag=True, help="List files without uploading.")
@click.option("--skip-existing", "skip_existing", is_flag=True, help="Skip files already marked uploaded in the manifest.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def upload_dir(
    directory: str,
    folder: str,
    manifest: str | None,
    dry_run: bool,
    skip_existing: bool,
    as_json: bool,
) -> None:
    """Upload every supported file in DIRECTORY to Vanjaro with manifest tracking."""
    directory_path = Path(directory)
    if not directory_path.exists() or not directory_path.is_dir():
        exit_error(f"Directory not found: {directory}", as_json)

    manifest_path = Path(manifest) if manifest else directory_path / "manifest.json"
    entries = _load_manifest(manifest_path, as_json)

    files = _scan_directory(directory_path)

    planned: list[tuple[Path, str, dict[str, Any]]] = []
    skipped = 0
    for file_path in files:
        local_file = file_path.relative_to(directory_path).as_posix()
        entry = _find_entry(entries, local_file)
        if entry is None:
            entry = _build_entry(local_file, file_path.name, file_path.stat().st_size)
            entries.append(entry)
        else:
            entry.setdefault("source_url", None)
            entry["filename"] = file_path.name
            entry["size_bytes"] = file_path.stat().st_size
            entry.setdefault("content_type", _guess_content_type(file_path.name))

        if skip_existing and entry.get("uploaded"):
            skipped += 1
            continue

        planned.append((file_path, local_file, entry))

    total = len(files)

    if dry_run:
        if as_json:
            output_result(
                as_json,
                status="ok",
                human_message="",
                dry_run=True,
                total=total,
                planned=[local for _, local, _ in planned],
                skipped=skipped,
                manifest=str(manifest_path),
            )
        else:
            click.echo(f"Dry run: {len(planned)} file(s) would be uploaded to {folder}.")
            for _, local_file, _ in planned:
                click.echo(f"  {local_file}")
            if skipped:
                click.echo(f"Skipped (already uploaded): {skipped}")
        return

    client, _ = get_client()

    uploaded = 0
    failed = 0
    for file_path, local_file, entry in planned:
        payload = {
            "fileName": file_path.name,
            "folderPath": folder,
            "fileContent": base64.b64encode(file_path.read_bytes()).decode("ascii"),
        }
        try:
            response = client.post(UPLOAD, json=payload)
        except (ApiError, ConfigError) as exc:
            failed += 1
            click.echo(f"Failed to upload {local_file}: {exc}", err=True)
            continue

        body = response.json() if response.content else {}
        entry["vanjaro_url"] = body.get("url") or body.get("Url")
        entry["vanjaro_file_id"] = body.get("fileId") or body.get("FileId")
        entry["uploaded"] = True
        uploaded += 1
        _save_manifest(manifest_path, entries)

    if not planned:
        _save_manifest(manifest_path, entries)

    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Uploaded {uploaded} of {total} file(s) to {folder} "
            f"(skipped: {skipped}, failed: {failed}). Manifest: {manifest_path}"
        ),
        total=total,
        uploaded=uploaded,
        skipped=skipped,
        failed=failed,
        manifest=str(manifest_path),
    )
