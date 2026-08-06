"""CLI workflow for agency project workspaces."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

import click
from pydantic import ValidationError

from vanjaro_cli.commands.helpers import exit_error, output_result
from vanjaro_cli.commands.project_inputs import parse_sources, parse_template_overrides
from vanjaro_cli.project import (
    ApprovalGate,
    ProjectApprovalError,
    ProjectStage,
    ProjectStageError,
    ProjectWorkspaceError,
    StageEngine,
    StageInputs,
    StageOperationError,
    create_manifest,
    initialize_workspace,
    load_manifest,
    request_approval,
    resolve_approval,
    workspace_status,
)
from vanjaro_cli.orchestration import (
    ProjectAnalysisError,
    run_project_analysis,
    run_project_planning,
    source_input_files,
    template_catalog_fingerprint,
)


@click.group("project")
def project() -> None:
    """Create and inspect resumable agency project workspaces."""


def _exit_project_analysis_error(
    error: ProjectAnalysisError,
    as_json: bool,
) -> None:
    """Render a recoverable analysis failure without losing structured context."""

    if as_json:
        click.echo(
            json.dumps(
                {
                    "status": "error",
                    "message": str(error),
                    "error": error.as_dict(),
                }
            )
        )
        raise SystemExit(1)
    detail = str(error)
    if error.recommended_action:
        detail += f"\nRecommended action: {error.recommended_action}"
    exit_error(detail, as_json)


@project.command("init")
@click.argument("directory", type=click.Path(path_type=Path))
@click.option("--name", required=True, help="Human-readable project name.")
@click.option("--project-id", default=None, help="Stable project ID; defaults to the name slug.")
@click.option(
    "--target-profile",
    required=True,
    help="Explicit Vanjaro CLI profile for all future portal operations.",
)
@click.option("--expected-portal-id", type=click.IntRange(min=0), default=None)
@click.option(
    "--expected-base-url",
    default=None,
    help="Pinned target URL checked before every portal mutation.",
)
@click.option(
    "--source",
    "source_specs",
    multiple=True,
    required=True,
    metavar="KIND=REFERENCE",
    help="Typed source input; repeat to combine HTML, Figma, image, or legacy evidence.",
)
@click.option(
    "--image-viewport",
    "image_viewports",
    multiple=True,
    metavar="WIDTHxHEIGHT",
    help="Viewport for each image source, in image-source order.",
)
@click.option(
    "--image-breakpoint",
    "image_breakpoints",
    multiple=True,
    metavar="SOURCE_ID=BREAKPOINT",
    help="Explicit desktop, tablet, or mobile ownership for each image source.",
)
@click.option(
    "--image-evidence",
    "image_evidence",
    multiple=True,
    metavar="SOURCE_ID=PATH",
    help="Workspace-local normalized evidence sidecar for an image source.",
)
@click.option(
    "--source-page",
    "source_pages",
    multiple=True,
    metavar="SOURCE_ID=PAGE_REFERENCE",
    help="Explicitly pair multiple source captures as evidence for the same page.",
)
@click.option("--agency-pack", default="clicks-and-mortars", show_default=True)
@click.option("--agency-pack-version", default="1.0.0", show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def init_project(
    directory: Path,
    name: str,
    project_id: str | None,
    target_profile: str,
    expected_portal_id: int | None,
    expected_base_url: str | None,
    source_specs: tuple[str, ...],
    image_viewports: tuple[str, ...],
    image_breakpoints: tuple[str, ...],
    image_evidence: tuple[str, ...],
    source_pages: tuple[str, ...],
    agency_pack: str,
    agency_pack_version: str,
    as_json: bool,
) -> None:
    """Initialize a non-destructive project workspace in DIRECTORY."""

    try:
        sources = parse_sources(
            source_specs,
            image_viewports,
            source_pages=source_pages,
            image_breakpoints=image_breakpoints,
            image_evidence=image_evidence,
        )
        manifest = create_manifest(
            name=name,
            project_id=project_id,
            target_profile=target_profile,
            expected_portal_id=expected_portal_id,
            expected_base_url=expected_base_url,
            sources=sources,
            agency_pack_name=agency_pack,
            agency_pack_version=agency_pack_version,
        )
        manifest_path = initialize_workspace(directory, manifest)
        status = workspace_status(directory, manifest)
    except (ProjectWorkspaceError, ValidationError, ValueError) as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Initialized agency project {manifest.project.name!r} at {manifest_path}.\n"
            f"Target profile: {manifest.target.profile}; sources: {len(manifest.sources)}; "
            f"next stage: {status.next_stage}."
        ),
        manifest=str(manifest_path),
        project_id=manifest.project.id,
        target_profile=manifest.target.profile,
        sources=len(manifest.sources),
        next_stage=status.next_stage,
    )


@project.command("status")
@click.argument(
    "directory",
    type=click.Path(path_type=Path),
    default=Path("."),
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def project_status(directory: Path, as_json: bool) -> None:
    """Report project state and the first resumable stage."""

    try:
        status = workspace_status(directory)
    except ProjectWorkspaceError as exc:
        exit_error(str(exc), as_json)
    payload = status.as_dict()
    if as_json:
        click.echo(json.dumps({"status": "ok", **payload}))
        return
    click.echo(f"Project: {status.project_name} ({status.project_id})")
    click.echo(f"Workspace: {status.root}")
    click.echo(f"Target profile: {status.target_profile}")
    click.echo(f"Sources: {status.source_count}")
    click.echo(f"Completed stages: {', '.join(status.completed_stages) or 'none'}")
    click.echo(f"Next stage: {status.next_stage or 'complete'}")
    if status.failed_stages:
        click.echo(f"Failed stages: {', '.join(status.failed_stages)}")
    if status.running_stages:
        click.echo(f"Running stages: {', '.join(status.running_stages)}")
    if status.pending_approvals:
        click.echo(f"Pending approvals: {status.pending_approvals}")
    if status.missing_directories:
        click.echo(f"Missing workspace directories: {', '.join(status.missing_directories)}")


@project.command("analyze")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--refresh",
    is_flag=True,
    help="Reacquire remote evidence even when the previous analysis is resumable.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help=(
        "Preview state transitions without analysis calls or writes; "
        "workspace-local inputs are validated and hashed."
    ),
)
@click.option(
    "--render",
    is_flag=True,
    help=(
        "Render HTML sources in a browser to record measured geometry and "
        "computed styles. Required for the colour, typography, spacing, and "
        "media fidelity dimensions to have any design-side evidence."
    ),
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def analyze_project(
    directory: Path,
    refresh: bool,
    dry_run: bool,
    render: bool,
    as_json: bool,
) -> None:
    """Analyze every declared source into project Design Document artifacts."""

    try:
        engine = StageEngine(directory)
        current = load_manifest(directory)
        files = source_input_files(engine.root, current)
        refresh_token = (
            datetime.now(timezone.utc).isoformat() if refresh else None
        )
        execution = engine.execute(
            ProjectStage.ANALYZE,
            StageInputs(
                data={"refresh_token": refresh_token, "render": render},
                files=files,
            ),
            partial(run_project_analysis, render=render),
            dry_run=dry_run,
        )
    except ProjectAnalysisError as exc:
        _exit_project_analysis_error(exc, as_json)
    except StageOperationError as exc:
        cause = exc.__cause__
        if isinstance(cause, ProjectAnalysisError):
            _exit_project_analysis_error(cause, as_json)
        exit_error(str(exc), as_json)
    except (ProjectStageError, ProjectWorkspaceError, ValidationError, ValueError) as exc:
        exit_error(str(exc), as_json)

    report = _read_optional_json(engine.root / "analysis" / "analysis-report.json")
    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Project analyze: {execution.status} ({execution.action}); "
            f"attempt {execution.attempt}."
            + (
                f"\nPages: {report.get('pages')}; sections: {report.get('sections')}; "
                f"warnings: {report.get('warnings')}."
                if report and not dry_run
                else ""
            )
        ),
        execution=execution.as_dict(),
        report=report if not dry_run else None,
    )


@project.command("plan")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--minimum-confidence",
    type=click.FloatRange(0.0, 1.0),
    default=0.65,
    show_default=True,
)
@click.option("--allow-simplification", is_flag=True)
@click.option("--css-rule-budget", type=click.IntRange(min=0), default=12, show_default=True)
@click.option(
    "--template-override",
    "template_overrides",
    multiple=True,
    metavar="SECTION_ID=TEMPLATE",
)
@click.option("--override-author", default="cli-user", show_default=True)
@click.option("--override-reason", default="explicit template override", show_default=True)
@click.option("--dry-run", is_flag=True, help="Preview state transitions without planning or writing files.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def plan_project(
    directory: Path,
    minimum_confidence: float,
    allow_simplification: bool,
    css_rule_budget: int,
    template_overrides: tuple[str, ...],
    override_author: str,
    override_reason: str,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Map analyzed sections to standard Vanjaro blocks and validate the plan."""

    try:
        overrides = parse_template_overrides(template_overrides)
        engine = StageEngine(directory)
        current = load_manifest(engine.root)
        plan_files = [Path("analysis/design-document.json")]
        if (engine.root / "analysis" / "design-overlays.json").is_file():
            plan_files.append(Path("analysis/design-overlays.json"))
        catalog_fingerprint = template_catalog_fingerprint()
        planning_request = {
            "schema_version": "1.0",
            "policy": {
                "minimum_confidence": minimum_confidence,
                "allow_simplification": allow_simplification,
                "css_rule_budget": css_rule_budget,
            },
            "template_overrides": overrides,
            "override_author": override_author,
            "override_reason": override_reason,
            "target_pack": current.agency_pack.model_dump(mode="json"),
            "template_catalog_fingerprint": catalog_fingerprint,
        }
        inputs = StageInputs(
            data=planning_request,
            files=tuple(plan_files),
        )
        execution = engine.execute(
            ProjectStage.PLAN,
            inputs,
            lambda context: run_project_planning(
                context,
                minimum_confidence=minimum_confidence,
                allow_simplification=allow_simplification,
                css_rule_budget=css_rule_budget,
                template_overrides=overrides,
                override_author=override_author,
                override_reason=override_reason,
                planning_request=planning_request,
            ),
            dry_run=dry_run,
        )
    except (ProjectStageError, ProjectWorkspaceError, ValidationError, ValueError) as exc:
        exit_error(str(exc), as_json)

    validation = _read_optional_json(engine.root / "plans" / "validation.json")
    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Project plan: {execution.status} ({execution.action}); attempt {execution.attempt}."
            + (
                f"\nSections: {validation.get('section_count')}; "
                f"approval blockers: {validation.get('issue_count')}."
                if validation and not dry_run
                else ""
            )
        ),
        execution=execution.as_dict(),
        validation=validation if not dry_run else None,
    )


