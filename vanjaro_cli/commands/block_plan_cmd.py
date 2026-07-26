"""Offline design-to-block planning and validation commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

import click
from pydantic import ValidationError

from vanjaro_cli.design.composition import (
    PlanPolicy,
    deserialize_composition_plan,
    serialize_composition_plan,
)
from vanjaro_cli.design.planner import (
    PlanningError,
    plan_design_document,
    serialize_library_plan,
    validate_composition_plan,
)
from vanjaro_cli.design.serialization import (
    DesignDocumentSerializationError,
    read_design_document,
)
from vanjaro_cli.design.template_catalog import TemplateCatalogError, load_template_catalog


def _exit_error(category: str, message: str, action: str, as_json: bool) -> NoReturn:
    if as_json:
        click.echo(
            json.dumps(
                {
                    "status": "error",
                    "error": {
                        "category": category,
                        "message": message,
                        "recommended_action": action,
                    },
                }
            )
        )
        raise SystemExit(1)
    raise click.ClickException(f"{message}\nRecommended action: {action}")


def _parse_overrides(values: tuple[str, ...], as_json: bool) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            _exit_error(
                "invalid_option",
                f"Invalid template override '{value}'.",
                "Use SECTION_ID=TEMPLATE_NAME.",
                as_json,
            )
        section_id, template = (part.strip() for part in value.split("=", 1))
        if not section_id or not template:
            _exit_error(
                "invalid_option",
                f"Invalid template override '{value}'.",
                "Provide both a section ID and template name.",
                as_json,
            )
        if section_id in parsed:
            _exit_error(
                "invalid_option",
                f"Duplicate template override for '{section_id}'.",
                "Pass at most one override for each section.",
                as_json,
            )
        parsed[section_id] = template
    return parsed


@click.command("plan")
@click.option("--design", "design_path", type=click.Path(path_type=Path), required=True)
@click.option("--output", "output_path", type=click.Path(path_type=Path), required=True)
@click.option("--library-plan", "library_path", type=click.Path(path_type=Path), default=None)
@click.option("--minimum-confidence", type=click.FloatRange(0.0, 1.0), default=0.65, show_default=True)
@click.option("--allow-simplification", is_flag=True)
@click.option("--template-override", "template_overrides", multiple=True, metavar="SECTION_ID=TEMPLATE")
@click.option("--override-author", default="cli-user", show_default=True)
@click.option("--override-reason", default="explicit template override", show_default=True)
@click.option("--explain", "explain_section", default=None, metavar="SECTION_ID")
@click.option("--dry-run", is_flag=True, help="Analyze without writing output files.")
@click.option("--json", "as_json", is_flag=True, help="Output a machine-readable result.")
def plan_blocks(
    design_path: Path,
    output_path: Path,
    library_path: Path | None,
    minimum_confidence: float,
    allow_simplification: bool,
    template_overrides: tuple[str, ...],
    override_author: str,
    override_reason: str,
    explain_section: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Map a Design Document to Composition Plan v2 and a library plan."""

    overrides = _parse_overrides(template_overrides, as_json)
    try:
        document = read_design_document(design_path)
        catalog = load_template_catalog()
        plan = plan_design_document(
            document,
            catalog=catalog,
            policy=PlanPolicy(
                minimum_confidence=minimum_confidence,
                allow_simplification=allow_simplification,
            ),
            template_overrides=overrides,
            override_author=override_author,
            override_reason=override_reason,
        )
        library_serialized = serialize_library_plan(plan)
    except DesignDocumentSerializationError as exc:
        _exit_error(
            "invalid_design_document",
            str(exc),
            "Regenerate the Design Document with `vanjaro migrate analyze` or `vanjaro figma analyze`.",
            as_json,
        )
    except TemplateCatalogError as exc:
        _exit_error(
            "invalid_template_catalog",
            str(exc),
            "Correct the reported capability metadata before planning.",
            as_json,
        )
    except (PlanningError, ValidationError, ValueError) as exc:
        _exit_error(
            "planning_failed",
            str(exc),
            "Resolve required content gaps or pass an explicit template override.",
            as_json,
        )

    explanation = None
    if explain_section:
        explained = next(
            (entry for entry in plan.entries if entry.source_section_id == explain_section), None
        )
        if explained is None:
            _exit_error(
                "unknown_section",
                f"Section '{explain_section}' is not present in the plan.",
                "Use a source_section_id from the Design Document.",
                as_json,
            )
        explanation = explained.model_dump(mode="json", exclude_none=True)

    if not dry_run:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(serialize_composition_plan(plan), encoding="utf-8")
            if library_path is not None:
                library_path.parent.mkdir(parents=True, exist_ok=True)
                library_path.write_text(library_serialized, encoding="utf-8")
        except OSError as exc:
            _exit_error(
                "write_failed",
                str(exc),
                "Choose writable output paths and retry.",
                as_json,
            )

    result = {
        "dry_run": dry_run,
        "composition_plan": str(output_path),
        "library_plan": str(library_path) if library_path else None,
        "sections": plan.summary.section_count,
        "blocking": plan.summary.blocking_count,
        "native_component_ratio": plan.summary.native_component_ratio,
        "editable_content_coverage": plan.summary.editable_content_coverage,
    }
    if explanation is not None:
        result["explanation"] = explanation
    if as_json:
        click.echo(json.dumps({"status": "ok", **result}))
    else:
        verb = "Would plan" if dry_run else "Planned"
        click.echo(
            f"{verb} {plan.summary.section_count} section(s); "
            f"{plan.summary.blocking_count} blocking."
        )
        if not dry_run:
            click.echo(f"Composition plan: {output_path}")
            if library_path:
                click.echo(f"Library plan:     {library_path}")
        if explanation is not None:
            click.echo(json.dumps(explanation, indent=2))


@click.command("plan-validate")
@click.argument("plan_path", type=click.Path(path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Output a machine-readable result.")
def plan_validate(plan_path: Path, as_json: bool) -> None:
    """Validate schemas, templates, bindings, confidence, gaps, and CSS budget."""

    try:
        plan = deserialize_composition_plan(plan_path.read_bytes())
        issues = validate_composition_plan(plan)
    except OSError as exc:
        _exit_error("read_failed", str(exc), "Pass an existing readable plan file.", as_json)
    except (ValueError, ValidationError) as exc:
        _exit_error(
            "invalid_composition_plan",
            str(exc),
            "Regenerate the plan with `vanjaro blocks plan`.",
            as_json,
        )
    except TemplateCatalogError as exc:
        _exit_error(
            "invalid_template_catalog",
            str(exc),
            "Correct the reported capability metadata before validation.",
            as_json,
        )

    if issues:
        _exit_error(
            "plan_validation_failed",
            "\n".join(issues),
            "Resolve all listed blockers, invalid bindings, placeholders, and budget violations.",
            as_json,
        )
    if as_json:
        click.echo(json.dumps({"status": "ok", "entries": len(plan.entries), "issues": []}))
    else:
        click.echo(f"Valid Composition Plan v2: {len(plan.entries)} entr{'y' if len(plan.entries) == 1 else 'ies'}.")
