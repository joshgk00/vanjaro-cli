"""CLI presentation for pinning and verifying project targets."""

from __future__ import annotations

from pathlib import Path

import click
from pydantic import ValidationError

from vanjaro_cli.client import ApiError
from vanjaro_cli.commands.helpers import exit_error, output_result
from vanjaro_cli.config import ConfigError, load_config
from vanjaro_cli.orchestration import PortalIdentityError, verify_project_portal
from vanjaro_cli.project import (
    ProjectTargetError,
    ProjectWorkspaceError,
    load_manifest,
    pin_project_target,
)


@click.group("target")
def target() -> None:
    """Pin and verify the exact portal identity used by this project."""


@target.command("pin")
@click.argument("directory", type=click.Path(path_type=Path))
@click.option("--base-url", default=None, help="Expected target base URL.")
@click.option("--portal-id", type=click.IntRange(min=0), default=None)
@click.option(
    "--from-profile",
    is_flag=True,
    help="Read missing identity values from the project's explicitly named profile.",
)
@click.option("--by", "pinned_by", required=True, help="Operator identity.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def pin_target(
    directory: Path,
    base_url: str | None,
    portal_id: int | None,
    from_profile: bool,
    pinned_by: str,
    as_json: bool,
) -> None:
    """Bind the project to a URL and portal ID before any portal mutation."""

    try:
        manifest = load_manifest(directory)
        if from_profile:
            config = load_config(manifest.target.profile)
            base_url = base_url or config.base_url
            portal_id = config.portal_id if portal_id is None else portal_id
        if base_url is None or portal_id is None:
            raise ValueError(
                "provide --base-url and --portal-id, or pass --from-profile"
            )
        pinned = pin_project_target(
            directory,
            expected_base_url=base_url,
            expected_portal_id=portal_id,
            pinned_by=pinned_by,
        )
    except (
        ConfigError,
        ProjectTargetError,
        ProjectWorkspaceError,
        ValidationError,
        ValueError,
    ) as exc:
        exit_error(str(exc), as_json)
    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Pinned project target: {pinned.profile} -> {pinned.expected_base_url} "
            f"(portal {pinned.expected_portal_id}). Re-run project plan for approval."
        ),
        target=pinned.model_dump(mode="json"),
        next_stage="plan",
    )


@target.command("check")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def check_target(directory: Path, as_json: bool) -> None:
    """Verify the pinned URL and portal ID against live health, without mutation."""

    try:
        manifest = load_manifest(directory)
        _, verified = verify_project_portal(manifest)
    except (
        ApiError,
        ConfigError,
        PortalIdentityError,
        ProjectWorkspaceError,
        ValidationError,
        ValueError,
    ) as exc:
        exit_error(str(exc), as_json)
    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Verified target {verified.base_url} portal {verified.portal_id} "
            f"as {verified.user_name}."
        ),
        target=verified.as_dict(),
    )


__all__ = ["target"]
