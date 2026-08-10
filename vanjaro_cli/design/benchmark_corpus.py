"""Design documents and matches for the committed offline benchmark corpus.

The benchmark command built these for scoring and kept them to itself, so
anything else that wants to know what the corpus looks like — the capability gap
report, for one — had no way to ask. Moved here unchanged so both callers read
one corpus rather than two.

This module runs adapters and reads committed fixtures. It makes no network
calls and writes nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from vanjaro_cli.design.matcher import match_design_document
from vanjaro_cli.design.metrics import BenchmarkCasePrediction, BenchmarkFixtureError
from vanjaro_cli.design.models import BreakpointName, SourceKind, Viewport
from vanjaro_cli.design.sources import (
    FigmaSourceRequest,
    HtmlSourceRequest,
    ImageSourceRequest,
    ReferenceImage,
    analyze_source,
)
from vanjaro_cli.design.template_catalog import load_template_catalog
from vanjaro_cli.orchestration.image_acquisition import (
    acquire_reference_image,
    load_image_evidence,
    resolve_evidence_file,
    validate_evidence_identity,
)
from vanjaro_cli.project.models import ProjectSource

__all__ = [
    "CAPTURED_AT",
    "DEFAULT_MANIFEST",
    "load_benchmark_predictions",
    "read_benchmark_manifest",
]


DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "design-benchmarks"
    / "manifest.json"
)
CAPTURED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def read_benchmark_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkFixtureError(f"invalid benchmark manifest: {exc}", path) from exc
    if not isinstance(data, dict):
        raise BenchmarkFixtureError("benchmark manifest must contain an object", path)
    return data


def load_benchmark_predictions(
    manifest_path: Path, case_ids: tuple[str, ...]
) -> dict[str, BenchmarkCasePrediction]:
    manifest = read_benchmark_manifest(manifest_path)
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
                captured_at=CAPTURED_AT,
            )
        elif case["source_kind"] == "figma":
            payload = json.loads(source_path.read_text(encoding="utf-8"))
            request = FigmaSourceRequest(
                payload=payload,
                file_key=case_id,
                captured_at=CAPTURED_AT,
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
                captured_at=CAPTURED_AT,
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
