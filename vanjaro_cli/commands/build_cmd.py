"""Build command — create a page and apply a template in one step."""

from __future__ import annotations

import json

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client, output_result

CREATE_PAGE = "/API/VanjaroAI/AIPage/Create"
APPLY_TEMPLATE = "/API/VanjaroAI/AITemplate/Apply"


@click.command()
@click.option("--title", "-t", required=True, help="Page title.")
@click.option("--template", "-T", "template_name", required=True, help="Template name to apply.")
@click.option("--parent", "-P", default=None, type=int, help="Parent page ID.")
@click.option("--hidden", is_flag=True, help="Exclude from navigation menu.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def build(
    title: str,
    template_name: str,
    parent: int | None,
    hidden: bool,
    as_json: bool,
) -> None:
    """Create a page and apply a template in one step."""
    client, _ = get_client()

    payload: dict = {
        "name": title,
        "title": title,
        "includeInMenu": not hidden,
    }
    if parent is not None:
        payload["parentId"] = parent

    try:
        response = client.post(CREATE_PAGE, json=payload)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    page_id = data.get("pageId", 0)

    try:
        client.post(APPLY_TEMPLATE, json={"pageId": page_id, "templateName": template_name})
    except (ApiError, ConfigError) as exc:
        if as_json:
            click.echo(json.dumps({
                "status": "partial",
                "page_id": page_id,
                "title": title,
                "template": template_name,
                "warning": f"Page created but template failed: {exc}",
            }))
        else:
            click.echo(
                f"Warning: Page '{title}' (ID: {page_id}) was created, "
                f"but template '{template_name}' could not be applied: {exc}"
            )
        return

    output_result(
        as_json,
        status="created",
        human_message=f"Created page '{title}' (ID: {page_id}) with template '{template_name}'.",
        page_id=page_id,
        title=title,
        template=template_name,
    )
