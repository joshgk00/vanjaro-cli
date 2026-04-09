"""vanjaro migrate rewrite-urls — replace source URLs with Vanjaro URLs."""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.commands.helpers import exit_error, output_result, read_json_file
from vanjaro_cli.migration.url_rewrite import (
    RewriteError,
    build_asset_lookup,
    build_page_lookup,
    rewrite_tree,
)

__all__ = ["rewrite_urls"]


@click.command("rewrite-urls")
@click.option(
    "--content",
    "content_file",
    type=click.Path(),
    required=True,
    help="Input content JSON file to rewrite.",
)
@click.option(
    "--asset-manifest",
    "asset_manifest_file",
    type=click.Path(),
    required=True,
    help="Asset manifest with source_url -> vanjaro_url entries.",
)
@click.option(
    "--page-map",
    "page_map_file",
    type=click.Path(),
    default=None,
    help="Page URL map with source URL -> Vanjaro path entries.",
)
@click.option(
    "--output",
    "-o",
    "output_file",
    type=click.Path(),
    default=None,
    help="Destination file (defaults to overwriting --content).",
)
@click.option("--report", is_flag=True, help="Print a summary of rewrites.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def rewrite_urls(
    content_file: str,
    asset_manifest_file: str,
    page_map_file: str | None,
    output_file: str | None,
    report: bool,
    as_json: bool,
) -> None:
    """Rewrite image and link URLs in a content JSON file.

    Walks the component tree and replaces image ``src`` values using the asset
    manifest and internal link ``href`` values using the page URL map. External
    URLs, anchors, and non-http schemes are left untouched.
    """
    content_path = Path(content_file)
    manifest_path = Path(asset_manifest_file)
    page_map_path = Path(page_map_file) if page_map_file else None
    output_path = Path(output_file) if output_file else content_path

    content = read_json_file(content_path, "Content file", as_json)
    if not isinstance(content, dict):
        exit_error(
            f"Content file {content_path} must be a JSON object.", as_json
        )

    manifest_data = read_json_file(manifest_path, "Asset manifest", as_json)
    if not isinstance(manifest_data, list):
        exit_error(
            f"Asset manifest {manifest_path} must be a JSON array of entries.",
            as_json,
        )

    page_map_data: dict | None = None
    if page_map_path is not None:
        raw_map = read_json_file(page_map_path, "Page URL map", as_json)
        if not isinstance(raw_map, dict):
            exit_error(
                f"Page URL map {page_map_path} must be a JSON object.", as_json
            )
        page_map_data = raw_map

    try:
        asset_lookup = build_asset_lookup(manifest_data)
    except RewriteError as exc:
        exit_error(f"{manifest_path}: {exc}", as_json)
    try:
        page_lookup = build_page_lookup(page_map_data)
    except RewriteError as exc:
        label = page_map_path if page_map_path else "page map"
        exit_error(f"{label}: {exc}", as_json)
    try:
        rewrite_report = rewrite_tree(content, asset_lookup, page_lookup)
    except RewriteError as exc:
        exit_error(f"{content_path}: {exc}", as_json)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(content, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        exit_error(f"Cannot write {output_path}: {exc}", as_json)

    report_data = rewrite_report.as_dict()
    human_lines = [
        f"Rewrote {rewrite_report.images_rewritten} image(s) and "
        f"{rewrite_report.links_rewritten} link(s) -> {output_path}"
    ]
    if report:
        human_lines.append(
            f"  images: {rewrite_report.images_rewritten} rewritten, "
            f"{rewrite_report.images_unchanged} unchanged, "
            f"{rewrite_report.missing_asset_count} missing"
        )
        human_lines.append(
            f"  links:  {rewrite_report.links_rewritten} rewritten, "
            f"{rewrite_report.links_unchanged} unchanged, "
            f"{rewrite_report.anchors_skipped} anchors, "
            f"{rewrite_report.external_skipped} external, "
            f"{rewrite_report.missing_page_count} missing"
        )

    output_result(
        as_json,
        status="ok",
        human_message="\n".join(human_lines),
        output=str(output_path),
        report=report_data,
    )
