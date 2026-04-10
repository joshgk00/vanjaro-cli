"""vanjaro auth login / logout / status commands."""

from __future__ import annotations

import json

import click

from vanjaro_cli.auth import AuthError, login, logout
from vanjaro_cli.client import ApiError, VanjaroClient
from vanjaro_cli.config import CONFIG_FILE, ConfigError, clear_session, get_active_profile_name, load_config
from vanjaro_cli.commands.helpers import exit_error, output_result

# Lightweight endpoint used by `auth status` to verify the session is still
# valid server-side. Requires authentication but returns quickly.
_STATUS_VERIFY_ENDPOINT = "/API/VanjaroAI/AIHealth/Check"


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
@click.option(
    "--offline",
    is_flag=True,
    help="Only check local cookies — skip the server-side verification call.",
)
@click.option("--json", "as_json", is_flag=True, help="Output result as JSON.")
def status_command(offline: bool, as_json: bool) -> None:
    """Show the current authentication status.

    By default, ``auth status`` verifies the stored session against the
    server. Cookies that exist locally but are expired server-side are
    reported as ``session_expired`` rather than ``authenticated`` — the
    original behavior produced a misleading green light that tripped up
    migration workflows. Use ``--offline`` to opt back in to the cookie-only
    check when you just want to know whether a profile is configured.
    """
    if not CONFIG_FILE.exists():
        _not_logged_in(as_json)
        return

    try:
        config = load_config()
    except ConfigError as exc:
        _not_logged_in(as_json, str(exc))
        return

    has_cookies = config.is_authenticated
    if not has_cookies:
        _emit_status(as_json, "unauthenticated", config, has_cookies=False)
        return

    if offline:
        _emit_status(as_json, "authenticated", config, has_cookies=True, verified=False)
        return

    # Default path: ping the server with the stored cookies to confirm the
    # session is actually live. Any failure downgrades the reported status.
    try:
        client = VanjaroClient(config)
        client.get(_STATUS_VERIFY_ENDPOINT)
    except ApiError as exc:
        _emit_status(
            as_json,
            "session_expired",
            config,
            has_cookies=True,
            verified=False,
            error=str(exc),
        )
        return
    except ConfigError as exc:
        _emit_status(
            as_json,
            "unauthenticated",
            config,
            has_cookies=False,
            error=str(exc),
        )
        return

    _emit_status(as_json, "authenticated", config, has_cookies=True, verified=True)


def _emit_status(
    as_json: bool,
    status: str,
    config,
    *,
    has_cookies: bool,
    verified: bool | None = None,
    error: str | None = None,
) -> None:
    """Write an ``auth status`` result in JSON or human format."""
    result: dict[str, object] = {
        "status": status,
        "base_url": config.base_url,
        "portal_id": config.portal_id,
        "has_cookies": has_cookies,
    }
    if verified is not None:
        result["verified"] = verified
    if error:
        result["error"] = error

    if as_json:
        click.echo(json.dumps(result))
        return

    icons = {
        "authenticated": "+",
        "session_expired": "!",
        "unauthenticated": "x",
    }
    icon = icons.get(status, "?")
    suffix = ""
    if status == "session_expired":
        suffix = " (run `vanjaro auth login` to re-authenticate)"
    click.echo(f"{icon} {status} — {config.base_url}{suffix}")


def _not_logged_in(as_json: bool, reason: str = "No config found.") -> None:
    result = {"status": "unauthenticated", "message": reason}
    if as_json:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Not logged in. {reason}")
