"""vanjaro profile list / use / delete commands."""

from __future__ import annotations

import json

import click

from vanjaro_cli.config import (
    ConfigError,
    delete_profile,
    list_profiles,
    set_active_profile,
)
from vanjaro_cli.commands.helpers import exit_error, output_result


@click.group()
def profile() -> None:
    """Manage named site profiles."""


@profile.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_command(as_json: bool) -> None:
    """List all configured profiles."""
    profiles = list_profiles()

    if as_json:
        click.echo(json.dumps(profiles, indent=2))
        return

    if not profiles:
        click.echo("No profiles configured. Run `vanjaro auth login --url <URL> --profile <name>` to create one.")
        return

    for p in profiles:
        marker = "*" if p["active"] else " "
        click.echo(f"  {marker} {p['name']:<20} {p['base_url']}")


@profile.command("use")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True)
def use_command(name: str, as_json: bool) -> None:
    """Switch the active profile."""
    try:
        set_active_profile(name)
    except ConfigError as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="ok",
        human_message=f"Switched to profile '{name}'.",
        profile=name,
    )


@profile.command("delete")
@click.argument("name")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True)
def delete_command(name: str, force: bool, as_json: bool) -> None:
    """Delete a profile."""
    if not force:
        click.confirm(f"Delete profile '{name}'? This cannot be undone.", abort=True)

    try:
        delete_profile(name)
    except ConfigError as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="deleted",
        human_message=f"Deleted profile '{name}'.",
        profile=name,
    )
