"""Offline Design Document analysis for existing migration artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

import click

from vanjaro_cli.commands.helpers import output_result
from vanjaro_cli.design.html_adapter import HtmlAdapterError
from vanjaro_cli.design.serialization import write_design_document
from vanjaro_cli.design.sources import (
    LegacyCrawlSourceRequest,
    analyze_source,
)

__all__ = ["analyze"]


def _analysis_error(
    *,
    category: str,
    message: str,
    artifact: Path,
    recommended_action: str,
    as_json: bool,
) -> NoReturn:
    """Emit a categorized analysis failure with an actionable recovery step."""

    if as_json:
        click.echo(
            json.dumps(
                {
                    "status": "error",
                    "category": category,
                    "message": message,
                    "artifact": str(artifact),
                    "recommended_action": recommended_action,
                }
            )
        )
        raise SystemExit(1)
    raise click.ClickException(
        f"{message}\nArtifact: {artifact}\nRecommended action: {recommended_action}"
    )


@click.command("analyze")
@click.argument("artifact_dir", type=click.Path(path_type=Path))
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Design Document JSON path. Defaults to ARTIFACT_DIR/design-document.json.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def analyze(artifact_dir: Path, output: Path | None, as_json: bool) -> None:
    """Convert or re-analyze an existing crawl in ARTIFACT_DIR offline."""

    inventory = artifact_dir / "site-inventory.json"
    if not artifact_dir.is_dir() or not inventory.is_file():
        _analysis_error(
            category="source_unavailable",
            message="A completed migration directory with site-inventory.json is required.",
            artifact=inventory,
            recommended_action=(
                "Run `vanjaro migrate crawl URL --output-dir ARTIFACT_DIR` first, "
                "or pass the directory containing the existing crawl."
            ),
            as_json=as_json,
        )

    try:
        document = analyze_source(
            LegacyCrawlSourceRequest(migration_directory=artifact_dir)
        )
    except HtmlAdapterError as exc:
        _analysis_error(
            category="schema_invalid",
            message=str(exc),
            artifact=inventory,
            recommended_action=(
                "Repair or restore the malformed legacy JSON artifact, then rerun "
                "`vanjaro migrate analyze`."
            ),
            as_json=as_json,
        )

    output_path = output or artifact_dir / "design-document.json"
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_design_document(output_path, document)
    except OSError as exc:
        _analysis_error(
            category="source_unavailable",
            message=f"Could not write Design Document: {exc}",
            artifact=output_path,
            recommended_action=(
                "Choose a writable --output path and confirm the parent directory permissions."
            ),
            as_json=as_json,
        )

    section_count = sum(len(page.sections) for page in document.pages)
    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Analyzed {len(document.pages)} page(s), {section_count} section(s). "
            f"Design Document: {output_path}"
        ),
        output=str(output_path),
        schema_version=document.schema_version,
        pages=len(document.pages),
        sections=section_count,
        warnings=len(document.warnings),
    )
