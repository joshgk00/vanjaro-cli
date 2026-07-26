"""Contract coverage for the agency source-adapter boundary."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from vanjaro_cli.design.figma_adapter import analyze_figma_document
from vanjaro_cli.design.html_adapter import design_document_from_html
from vanjaro_cli.design.image_evidence import ImageEvidenceSet
from vanjaro_cli.design.models import BreakpointName, SourceKind
from vanjaro_cli.design.serialization import serialize_design_document
from vanjaro_cli.design.sources import (
    DEFAULT_SOURCE_ADAPTERS,
    FigmaSourceAdapter,
    FigmaSourceRequest,
    HtmlSourceAdapter,
    HtmlSourceRequest,
    ImageSourceRequest,
    LegacyCrawlSourceRequest,
    ReferenceImage,
    SourceAdapterError,
    SourceAdapterRegistry,
    analyze_source,
)


CORPUS = Path(__file__).parent / "fixtures" / "design-benchmarks" / "cases"
CAPTURED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


def test_default_registry_exposes_implemented_adapters_in_stable_order() -> None:
    assert DEFAULT_SOURCE_ADAPTERS.supported_kinds == (
        SourceKind.FIGMA,
        SourceKind.IMAGE,
        SourceKind.LEGACY_SECTIONS,
        SourceKind.LIVE_HTML,
    )
    assert DEFAULT_SOURCE_ADAPTERS.get(SourceKind.IMAGE).request_type is ImageSourceRequest


def test_html_adapter_is_byte_equivalent_to_legacy_entry_point() -> None:
    source = (
        CORPUS / "html-bootstrap-agency" / "source.html"
    ).read_text(encoding="utf-8")
    request = HtmlSourceRequest(
        html=source,
        source_url="https://benchmark.invalid/html-bootstrap-agency",
        title="Northstar Agency",
        captured_at=CAPTURED_AT,
    )

    legacy = design_document_from_html(
        source,
        request.source_url,
        title=request.title,
        captured_at=CAPTURED_AT,
    )
    dispatched = analyze_source(request)

    assert serialize_design_document(dispatched) == serialize_design_document(legacy)


def test_figma_adapter_is_byte_equivalent_to_legacy_entry_point() -> None:
    payload = json.loads(
        (CORPUS / "figma-auto-layout-saas" / "source.json").read_text(
            encoding="utf-8"
        )
    )
    request = FigmaSourceRequest(
        payload=payload,
        file_key="figma-auto-layout-saas",
        captured_at=CAPTURED_AT,
    )

    legacy = analyze_figma_document(
        payload,
        file_key=request.file_key,
        captured_at=CAPTURED_AT,
    )
    dispatched = analyze_source(request)

    assert serialize_design_document(dispatched) == serialize_design_document(legacy)


def test_registry_rejects_duplicate_and_wrong_request_ownership() -> None:
    registry = SourceAdapterRegistry((HtmlSourceAdapter(),))
    with pytest.raises(SourceAdapterError, match="already registered"):
        registry.register(HtmlSourceAdapter())

    registry.register(FigmaSourceAdapter())
    request = FigmaSourceRequest(payload={"document": {}}, file_key="fixture")
    object.__setattr__(request, "source_kind", SourceKind.LIVE_HTML)
    with pytest.raises(SourceAdapterError, match="requires HtmlSourceRequest"):
        registry.analyze(request)


def test_image_request_contract_records_explicit_viewport_ownership() -> None:
    digest = "a" * 64
    evidence = ImageEvidenceSet.model_validate(
        {
            "schema_version": "1.0",
            "producer": {"name": "fixture", "version": "1"},
            "observations": [
                {
                    "source_sha256": digest,
                    "captured_at": CAPTURED_AT.isoformat(),
                    "page_slug": "home",
                    "breakpoint": "mobile",
                    "viewport": {"width": 390, "height": 844},
                    "image_width": 390,
                    "image_height": 844,
                    "sections": [
                        {
                            "id": "hero",
                            "order": 0,
                            "semantic_role": "hero",
                            "role_confidence": 0.8,
                            "bounds": {"x": 0, "y": 0, "width": 390, "height": 400},
                            "layout": {"kind": "stack", "contained": True},
                        }
                    ],
                }
            ],
        }
    )
    reference = ReferenceImage(
        path=Path("homepage-mobile.png"),
        page_slug="home",
        breakpoint=BreakpointName.MOBILE,
        viewport_width=390,
        viewport_height=844,
        sha256=digest,
    )
    request = ImageSourceRequest(
        images=(reference,), project_id="agency-demo", evidence=evidence
    )

    assert request.source_kind == SourceKind.IMAGE
    assert request.images[0].breakpoint == BreakpointName.MOBILE
    with pytest.raises(ValueError, match="at least one reference image"):
        ImageSourceRequest(images=(), project_id="agency-demo", evidence=evidence)


def test_legacy_request_uses_the_same_dispatch_boundary(tmp_path: Path) -> None:
    request = LegacyCrawlSourceRequest(migration_directory=tmp_path)
    assert request.source_kind == SourceKind.LEGACY_SECTIONS
