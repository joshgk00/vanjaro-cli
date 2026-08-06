"""Contract coverage for the agency source-adapter boundary."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from vanjaro_cli.design.figma_adapter import analyze_figma_document
from vanjaro_cli.design.html_adapter import (
    RenderedCaptureResult,
    RenderedPageObservation,
    RenderedSectionObservation,
    design_document_from_html,
)
from vanjaro_cli.design.image_evidence import ImageEvidenceSet
from vanjaro_cli.design.models import (
    BoundingBox,
    BreakpointName,
    DesignWarning,
    SourceKind,
    Viewport,
)
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


RENDERABLE_HTML = """
<html><head><title>Northstar</title></head><body><main>
  <section id="hero"><h1>Build with confidence</h1><p>We ship measured work.</p>
    <a class="btn" href="/contact">Talk to us</a></section>
  <section id="story"><h2>Our story</h2><p>Founded on evidence.</p></section>
</main></body></html>
"""


MEASURED_STYLES = {
    "background_color": "#0b1f3a",
    "text_color": "#ffffff",
    "font_family": "Inter",
    "font_size": "48px",
    "font_weight": "700",
    "padding": "96px",
}


def _rendered_section(
    selector: str, *, y: float, styles: dict[str, str] | None = None
) -> RenderedSectionObservation:
    """Build one rendered section. An empty ``styles`` map means the browser
    reported nothing, which is not the same as asking for the defaults."""

    return RenderedSectionObservation(
        selector=selector,
        bounds=BoundingBox(x=0.0, y=y, width=1440.0, height=520.0),
        hidden=False,
        styles=dict(MEASURED_STYLES) if styles is None else styles,
    )


def _capture_result(
    *, warnings: tuple[DesignWarning, ...] = ()
) -> RenderedCaptureResult:
    return RenderedCaptureResult(
        observations=(
            RenderedPageObservation(
                breakpoint=BreakpointName.DESKTOP,
                viewport=Viewport(width=1440, height=900),
                html=RENDERABLE_HTML,
                sections=(
                    _rendered_section("#hero", y=0.0),
                    _rendered_section("#story", y=520.0),
                ),
            ),
        ),
        warnings=warnings,
    )


def _html_request(**overrides: object) -> HtmlSourceRequest:
    defaults: dict[str, object] = {
        "html": RENDERABLE_HTML,
        "source_url": "https://northstar.test/",
        "captured_at": CAPTURED_AT,
    }
    defaults.update(overrides)
    return HtmlSourceRequest(**defaults)  # type: ignore[arg-type]


def _section_style_values(document, section_index: int = 0) -> dict[str, tuple[str, float]]:
    section = document.pages[0].sections[section_index]
    return {
        observation.property.value: (
            observation.provenance[0].method.value,
            observation.confidence,
        )
        for observation in section.style.observations
    }


def test_static_analysis_is_the_default_and_never_renders() -> None:
    def refuse(url: str) -> RenderedCaptureResult:
        raise AssertionError(f"static analysis must not launch a browser for {url}")

    document = HtmlSourceAdapter(capture=refuse).analyze(_html_request())

    section = document.pages[0].sections[0]
    assert section.provenance[0].method.value == "static"
    assert section.provenance[0].bounds is None


def test_render_records_measured_geometry_the_static_parse_cannot() -> None:
    static_document = HtmlSourceAdapter().analyze(_html_request())
    rendered_document = HtmlSourceAdapter(
        capture=lambda url: _capture_result()
    ).analyze(_html_request(render=True))

    static_section = static_document.pages[0].sections[0]
    rendered_section = rendered_document.pages[0].sections[0]

    assert static_section.provenance[0].bounds is None
    assert rendered_section.provenance[0].method.value == "rendered"
    assert rendered_section.provenance[0].bounds is not None
    assert rendered_section.provenance[0].bounds.width == 1440.0
    assert rendered_section.provenance[0].bounds.height == 520.0


def test_render_supplies_the_style_evidence_four_dimensions_need() -> None:
    static_values = _section_style_values(
        HtmlSourceAdapter().analyze(_html_request())
    )
    rendered_values = _section_style_values(
        HtmlSourceAdapter(capture=lambda url: _capture_result()).analyze(
            _html_request(render=True)
        )
    )

    for style_property in (
        "background_color",
        "text_color",
        "font_family",
        "font_size",
        "font_weight",
        "padding",
    ):
        assert style_property not in static_values
        method, confidence = rendered_values[style_property]
        assert method == "rendered"
        assert confidence == 1.0


def test_failed_render_keeps_static_provenance_and_reports_the_failure() -> None:
    failure = DesignWarning(
        code="rendered_viewport_failed",
        message="Rendered desktop capture failed for https://northstar.test/: timeout",
        path="https://northstar.test/",
    )
    document = HtmlSourceAdapter(
        capture=lambda url: RenderedCaptureResult(observations=(), warnings=(failure,))
    ).analyze(_html_request(render=True))

    section = document.pages[0].sections[0]
    assert section.provenance[0].method.value == "static"
    assert section.provenance[0].bounds is None
    assert any(
        warning.code == "rendered_viewport_failed" for warning in document.warnings
    )


def test_a_style_the_browser_did_not_report_never_gains_rendered_confidence() -> None:
    """Rendering a page does not make its statically-parsed styles measured.

    Section provenance legitimately becomes ``rendered`` once the browser
    measured the section, so the guard that matters is the observation's own
    confidence: only a value the browser actually reported may carry 1.0.
    """

    document = HtmlSourceAdapter(
        capture=lambda url: RenderedCaptureResult(
            observations=(
                RenderedPageObservation(
                    breakpoint=BreakpointName.DESKTOP,
                    viewport=Viewport(width=1440, height=900),
                    html=RENDERABLE_HTML,
                    sections=(
                        _rendered_section("#hero", y=0.0, styles={}),
                        _rendered_section("#story", y=520.0, styles={}),
                    ),
                ),
            ),
            warnings=(),
        )
    ).analyze(_html_request(render=True))

    values = _section_style_values(document)
    assert all(confidence < 1.0 for _, confidence in values.values())
    assert "background_color" not in values


def test_rendered_analysis_is_deterministic() -> None:
    first = HtmlSourceAdapter(capture=lambda url: _capture_result()).analyze(
        _html_request(render=True)
    )
    second = HtmlSourceAdapter(capture=lambda url: _capture_result()).analyze(
        _html_request(render=True)
    )

    assert serialize_design_document(first) == serialize_design_document(second)


def test_render_url_defaults_to_the_source_url_and_is_overridable() -> None:
    assert _html_request().effective_render_url == "https://northstar.test/"
    assert (
        _html_request(render_url="file:///workspace/northstar.html").effective_render_url
        == "file:///workspace/northstar.html"
    )
    with pytest.raises(ValueError, match="render_url must not be empty"):
        _html_request(render_url="   ")


def test_render_loads_the_render_url_not_the_recorded_source_url() -> None:
    loaded: list[str] = []

    def capture(url: str) -> RenderedCaptureResult:
        loaded.append(url)
        return _capture_result()

    HtmlSourceAdapter(capture=capture).analyze(
        _html_request(render=True, render_url="file:///workspace/northstar.html")
    )

    assert loaded == ["file:///workspace/northstar.html"]
