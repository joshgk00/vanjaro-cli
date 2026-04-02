"""vanjaro site info, health, and nav commands."""

from __future__ import annotations

import json

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client
from vanjaro_cli.models.page import Page
from vanjaro_cli.models.site import HealthCheck, SiteAnalysis

ANALYZE_ENDPOINT = "/API/VanjaroAI/AISiteAnalysis/Analyze"
HEALTH_ENDPOINT = "/API/VanjaroAI/AIHealth/Check"
GET_PAGES = "/API/Vanjaro/Page/GetPages"


@click.group()
def site() -> None:
    """View site information and health status."""


@site.command("info")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def info(as_json: bool) -> None:
    """Show comprehensive site analysis."""
    client, _ = get_client()

    try:
        response = client.get(ANALYZE_ENDPOINT)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    analysis = SiteAnalysis.from_api(response.json())

    if as_json:
        click.echo(json.dumps(analysis.model_dump(by_alias=False), indent=2))
        return

    site_data = analysis.site
    pages = analysis.pages
    global_blocks = analysis.global_blocks
    assets_data = analysis.assets
    design = analysis.design_summary
    branding_data = analysis.branding

    published_count = sum(1 for page in pages if page.get("isPublished"))
    block_names = ", ".join(block.get("name", "") for block in global_blocks)

    click.echo(f"Site: {site_data.get('name', '')}")
    click.echo(f"Theme: {site_data.get('theme', '')}")
    click.echo(f"URL: {site_data.get('url', '')}")
    click.echo()
    click.echo(f"Pages: {len(pages)} ({published_count} published)")
    click.echo(f"Global Blocks: {len(global_blocks)} ({block_names})")
    click.echo(
        f"Assets: {assets_data.get('totalFiles', 0)} files "
        f"in {assets_data.get('totalFolders', 0)} folders "
        f"({assets_data.get('totalSizeMB', 0)} MB)"
    )
    click.echo()
    click.echo(
        f"Design: {design.get('themeName', '')} theme, "
        f"{design.get('customizedControls', 0)}/{design.get('totalControls', 0)} controls customized"
    )
    click.echo(
        f"Branding: logo {'yes' if branding_data.get('hasLogo') else 'no'}, "
        f"favicon {'yes' if branding_data.get('hasFavicon') else 'no'}"
    )


@site.command("health")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def health(as_json: bool) -> None:
    """Check site health status."""
    client, _ = get_client()

    try:
        response = client.get(HEALTH_ENDPOINT)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    check = HealthCheck.from_api(response.json())

    if as_json:
        click.echo(json.dumps(check.model_dump(by_alias=False), indent=2))
        return

    click.echo(f"Status:  {check.status}")
    click.echo(f"DNN:     {check.dnn_version}")
    click.echo(f"Vanjaro: {check.vanjaro_version}")
    click.echo(f"User:    {check.user_name} (ID: {check.user_id})")
    click.echo(f"Portal:  {check.portal_id}")


@site.command("nav")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def nav(as_json: bool) -> None:
    """Show site navigation tree."""
    client, _ = get_client()

    try:
        response = client.get(GET_PAGES)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    raw_pages = data if isinstance(data, list) else data.get("pages", data.get("Pages", []))

    raw_pages = [
        p for p in raw_pages
        if p.get("Value", -1) != 0 and p.get("Text") != "Select Page"
    ]

    page_list = [Page.from_api(p) for p in raw_pages]

    if as_json:
        click.echo(json.dumps(
            [{"id": p.id, "name": p.name, "level": p.level} for p in page_list],
            indent=2,
        ))
        return

    if not page_list:
        click.echo("No pages found.")
        return

    click.echo("Navigation:")
    for page in page_list:
        indent = "  " * (page.level + 1)
        click.echo(f"{indent}{page.name} ({page.id})")
