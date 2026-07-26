"""`vanjaro migrate visual-capture` — screenshot pairs for visual QA."""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.commands.helpers import exit_error, output_result, read_json_object
from vanjaro_cli.config import ConfigError, load_config
from vanjaro_cli.migration.visual import (
    VisualCaptureError,
    build_capture_plan,
    parse_viewport,
    run_capture,
)

__all__ = ["visual_capture"]


@click.command("visual-capture")
@click.option(
    "--dir",
    "migration_dir",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Migration output directory containing page-url-map.json.",
)
@click.option(
    "--page-map",
    "page_map_file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Explicit page-url-map.json path (overrides --dir lookup).",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    type=click.Path(file_okay=False),
    default=None,
    help="Destination for screenshots + manifest (default: {dir}/visual-report).",
)
@click.option(
    "--viewport",
    default="1280x800",
    show_default=True,
    help="Browser viewport as WIDTHxHEIGHT.",
)
@click.option(
    "--pages",
    "pages_filter",
    default=None,
    help="Comma-separated Vanjaro paths to capture (default: all).",
)
@click.option(
    "--auth",
    "use_auth",
    is_flag=True,
    help=(
        "Send profile session cookies to the Vanjaro site (needed for hidden/"
        "draft pages). Default is anonymous so admin chrome never appears in "
        "screenshots."
    ),
)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=int,
    default=45,
    show_default=True,
    help="Per-page navigation timeout in seconds.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def visual_capture(
    migration_dir: str | None,
    page_map_file: str | None,
    output_dir: str | None,
    viewport: str,
    pages_filter: str | None,
    use_auth: bool,
    timeout_seconds: int,
    as_json: bool,
) -> None:
    """Capture source vs migrated screenshot pairs for visual comparison.

    Reads page-url-map.json from the migration output directory, screenshots
    every distinct page pair with a deterministic settle (fonts loaded, lazy
    images triggered, animations disabled), and writes a manifest.json that
    the vision-comparison step consumes.
    """
    if migration_dir is None and page_map_file is None:
        exit_error("Provide --dir or --page-map.", as_json)

    map_path = (
        Path(page_map_file)
        if page_map_file
        else Path(migration_dir) / "page-url-map.json"
    )
    if not map_path.exists():
        exit_error(f"Page URL map not found: {map_path}", as_json)

    page_url_map = read_json_object(map_path, "Page URL map", as_json)

    try:
        config = load_config()
    except ConfigError as exc:
        exit_error(str(exc), as_json)

    try:
        viewport_size = parse_viewport(viewport)
    except VisualCaptureError as exc:
        exit_error(str(exc), as_json)

    include_paths = (
        [p.strip() for p in pages_filter.split(",") if p.strip()]
        if pages_filter
        else None
    )
    plan = build_capture_plan(page_url_map, config.base_url, include_paths)
    if not plan:
        exit_error("No pages to capture after filtering.", as_json)

    destination = Path(output_dir) if output_dir else (
        Path(migration_dir) / "visual-report"
        if migration_dir
        else map_path.parent / "visual-report"
    )

    try:
        capture_cookies = (
            {**config.cookies, "vj_IsPageEdit": "true"} if use_auth else None
        )
        manifest = run_capture(
            plan,
            destination,
            viewport_size,
            cookies=capture_cookies,
            vanjaro_base_url=config.base_url,
            timeout_seconds=timeout_seconds,
        )
    except VisualCaptureError as exc:
        exit_error(str(exc), as_json)

    pages_with_warnings = [p for p in manifest["pages"] if p["warnings"]]
    output_result(
        as_json,
        status="captured",
        human_message=(
            f"Captured {len(manifest['pages'])} page pairs to {destination} "
            f"({len(pages_with_warnings)} with warnings, "
            f"{len(manifest['warnings'])} global warnings)."
        ),
        output_dir=str(destination),
        page_count=len(manifest["pages"]),
        pages_with_warnings=[p["slug"] for p in pages_with_warnings],
        global_warnings=manifest["warnings"],
    )
    if not as_json:
        for page in pages_with_warnings:
            for warning in page["warnings"]:
                click.echo(f"  [{page['slug']}] {warning}")
        for warning in manifest["warnings"]:
            click.echo(f"  [site] {warning}")
