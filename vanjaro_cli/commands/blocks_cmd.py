"""vanjaro blocks list/get/tree/add/remove commands for page components."""

from __future__ import annotations

import json

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client, output_result, parse_json_field, print_table, write_output
from vanjaro_cli.models.block import PageBlock, PageBlockDetail
from vanjaro_cli.utils.grapesjs import (
    create_component,
    insert_component,
    list_components,
    remove_component,
)

LIST_BLOCKS = "/API/VanjaroAI/AIBlock/List"
GET_BLOCK = "/API/VanjaroAI/AIBlock/Get"
GET_PAGE = "/API/VanjaroAI/AIPage/Get"
UPDATE_PAGE = "/API/VanjaroAI/AIPage/Update"


@click.group()
def blocks() -> None:
    """Inspect and manipulate page components (blocks)."""


@blocks.command("list")
@click.argument("page_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_blocks(page_id: int, as_json: bool) -> None:
    """List top-level blocks on a page."""
    client, _ = get_client()

    try:
        response = client.get(LIST_BLOCKS, params={"pageId": page_id})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    raw_blocks = data.get("blocks", [])
    block_list = [PageBlock.from_api(b) for b in raw_blocks]

    if as_json:
        click.echo(json.dumps({
            "page_id": page_id,
            "version": data.get("version", 0),
            "total": data.get("total", len(block_list)),
            "blocks": [b.model_dump(by_alias=False) for b in block_list],
        }, indent=2))
    else:
        if not block_list:
            click.echo(f"No blocks found on page {page_id}.")
            return
        print_table(
            ["component_id", "type", "name", "children"],
            [b.to_row() for b in block_list],
        )


@blocks.command("get")
@click.argument("page_id", type=int)
@click.argument("component_id")
@click.option("--output", "-o", type=click.Path(), default=None, help="Write block JSON to file.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def get_block(page_id: int, component_id: str, output: str | None, as_json: bool) -> None:
    """Get details for a specific block/component."""
    client, _ = get_client()

    try:
        response = client.get(GET_BLOCK, params={"pageId": page_id, "componentId": component_id})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    block = PageBlockDetail.from_api(data)

    if output:
        payload = json.dumps(block.model_dump(by_alias=False), indent=2)
        write_output(output, payload, as_json)
        if not as_json:
            click.echo(f"Block written to {output}")
    elif as_json:
        click.echo(json.dumps(block.model_dump(by_alias=False), indent=2))
    else:
        click.echo(f"Component: {block.component_id}")
        click.echo(f"Type:      {block.type}")
        click.echo(f"Name:      {block.name}")
        click.echo(f"Page:      {block.page_id}")
        click.echo(f"Version:   {block.version}")


@blocks.command("tree")
@click.argument("page_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def tree_blocks(page_id: int, as_json: bool) -> None:
    """Show the full component tree for a page."""
    client, _ = get_client()

    try:
        response = client.get(GET_PAGE, params={"pageId": page_id, "includeDraft": "true"})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    components = parse_json_field(data, "contentJSON")

    flat = list_components(components)

    if as_json:
        click.echo(json.dumps(flat, indent=2))
    else:
        if not flat:
            click.echo(f"Page {page_id} has no components.")
            return
        for item in flat:
            indent = "  " * item["depth"]
            name = item["name"] or item["content_preview"] or ""
            suffix = f" — {name}" if name else ""
            click.echo(f"{indent}{item['type']} [{item['id']}]{suffix}")


@blocks.command("add")
@click.argument("page_id", type=int)
@click.option("--type", "-t", "block_type", required=True, help="Component type (section, text, heading, image, etc.).")
@click.option("--content", "-c", default="", help="Text content for the component.")
@click.option("--parent", "-p", "parent_id", default=None, help="Parent component ID (default: root level).")
@click.option("--position", type=int, default=-1, help="Insert position (-1 = append).")
@click.option("--classes", default=None, help="Comma-separated CSS class names.")
@click.option("--locale", "-l", default="en-US", show_default=True)
@click.option("--json", "as_json", is_flag=True)
def add_block(
    page_id: int,
    block_type: str,
    content: str,
    parent_id: str | None,
    position: int,
    classes: str | None,
    locale: str,
    as_json: bool,
) -> None:
    """Add a component to a page. Fetches current content, inserts, and saves as draft."""
    client, _ = get_client()

    try:
        response = client.get(GET_PAGE, params={"pageId": page_id, "includeDraft": "true", "locale": locale})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    version = data.get("version", 0)
    components = parse_json_field(data, "contentJSON")
    styles = parse_json_field(data, "styleJSON")

    class_list = [c.strip() for c in classes.split(",") if c.strip()] if classes else None
    new_component = create_component(block_type, content=content, classes=class_list)

    try:
        updated = insert_component(components, new_component, parent_id=parent_id, position=position)
    except ValueError as exc:
        exit_error(str(exc), as_json)

    payload = {
        "pageId": page_id,
        "contentJSON": json.dumps(updated),
        "styleJSON": json.dumps(styles),
        "expectedVersion": version,
        "locale": locale,
    }

    try:
        save_response = client.post(UPDATE_PAGE, json=payload)
    except ApiError as exc:
        if exc.status_code == 409:
            exit_error(
                f"Page {page_id} was modified since it was read (version {version}). "
                "Re-run the command to retry with the latest content.",
                as_json,
            )
        exit_error(str(exc), as_json)
    except ConfigError as exc:
        exit_error(str(exc), as_json)

    result = save_response.json()
    new_id = new_component["attributes"]["id"]

    output_result(
        as_json,
        status="added",
        human_message=f"Added {block_type} [{new_id}] to page {page_id} (version {result.get('version', '?')}, draft).",
        page_id=page_id,
        component_id=new_id,
        version=result.get("version"),
    )


@blocks.command("remove")
@click.argument("page_id", type=int)
@click.argument("component_id")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.option("--locale", "-l", default="en-US", show_default=True)
@click.option("--json", "as_json", is_flag=True)
def remove_block(page_id: int, component_id: str, force: bool, locale: str, as_json: bool) -> None:
    """Remove a component from a page. Saves as draft."""
    if not force:
        click.confirm(f"Remove component {component_id} from page {page_id}?", abort=True)

    client, _ = get_client()

    try:
        response = client.get(GET_PAGE, params={"pageId": page_id, "includeDraft": "true", "locale": locale})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    version = data.get("version", 0)
    components = parse_json_field(data, "contentJSON")
    styles = parse_json_field(data, "styleJSON")

    try:
        updated = remove_component(components, component_id)
    except ValueError as exc:
        exit_error(str(exc), as_json)

    payload = {
        "pageId": page_id,
        "contentJSON": json.dumps(updated),
        "styleJSON": json.dumps(styles),
        "expectedVersion": version,
        "locale": locale,
    }

    try:
        save_response = client.post(UPDATE_PAGE, json=payload)
    except ApiError as exc:
        if exc.status_code == 409:
            exit_error(
                f"Page {page_id} was modified since it was read (version {version}). "
                "Re-run the command to retry with the latest content.",
                as_json,
            )
        exit_error(str(exc), as_json)
    except ConfigError as exc:
        exit_error(str(exc), as_json)

    result = save_response.json()

    output_result(
        as_json,
        status="removed",
        human_message=f"Removed {component_id} from page {page_id} (version {result.get('version', '?')}, draft).",
        page_id=page_id,
        component_id=component_id,
        version=result.get("version"),
    )
