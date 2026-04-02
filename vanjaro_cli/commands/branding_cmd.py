"""vanjaro branding get/update commands via VanjaroAI API."""

from __future__ import annotations

import json

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client, output_result
from vanjaro_cli.models.asset import Branding

GET_BRANDING = "/API/VanjaroAI/AIBranding/GetBranding"
UPDATE_BRANDING = "/API/VanjaroAI/AIBranding/UpdateBranding"


def _format_logo(logo: dict | None) -> str:
    """Build a human-readable summary of the logo field."""
    if not logo:
        return "(none)"
    name = logo.get("fileName", "unknown")
    width = logo.get("width")
    height = logo.get("height")
    folder = logo.get("folderPath", "")
    dimensions = f" ({width}x{height}, {folder})" if width is not None and height is not None else ""
    return f"{name}{dimensions}"


def _display_branding(brand: Branding, as_json: bool) -> None:
    """Show branding in human or JSON format."""
    if as_json:
        click.echo(json.dumps(brand.model_dump(by_alias=False), indent=2))
    else:
        click.echo(f"Site Name:   {brand.site_name}")
        click.echo(f"Description: {brand.description}")
        click.echo(f"Footer:      {brand.footer_text}")
        click.echo(f"Logo:        {_format_logo(brand.logo)}")


@click.group("branding")
def branding() -> None:
    """View and update site branding (name, logo, footer)."""


@branding.command("get")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def get_branding(as_json: bool) -> None:
    """Show current site branding."""
    client, _ = get_client()

    try:
        response = client.get(GET_BRANDING)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    brand = Branding.from_api(response.json())
    _display_branding(brand, as_json)


@branding.command("update")
@click.option("--site-name", default=None, help="Update site name.")
@click.option("--description", default=None, help="Update site description.")
@click.option("--footer-text", default=None, help="Update footer text.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def update_branding(
    site_name: str | None,
    description: str | None,
    footer_text: str | None,
    as_json: bool,
) -> None:
    """Update site branding, or show current values when no flags are given."""
    payload: dict[str, str] = {}
    if site_name is not None:
        payload["siteName"] = site_name
    if description is not None:
        payload["description"] = description
    if footer_text is not None:
        payload["footerText"] = footer_text

    client, _ = get_client()

    if not payload:
        try:
            response = client.get(GET_BRANDING)
        except (ApiError, ConfigError) as exc:
            exit_error(str(exc), as_json)

        brand = Branding.from_api(response.json())
        _display_branding(brand, as_json)
        return

    try:
        client.post(UPDATE_BRANDING, json=payload)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="updated",
        human_message="Branding updated.",
        **payload,
    )
