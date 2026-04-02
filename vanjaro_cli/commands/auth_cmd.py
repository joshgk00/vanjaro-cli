"""vanjaro auth login / logout / status commands."""

from __future__ import annotations

import json
import os

import click

from vanjaro_cli.auth import AuthError, login, logout
from vanjaro_cli.config import CONFIG_FILE, ConfigError, clear_token, load_config


@click.group()
def auth() -> None:
    """Manage authentication with a Vanjaro/DNN site."""


@auth.command()
@click.option("--url", envvar="VANJARO_BASE_URL", help="Base URL of the Vanjaro site.")
@click.option("--username", "-u", envvar="VANJARO_USERNAME", prompt=True)
@click.option(
    "--password",
    "-p",
    envvar="VANJARO_PASSWORD",
    prompt=True,
    hide_input=True,
)
@click.option("--json", "as_json", is_flag=True, help="Output result as JSON.")
def login_cmd(url: str, username: str, password: str, as_json: bool) -> None:
    """Authenticate and store a JWT token."""
    if not url:
        raise click.UsageError(
            "No site URL provided. Pass --url or set VANJARO_BASE_URL."
        )
    try:
        config = login(url, username, password)
    except AuthError as exc:
        _error(str(exc), as_json)
        raise SystemExit(1)

    result = {"status": "ok", "base_url": config.base_url, "message": "Logged in successfully."}
    if as_json:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Logged in to {config.base_url}")


@auth.command()
@click.option("--json", "as_json", is_flag=True, help="Output result as JSON.")
def logout_cmd(as_json: bool) -> None:
    """Invalidate the stored token and clear local config."""
    try:
        config = load_config()
        logout(config)
    except ConfigError:
        pass  # No config to clear is fine

    clear_token()
    result = {"status": "ok", "message": "Logged out."}
    if as_json:
        click.echo(json.dumps(result))
    else:
        click.echo("Logged out.")


@auth.command()
@click.option("--json", "as_json", is_flag=True, help="Output result as JSON.")
def status(as_json: bool) -> None:
    """Show the current authentication status."""
    if not CONFIG_FILE.exists():
        _not_logged_in(as_json)
        return

    try:
        config = load_config()
    except ConfigError as exc:
        _not_logged_in(as_json, str(exc))
        return

    has_token = bool(config.token)
    result = {
        "status": "authenticated" if has_token else "unauthenticated",
        "base_url": config.base_url,
        "portal_id": config.portal_id,
        "has_token": has_token,
    }
    if as_json:
        click.echo(json.dumps(result))
    else:
        icon = "✓" if has_token else "✗"
        click.echo(f"{icon} {result['status']} — {config.base_url}")


def _not_logged_in(as_json: bool, reason: str = "No config found.") -> None:
    result = {"status": "unauthenticated", "message": reason}
    if as_json:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Not logged in. {reason}")


def _error(message: str, as_json: bool) -> None:
    result = {"status": "error", "message": message}
    if as_json:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Error: {message}", err=True)
