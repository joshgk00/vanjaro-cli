"""The normal HTML source adapter must carry captured responsive media evidence.

``HtmlSourceAdapter.analyze`` used to discard ``RenderedCaptureResult.media_evidence``
entirely: it forwarded ``observations``/``warnings`` to ``design_document_from_html``
but never the accessible ``@media`` declaration evidence the same capture collected,
so a rendered section's responsive style deltas could never carry a proven source
condition through the *normal* source-adapter path (the direct browser probe used
elsewhere forwarded it manually).

These tests use a scripted/fake browser-capture fixture (a plain callable standing
in for ``RenderedCapture``) rather than a real Playwright session -- no live browser
is required or exercised here. ``tests/test_source_adapters.py`` already proves this
project's convention that ``HtmlSourceAdapter`` unit tests substitute the capture
callable rather than launch a browser, and the full browser-integration path is
exercised separately once the concurrent responsive-evidence work lands.
"""

from __future__ import annotations

from datetime import UTC, datetime

from vanjaro_cli.design.html_adapter import (
    RenderedCaptureResult,
    RenderedPageObservation,
    RenderedSectionObservation,
)
from vanjaro_cli.design.html_media_evidence import MediaEvidenceResult, SectionMediaEvidence
from vanjaro_cli.design.models import (
    BreakpointName,
    BoundingBox,
    ConditionBound,
    DesignWarning,
    ResponsiveConditionKind,
    ResponsiveConditionStatus,
    StyleProperty,
    Viewport,
)
from vanjaro_cli.design.responsive_conditions import RawDeclaration
from vanjaro_cli.design.sources import html as adapter_module
from vanjaro_cli.design.sources.html import HtmlSourceAdapter, HtmlSourceRequest


CAPTURED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)

HTML = """
<html><head><title>Northstar</title></head><body><main>
  <section id="hero"><h1>Build with confidence</h1><p>We ship measured work.</p></section>
</main></body></html>
"""


def _html_request(**overrides: object) -> HtmlSourceRequest:
    defaults: dict[str, object] = {
        "html": HTML,
        "source_url": "https://northstar.test/",
        "captured_at": CAPTURED_AT,
    }
    defaults.update(overrides)
    return HtmlSourceRequest(**defaults)  # type: ignore[arg-type]


