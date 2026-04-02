"""Main Click CLI entry point."""

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

# Register sub-command aliases for discoverability
auth.name = "auth"
pages.name = "pages"
content.name = "content"

# Rename auth sub-commands from *_cmd to friendlier names
from vanjaro_cli.commands.auth_cmd import login_cmd, logout_cmd  # noqa: E402

auth.add_command(login_cmd, name="login")
auth.add_command(logout_cmd, name="logout")
