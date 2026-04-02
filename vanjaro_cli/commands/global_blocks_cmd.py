"""vanjaro global-blocks list/get commands via VanjaroAI API."""

from __future__ import annotations

import json

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client, print_table, write_output
from vanjaro_cli.models.block import GlobalBlock, GlobalBlockDetail

LIST_BLOCKS = "/API/VanjaroAI/AIGlobalBlock/List"
GET_BLOCK = "/API/VanjaroAI/AIGlobalBlock/Get"


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
