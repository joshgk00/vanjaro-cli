"""Committed-fixture design translation benchmark command."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import click
from pydantic import ValidationError

from vanjaro_cli.design.figma_adapter import FigmaAdapterError
from vanjaro_cli.design.html_adapter import HtmlAdapterError
from vanjaro_cli.design.image_adapter import ImageEvidenceConversionError
from vanjaro_cli.design.matcher import match_design_document
from vanjaro_cli.design.metrics import (
    BenchmarkCasePrediction,
    BenchmarkFixtureError,
    BenchmarkThresholds,
    run_offline_benchmark,
)
from vanjaro_cli.design.template_catalog import TemplateCatalogError, load_template_catalog
from vanjaro_cli.design.sources import (
    FigmaSourceRequest,
    HtmlSourceRequest,
    ImageSourceRequest,
    ReferenceImage,
    analyze_source,
)
from vanjaro_cli.design.models import BreakpointName, SourceKind, Viewport
from vanjaro_cli.orchestration.image_acquisition import (
    ImageAcquisitionError,
    acquire_reference_image,
    load_image_evidence,
    resolve_evidence_file,
    validate_evidence_identity,
)
from vanjaro_cli.project.models import ProjectSource


DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "design-benchmarks"
    / "manifest.json"
)
_CAPTURED_AT = datetime(2026, 1, 1, tzinfo=UTC)


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


def _read_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkFixtureError(f"invalid benchmark manifest: {exc}", path) from exc
    if not isinstance(data, dict):
        raise BenchmarkFixtureError("benchmark manifest must contain an object", path)
    return data


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


def _predictions(manifest_path: Path, case_ids: tuple[str, ...]) -> dict[str, BenchmarkCasePrediction]:
    manifest = _read_manifest(manifest_path)
    catalog = load_template_catalog()
    selected = set(case_ids)
    predictions: dict[str, BenchmarkCasePrediction] = {}
    for case in manifest.get("cases", []):
        case_id = case["id"]
        if selected and case_id not in selected:
            continue
        source_path = manifest_path.parent / case["source"]["path"]
        if case["source_kind"] == "live_html":
            request = HtmlSourceRequest(
                html=source_path.read_text(encoding="utf-8"),
                source_url=f"https://benchmark.invalid/{case_id}",
                title=case.get("title"),
                captured_at=_CAPTURED_AT,
            )
        elif case["source_kind"] == "figma":
            payload = json.loads(source_path.read_text(encoding="utf-8"))
            request = FigmaSourceRequest(
                payload=payload,
                file_key=case_id,
                captured_at=_CAPTURED_AT,
            )
        elif case["source_kind"] == "image":
            references: list[ReferenceImage] = []
            evidence = None
            for index, item in enumerate(case.get("references", []), start=1):
                source = ProjectSource(
                    id=f"{case_id}-{index}",
                    kind=SourceKind.IMAGE,
                    reference=item["path"],
                    evidence_reference=case["source"]["path"],
                    page_reference=item["page_slug"],
                    breakpoint=BreakpointName(item["breakpoint"]),
                    viewport=Viewport(width=item["width"], height=item["height"]),
                )
                acquired = acquire_reference_image(manifest_path.parent, source)
                evidence_path, _ = resolve_evidence_file(manifest_path.parent, source)
                current_evidence = load_image_evidence(evidence_path, source)
                validate_evidence_identity(current_evidence, source, acquired)
                if evidence is None:
                    evidence = current_evidence
                elif current_evidence != evidence:
                    raise BenchmarkFixtureError(
                        "image references must share one evidence sidecar", evidence_path
                    )
                references.append(
                    ReferenceImage(
                        path=acquired.relative_path,
                        page_slug=source.page_reference or "",
                        breakpoint=source.breakpoint,
                        viewport_width=source.viewport.width,
                        viewport_height=source.viewport.height,
                        sha256=acquired.sha256,
                    )
                )
            if evidence is None:
                raise BenchmarkFixtureError(
                    "image benchmark requires at least one reference", source_path
                )
            request = ImageSourceRequest(
                images=tuple(references),
                project_id=case_id,
                evidence=evidence,
                captured_at=_CAPTURED_AT,
            )
        else:
            raise BenchmarkFixtureError(
                f"unsupported benchmark source_kind {case['source_kind']}", source_path
            )
        document = analyze_source(request)
        predictions[case_id] = BenchmarkCasePrediction(
            case_id=case_id,
            document=document,
            matches=match_design_document(document, catalog),
        )
    return predictions


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
        predictions = _predictions(manifest_path, case_ids)
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
