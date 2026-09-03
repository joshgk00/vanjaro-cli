"""CLI presentation for fingerprint-bound, one-stage project builds."""

from __future__ import annotations

import json
from pathlib import Path

import click
from click.core import ParameterSource

from vanjaro_cli.client import ApiError
from vanjaro_cli.commands.helpers import exit_error
from vanjaro_cli.orchestration.project_build_review import (
    ProjectBuildReviewError,
    apply_build_review,
    prepare_next_build_review,
)
from vanjaro_cli.portal import (
    BlockLibraryError,
    ProjectGlobalBlockError,
    ProjectPageError,
)
from vanjaro_cli.project.build_receipt import (
    BuildReceiptError,
    load_build_receipt,
)
from vanjaro_cli.project.publish_lock import PublishLockError
from vanjaro_cli.project.stage_engine import ProjectStageError
from vanjaro_cli.project.workspace import ProjectWorkspaceError


@click.command("build")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--theme-mode",
    type=click.Choice(["preserve", "plan"]),
    default="preserve",
    show_default=True,
    help=(
        "Theme mode: preserve leaves the portal unchanged; plan maps design tokens "
        "to existing controls and writes review artifacts without applying them."
    ),
)
@click.option(
    "--through",
    type=click.Choice(["theme", "assets", "library", "pages", "globals", "verify"]),
    default="verify",
    show_default=True,
    help="Build ceiling; each invocation reviews or applies only the next stage.",
)
@click.option(
    "--page-mode",
    type=click.Choice(["isolated"]),
    default="isolated",
    show_default=True,
    help="Create hidden project-prefixed drafts without altering current navigation.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Emit a zero-write receipt for exactly the next stage.",
)
@click.option(
    "--review-receipt",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Detached JSON receipt saved from a current --dry-run.",
)
@click.option(
    "--confirm-build",
    default=None,
    help="Full SHA-256 fingerprint from the reviewed receipt.",
)
@click.option(
    "--by",
    "operator",
    default=None,
    help="Operator identity bound to the review and action.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def build_project(
    click_context: click.Context,
    directory: Path,
    theme_mode: str,
    through: str,
    page_mode: str,
    dry_run: bool,
    review_receipt: Path | None,
    confirm_build: str | None,
    operator: str | None,
    as_json: bool,
) -> None:
    """Review or apply one approved build stage with exact target guards."""

    try:
        if (
            theme_mode == "plan"
            and click_context.get_parameter_source("through") == ParameterSource.DEFAULT
        ):
            through = "theme"
        if theme_mode == "plan" and through != "theme":
            raise ProjectBuildReviewError(
                "theme-mode plan is artifact-only and can run only through theme"
            )
        if not operator or not operator.strip():
            raise ProjectBuildReviewError("project build requires a non-empty --by operator")
        if dry_run:
            if review_receipt is not None or confirm_build is not None:
                raise ProjectBuildReviewError(
                    "--dry-run cannot be combined with --review-receipt or --confirm-build"
                )
            prepared = prepare_next_build_review(
                directory,
                theme_mode=theme_mode,
                through=through,
                page_mode=page_mode,
                operator=operator,
            )
            execution = prepared.execution.as_dict()
            execution["preview"] = prepared.receipt["preview"]
            payload = {
                "status": "preview",
                "dry_run": True,
                "through": through,
                "executions": [execution],
                "receipt": prepared.receipt,
                "portal_mutated": False,
                "workspace_mutated": False,
            }
        else:
            if review_receipt is None or not confirm_build:
                raise ProjectBuildReviewError(
                    "real build execution requires --review-receipt, --confirm-build, "
                    "and --by from a current --dry-run"
                )
            reviewed = load_build_receipt(review_receipt)
            execution = apply_build_review(
                directory,
                reviewed_receipt=reviewed,
                confirmation=confirm_build,
                operator=operator,
                theme_mode=theme_mode,
                through=through,
                page_mode=page_mode,
            )
            payload = {
                "status": "ok",
                "dry_run": False,
                "through": through,
                "executions": [execution.as_dict()],
                "review_fingerprint": reviewed["fingerprint"],
                "operator": operator.strip(),
            }
    except (
        ApiError,
        BlockLibraryError,
        BuildReceiptError,
        ProjectBuildReviewError,
        ProjectPageError,
        ProjectGlobalBlockError,
        ProjectStageError,
        ProjectWorkspaceError,
        PublishLockError,
        ValueError,
    ) as exc:
        exit_error(str(exc), as_json)

    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    execution = payload["executions"][0]
    click.echo(
        f"{execution['stage']}: {execution['status']} ({execution['action']})"
    )
    if dry_run:
        fingerprint = payload["receipt"]["fingerprint"]
        click.echo(f"Build review fingerprint: {fingerprint}")
        click.echo(
            "Save the receipt JSON, then apply it with --review-receipt PATH "
            f"--confirm-build {fingerprint} --by {operator.strip()!r}."
        )


__all__ = ["build_project"]
