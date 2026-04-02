"""Shared helpers for Click command modules."""

from __future__ import annotations

import json
from typing import NoReturn

import click

from vanjaro_cli.client import VanjaroClient
from vanjaro_cli.config import Config, ConfigError, load_config

__all__ = ["get_client", "exit_error", "output_result"]


def get_client() -> tuple[VanjaroClient, Config]:
    """Load config and return an authenticated client."""
    try:
        config = load_config()
    except ConfigError as exc:
        raise click.ClickException(str(exc))
    return VanjaroClient(config), config


def exit_error(message: str, as_json: bool) -> NoReturn:
    """Print an error in human or JSON format, then exit."""
    if as_json:
        click.echo(json.dumps({"status": "error", "message": message}))
        raise SystemExit(1)
    raise click.ClickException(message)


def output_result(
    as_json: bool,
    status: str,
    human_message: str,
    **extra: object,
) -> None:
    """Print a success result in human or JSON format."""
    if as_json:
        click.echo(json.dumps({"status": status, **extra}, indent=None))
    else:
        click.echo(human_message)