def _empty_capture(
    *, warnings: tuple[DesignWarning, ...] = (), media_evidence: MediaEvidenceResult | None = None
) -> RenderedCaptureResult:
    kwargs: dict[str, object] = {"observations": (), "warnings": warnings}
    if media_evidence is not None:
        kwargs["media_evidence"] = media_evidence
    return RenderedCaptureResult(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Spy-based wiring: proves the exact object reaches design_document_from_html
# ---------------------------------------------------------------------------


def test_render_forwards_captured_media_evidence_to_the_analyzer(monkeypatch) -> None:
    evidence = MediaEvidenceResult(by_selector={}, sheet_gaps=())
    captured = RenderedCaptureResult(observations=(), warnings=(), media_evidence=evidence)
    received: dict[str, object] = {}
    sentinel = object()

    def fake_analyze(html, url, **kwargs):
        received.update(kwargs)
        return sentinel

    monkeypatch.setattr(adapter_module, "design_document_from_html", fake_analyze)
    adapter = HtmlSourceAdapter(capture=lambda url: captured)

    result = adapter.analyze(_html_request(render=True))

    assert result is sentinel
    assert received.get("media_evidence") is evidence


def test_static_render_false_never_calls_capture_and_passes_no_media_evidence(
    monkeypatch,
) -> None:
    def refuse(url: str) -> RenderedCaptureResult:
        raise AssertionError(f"static analysis must not launch a browser for {url}")

    received: dict[str, object] = {}
    sentinel = object()

    def fake_analyze(html, url, **kwargs):
        received.update(kwargs)
        return sentinel

    monkeypatch.setattr(adapter_module, "design_document_from_html", fake_analyze)
    adapter = HtmlSourceAdapter(capture=refuse)

    result = adapter.analyze(_html_request(render=False))

    assert result is sentinel
    assert received.get("media_evidence") is None
    assert received.get("rendered_observations") == ()
    assert received.get("rendered_warnings") == ()


def test_legacy_capture_result_without_media_evidence_field_still_works(
    monkeypatch,
) -> None:
    """A pre-existing ``RenderedCaptureResult(observations, warnings)`` construction
    (no ``media_evidence`` argument at all) must keep working: the field's default
    factory supplies an empty ``MediaEvidenceResult``, and the adapter must forward
    that default rather than crash on a missing attribute."""

    captured = RenderedCaptureResult(observations=(), warnings=())
    received: dict[str, object] = {}
    sentinel = object()

    def fake_analyze(html, url, **kwargs):
        received.update(kwargs)
        return sentinel

    monkeypatch.setattr(adapter_module, "design_document_from_html", fake_analyze)
    adapter = HtmlSourceAdapter(capture=lambda url: captured)

    result = adapter.analyze(_html_request(render=True))

    assert result is sentinel
    forwarded = received.get("media_evidence")
    assert isinstance(forwarded, MediaEvidenceResult)
    assert forwarded.by_selector == {}
    assert forwarded.sheet_gaps == ()


def test_warnings_and_observations_still_forwarded_alongside_media_evidence(
    monkeypatch,
) -> None:
    """Wiring the new field must not disturb the existing forwarded evidence."""

    failure = DesignWarning(
        code="rendered_viewport_failed",
        message="Rendered mobile capture failed for https://northstar.test/: timeout",
        path="https://northstar.test/",
    )
    observation = RenderedPageObservation(
        breakpoint=BreakpointName.DESKTOP,
        viewport=Viewport(width=1440, height=900),
        html=HTML,
        sections=(
            RenderedSectionObservation(
                selector="#hero",
                bounds=BoundingBox(x=0.0, y=0.0, width=1440.0, height=520.0),
                hidden=False,
            ),
        ),
    )
    evidence = MediaEvidenceResult(by_selector={}, sheet_gaps=("https://x.test/sheet.css: blocked",))
    captured = RenderedCaptureResult(
        observations=(observation,), warnings=(failure,), media_evidence=evidence
    )
    received: dict[str, object] = {}
    sentinel = object()

    def fake_analyze(html, url, **kwargs):
        received.update(kwargs)
        return sentinel

    monkeypatch.setattr(adapter_module, "design_document_from_html", fake_analyze)
    adapter = HtmlSourceAdapter(capture=lambda url: captured)

    adapter.analyze(_html_request(render=True))

    assert received.get("media_evidence") is evidence
    assert received.get("rendered_warnings") == (failure,)
    forwarded_observations = received.get("rendered_observations")
    assert forwarded_observations is not None
    assert len(forwarded_observations) == 1
    assert forwarded_observations[0].sections[0].selector == "#hero"


def test_alternate_render_url_still_forwards_captured_media_evidence(monkeypatch) -> None:
    loaded: list[str] = []
    evidence = MediaEvidenceResult(by_selector={}, sheet_gaps=())

    def capture(url: str) -> RenderedCaptureResult:
        loaded.append(url)
        return RenderedCaptureResult(observations=(), warnings=(), media_evidence=evidence)

    received: dict[str, object] = {}
    sentinel = object()

    def fake_analyze(html, url, **kwargs):
        received.update(kwargs)
        return sentinel

    monkeypatch.setattr(adapter_module, "design_document_from_html", fake_analyze)
    adapter = HtmlSourceAdapter(capture=capture)

    adapter.analyze(
        _html_request(render=True, render_url="file:///workspace/northstar.html")
    )

    assert loaded == ["file:///workspace/northstar.html"]
    assert received.get("media_evidence") is evidence


# ---------------------------------------------------------------------------
# Real analyzer: evidence survives onto the typed responsive property condition
# ---------------------------------------------------------------------------


def _section(selector: str, *, y: float, min_height: str) -> RenderedSectionObservation:
    return RenderedSectionObservation(
        selector=selector,
        bounds=BoundingBox(x=0.0, y=y, width=1440.0, height=520.0),
        hidden=False,
        styles={"min_height": min_height},
    )


def test_real_analyzer_carries_media_evidence_onto_the_hero_property_condition() -> None:
    """Exercises the real ``HtmlSourceAdapter.analyze`` -> ``design_document_from_html``
    path (not only a spy) with a deterministic fake browser-capture fixture, and
    proves the responsive media evidence it collected survives onto the exact
    typed ``StyleObservation.condition`` it describes -- attributed to the right
    section, breakpoint and property, and nowhere else."""

    desktop = RenderedPageObservation(
        breakpoint=BreakpointName.DESKTOP,
        viewport=Viewport(width=1440, height=900),
        html=HTML,
        sections=(_section("#hero", y=0.0, min_height="720px"),),
    )
    tablet = RenderedPageObservation(
        breakpoint=BreakpointName.TABLET,
        viewport=Viewport(width=768, height=1024),
        html=HTML,
        sections=(_section("#hero", y=0.0, min_height="620px"),),
    )
    declaration = RawDeclaration(
        css_property="min-height",
        value="620px",
        important=False,
        order=5,
        specificity=(1, 0, 0),
        bounds=(("max_width", 768),),
        supported=True,
        selector="#hero",
    )
    evidence = MediaEvidenceResult(
        by_selector={"#hero": SectionMediaEvidence(selector="#hero", declarations=(declaration,))},
        sheet_gaps=(),
    )
    captured = RenderedCaptureResult(
        observations=(desktop, tablet), warnings=(), media_evidence=evidence
    )

    document = HtmlSourceAdapter(capture=lambda url: captured).analyze(
        _html_request(render=True)
    )

    section = document.pages[0].sections[0]
    assert section.provenance[0].css_selector == "#hero"

    tablet_observation = next(
        entry for entry in section.responsive if entry.breakpoint == BreakpointName.TABLET
    )
    min_height = next(
        obs for obs in tablet_observation.style.observations if obs.property == StyleProperty.MIN_HEIGHT
    )
    assert min_height.value == "620px"
    assert min_height.condition is not None
    assert min_height.condition.status == ResponsiveConditionStatus.OBSERVED
    assert min_height.condition.bounds == [
        ConditionBound(kind=ResponsiveConditionKind.MAX_WIDTH, threshold_px=768)
    ]

    # Ownership: nothing else on the document was handed a condition it never
    # earned. The desktop delta has no changed styles at all (it is the
    # baseline breakpoint), so it must carry no responsive observations.
    desktop_observation = next(
        entry for entry in section.responsive if entry.breakpoint == BreakpointName.DESKTOP
    )
    assert desktop_observation.style.observations == []
