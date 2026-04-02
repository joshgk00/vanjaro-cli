"""Shared helpers for Click command modules."""

from __future__ import annotations

import json
from typing import NoReturn

import click

from vanjaro_cli.client import VanjaroClient
from vanjaro_cli.config import Config, ConfigError, load_config

__all__ = ["get_client", "exit_error", "output_result", "parse_json_field", "print_table", "write_output"]


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


def write_output(path: str, content: str, as_json: bool) -> None:
    """Write content to a file, handling OS errors cleanly."""
    from pathlib import Path

    try:
        Path(path).write_text(content)
    except OSError as exc:
        exit_error(f"Cannot write to {path}: {exc}", as_json)


def parse_json_field(data: dict, field: str, default: str = "[]") -> list | dict:
    """Parse a Vanjaro JSON field that may be a string or already-parsed object."""
    raw = data.get(field, default)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return json.loads(default)
    return raw


def print_table(headers: list[str], rows: list[dict]) -> None:
    """Print a formatted ASCII table to stdout."""
    if not rows:
        return
    col_widths = {h: len(h) for h in headers}
    for row in rows:
        for h in headers:
            col_widths[h] = max(col_widths[h], len(str(row.get(h, ""))))

    header_line = "  ".join(h.upper().ljust(col_widths[h]) for h in headers)
    click.echo(header_line)
    click.echo("-" * len(header_line))
    for row in rows:
        click.echo("  ".join(str(row.get(h, "")).ljust(col_widths[h]) for h in headers))
