"""Committed-fixture design translation benchmark command."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import click
from pydantic import ValidationError

from vanjaro_cli.design.benchmark_corpus import (
    DEFAULT_MANIFEST,
    load_benchmark_predictions,
)
from vanjaro_cli.design.figma_adapter import FigmaAdapterError
from vanjaro_cli.design.html_adapter import HtmlAdapterError
from vanjaro_cli.design.image_adapter import ImageEvidenceConversionError
from vanjaro_cli.design.metrics import (
    BenchmarkFixtureError,
    BenchmarkThresholds,
    run_offline_benchmark,
)
from vanjaro_cli.design.template_catalog import TemplateCatalogError
from vanjaro_cli.orchestration.image_acquisition import ImageAcquisitionError


def _exit(category: str, message: str, action: str, as_json: bool) -> NoReturn:
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


def _thresholds(values: tuple[str, ...]) -> BenchmarkThresholds:
    overrides: dict[str, float | None] = {}
    fields = BenchmarkThresholds.model_fields
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid threshold '{value}'; use METRIC=FLOAT")
        name, raw = (part.strip() for part in value.split("=", 1))
        if name not in fields:
            raise ValueError(f"unknown threshold metric '{name}'")
        try:
            overrides[name] = float(raw)
        except ValueError as exc:
            raise ValueError(f"threshold for '{name}' must be a number") from exc
    return BenchmarkThresholds(**overrides)


@click.command("benchmark")
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(path_type=Path),
    default=DEFAULT_MANIFEST,
    show_default=True,
)
@click.option("--output", "output_dir", type=click.Path(path_type=Path), required=True)
@click.option("--case", "case_ids", multiple=True, help="Run only this case ID (repeatable).")
@click.option("--threshold", "threshold_values", multiple=True, metavar="METRIC=FLOAT")
@click.option("--json", "as_json", is_flag=True, help="Output a machine-readable summary.")
def benchmark(
    manifest_path: Path,
    output_dir: Path,
    case_ids: tuple[str, ...],
    threshold_values: tuple[str, ...],
    as_json: bool,
) -> None:
    """Run offline HTML, Figma, or assisted-image translation quality gates."""

    try:
        thresholds = _thresholds(threshold_values)
        predictions = load_benchmark_predictions(manifest_path, case_ids)
        result = run_offline_benchmark(
            predictions,
            manifest_path=manifest_path,
            case_ids=case_ids or None,
            thresholds=thresholds,
            json_output=output_dir / "benchmark.json",
            human_output=output_dir / "benchmark.md",
        )
    except (
        BenchmarkFixtureError,
        HtmlAdapterError,
        FigmaAdapterError,
        ImageAcquisitionError,
        ImageEvidenceConversionError,
        TemplateCatalogError,
    ) as exc:
        _exit(
            "benchmark_fixture_error",
            str(exc),
            "Repair or regenerate the committed offline fixture and retry.",
            as_json,
        )
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        _exit(
            "benchmark_configuration_error",
            str(exc),
            "Check the manifest, case filters, and METRIC=FLOAT threshold values.",
            as_json,
        )

    summary = {
        "status": "ok" if result.passed else "failed",
        "passed": result.passed,
        "cases": list(result.report.case_filter),
        "json_report": str(output_dir / "benchmark.json"),
        "human_report": str(output_dir / "benchmark.md"),
        "threshold_failures": [
            failure.model_dump(mode="json") for failure in result.report.threshold_failures
        ],
        "regression_failures": [
            comparison.model_dump(mode="json")
            for comparison in result.report.regressions
            if comparison.failed
        ],
    }
    if as_json:
        click.echo(json.dumps(summary))
    else:
        click.echo(
            f"Offline benchmark {'passed' if result.passed else 'failed'}: "
            f"{len(result.report.case_filter)} case(s)."
        )
        click.echo(f"JSON: {summary['json_report']}")
        click.echo(f"Report: {summary['human_report']}")
    if result.exit_code:
        raise SystemExit(result.exit_code)
