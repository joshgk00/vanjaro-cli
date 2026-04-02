"""vanjaro auth login / logout / status commands."""

from __future__ import annotations

import json

import click

from vanjaro_cli.auth import AuthError, login, logout
from vanjaro_cli.config import CONFIG_FILE, ConfigError, clear_session, get_active_profile_name, load_config
from vanjaro_cli.commands.helpers import exit_error, output_result


@click.group()
def auth() -> None:
    """Manage authentication with a Vanjaro/DNN site."""


@auth.command("login")
@click.option("--url", envvar="VANJARO_BASE_URL", help="Base URL of the Vanjaro site.")
@click.option("--username", "-u", envvar="VANJARO_USERNAME", prompt=True)
@click.option(
    "--password",
    "-p",
    envvar="VANJARO_PASSWORD",
    prompt=True,
    hide_input=True,
)
@click.option("--profile", "profile_name", default=None, help="Save to a named profile.")
@click.option("--json", "as_json", is_flag=True, help="Output result as JSON.")
def login_command(url: str, username: str, password: str, profile_name: str | None, as_json: bool) -> None:
    """Authenticate via DNN login form and store session cookies."""
    if not url:
        raise click.UsageError(
            "No site URL provided. Pass --url or set VANJARO_BASE_URL."
        )
    try:
        config = login(url, username, password, profile_name=profile_name)
    except AuthError as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="ok",
        human_message=f"Logged in to {config.base_url}",
        base_url=config.base_url,
        message="Logged in successfully.",
    )


@auth.command("logout")
@click.option("--json", "as_json", is_flag=True, help="Output result as JSON.")
def logout_command(as_json: bool) -> None:
    """Clear stored session cookies."""
    try:
        config = load_config()
        logout(config)
    except ConfigError:
        pass  # No config to clear is fine

    clear_session()
    output_result(as_json, status="ok", human_message="Logged out.", message="Logged out.")


@auth.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output result as JSON.")
def status_command(as_json: bool) -> None:
    """Show the current authentication status."""
    if not CONFIG_FILE.exists():
        _not_logged_in(as_json)
        return

    try:
        config = load_config()
    except ConfigError as exc:
        _not_logged_in(as_json, str(exc))
        return

    is_authed = config.is_authenticated
    result = {
        "status": "authenticated" if is_authed else "unauthenticated",
        "base_url": config.base_url,
        "portal_id": config.portal_id,
        "has_cookies": is_authed,
    }
    if as_json:
        click.echo(json.dumps(result))
    else:
        icon = "+" if is_authed else "x"
        click.echo(f"{icon} {result['status']} — {config.base_url}")


def _not_logged_in(as_json: bool, reason: str = "No config found.") -> None:
    result = {"status": "unauthenticated", "message": reason}
    if as_json:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Not logged in. {reason}")
