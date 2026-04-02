"""vanjaro templates list/get/apply commands via VanjaroAI API."""

from __future__ import annotations

import json

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client, output_result, print_table, write_output
from vanjaro_cli.models.block import Template, TemplateDetail

LIST_TEMPLATES = "/API/VanjaroAI/AITemplate/List"
GET_TEMPLATE = "/API/VanjaroAI/AITemplate/Get"
APPLY_TEMPLATE = "/API/VanjaroAI/AITemplate/Apply"


@click.group()
def templates() -> None:
    """Manage page templates."""


@templates.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_templates(as_json: bool) -> None:
    """List available templates."""
    client, _ = get_client()

    try:
        response = client.get(LIST_TEMPLATES)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    raw_templates = data.get("templates", [])
    template_list = [Template.from_api(t) for t in raw_templates]

    if as_json:
        click.echo(json.dumps([t.model_dump(by_alias=False) for t in template_list], indent=2))
    else:
        if not template_list:
            click.echo("No templates found.")
            return
        print_table(
            ["name", "type", "system"],
            [t.to_row() for t in template_list],
        )


@templates.command("get")
@click.argument("name")
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Write full template JSON to this file.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def get_template(name: str, output: str | None, as_json: bool) -> None:
    """Fetch a template by name."""
    client, _ = get_client()

    try:
        response = client.get(GET_TEMPLATE, params={"name": name})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    template = TemplateDetail.from_api(data)

    if output:
        write_output(output, json.dumps(template.model_dump(by_alias=False), indent=2), as_json)
        if not as_json:
            click.echo(f"Template written to {output}")
    elif as_json:
        click.echo(json.dumps(template.model_dump(by_alias=False), indent=2))
    else:
        click.echo(f"Name:       {template.name}")
        click.echo(f"Type:       {template.type}")
        click.echo(f"System:     {template.is_system}")
        click.echo(f"Components: {len(template.content_json)}")


@templates.command("apply")
@click.argument("page_id", type=int)
@click.option("--template", "-t", "template_name", required=True, help="Template name to apply.")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def apply_template(page_id: int, template_name: str, force: bool, as_json: bool) -> None:
    """Apply a template to a page. This replaces existing page content."""
    if not force:
        click.confirm(
            f"Apply template '{template_name}' to page {page_id}? This replaces existing content.",
            abort=True,
        )

    client, _ = get_client()

    try:
        client.post(APPLY_TEMPLATE, json={"pageId": page_id, "templateName": template_name})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="applied",
        human_message=f"Template '{template_name}' applied to page {page_id}.",
        page_id=page_id,
        template_name=template_name,
    )
