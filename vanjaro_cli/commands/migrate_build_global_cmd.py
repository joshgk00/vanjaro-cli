"""vanjaro migrate build-global — build a site-specific header/footer global block.

Reads a crawled ``global/header.json`` or ``global/footer.json`` and produces
a GrapesJS tree wrapped in the shape ``vanjaro global-blocks create --file``
accepts. Unlike template-based composition, this builds the tree directly
from the crawl — every source site has a different header and footer
design, so a prefab template is always a fidelity compromise. The builder
here is opinionated about structure (header = row with logo+nav, footer =
N columns plus optional about/badges rows) but the content comes entirely
from the crawled data.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.commands.helpers import exit_error, output_result, read_json_object
from vanjaro_cli.migration.global_blocks import (
    build_footer_block,
    build_header_block,
)
from vanjaro_cli.utils.theme_palette import PaletteError, load_palette

__all__ = ["build_global"]


@click.command("build-global")
@click.option(
    "--source",
    "source_file",
    type=click.Path(),
    required=True,
    help="Path to the crawled global element JSON "
    "(``global/header.json`` or ``global/footer.json``).",
)
@click.option(
    "--kind",
    type=click.Choice(["header", "footer"]),
    required=True,
    help="Which global element to build. Determines the layout shape.",
)
@click.option(
    "--output",
    "-o",
    "output_file",
    type=click.Path(),
    required=True,
    help="Destination path for the built block JSON — pass this to "
    "``vanjaro global-blocks create --file ...``.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option(
    "--static-nav",
    "static_nav",
    is_flag=True,
    default=False,
    help=(
        "Header only: embed a static nav list from the crawled nav entries "
        "instead of the live Vanjaro Menu block. Useful when the DNN page "
        "tree doesn't match the source site's navigation."
    ),
)
@click.option(
    "--theme-palette",
    "theme_palette_file",
    type=click.Path(),
    default=None,
    help="Palette JSON (from `vanjaro theme palette-export`). Maps band colors "
    "to theme classes (bg-primary, text-light, ...) instead of inline color.",
)
def build_global(
    source_file: str,
    kind: str,
    output_file: str,
    as_json: bool,
    static_nav: bool,
    theme_palette_file: str | None,
) -> None:
    """Build a site-specific global header/footer from a crawled global element.

    \b
    Example:
      vanjaro migrate build-global \\
        --source artifacts/migration/example-com/global/header.json \\
        --kind header \\
        --output artifacts/migration/example-com/global/header-built.json

      vanjaro migrate build-global \\
        --source artifacts/migration/example-com/global/footer.json \\
        --kind footer \\
        --output artifacts/migration/example-com/global/footer-built.json
    """
    source_path = Path(source_file)
    source = read_json_object(source_path, "Global element file", as_json)

    content = source.get("content")
    if not isinstance(content, dict):
        exit_error(
            f"{source_path} is missing a top-level 'content' object — "
            "is this a crawled header/footer file?",
            as_json,
        )

    source_url = source.get("source_url") if isinstance(source.get("source_url"), str) else ""

    palette: dict[str, tuple[int, int, int]] | None = None
    if theme_palette_file:
        try:
            palette = load_palette(theme_palette_file)
        except PaletteError as exc:
            exit_error(str(exc), as_json)

    if kind == "header":
        built = build_header_block(
            content, base_url=source_url, static_nav=static_nav, palette=palette
        )
    else:
        built = build_footer_block(content, base_url=source_url, palette=palette)

    output_path = Path(output_file)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(built, indent=2), encoding="utf-8")
    except OSError as exc:
        exit_error(f"Cannot write {output_path}: {exc}", as_json)

    output_result(
        as_json,
        status="built",
        human_message=(
            f"Built {kind} block from {source_path.name} -> {output_path} "
            f"(top-level components: {len(built['components'])})"
        ),
        source=str(source_path),
        kind=kind,
        output=str(output_path),
        component_count=len(built["components"]),
    )
