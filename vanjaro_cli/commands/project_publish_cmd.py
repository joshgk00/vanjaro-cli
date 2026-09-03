"""CLI presentation for reviewed agency project publication."""

from __future__ import annotations

from pathlib import Path

import click

from vanjaro_cli.commands.helpers import exit_error, output_result
from vanjaro_cli.orchestration.project_publish import (
    ProjectPublishError,
    apply_project_publish,
    prepare_project_publish,
)
from vanjaro_cli.orchestration.project_publish_recovery import (
    recover_project_publish_lock,
)


@click.group("publish")
def publish_project() -> None:
    """Prepare and apply fingerprint-bound project publication."""


@publish_project.command("prepare")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview the receipt without workspace writes or portal mutations.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def prepare_publish(directory: Path, dry_run: bool, as_json: bool) -> None:
    """GET-only portal preflight and optional local receipt adoption."""

    try:
        result = prepare_project_publish(directory, dry_run=dry_run)
    except (ProjectPublishError, ValueError) as exc:
        exit_error(str(exc), as_json)
    receipt = result["receipt"]
    payload = {key: value for key, value in result.items() if key != "status"}
    output_result(
        as_json,
        status="ready_for_review",
        human_message=(
            f"Publish review prepared for {len(receipt['actions'])} hidden content object(s).\n"
            f"Receipt fingerprint: {receipt['fingerprint']}\n"
            f"Portal mutated: no; workspace mutated: {'yes' if result['workspace_mutated'] else 'no'}.\n"
            "Review the receipt, request/resolve its publish approval, then apply it explicitly."
        ),
        **payload,
    )


@publish_project.command("apply")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option("--receipt", "receipt_fingerprint", required=True)
@click.option("--approval-id", required=True)
@click.option("--confirm-publish", "confirmation", required=True)
@click.option("--by", "published_by", required=True)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def apply_publish(
    directory: Path,
    receipt_fingerprint: str,
    approval_id: str,
    confirmation: str,
    published_by: str,
    as_json: bool,
) -> None:
    """Publish the exact approved receipt after action-time confirmation."""

    try:
        result = apply_project_publish(
            directory,
            receipt_fingerprint=receipt_fingerprint,
            approval_id=approval_id,
            confirmation=confirmation,
            published_by=published_by,
        )
    except (ProjectPublishError, ValueError) as exc:
        exit_error(str(exc), as_json)
    payload = {key: value for key, value in result.items() if key != "status"}
    output_result(
        as_json,
        status=result["status"],
        human_message=(
            f"Project publish: {result['status']}.\n"
            f"Receipt: {result['receipt_fingerprint']}\n"
            "Managed content is published but page navigation/name promotion remains separate."
        ),
        **payload,
    )


@publish_project.command("recover-lock")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option("--token", "owner_token", required=True)
@click.option("--confirm-clear", "confirmation", required=True)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def recover_publish_lock(
    directory: Path,
    owner_token: str,
    confirmation: str,
    as_json: bool,
) -> None:
    """Clear a proven-dead publication lock after reviewing recovery evidence."""

    try:
        result = recover_project_publish_lock(
            directory,
            owner_token=owner_token,
            confirmation=confirmation,
        )
    except (ProjectPublishError, ValueError) as exc:
        exit_error(str(exc), as_json)
    payload = {key: value for key, value in result.items() if key != "status"}
    output_result(
        as_json,
        status=result["status"],
        human_message=(
            "The proven-stale local publish lock was cleared. No portal request was made. "
            "Review the transaction journal, then retry the exact approved receipt."
        ),
        **payload,
    )


__all__ = ["publish_project"]
