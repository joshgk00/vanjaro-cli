"""vanjaro global-blocks list/create/get/update/publish/delete commands via VanjaroAI API."""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client, output_result, print_table, write_output
from vanjaro_cli.models.block import GlobalBlock, GlobalBlockDetail
from vanjaro_cli.utils.grapesjs import render_components, render_styles

LIST_BLOCKS = "/API/VanjaroAI/AIGlobalBlock/List"
GET_BLOCK = "/API/VanjaroAI/AIGlobalBlock/Get"
# Create goes through the core Block endpoint the admin UI uses — the VanjaroAI
# `AIGlobalBlock/Create` variant persists the block but doesn't populate the
# server-side registry that governs wrapper expansion at render time, so
# wrappers pointing at blocks made through it render as empty divs.
CREATE_BLOCK = "/API/Vanjaro/Block/AddCustomBlock"
UPDATE_BLOCK = "/API/VanjaroAI/AIGlobalBlock/Update"
PUBLISH_BLOCK = "/API/VanjaroAI/AIGlobalBlock/Publish"
DELETE_BLOCK = "/API/VanjaroAI/AIGlobalBlock/Delete"


@click.group("global-blocks")
def global_blocks() -> None:
    """Manage global reusable blocks (Header, Footer, etc.)."""


@global_blocks.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_blocks(as_json: bool) -> None:
    """List all global blocks."""
    client, _ = get_client()

    try:
        response = client.get(LIST_BLOCKS)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    raw_blocks = data.get("blocks", [])
    block_list = [GlobalBlock.from_api(b) for b in raw_blocks]

    if as_json:
        click.echo(json.dumps([b.model_dump(by_alias=False) for b in block_list], indent=2))
    else:
        if not block_list:
            click.echo("No global blocks found.")
            return
        print_table(
            ["id", "name", "category", "published", "version"],
            [b.to_row() for b in block_list],
        )


@global_blocks.command("create")
@click.option("--name", "-n", required=True, help="Block name (must be unique).")
@click.option("--category", "-c", default="general", show_default=True, help="Block category.")
@click.option(
    "--file",
    "-f",
    "file_path",
    required=True,
    type=click.Path(exists=True),
    help="JSON file with contentJSON and styleJSON.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def create_block(name: str, category: str, file_path: str, as_json: bool) -> None:
    """Create a new global block from a JSON file."""
    try:
        raw = json.loads(Path(file_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        exit_error(f"Cannot read {file_path}: {exc}", as_json)

    content_json = raw.get("content_json") or raw.get("contentJSON") or raw.get("components", [])
    style_json = raw.get("style_json") or raw.get("styleJSON") or raw.get("styles", [])

    # Pre-render the Html from the component tree. The admin UI sends a fully
    # rendered HTML string and the server relies on it when registering the
    # block for render-time wrapper expansion — an empty Html causes the
    # record to land in the custom-block table instead of the global one.
    html = render_components(content_json) if isinstance(content_json, list) else ""
    style_css = render_styles(style_json) if isinstance(style_json, list) else ""
    if style_css:
        # Wrapper expansion serves the stored Html verbatim — per-id style
        # rules must travel inside it to reach anonymous visitors.
        html = f"<style>{style_css}</style>{html}"

    form_data = {
        "Name": name,
        "Category": category,
        "Html": html,
        "Css": style_css,
        "IsGlobal": "true",
        "ContentJSON": json.dumps(content_json) if isinstance(content_json, (list, dict)) else content_json,
        "StyleJSON": json.dumps(style_json) if isinstance(style_json, (list, dict)) else style_json,
    }

    client, _ = get_client()

    try:
        response = client.post_form(CREATE_BLOCK, form_data)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    if data.get("Status") == "Exist":
        exit_error(f"A global block named '{name}' already exists.", as_json)
    if data.get("Status") != "Success":
        exit_error(f"Unexpected response: {data}", as_json)

    guid = data.get("Guid", "")

    output_result(
        as_json,
        status="created",
        human_message=f"Created global block '{name}' [{guid}].",
        name=name,
        guid=guid,
        category=category,
    )


@global_blocks.command("get")
@click.argument("guid")
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Write block JSON to this file instead of stdout.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def get_block(guid: str, output: str | None, as_json: bool) -> None:
    """Fetch a global block by GUID."""
    client, _ = get_client()

    try:
        response = client.get(GET_BLOCK, params={"guid": guid})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    block = GlobalBlockDetail.from_api(data)

    if output:
        payload = json.dumps(block.model_dump(by_alias=False), indent=2)
        write_output(output, payload, as_json)
        if not as_json:
            click.echo(f"Block written to {output}")
    elif as_json:
        click.echo(json.dumps(block.model_dump(by_alias=False), indent=2))
    else:
        click.echo(f"ID:        {block.id}")
        click.echo(f"GUID:      {block.guid}")
        click.echo(f"Name:      {block.name}")
        click.echo(f"Category:  {block.category}")
        click.echo(f"Version:   {block.version}")
        click.echo(f"Published: {block.is_published}")


@global_blocks.command("update")
@click.argument("guid")
@click.option(
    "--file",
    "-f",
    "file_path",
    required=True,
    type=click.Path(exists=True),
    help="JSON file containing contentJSON and styleJSON.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def update_block(guid: str, file_path: str, as_json: bool) -> None:
    """Update a global block's content from a JSON file."""
    client, _ = get_client()

    try:
        raw = json.loads(Path(file_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        exit_error(f"Cannot read {file_path}: {exc}", as_json)

    content_json = raw.get("content_json") or raw.get("contentJSON") or raw.get("components", [])
    style_json = raw.get("style_json") or raw.get("styleJSON") or raw.get("styles", [])

    # Wrapper expansion renders the block's stored Html, and the server keeps
    # the existing Html when the request omits it — without re-rendering here,
    # content updates would never reach the live pages.
    html = raw.get("html")
    if not isinstance(html, str):
        html = render_components(content_json) if isinstance(content_json, list) else ""
        style_css = render_styles(style_json) if isinstance(style_json, list) else ""
        if style_css:
            html = f"<style>{style_css}</style>{html}"

    # AIGlobalBlock/Update binds contentJSON/styleJSON as strings — sending
    # raw arrays fails model binding with HTTP 500.
    payload = {
        "guid": guid,
        "contentJSON": json.dumps(content_json) if isinstance(content_json, (list, dict)) else content_json,
        "styleJSON": json.dumps(style_json) if isinstance(style_json, (list, dict)) else style_json,
        "html": html,
    }

    try:
        client.post(UPDATE_BLOCK, json=payload)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    output_result(as_json, "updated", f"Global block {guid} updated.", guid=guid)


@global_blocks.command("publish")
@click.argument("guid")
@click.option("--version", type=click.IntRange(min=1), default=None)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def publish_block(guid: str, version: int | None, as_json: bool) -> None:
    """Publish the latest draft of a global block."""
    client, _ = get_client()

    payload: dict[str, object] = {"guid": guid}
    if version is not None:
        payload["version"] = version

    try:
        client.post(PUBLISH_BLOCK, json=payload)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    output_result(as_json, "ok", f"Global block {guid} published.", guid=guid)


@global_blocks.command("delete")
@click.argument("guid")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def delete_block(guid: str, force: bool, as_json: bool) -> None:
    """Delete a global block."""
    if not force and not click.confirm(f"Delete global block {guid}?"):
        raise click.Abort()

    client, _ = get_client()

    try:
        client.post(DELETE_BLOCK, json={"guid": guid})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    output_result(as_json, "deleted", f"Global block {guid} deleted.", guid=guid)
