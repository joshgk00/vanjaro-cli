"""Main Click CLI entry point."""

from __future__ import annotations

import click
from dotenv import load_dotenv

from vanjaro_cli import __version__
from vanjaro_cli.commands import auth, content, pages

load_dotenv()


@click.group()
@click.version_option(version=__version__, prog_name="vanjaro")
def cli() -> None:
    """Manage Vanjaro/DNN websites from the command line."""


cli.add_command(auth)
cli.add_command(pages)
cli.add_command(content)
