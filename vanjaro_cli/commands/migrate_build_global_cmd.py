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

from vanjaro_cli.commands.helpers import (
    exit_error,
    output_result,
    read_json_array,
    read_json_object,
)
from vanjaro_cli.migration.global_blocks import (
    NAV_TOGGLE_PORTAL_CSS,
    build_footer_block,
    build_header_block,
)
from vanjaro_cli.migration.url_rewrite import (
    RewriteError,
    build_variant_lookup,
    rewrite_tree,
)
from vanjaro_cli.utils.block_compose import _add_class
from vanjaro_cli.utils.theme_palette import PaletteError, load_palette

__all__ = ["build_global"]


def _collect_image_classes(node: object, out: dict[str, list[str]]) -> None:
    """Record each image component's ``src -> class names`` before wrapping.

    ``build_picture_box`` rebuilds the inner ``<img>`` with a fixed
    ``vj-image``/``img-fluid`` class set and drops everything else, so the
    ``header-logo``/``footer-logo`` class the site CSS targets would be lost.
    Capturing the classes here lets :func:`_restore_image_classes` re-apply
    them after the wrap. If ``build_picture_box`` is ever taught to carry
    source classes forward (as it already does source attributes), this
    collect/restore pair can retire.
    """
    if not isinstance(node, dict):
        return
    if node.get("type") == "image":
        attributes = node.get("attributes")
        classes = node.get("classes")
        if isinstance(attributes, dict) and isinstance(classes, list):
            src = attributes.get("src")
            if isinstance(src, str) and src:
                out[src] = [
                    entry["name"]
                    for entry in classes
                    if isinstance(entry, dict) and entry.get("name")
                ]
    for child in node.get("components") or []:
        _collect_image_classes(child, out)


def _restore_image_classes(node: object, class_map: dict[str, list[str]]) -> None:
    """Re-apply original image classes dropped when wrapping in a ``<picture>``."""
    if not isinstance(node, dict):
        return
    if node.get("type") == "image":
        attributes = node.get("attributes")
        src = attributes.get("src") if isinstance(attributes, dict) else None
        original = class_map.get(src) if isinstance(src, str) else None
        if original:
            for name in original:
                _add_class(node, name)
    for child in node.get("components") or []:
        _restore_image_classes(child, class_map)


def _wrap_logo_variants(built: dict, manifest_path: Path, as_json: bool) -> None:
    """Wrap logos that have responsive variants in a ``<picture>`` srcset.

    The global-block builder emits logos as plain ``<img>``, so they never
    reach the responsive-wrapping pass page-body images get in
    ``migrate rewrite-urls``. This reruns only that wrapping pass — empty URL
    maps mean no ``src``/``href`` rewriting, just variant wrapping — so
    header/footer logos land the same ``<picture>`` markup and the
    responsive-images audit stops flagging them.
    """
    manifest = read_json_array(manifest_path, "Asset manifest", as_json)
    try:
        variant_lookup = build_variant_lookup(manifest)
    except RewriteError as exc:
        exit_error(f"{manifest_path}: {exc}", as_json)
    if not variant_lookup:
        return

    original_classes: dict[str, list[str]] = {}
    _collect_image_classes(built, original_classes)
    rewrite_tree(built, {}, {}, variant_lookup)
    _restore_image_classes(built, original_classes)


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
@click.option(
    "--asset-manifest",
    "asset_manifest_file",
    type=click.Path(),
    default=None,
    help="Asset manifest (source_url -> vanjaro_url with variants). When "
    "provided, header/footer logos that have responsive variants are wrapped "
    "in a <picture> srcset, matching the page-body responsive-image pass. "
    "Omit to leave logos as plain <img>.",
)
@click.option(
    "--portal-css-out",
    "portal_css_out",
    type=click.Path(),
    default=None,
    help="Header + --static-nav only: write the hamburger's site-wide CSS to "
    "this path so the build flow can `vanjaro theme css append` it. The "
    "styleJSON store strips @media/combinator rules, so this CSS must live in "
    "portal.css, not the block itself.",
)
def build_global(
    source_file: str,
    kind: str,
    output_file: str,
    as_json: bool,
    static_nav: bool,
    theme_palette_file: str | None,
    asset_manifest_file: str | None,
    portal_css_out: str | None,
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

    if asset_manifest_file:
        _wrap_logo_variants(built, Path(asset_manifest_file), as_json)

    output_path = Path(output_file)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(built, indent=2), encoding="utf-8")
    except OSError as exc:
        exit_error(f"Cannot write {output_path}: {exc}", as_json)

    portal_css_path: Path | None = None
    if portal_css_out and kind == "header" and static_nav:
        portal_css_path = Path(portal_css_out)
        try:
            portal_css_path.parent.mkdir(parents=True, exist_ok=True)
            portal_css_path.write_text(NAV_TOGGLE_PORTAL_CSS, encoding="utf-8")
        except OSError as exc:
            exit_error(f"Cannot write {portal_css_path}: {exc}", as_json)

    output_result(
        as_json,
        status="built",
        human_message=(
            f"Built {kind} block from {source_path.name} -> {output_path} "
            f"(top-level components: {len(built['components'])})"
            + (f"; hamburger CSS -> {portal_css_path}" if portal_css_path else "")
        ),
        source=str(source_path),
        kind=kind,
        output=str(output_path),
        component_count=len(built["components"]),
        portal_css_out=str(portal_css_path) if portal_css_path else None,
    )
