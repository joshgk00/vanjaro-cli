"""CLI presentation for approved project build stages."""

from __future__ import annotations

import json
from pathlib import Path

import click
from click.core import ParameterSource

from vanjaro_cli.commands.helpers import exit_error
from vanjaro_cli.orchestration import (
    PortalIdentityError,
    ProjectVerificationError,
    plan_project_theme_stage,
    preserve_project_theme,
    preview_project_library_stage,
    preview_project_page_stage,
    preview_project_global_stage,
    preview_project_theme_stage,
    reconcile_project_page_stage,
    reconcile_project_global_stage,
    register_project_library_stage,
    upload_project_asset_stage,
    verify_project_drafts,
)
from vanjaro_cli.portal import (
    BlockLibraryError,
    ProjectGlobalBlockError,
    ProjectPageError,
)
from vanjaro_cli.project import (
    ProjectStage,
    ProjectStageError,
    ProjectWorkspaceError,
    StageEngine,
    StageInputs,
    StageStatus,
    load_manifest,
)


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
    help="Last supported build stage to execute.",
)
@click.option(
    "--page-mode",
    type=click.Choice(["isolated"]),
    default="isolated",
    show_default=True,
    help="Create hidden project-prefixed drafts without altering current navigation.",
)
@click.option("--dry-run", is_flag=True, help="Preview only the next executable stage without writes or POSTs.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def build_project(
    click_context: click.Context,
    directory: Path,
    theme_mode: str,
    through: str,
    page_mode: str,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Run approved build stages with exact target-identity guards."""

    try:
        if (
            theme_mode == "plan"
            and click_context.get_parameter_source("through") == ParameterSource.DEFAULT
        ):
            through = "theme"
        if theme_mode == "plan" and through != "theme" and not dry_run:
            raise ValueError(
                "theme-mode plan is artifact-only and can execute only with --through theme; "
                "review/apply the proposed theme before running portal build stages"
            )
        engine = StageEngine(directory)
        executions = []
        stages = [ProjectStage.THEME]
        if through in {"assets", "library", "pages", "globals", "verify"}:
            stages.append(ProjectStage.ASSETS)
        if through in {"library", "pages", "globals", "verify"}:
            stages.append(ProjectStage.LIBRARY)
        if through in {"pages", "globals", "verify"}:
            stages.append(ProjectStage.PAGES)
        if through in {"globals", "verify"}:
            stages.append(ProjectStage.GLOBAL_BLOCKS)
        if through == "verify":
            stages.append(ProjectStage.VERIFY)
        for stage in stages:
            manifest = load_manifest(engine.root)
            if dry_run and any(
                manifest.stages[dependency].status
                not in {StageStatus.COMPLETED, StageStatus.SKIPPED}
                for dependency in _dependencies(stage)
            ):
                break
            if stage == ProjectStage.THEME:
                inputs = StageInputs(
                    data={"theme_mode": theme_mode},
                    files=tuple(
                        Path(value)
                        for value in manifest.stages[ProjectStage.PLAN].artifacts
                    ),
                )
                operation = (
                    preserve_project_theme
                    if theme_mode == "preserve"
                    else plan_project_theme_stage
                )
            elif stage == ProjectStage.ASSETS:
                inputs = StageInputs(
                    data={
                        "folder": f"Images/agency/{manifest.project.id}/",
                    },
                    files=(
                        Path("plans/resolved-design-document.json"),
                        Path("plans/library-plan.json"),
                    ),
                )
                operation = upload_project_asset_stage
            elif stage == ProjectStage.LIBRARY:
                inputs = StageInputs(
                    data={"registration_policy": "reconcile-no-update-v1"},
                    files=(
                        Path("build/library-plan.json"),
                        Path("build/asset-manifest.json"),
                    ),
                )
                operation = register_project_library_stage
            elif stage == ProjectStage.PAGES:
                inputs = StageInputs(
                    data={"page_mode": page_mode},
                    files=(
                        Path("build/design-document.json"),
                        Path("build/composed-blocks.json"),
                        Path("build/asset-manifest.json"),
                        Path("plans/global-block-plan.json"),
                    ),
                )
                operation = lambda context: reconcile_project_page_stage(
                    context, isolated=page_mode == "isolated"
                )
            elif stage == ProjectStage.GLOBAL_BLOCKS:
                inputs = StageInputs(
                    data={"global_policy": "unpublished-v2-with-draft-wrappers"},
                    files=(
                        Path("build/design-document.json"),
                        Path("plans/global-block-plan.json"),
                        Path("build/pages-desired.json"),
                        Path("build/page-manifest.json"),
                    ),
                )
                operation = reconcile_project_global_stage
            else:
                inputs = StageInputs(
                    data={"verification_policy": "draft-publish-gate-v1"},
                    files=(
                        Path("build/design-document.json"),
                        Path("build/global-block-manifest.json"),
                        Path("build/global-page-manifest.json"),
                        Path("build/pages-with-globals-desired.json"),
                    ),
                )
                operation = verify_project_drafts
            execution = engine.execute(
                stage,
                inputs,
                operation,
                dry_run=dry_run,
            )
            executions.append(execution.as_dict())
            if (
                dry_run
                and stage == ProjectStage.THEME
                and theme_mode == "plan"
                and execution.status == "dry_run"
                and execution.action == "execute"
            ):
                executions[-1]["preview"] = preview_project_theme_stage(
                    engine.root, load_manifest(engine.root)
                )
            if (
                dry_run
                and stage == ProjectStage.LIBRARY
                and execution.status == "dry_run"
                and execution.action == "execute"
            ):
                preview = preview_project_library_stage(
                    engine.root, load_manifest(engine.root)
                )
                executions[-1]["preview"] = preview
            if (
                dry_run
                and stage == ProjectStage.GLOBAL_BLOCKS
                and execution.status == "dry_run"
                and execution.action == "execute"
            ):
                preview = preview_project_global_stage(
                    engine.root, load_manifest(engine.root)
                )
                executions[-1]["preview"] = preview
            if (
                dry_run
                and stage == ProjectStage.PAGES
                and execution.status == "dry_run"
                and execution.action == "execute"
            ):
                preview = preview_project_page_stage(
                    engine.root,
                    load_manifest(engine.root),
                    isolated=page_mode == "isolated",
                )
                executions[-1]["preview"] = preview
            if dry_run and execution.status == "dry_run" and execution.action == "execute":
                break
    except (
        BlockLibraryError,
        ProjectPageError,
        ProjectGlobalBlockError,
        ProjectVerificationError,
        PortalIdentityError,
        ProjectStageError,
        ProjectWorkspaceError,
        ValueError,
    ) as exc:
        exit_error(str(exc), as_json)

    payload = {
        "status": "ok",
        "dry_run": dry_run,
        "through": through,
        "executions": executions,
    }
    if as_json:
        click.echo(json.dumps(payload))
        return
    if not executions:
        click.echo("No build stage could be previewed because an upstream dependency is incomplete.")
        return
    for execution in executions:
        click.echo(
            f"{execution['stage']}: {execution['status']} ({execution['action']})"
        )


def _dependencies(stage: ProjectStage) -> tuple[ProjectStage, ...]:
    if stage == ProjectStage.THEME:
        return (ProjectStage.PLAN,)
    if stage == ProjectStage.ASSETS:
        return (ProjectStage.THEME,)
    if stage == ProjectStage.LIBRARY:
        return (ProjectStage.ASSETS,)
    if stage == ProjectStage.PAGES:
        return (ProjectStage.LIBRARY,)
    if stage == ProjectStage.GLOBAL_BLOCKS:
        return (ProjectStage.PAGES,)
    if stage == ProjectStage.VERIFY:
        return (ProjectStage.GLOBAL_BLOCKS,)
    return ()


__all__ = ["build_project"]
