"""Run the committed offline benchmark corpora together and combine the score."""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

import click
from pydantic import ValidationError

from vanjaro_cli.design.benchmark_combined import build_combined_report, render_combined_markdown
from vanjaro_cli.design.benchmark_corpus import DEFAULT_MANIFEST, load_benchmark_predictions
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
from vanjaro_cli.reliability import atomic_write_json

# The two committed corpora, in the fixed order every combined run reports
# them: HTML/Figma cases first, then the assisted-image corpus. This mirrors
# `benchmark`'s own DEFAULT_MANIFEST rather than duplicating its resolution.
DEFAULT_IMAGE_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "design-image-benchmarks"
    / "manifest.json"
)
DEFAULT_MANIFESTS = (DEFAULT_MANIFEST, DEFAULT_IMAGE_MANIFEST)


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


def _corpus_label(manifest_path: Path) -> str:
    return manifest_path.resolve().parent.name


@click.command("benchmark-all")
@click.option("--output", "output_dir", type=click.Path(path_type=Path), required=True)
@click.option(
    "--manifest",
    "manifest_paths",
    type=click.Path(path_type=Path),
    multiple=True,
    help="Corpus manifest (repeatable). Defaults to both committed corpora.",
)
@click.option("--json", "as_json", is_flag=True, help="Output a machine-readable summary.")
def benchmark_all(
    output_dir: Path,
    manifest_paths: tuple[Path, ...],
    as_json: bool,
) -> None:
    """Run every committed offline benchmark corpus and combine the score."""

    manifests = manifest_paths or DEFAULT_MANIFESTS
    thresholds = BenchmarkThresholds()

    entries: list[tuple[str, object, bool]] = []
    corpus_summaries: list[dict] = []
    for manifest_path in manifests:
        label = _corpus_label(manifest_path)
        corpus_dir = output_dir / label
        try:
            predictions = load_benchmark_predictions(manifest_path, ())
            result = run_offline_benchmark(
                predictions,
                manifest_path=manifest_path,
                case_ids=None,
                thresholds=thresholds,
                json_output=corpus_dir / "benchmark.json",
                human_output=corpus_dir / "benchmark.md",
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
                "Check the manifest paths and committed benchmark fixtures.",
                as_json,
            )

        entries.append((label, result.report, result.passed))
        corpus_summaries.append(
            {
                "corpus": label,
                "passed": result.passed,
                "cases": list(result.report.case_filter),
                "json_report": str(corpus_dir / "benchmark.json"),
                "human_report": str(corpus_dir / "benchmark.md"),
            }
        )

    combined = build_combined_report(tuple(entries))
    combined_json_path = output_dir / "combined.json"
    combined_md_path = output_dir / "combined.md"
    atomic_write_json(combined_json_path, combined)
    combined_md_path.parent.mkdir(parents=True, exist_ok=True)
    combined_md_path.write_text(render_combined_markdown(combined), encoding="utf-8")

    summary = {
        "status": "ok" if combined.passed else "failed",
        "passed": combined.passed,
        "corpora": corpus_summaries,
        "combined_json": str(combined_json_path),
        "combined_md": str(combined_md_path),
    }
    if as_json:
        click.echo(json.dumps(summary))
    else:
        click.echo(render_combined_markdown(combined))
        click.echo(f"Combined JSON: {combined_json_path}")
        click.echo(f"Combined report: {combined_md_path}")

    if not combined.passed:
        raise SystemExit(1)
