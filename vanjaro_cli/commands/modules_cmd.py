"""vanjaro modules list command — shows DNN modules on a page."""

from __future__ import annotations

import json

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client, print_table

GET_PAGE_DETAILS = "/API/PersonaBar/Pages/GetPageDetails"


@click.group()
def modules() -> None:
    """List DNN modules on pages."""


@modules.command("list")
@click.argument("page_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_modules(page_id: int, as_json: bool) -> None:
    """List DNN modules on a page."""
    client, _ = get_client()

    try:
        response = client.get(GET_PAGE_DETAILS, params={"pageId": page_id})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    page_data = data.get("page", data)
    module_list = page_data.get("modules", [])

    if as_json:
        click.echo(json.dumps(module_list, indent=2))
        return

    if not module_list:
        click.echo(f"No modules on page {page_id}.")
        return

    click.echo(f"Page {page_id} modules:")
    print_table(
        ["id", "title", "type"],
        [
            {
                "id": module.get("id", ""),
                "title": module.get("title", ""),
                "type": module.get("friendlyName", ""),
            }
            for module in module_list
        ],
    )