@project.group("approval")
def approval() -> None:
    """Request and resolve fingerprint-bound project gates."""


@approval.command("request")
@click.argument("directory", type=click.Path(path_type=Path))
@click.option(
    "--gate",
    type=click.Choice([gate.value for gate in ApprovalGate]),
    required=True,
)
@click.option("--by", "requested_by", required=True, help="Requesting operator identity.")
@click.option(
    "--fingerprint",
    default=None,
    help="Exact artifact SHA-256; defaults to the owning plan/verify output.",
)
@click.option("--note", default=None)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def request_project_approval(
    directory: Path,
    gate: str,
    requested_by: str,
    fingerprint: str | None,
    note: str | None,
    as_json: bool,
) -> None:
    """Request approval for an exact plan or verification artifact."""

    try:
        record = request_approval(
            directory,
            gate=ApprovalGate(gate),
            requested_by=requested_by,
            fingerprint=fingerprint,
            note=note,
        )
    except (ProjectApprovalError, ProjectWorkspaceError, ValidationError) as exc:
        exit_error(str(exc), as_json)
    payload = record.model_dump(mode="json")
    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Approval requested: {record.id} ({record.gate.value})\n"
            f"Fingerprint: {record.fingerprint}"
        ),
        approval=payload,
    )


@approval.command("resolve")
@click.argument("directory", type=click.Path(path_type=Path))
@click.argument("approval_id")
@click.option(
    "--decision",
    type=click.Choice(["approve", "reject"]),
    required=True,
)
@click.option("--by", "resolved_by", required=True, help="Resolving operator identity.")
@click.option("--note", default=None)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def resolve_project_approval(
    directory: Path,
    approval_id: str,
    decision: str,
    resolved_by: str,
    note: str | None,
    as_json: bool,
) -> None:
    """Approve or reject one pending project gate."""

    try:
        record = resolve_approval(
            directory,
            approval_id,
            approved=decision == "approve",
            resolved_by=resolved_by,
            note=note,
        )
    except (ProjectApprovalError, ProjectWorkspaceError, ValidationError) as exc:
        exit_error(str(exc), as_json)
    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Approval {record.id}: {record.status.value} by {record.resolved_by}."
        ),
        approval=record.model_dump(mode="json"),
    )


def _read_optional_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


from vanjaro_cli.commands.project_build_cmd import build_project
from vanjaro_cli.commands.project_evidence_cmd import evidence
from vanjaro_cli.commands.project_pack_cmd import pack
from vanjaro_cli.commands.project_overlay_cmd import overlay
from vanjaro_cli.commands.project_target_cmd import target

project.add_command(build_project)
project.add_command(evidence)
project.add_command(pack)
project.add_command(overlay)
project.add_command(target)


__all__ = ["project"]
