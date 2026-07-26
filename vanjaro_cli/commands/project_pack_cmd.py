"""Reviewed project CLI for agency-pack compatibility and local apply."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import NoReturn

import click

from vanjaro_cli.agency_library import (
    AgencyPackCompatibilityError,
    AgencyPackApplyError,
    AgencyPackRegistry,
    AgencyPackRegistryError,
    plan_agency_pack_upgrade,
    apply_agency_pack_upgrade,
    rollback_agency_pack_upgrade,
    read_project_pack_usage,
)
from vanjaro_cli.project import ProjectWorkspaceError, load_manifest


_DEFAULT_PACKS_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "agency-packs"


@click.group("pack")
def pack() -> None:
    """Inspect and upgrade the versioned agency library assigned to a project."""


@pack.command("upgrade")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option("--to-version", required=True, help="Newer published agency-pack version.")
@click.option(
    "--packs-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Agency-pack registry root; defaults to VANJARO_AGENCY_PACKS_DIR or the repository registry.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Emit compatibility and remediation without changing the project.",
)
@click.option("--apply", "apply_upgrade", is_flag=True, help="Apply an accepted compatible report offline.")
@click.option(
    "--accept-fingerprint",
    "accepted_fingerprint",
    default=None,
    help="Exact fingerprint from the reviewed dry-run report.",
)
@click.option("--by", "reviewed_by", default=None, help="Identity of the report reviewer.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def upgrade_pack(
    directory: Path,
    to_version: str,
    packs_dir: Path | None,
    dry_run: bool,
    apply_upgrade: bool,
    accepted_fingerprint: str | None,
    reviewed_by: str | None,
    as_json: bool,
) -> None:
    """Review or transactionally apply an agency-pack upgrade."""

    if dry_run == apply_upgrade:
        _exit(
            {
                "category": "agency_pack_mode_required",
                "message": "choose exactly one of --dry-run or --apply",
                "recommended_action": "Use --dry-run first; then use --apply with its accepted fingerprint.",
            },
            as_json,
        )
    if apply_upgrade and (not accepted_fingerprint or not reviewed_by):
        _exit(
            {
                "category": "agency_pack_review_required",
                "message": "--apply requires --accept-fingerprint and --by",
                "recommended_action": "Review a fresh dry-run and identify the reviewer explicitly.",
            },
            as_json,
        )
    try:
        root = directory.expanduser().resolve()
        registry_root = packs_dir or Path(
            os.environ.get("VANJARO_AGENCY_PACKS_DIR", _DEFAULT_PACKS_DIR)
        )
        registry = AgencyPackRegistry(registry_root)
        if apply_upgrade:
            result = apply_agency_pack_upgrade(
                root,
                registry=registry,
                to_version=to_version,
                accepted_fingerprint=accepted_fingerprint or "",
                reviewed_by=reviewed_by or "",
            )
            payload = {"status": "ok", "dry_run": False, "result": result}
            if as_json:
                click.echo(json.dumps(payload))
            else:
                click.echo(
                    f"Committed agency pack {result['from_version']} -> {result['to_version']} "
                    f"as transaction {result['transaction_id']}."
                )
            return
        manifest = load_manifest(root)
        current = registry.resolve(
            manifest.agency_pack.name,
            manifest.agency_pack.version,
        )
        target = registry.resolve(manifest.agency_pack.name, to_version)
        usage = read_project_pack_usage(
            root / "plans" / "composition-plan.json",
            replan_inputs=_replan_inputs(root),
        )
        report = plan_agency_pack_upgrade(current, target, usage)
    except (AgencyPackRegistryError, AgencyPackCompatibilityError, AgencyPackApplyError) as exc:
        _exit(exc.as_dict(), as_json)
    except ProjectWorkspaceError as exc:
        _exit(
            {
                "category": "agency_pack_project_invalid",
                "message": str(exc),
                "recommended_action": "Initialize or repair the project workspace, then retry.",
            },
            as_json,
        )

    payload = {
        "status": "ok",
        "dry_run": True,
        "project_id": manifest.project.id,
        "report": report.as_dict(),
    }
    if as_json:
        click.echo(json.dumps(payload))
        return
    click.echo(
        f"Agency pack {report.pack_name}: {report.from_version} -> {report.to_version}"
    )
    click.echo(f"Compatibility: {report.status}; issues: {len(report.issues)}")
    for issue in report.issues:
        click.echo(f"- [{issue.severity}] {issue.code}: {issue.message}")


@pack.command("rollback")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option("--transaction", "transaction_id", required=True, help="Interrupted transaction ID.")
@click.option("--by", "rolled_back_by", required=True, help="Recovery operator identity.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def rollback_pack(
    directory: Path, transaction_id: str, rolled_back_by: str, as_json: bool
) -> None:
    """Restore an interrupted local pack transaction from its verified snapshot."""

    try:
        result = rollback_agency_pack_upgrade(
            directory,
            transaction_id=transaction_id,
            rolled_back_by=rolled_back_by,
        )
    except (AgencyPackApplyError, ProjectWorkspaceError) as exc:
        if isinstance(exc, AgencyPackApplyError):
            _exit(exc.as_dict(), as_json)
        _exit(
            {
                "category": "agency_pack_project_invalid",
                "message": str(exc),
                "recommended_action": "Repair the project workspace before recovery.",
            },
            as_json,
        )
    payload = {"status": "ok", "result": result}
    if as_json:
        click.echo(json.dumps(payload))
    else:
        click.echo(f"Rolled back transaction {transaction_id}.")


def _exit(error: dict[str, object], as_json: bool) -> NoReturn:
    if as_json:
        click.echo(json.dumps({"status": "error", "error": error}))
        raise SystemExit(1)
    message = str(error.get("message", "agency-pack upgrade planning failed"))
    action = error.get("recommended_action")
    if action:
        message += f"\nRecommended action: {action}"
    raise click.ClickException(message)


def _replan_inputs(root: Path) -> tuple[Path, ...]:
    return (
        root / "project.json",
        root / "analysis" / "design-document.json",
        root / "analysis" / "design-overlays.json",
        root / "plans" / "library-plan.json",
        root / "plans" / "planning-request.json",
    )


__all__ = ["pack"]
