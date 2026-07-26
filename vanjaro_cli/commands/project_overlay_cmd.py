"""CLI presentation for audited project design overlays."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import click
from pydantic import ValidationError

from vanjaro_cli.commands.helpers import exit_error, output_result
from vanjaro_cli.design.models import ContentKind
from vanjaro_cli.design.overlays import DesignOverlay, OverlayOperation
from vanjaro_cli.project import (
    ProjectOverlayError,
    ProjectWorkspaceError,
    add_project_overlay,
    load_project_overlays,
)


@click.group("overlay")
def overlay() -> None:
    """Record explicit, audited corrections to ambiguous source evidence."""


@overlay.command("add-repeat-field")
@click.argument("directory", type=click.Path(path_type=Path))
@click.option("--id", "overlay_id", required=True, help="Stable correction ID.")
@click.option("--target-item", required=True, help="Exact repeat-group item ID.")
@click.option("--field", required=True, help="Semantic field to add, such as value.")
@click.option(
    "--kind",
    "content_kind",
    type=click.Choice([kind.value for kind in ContentKind]),
    required=True,
)
@click.option("--value", required=True, help="Explicit visitor-facing value.")
@click.option("--by", "author", required=True, help="Correction author identity.")
@click.option("--reason", required=True, help="Evidence and rationale for the correction.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def add_repeat_field_overlay(
    directory: Path,
    overlay_id: str,
    target_item: str,
    field: str,
    content_kind: str,
    value: str,
    author: str,
    reason: str,
    as_json: bool,
) -> None:
    """Add one missing repeat-item field without altering captured evidence."""

    try:
        record = add_project_overlay(
            directory,
            DesignOverlay(
                id=overlay_id,
                operation=OverlayOperation.ADD_REPEAT_FIELD,
                target_id=target_item,
                field=field,
                content_kind=ContentKind(content_kind),
                value=value,
                author=author,
                reason=reason,
                created_at=datetime.now(timezone.utc),
            ),
        )
    except (ProjectOverlayError, ProjectWorkspaceError, ValidationError, ValueError) as exc:
        exit_error(str(exc), as_json)
    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Recorded design overlay {record.id}; the plan and downstream approvals "
            "must be regenerated."
        ),
        overlay=record.model_dump(mode="json"),
        next_stage="plan",
    )


@overlay.command("set-value")
@click.argument("directory", type=click.Path(path_type=Path))
@click.option("--id", "overlay_id", required=True, help="Stable correction ID.")
@click.option("--target-element", required=True, help="Exact content element ID.")
@click.option("--value", required=True, help="Replacement visitor-facing value.")
@click.option("--by", "author", required=True, help="Correction author identity.")
@click.option("--reason", required=True, help="Evidence and rationale for the correction.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def set_value_overlay(
    directory: Path,
    overlay_id: str,
    target_element: str,
    value: str,
    author: str,
    reason: str,
    as_json: bool,
) -> None:
    """Replace one captured visitor value while retaining original provenance."""

    try:
        record = add_project_overlay(
            directory,
            DesignOverlay(
                id=overlay_id,
                operation=OverlayOperation.SET_ELEMENT_VALUE,
                target_id=target_element,
                value=value,
                author=author,
                reason=reason,
                created_at=datetime.now(timezone.utc),
            ),
        )
    except (ProjectOverlayError, ProjectWorkspaceError, ValidationError, ValueError) as exc:
        exit_error(str(exc), as_json)
    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Recorded design overlay {record.id}; the plan and downstream approvals "
            "must be regenerated."
        ),
        overlay=record.model_dump(mode="json"),
        next_stage="plan",
    )


@overlay.command("list")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_overlays(directory: Path, as_json: bool) -> None:
    """List every audited correction in application order."""

    try:
        overlay_set = load_project_overlays(directory)
    except (ProjectOverlayError, ProjectWorkspaceError, ValidationError, ValueError) as exc:
        exit_error(str(exc), as_json)
    records = [item.model_dump(mode="json") for item in overlay_set.overlays]
    if as_json:
        click.echo(json.dumps({"status": "ok", "overlays": records}))
        return
    click.echo(f"Design overlays: {len(records)}")
    for record in records:
        click.echo(
            f"- {record['id']}: {record['operation']} -> {record['target_id']} "
            f"({record['author']})"
        )


__all__ = ["overlay"]
