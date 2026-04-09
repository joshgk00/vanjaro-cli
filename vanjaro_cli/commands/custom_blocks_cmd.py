"""vanjaro custom-blocks list/create/edit/delete commands via core Vanjaro Block API."""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client, output_result, print_table

LIST_BLOCKS = "/API/Vanjaro/Block/GetAllCustomBlock"
ADD_BLOCK = "/API/Vanjaro/Block/AddCustomBlock"
EDIT_BLOCK = "/API/Vanjaro/Block/EditCustomBlock"
DELETE_BLOCK = "/API/Vanjaro/Block/DeleteCustomBlock"


@click.group("custom-blocks")
def custom_blocks() -> None:
    """Manage custom reusable blocks (drag-and-drop creates independent copies)."""


@custom_blocks.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_blocks(as_json: bool) -> None:
    """List all custom blocks."""
    client, _ = get_client()

    try:
        response = client.get(LIST_BLOCKS)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    blocks = response.json()

    if as_json:
        # Normalize keys to snake_case for consistency with the rest of the CLI
        normalized = []
        for block in blocks:
            normalized.append({
                "id": block.get("ID", 0),
                "guid": block.get("Guid", ""),
                "name": block.get("Name", ""),
                "category": block.get("Category", ""),
                "content_json": json.loads(block["ContentJSON"]) if isinstance(block.get("ContentJSON"), str) else block.get("ContentJSON", []),
                "style_json": json.loads(block["StyleJSON"]) if isinstance(block.get("StyleJSON"), str) else block.get("StyleJSON", []),
            })
        click.echo(json.dumps(normalized, indent=2))
    else:
        if not blocks:
            click.echo("No custom blocks found.")
            return
        rows = [
            {
                "id": block.get("ID", 0),
                "name": block.get("Name", ""),
                "category": block.get("Category", ""),
                "guid": block.get("Guid", "")[:8] + "...",
            }
            for block in blocks
        ]
        print_table(["id", "name", "category", "guid"], rows)


@custom_blocks.command("create")
@click.option("--name", "-n", required=True, help="Block name (must be unique).")
@click.option("--category", "-c", default="general", show_default=True, help="Block category.")
@click.option(
    "--file",
    "-f",
    "file_path",
    required=True,
    type=click.Path(exists=True),
    help="JSON file with contentJSON/components and styleJSON/styles.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def create_block(name: str, category: str, file_path: str, as_json: bool) -> None:
    """Create a custom block from a JSON file.

    Custom blocks appear in the editor sidebar. Dragging one onto a page
    creates an independent copy that can be edited per-page.
    """
    try:
        raw = json.loads(Path(file_path).read_text())
    except (json.JSONDecodeError, OSError) as exc:
        exit_error(f"Cannot read {file_path}: {exc}", as_json)

    # Support both raw API format (components/contentJSON) and authoring format (template)
    content_json = raw.get("content_json") or raw.get("contentJSON") or raw.get("components")
    if content_json is None and "template" in raw:
        content_json = [raw["template"]]
    content_json = content_json or []
    style_json = raw.get("style_json") or raw.get("styleJSON") or raw.get("styles", [])

    form_data = {
        "Name": name,
        "Category": category,
        "Html": "",
        "Css": "",
        "IsGlobal": "false",
        "ContentJSON": json.dumps(content_json) if isinstance(content_json, (list, dict)) else content_json,
        "StyleJSON": json.dumps(style_json) if isinstance(style_json, (list, dict)) else style_json,
    }

    client, _ = get_client()

    try:
        response = client.post_form(ADD_BLOCK, form_data)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    status = data.get("Status", "")

    if status == "Exist":
        exit_error(f"A custom block named '{name}' already exists.", as_json)

    if status != "Success":
        exit_error(f"Unexpected response: {data}", as_json)

    # AddCustomBlock doesn't return the GUID for custom blocks.
    # Fetch it from the list so we can report it.
    guid = _fetch_guid_by_name(client, name)

    output_result(
        as_json,
        status="created",
        human_message=f"Created custom block '{name}'" + (f" [{guid}]." if guid else "."),
        name=name,
        guid=guid or "",
        category=category,
    )


@custom_blocks.command("delete")
@click.argument("guid")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def delete_block(guid: str, force: bool, as_json: bool) -> None:
    """Delete a custom block by GUID."""
    if not force and not click.confirm(f"Delete custom block {guid}?"):
        raise click.Abort()

    client, _ = get_client()

    try:
        response = client.post_form(DELETE_BLOCK, {}, params={"CustomBlockGuid": guid})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    if data.get("Status") != "Success":
        exit_error(f"Delete failed: {data}", as_json)

    output_result(as_json, "deleted", f"Custom block {guid} deleted.", guid=guid)


def _fetch_guid_by_name(client: object, name: str) -> str | None:
    """Look up a custom block's GUID by name from the list endpoint."""
    try:
        response = client.get(LIST_BLOCKS)  # type: ignore[union-attr]
        for block in response.json():
            if block.get("Name") == name:
                return block.get("Guid", "")
    except (ApiError, ConfigError):
        pass
    return None
