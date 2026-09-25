"""CLI presentation for composition-plan-derived project quality counts."""

from __future__ import annotations

import json
from pathlib import Path

import click
from pydantic import ValidationError

from vanjaro_cli.commands.helpers import exit_error, print_table
from vanjaro_cli.design.composition import deserialize_composition_plan
from vanjaro_cli.design.quality_counts import (
    QualityCount,
    QualityCountsReport,
    compute_quality_counts,
)
from vanjaro_cli.design.template_catalog import TemplateCatalogError, load_template_catalog
from vanjaro_cli.orchestration.project_capture_evidence import (
    resolve_workspace_capture_coverage,
)
from vanjaro_cli.project import ProjectWorkspaceError, load_manifest
from vanjaro_cli.release.models import (
    ProjectQualityEvidence,
    QualityCount as ReleaseQualityCount,
    QualityCounts,
)
from vanjaro_cli.reliability.artifacts import ArtifactContractError, atomic_write_json

__all__ = ["project_quality"]

_PLAN_RELATIVE_PATH = Path("plans") / "composition-plan.json"
_RELEASE_SOURCE_KINDS = ("live_html", "figma", "image")


def _release_count(count: QualityCount) -> ReleaseQualityCount:
    return ReleaseQualityCount(numerator=count.numerator, denominator=count.denominator)


def _release_counts(report: QualityCountsReport) -> QualityCounts:
    return QualityCounts(
        eligible_section_editable_coverage=_release_count(
            report.eligible_section_editable_coverage
        ),
        native_agency_component_ratio=_release_count(
            report.native_agency_component_ratio
        ),
        body_without_generic_fallback=_release_count(
            report.body_without_generic_fallback
        ),
        desktop_tablet_mobile_evidence=_release_count(
            report.desktop_tablet_mobile_evidence
        ),
    )


def _rows_payload(report: QualityCountsReport) -> list[dict[str, object]]:
    return [
        {
            "entry_id": row.entry_id,
            "template_id": row.template_id,
            "body": row.is_body,
            "editable": row.is_editable,
            "native": row.is_native,
            "generic_fallback": row.is_generic_fallback,
        }
        for row in report.rows
    ]


def _counts_payload(report: QualityCountsReport) -> dict[str, dict[str, object]]:
    metrics = (
        "eligible_section_editable_coverage",
        "native_agency_component_ratio",
        "body_without_generic_fallback",
        "desktop_tablet_mobile_evidence",
    )
    payload: dict[str, dict[str, object]] = {}
    for name in metrics:
        count: QualityCount = getattr(report, name)
        payload[name] = {
            "numerator": count.numerator,
            "denominator": count.denominator,
            "ratio": round(count.ratio, 4),
        }
    return payload


@click.command("quality")
@click.argument("directory", type=click.Path(path_type=Path), default=Path("."))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option(
    "--candidate-id",
    default=None,
    help="Release candidate ID; required together with --output.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default=None,
    help=(
        "Write a project-quality-evidence-v1 document to this path; "
        "required together with --candidate-id."
    ),
)
def project_quality(
    directory: Path,
    as_json: bool,
    candidate_id: str | None,
    output_path: Path | None,
) -> None:
    """Compute release quality ratios from the workspace's composition plan.

    These four numbers (eligible-section editable coverage, native/agency
    component ratio, body-without-generic-fallback, and desktop/tablet/mobile
    evidence) come directly from `plans/composition-plan.json` and the
    template catalog it was planned against -- never from an operator-typed
    worksheet. Use --candidate-id with --output to produce the
    project-quality-evidence-v1 document that release worksheets used to be
    filled in by hand.
    """

    if bool(candidate_id) != bool(output_path is not None):
        exit_error("--candidate-id and --output must be used together.", as_json)

    root = directory.expanduser().resolve()
    try:
        manifest = load_manifest(root)
    except ProjectWorkspaceError as exc:
        exit_error(str(exc), as_json)

    plan_path = root / _PLAN_RELATIVE_PATH
    try:
        plan_text = plan_path.read_text(encoding="utf-8")
    except OSError as exc:
        exit_error(f"cannot read {_PLAN_RELATIVE_PATH.as_posix()}: {exc}", as_json)
    try:
        plan = deserialize_composition_plan(plan_text)
    except (ValueError, ValidationError) as exc:
        exit_error(f"invalid composition plan at {_PLAN_RELATIVE_PATH.as_posix()}: {exc}", as_json)

    try:
        catalog = load_template_catalog()
    except TemplateCatalogError as exc:
        exit_error(f"cannot read the template library: {'; '.join(exc.issues)}", as_json)

    coverage = resolve_workspace_capture_coverage(root, manifest)
    report = compute_quality_counts(
        plan, catalog, coverage.capture_evidence, page_identity=coverage.page_identity
    )
    warnings = (*report.warnings, *coverage.warnings)

    written_path: Path | None = None
    if output_path is not None:
        if not manifest.sources:
            exit_error("project manifest has no declared sources.", as_json)
        source_kind = manifest.sources[0].kind.value
        if source_kind not in _RELEASE_SOURCE_KINDS:
            exit_error(
                f"first source kind {source_kind!r} is not a release source kind "
                f"({', '.join(_RELEASE_SOURCE_KINDS)}).",
                as_json,
            )
        try:
            evidence = ProjectQualityEvidence(
                candidate_id=candidate_id,
                project_id=manifest.project.id,
                source_kind=source_kind,
                quality=_release_counts(report),
            )
        except ValidationError as exc:
            exit_error(f"cannot build project quality evidence: {exc}", as_json)
        try:
            atomic_write_json(output_path, evidence)
        except ArtifactContractError as exc:
            exit_error(f"cannot write {output_path}: {exc}", as_json)
        written_path = output_path

    if as_json:
        payload = {
            "status": "ok",
            "project_id": manifest.project.id,
            "quality": _counts_payload(report),
            "rows": _rows_payload(report),
            "warnings": list(warnings),
            "output": str(written_path) if written_path else None,
        }
        click.echo(json.dumps(payload, sort_keys=True))
        return

    click.echo(f"Project quality counts for {manifest.project.id} (from the composition plan):")
    print_table(
        ["entry_id", "template_id", "body", "editable", "native", "generic_fallback"],
        _rows_payload(report),
    )
    counts = _counts_payload(report)
    for name in (
        "eligible_section_editable_coverage",
        "native_agency_component_ratio",
        "body_without_generic_fallback",
        "desktop_tablet_mobile_evidence",
    ):
        values = counts[name]
        click.echo(
            f"{name}: {values['numerator']}/{values['denominator']} ({values['ratio']:.2%})"
        )
    for warning in warnings:
        click.echo(f"warning: {warning}")
    if written_path is not None:
        click.echo(f"Wrote {written_path}")
