"""Main Click CLI entry point."""

from __future__ import annotations

import click
from dotenv import load_dotenv

from vanjaro_cli import __version__
from vanjaro_cli.config import set_profile_override
from vanjaro_cli.commands import api_key, assets, auth, blocks, branding, build, content, global_blocks, modules, pages, profile, site, templates, theme

load_dotenv()


@click.group()
@click.version_option(version=__version__, prog_name="vanjaro")
@click.option(
    "--profile",
    "-P",
    "profile_name",
    default=None,
    help="Use a specific profile instead of the active one.",
)
def cli(profile_name: str | None) -> None:
    """Manage Vanjaro/DNN websites from the command line."""
    if profile_name:
        set_profile_override(profile_name)


cli.add_command(assets)
cli.add_command(auth)
cli.add_command(branding)
cli.add_command(build)
cli.add_command(pages)
cli.add_command(content)
cli.add_command(blocks)
cli.add_command(profile)
cli.add_command(api_key)
cli.add_command(global_blocks)
cli.add_command(modules)
cli.add_command(site)
cli.add_command(templates)
cli.add_command(theme)
