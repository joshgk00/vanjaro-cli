"""vanjaro api-key generate / revoke / status / set commands."""

from __future__ import annotations

import json

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError, remove_api_key, save_api_key
from vanjaro_cli.commands.helpers import exit_error, get_client, output_result

# VanjaroAI API key management endpoints (SuperUser only)
GENERATE_KEY = "/API/VanjaroAI/AIApiKey/Generate"
REVOKE_KEY = "/API/VanjaroAI/AIApiKey/Revoke"
KEY_STATUS = "/API/VanjaroAI/AIApiKey/Status"


@click.group("api-key")
def api_key() -> None:
    """Manage API keys for VanjaroAI endpoints."""


@api_key.command("generate")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def generate_command(as_json: bool) -> None:
    """Generate a new API key (requires SuperUser login).

    The key is saved to the active profile automatically.
    Any previous key is replaced.
    """
    client, _ = get_client()

    try:
        response = client.post(GENERATE_KEY)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    raw_key = data.get("apiKey", "")
    if not raw_key:
        exit_error("Server did not return an API key.", as_json)

    save_api_key(raw_key)

    output_result(
        as_json,
        status="ok",
        human_message="API key generated and saved to config.",
        api_key=raw_key,
        message=data.get("message", ""),
    )


@api_key.command("revoke")
@click.option("--json", "as_json", is_flag=True)
def revoke_command(as_json: bool) -> None:
    """Revoke the current API key on the server and remove it from config."""
    client, _ = get_client()

    try:
        response = client.post(REVOKE_KEY)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    remove_api_key()

    output_result(
        as_json,
        status="ok",
        human_message="API key revoked.",
        message=data.get("message", ""),
    )


@api_key.command("status")
@click.option("--json", "as_json", is_flag=True)
def status_command(as_json: bool) -> None:
    """Check API key status on both server and local config."""
    client, config = get_client()

    try:
        response = client.get(KEY_STATUS)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    server_configured = data.get("isConfigured", False)
    local_configured = config.has_api_key

    if as_json:
        click.echo(json.dumps({
            "server_configured": server_configured,
            "local_configured": local_configured,
            "message": data.get("message", ""),
        }))
    else:
        server_icon = "+" if server_configured else "x"
        local_icon = "+" if local_configured else "x"
        click.echo(f"  {server_icon} Server: {'API key configured' if server_configured else 'No API key configured'}")
        click.echo(f"  {local_icon} Local:  {'API key in config' if local_configured else 'No API key in config'}")


@api_key.command("set")
@click.argument("key")
@click.option("--json", "as_json", is_flag=True)
def set_command(key: str, as_json: bool) -> None:
    """Manually set an API key in the active profile (no server call)."""
    save_api_key(key)
    output_result(
        as_json,
        status="ok",
        human_message="API key saved to config.",
    )
