from vanjaro_cli.commands.api_key_cmd import api_key
from vanjaro_cli.commands.assets_cmd import assets
from vanjaro_cli.commands.auth_cmd import auth
from vanjaro_cli.commands.blocks_cmd import blocks
from vanjaro_cli.commands.branding_cmd import branding
from vanjaro_cli.commands.build_cmd import build
from vanjaro_cli.commands.content_cmd import content
from vanjaro_cli.commands.custom_blocks_cmd import custom_blocks
from vanjaro_cli.commands.global_blocks_cmd import global_blocks
from vanjaro_cli.commands.modules_cmd import modules
from vanjaro_cli.commands.pages_cmd import pages
from vanjaro_cli.commands.profile_cmd import profile
from vanjaro_cli.commands.site_cmd import site
from vanjaro_cli.commands.templates_cmd import templates
from vanjaro_cli.commands.theme_cmd import theme

# `migrate` pulls in `beautifulsoup4` transitively through
# `vanjaro_cli.migration.*`. If that optional-at-runtime package is missing
# (e.g. a stale .venv predates when bs4 was added to pyproject.toml), the
# bare import here would take down every other `vanjaro` command — including
# `vanjaro auth login`, which is the one command you need to recover. Fall
# back to a stub that intercepts `vanjaro migrate ...` and prints the fix.
try:
    from vanjaro_cli.commands.migrate_cmd import migrate
except ImportError as _migrate_import_error:  # pragma: no cover - exercised via stale venv
    import click as _click

    _migrate_missing_dep = str(_migrate_import_error)

    @_click.command(
        "migrate",
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
        help="Migrate a live site into Vanjaro (unavailable — dependencies missing).",
    )
    @_click.pass_context
    def migrate(context: _click.Context) -> None:
        _click.echo(
            "error: `vanjaro migrate` needs additional Python packages.\n"
            f"  missing: {_migrate_missing_dep}\n"
            "  fix:     pip install -e \".[dev]\"",
            err=True,
        )
        context.exit(1)

__all__ = ["api_key", "assets", "auth", "blocks", "branding", "build", "content", "custom_blocks", "global_blocks", "migrate", "modules", "pages", "profile", "site", "templates", "theme"]
