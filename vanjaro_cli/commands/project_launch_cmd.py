"""CLI presentation for reviewed agency-site launch promotion."""

from __future__ import annotations

from pathlib import Path

import click

from vanjaro_cli.commands.helpers import exit_error, output_result
from vanjaro_cli.orchestration.project_launch import (
    ProjectLaunchWorkflowError,
    apply_project_launch,
    prepare_project_launch,
)
from vanjaro_cli.orchestration.project_launch_plan import (
    ProjectLaunchPlanError,
    create_project_launch_plan,
)
from vanjaro_cli.orchestration.project_publish import ProjectPublishError
from vanjaro_cli.orchestration.project_publish_recovery import (
    recover_project_publish_lock,
)


@click.group("launch")
def launch_project() -> None:
    """Plan, review, and apply editor-facing site promotion."""


@launch_project.command("plan")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option("--home-page", "home_page_key", default=None, metavar="PAGE_KEY")
@click.option(
    "--preserve-home",
    is_flag=True,
    help="Keep the portal's current home page instead of selecting a managed page.",
)
@click.option("--visible", "visible_pages", multiple=True, metavar="PAGE_KEY")
@click.option("--hidden", "hidden_pages", multiple=True, metavar="PAGE_KEY")
@click.option("--name", "name_values", multiple=True, metavar="PAGE_KEY=NAME")
@click.option("--title", "title_values", multiple=True, metavar="PAGE_KEY=TITLE")
@click.option("--dry-run", is_flag=True, help="Preview without writing the launch plan.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def plan_launch(
    directory: Path,
    home_page_key: str | None,
    preserve_home: bool,
    visible_pages: tuple[str, ...],
    hidden_pages: tuple[str, ...],
    name_values: tuple[str, ...],
    title_values: tuple[str, ...],
    dry_run: bool,
    as_json: bool,
) -> None:
    """Create the sole reviewed authority for final page structure."""

    try:
        if preserve_home == (home_page_key is not None):
            raise ValueError("choose exactly one of --home-page or --preserve-home")
        overlap = sorted(set(visible_pages) & set(hidden_pages))
        if overlap:
            raise ValueError(
                f"page {overlap[0]!r} cannot be both visible and hidden"
            )
        visibility = {key: True for key in visible_pages}
        visibility.update({key: False for key in hidden_pages})
        result = create_project_launch_plan(
            directory,
            home_page_key=home_page_key,
            preserve_current_home=preserve_home,
            visibility_overrides=visibility,
            name_overrides=_assignments(name_values, "name"),
            title_overrides=_assignments(title_values, "title"),
            dry_run=dry_run,
        )
    except (ProjectLaunchPlanError, ValueError) as exc:
        exit_error(str(exc), as_json)
    plan = result["plan"]
    payload = {key: value for key, value in result.items() if key != "status"}
    output_result(
        as_json,
        status=result["status"],
        human_message=(
            f"Launch plan: {result['status']} ({len(plan['pages'])} page(s)).\n"
            f"Fingerprint: {plan['fingerprint']}\n"
            f"Workspace mutated: {result['workspace_mutated']}."
        ),
        **payload,
    )


@launch_project.command("prepare")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--dry-run",
    is_flag=True,
    help="Request the authoritative read-only preview without adopting it.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def prepare_launch(directory: Path, dry_run: bool, as_json: bool) -> None:
    """Prepare a fingerprint-bound live launch review receipt."""

    try:
        result = prepare_project_launch(directory, dry_run=dry_run)
    except (ProjectLaunchWorkflowError, ValueError) as exc:
        exit_error(str(exc), as_json)
    receipt = result["receipt"]
    payload = {key: value for key, value in result.items() if key != "status"}
    output_result(
        as_json,
        status=result["status"],
        human_message=(
            f"Launch review: {result['status']} ({len(receipt['actions'])} page(s)).\n"
            f"Receipt: {receipt['fingerprint']}\n"
            "No launch mutation was performed."
        ),
        **payload,
    )


@launch_project.command("apply")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option("--receipt", "receipt_fingerprint", required=True)
@click.option("--approval-id", required=True)
@click.option(
    "--confirm-launch",
    "confirmation",
    required=True,
    help="Repeat the complete launch receipt fingerprint at action time.",
)
@click.option(
    "--confirm-home",
    "home_confirmation",
    type=click.IntRange(min=0),
    default=None,
    help="Required only when the receipt changes the home page.",
)
@click.option("--by", "launched_by", required=True, help="Launching operator identity.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def apply_launch(
    directory: Path,
    receipt_fingerprint: str,
    approval_id: str,
    confirmation: str,
    home_confirmation: int | None,
    launched_by: str,
    as_json: bool,
) -> None:
    """Apply the exact approved launch batch after full confirmation."""

    try:
        result = apply_project_launch(
            directory,
            receipt_fingerprint=receipt_fingerprint,
            approval_id=approval_id,
            confirmation=confirmation,
            home_confirmation=home_confirmation,
            launched_by=launched_by,
        )
    except (ProjectLaunchWorkflowError, ValueError) as exc:
        exit_error(str(exc), as_json)
    payload = {key: value for key, value in result.items() if key != "status"}
    output_result(
        as_json,
        status=result["status"],
        human_message=(
            f"Project launch: {result['status']}.\n"
            f"Receipt: {result['receipt_fingerprint']}\n"
            "Review the launch result and final public routes."
        ),
        **payload,
    )


@launch_project.command("recover-lock")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option("--token", "owner_token", required=True)
@click.option("--confirm-clear", "confirmation", required=True)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def recover_launch_lock(
    directory: Path,
    owner_token: str,
    confirmation: str,
    as_json: bool,
) -> None:
    """Clear a proven-dead shared publish/launch authority lock."""

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
            "The proven-stale shared authority lock was cleared. No portal request "
            "was made. Review the launch journal before retrying."
        ),
        **payload,
    )


def _assignments(values: tuple[str, ...], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--{label} must use PAGE_KEY=VALUE")
        key, assigned = value.split("=", 1)
        key = key.strip()
        assigned = " ".join(assigned.split())
        if not key or not assigned:
            raise ValueError(f"--{label} must use a nonempty PAGE_KEY=VALUE")
        if key in result:
            raise ValueError(f"duplicate --{label} assignment for page {key!r}")
        result[key] = assigned
    return result


__all__ = ["launch_project"]
