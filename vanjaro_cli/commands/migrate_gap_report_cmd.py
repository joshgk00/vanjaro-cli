"""`vanjaro migrate gap-report` — consolidated punch list of remaining migration gaps."""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.commands.helpers import exit_error, read_json_object
from vanjaro_cli.migration.gap_report import (
    GapItem,
    GapReport,
    compute_verify_score,
    gaps_from_audit,
    gaps_from_verify,
    gaps_from_visual_report,
    merge_and_sort,
    render_markdown,
)

__all__ = ["gap_report"]


@click.command("gap-report")
@click.argument("migration_root", metavar="MIGRATION_ROOT", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--verify-json",
    "verify_json_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help=(
        "Path to a verify-all JSON output file (produced via "
        "`vanjaro migrate verify-all --output <path.json>`). "
        "Required for content gap analysis."
    ),
)
@click.option(
    "--audit-json",
    "audit_json_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help=(
        "Path to an audit-structure JSON output file (produced via "
        "`vanjaro migrate audit-structure --json <path.json>`). "
        "Required for structural gap analysis."
    ),
)
@click.option(
    "--visual-report",
    "visual_report_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help=(
        "Path to a visual discrepancy report markdown file produced by the "
        "migration-visual-report skill. Optional."
    ),
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(),
    default=None,
    help=(
        "Path for the markdown gap report output. "
        "Defaults to {MIGRATION_ROOT}/gap-report.md."
    ),
)
@click.option(
    "--json",
    "json_output_path",
    type=click.Path(),
    default=None,
    help="Also write machine-readable JSON to this path.",
)
@click.option("--as-json", "as_json", is_flag=True, help="Print JSON report to stdout.")
def gap_report(
    migration_root: str,
    verify_json_path: str | None,
    audit_json_path: str | None,
    visual_report_path: str | None,
    output_path: str | None,
    json_output_path: str | None,
    as_json: bool,
) -> None:
    """Produce a consolidated punch list of remaining migration gaps.

    Aggregates findings from up to three sources:

    \b
    1. Content fidelity  -- verify-all JSON (--verify-json)
    2. Structural lint   -- audit-structure JSON (--audit-json)
    3. Visual diff       -- visual report markdown (--visual-report)

    At least one of --verify-json or --audit-json is required. The output is a
    human-readable markdown file and an optional machine-readable JSON file.

    \b
    Example workflow:
        vanjaro migrate verify-all --inventory site-inventory.json \\
            --page-id-map page-id-map.json --output verify.json
        vanjaro migrate audit-structure --all --json audit.json
        vanjaro migrate gap-report ./migration \\
            --verify-json verify.json --audit-json audit.json \\
            --output gap-report.md
    """
    if not verify_json_path and not audit_json_path:
        exit_error(
            "At least one of --verify-json or --audit-json is required.",
            as_json,
        )

    root = Path(migration_root)
    item_lists: list[list[GapItem]] = []
    verify_score: float | None = None
    audit_score: float | None = None

    if verify_json_path:
        verify_json = read_json_object(Path(verify_json_path), "Verify JSON", as_json)
        item_lists.append(gaps_from_verify(verify_json))
        verify_score = compute_verify_score(verify_json)

    if audit_json_path:
        audit_json = read_json_object(Path(audit_json_path), "Audit JSON", as_json)
        item_lists.append(gaps_from_audit(audit_json))
        audit_score = float(audit_json.get("score", 0))

    if visual_report_path:
        try:
            report_text = Path(visual_report_path).read_text(encoding="utf-8")
        except OSError as exc:
            exit_error(f"Cannot read visual report ({visual_report_path}): {exc}", as_json)
        item_lists.append(gaps_from_visual_report(report_text))

    merged = merge_and_sort(item_lists)
    report = GapReport(items=merged)
    markdown = render_markdown(merged, verify_score=verify_score, audit_score=audit_score)

    md_path = Path(output_path) if output_path else root / "gap-report.md"
    try:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(markdown, encoding="utf-8")
    except OSError as exc:
        exit_error(f"Cannot write gap report to {md_path}: {exc}", as_json)

    if json_output_path:
        payload = {
            "total": len(merged),
            "high": report.high_count,
            "medium": report.medium_count,
            "low": report.low_count,
            "verify_score": verify_score,
            "audit_score": audit_score,
            "items": report.as_list(),
        }
        try:
            Path(json_output_path).write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            exit_error(f"Cannot write JSON output to {json_output_path}: {exc}", as_json)

    if as_json:
        summary = {
            "status": "ok",
            "output": str(md_path),
            "total": len(merged),
            "high": report.high_count,
            "medium": report.medium_count,
            "low": report.low_count,
        }
        click.echo(json.dumps(summary))
        return

    click.echo(
        f"Gap report written to {md_path} "
        f"({len(merged)} gap(s): "
        f"{report.high_count} high, "
        f"{report.medium_count} medium, "
        f"{report.low_count} low)"
    )
