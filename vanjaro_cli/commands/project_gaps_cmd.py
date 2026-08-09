"""vanjaro project capability-gaps — rank the template fields that drop content."""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.commands.helpers import exit_error
from vanjaro_cli.design.capability_gaps import (
    CapabilityGapReport,
    PlannedProject,
    build_capability_gap_report,
)
from vanjaro_cli.design.composition import deserialize_composition_plan
from vanjaro_cli.design.template_catalog import TemplateCatalogError, load_template_catalog

__all__ = ["capability_gaps", "collect_planned_projects"]

_PLAN_RELATIVE_PATH = Path("plans") / "composition-plan.json"


def collect_planned_projects(root: Path) -> list[PlannedProject]:
    """Read every planned project under a workspace root, in a stable order.

    A project without a plan is skipped rather than reported as an error: a
    workspace mid-run is the normal state, and refusing to report until every
    project has planned would make the report unusable exactly when it is most
    wanted.
    """

    projects: list[PlannedProject] = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        plan_path = directory / _PLAN_RELATIVE_PATH
        if not plan_path.is_file():
            continue
        plan = deserialize_composition_plan(plan_path.read_text(encoding="utf-8"))
        projects.append(PlannedProject(project_id=directory.name, plan=plan))
    return projects


def _report_payload(report: CapabilityGapReport) -> dict:
    return {
        "schema_version": report.schema_version,
        "projects": list(report.projects),
        "section_count": report.section_count,
        "dropped_field_count": report.dropped_field_count,
        "gaps": [
            {
                **gap.model_dump(mode="json", exclude_none=True),
                "dropped_field_count": gap.dropped_field_count,
            }
            for gap in report.gaps
        ],
        "stale": [
            {
                **stale.gap.model_dump(mode="json", exclude_none=True),
                "dropped_field_count": stale.gap.dropped_field_count,
                "stale_reason": stale.reason,
            }
            for stale in report.stale
        ],
        "held_back": [loss.model_dump(mode="json") for loss in report.held_back],
    }


def _describe(gap_kind: str, demanded: int | None, owned: int | None) -> str:
    if gap_kind == "insufficient_capacity":
        return f"owns {owned}, needs {demanded}"
    if gap_kind == "static_only":
        return "declared but static"
    return "no field"


@click.command("capability-gaps")
@click.argument(
    "root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("artifacts") / "projects",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option(
    "--held-back",
    is_flag=True,
    help="Also list losses that are not capability gaps, with the reason each was held back.",
)
def capability_gaps(root: Path, as_json: bool, held_back: bool) -> None:
    """Rank the template fields that dropped visitor content, worst first."""

    if not root.is_dir():
        exit_error(f"project root not found: {root}", as_json)
    try:
        projects = collect_planned_projects(root)
    except (OSError, ValueError) as exc:
        exit_error(f"cannot read composition plans under {root}: {exc}", as_json)
    try:
        catalog = {entry.template_id: entry.capabilities for entry in load_template_catalog()}
    except TemplateCatalogError as exc:
        exit_error(f"cannot read the template library: {'; '.join(exc.issues)}", as_json)

    report = build_capability_gap_report(projects, catalog=catalog)

    if as_json:
        click.echo(json.dumps({"status": "ok", **_report_payload(report)}, sort_keys=True))
        return

    click.echo(
        f"Scanned {len(report.projects)} planned project(s), "
        f"{report.section_count} section(s): {', '.join(report.projects) or 'none'}"
    )
    if not report.gaps:
        click.echo("No template capability gaps: every section's content reached a field.")
    else:
        click.echo(f"{len(report.gaps)} capability gap(s), {report.dropped_field_count} dropped field(s):")
        for rank, gap in enumerate(report.gaps, start=1):
            click.echo(
                f"  {rank}. {gap.template_id} · {gap.field} "
                f"({_describe(gap.kind, gap.demanded_slots, gap.owned_slots)}) — "
                f"{gap.dropped_field_count} section(s) across {', '.join(gap.projects)}"
            )
            for section in gap.sections:
                click.echo(f"       {section}")
    if report.stale:
        click.echo(f"{len(report.stale)} gap(s) the library has since closed:")
        for stale in report.stale:
            click.echo(
                f"  {stale.gap.template_id} · {stale.gap.field} "
                f"({stale.gap.dropped_field_count} section(s)) — {stale.reason}"
            )
    if held_back:
        click.echo(f"{len(report.held_back)} loss(es) held back as not capability gaps:")
        for loss in report.held_back:
            click.echo(f"  {loss.project_id} · {loss.section_id} · {loss.template_id}")
            click.echo(f"       {loss.warning}")
            click.echo(f"       held back: {loss.reason}")
