"""Contracts for producing the fidelity evidence the gate consumes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from vanjaro_cli.design.fidelity_capture import RenderFailure
from vanjaro_cli.design.fidelity_layout import BoundingBox as LayoutBox
from vanjaro_cli.design.fidelity_observation import (
    RenderedPage,
    RenderedSection,
    RenderedText,
)
from vanjaro_cli.design.models import (
    BoundingBox,
    BreakpointName,
    ContentElement,
    ContentKind,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    LayoutKind,
    LayoutObservation,
    NavigationVisibility,
    ObservationMethod,
    Page,
    Provenance,
    Section,
    SourceKind,
    StyleObservation,
    StyleProperty,
    StyleSet,
)
from vanjaro_cli.design.serialization import serialize_design_document
from vanjaro_cli.design.visual_gate import CaptureStability
from vanjaro_cli.orchestration.project_fidelity import (
    FIDELITY_EVIDENCE_PATH,
    ProjectFidelityError,
    evaluate_project_fidelity,
)
from vanjaro_cli.orchestration.project_fidelity_recording import (
    record_project_fidelity_evidence,
)
from vanjaro_cli.project import ProjectSource, create_manifest
from vanjaro_cli.project.models import ProjectManifest
from vanjaro_cli.reliability.artifacts import atomic_write_json


def _document() -> DesignDocument:
    heading = ContentElement(
        id="h",
        order=1,
        kind=ContentKind.HEADING,
        role="section_title",
        value="Services",
        style=StyleSet(
            observations=[
                StyleObservation(property=StyleProperty.FONT_FAMILY, value="Inter"),
                StyleObservation(property=StyleProperty.FONT_SIZE, value="48px"),
                StyleObservation(property=StyleProperty.FONT_WEIGHT, value=700),
            ]
        ),
        provenance=[],
        confidence=1,
    )
    section = Section(
        id="home.s1",
        order=0,
        semantic_role="feature_cards",
        role_confidence=1,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.GRID, contained=True, columns=3),
        content=[heading],
        groups=[],
        style=StyleSet(
            observations=[
                StyleObservation(property=StyleProperty.BACKGROUND_COLOR, value="#ffffff"),
                StyleObservation(property=StyleProperty.TEXT_COLOR, value="#111111"),
                StyleObservation(property=StyleProperty.PADDING, value="64px 0"),
            ]
        ),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[
            Provenance(
                source_kind=SourceKind.LIVE_HTML,
                method=ObservationMethod.RENDERED,
                source_url="https://agency.example/",
                viewport=breakpoint,
                bounds=BoundingBox(x=0, y=0, width=width, height=560),
            )
            for breakpoint, width in (
                (BreakpointName.DESKTOP, 1440),
                (BreakpointName.TABLET, 768),
                (BreakpointName.MOBILE, 390),
            )
        ],
    )
    page = Page(
        id="home",
        source_reference="https://agency.example/",
        title="Home",
        slug="home",
        sections=[section],
        breakpoints=[BreakpointName.DESKTOP],
        navigation_visibility=NavigationVisibility.VISIBLE,
        provenance=[],
    )
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.LIVE_HTML,
            identifier="https://agency.example/",
            captured_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            adapter_version="1.0.0",
        ),
        tokens=DesignTokens(),
        assets=[],
        pages=[page],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1.0, unsupported_traits=[]),
    )


class _FakeRenderer:
    """Writes a placeholder file so capture paths point at something real."""

    def __init__(self, *, failing: set[BreakpointName] | None = None) -> None:
        self.failing = failing or set()

    def render(self, url: str, breakpoint: BreakpointName, destination: Path):
        if breakpoint in self.failing:
            raise RenderFailure(f"{breakpoint.value} timed out")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"png")
        return CaptureStability(
            lazy_load_triggered=True, fonts_settled=True, animations_disabled=True
        )


_WIDTHS = {
    BreakpointName.DESKTOP: 1440.0,
    BreakpointName.TABLET: 768.0,
    BreakpointName.MOBILE: 390.0,
}


class _FakeMeasurer:
    def __init__(self, *, failing: set[BreakpointName] | None = None, sections=None) -> None:
        self.failing = failing or set()
        self.sections = sections

    def measure(self, url: str, breakpoint: BreakpointName) -> RenderedPage:
        if breakpoint in self.failing:
            raise RuntimeError(f"{breakpoint.value} execution context destroyed")
        width = _WIDTHS[breakpoint]
        sections = self.sections
        if sections is None:
            sections = (
                RenderedSection(
                    section_id="home.s1",
                    order=0,
                    bounds=LayoutBox(x=0, y=0, width=width, height=560),
                    columns=3,
                    background_color="#ffffff",
                    text_color="#111111",
                    typography={
                        "heading": RenderedText(family="Inter", size_px=48, weight=700)
                    },
                    padding_top=64,
                    padding_bottom=64,
                    horizontal_overflow_px=0,
                    empty_slot_count=0,
                ),
            )
        return RenderedPage(
            viewport_width=width, sections=sections, console_error_count=0
        )


def _manifest() -> ProjectManifest:
    return create_manifest(
        name="Fidelity Recording",
        project_id="fidelity-recording",
        target_profile="client-one",
        sources=[
            ProjectSource(
                id="live-home",
                kind=SourceKind.LIVE_HTML,
                reference="https://agency.example/",
            )
        ],
        agency_pack_name="clicks-and-mortars",
        agency_pack_version="2.0.0",
        clock=lambda: datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


def _write_build_manifests(root: Path) -> None:
    atomic_write_json(root / "build/page-manifest.json", {"schema_version": "1.0", "page": {}})
    atomic_write_json(root / "build/global-page-manifest.json", {"schema_version": "1.0", "pages": []})
    atomic_write_json(
        root / "build/global-block-manifest.json", {"schema_version": "1.0", "blocks": []}
    )


_UNSET = object()


def _record(tmp_path: Path, **kwargs):
    """Record with a real, current local build and target binding by
    default -- exactly what the reader now requires for scored evidence.
    Pass `manifest=None` to deliberately record unbound evidence."""

    document = _document()
    resolved_path = tmp_path / "plans/resolved-design-document.json"
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(serialize_design_document(document), encoding="utf-8", newline="\n")
    _write_build_manifests(tmp_path)
    manifest = kwargs.pop("manifest", _UNSET)
    manifest = _manifest() if manifest is _UNSET else manifest
    return record_project_fidelity_evidence(
        tmp_path,
        document,
        page_id="home",
        source_url="https://agency.example/",
        built_url="https://build.example/home",
        renderer=kwargs.pop("renderer", _FakeRenderer()),
        measurer=kwargs.pop("measurer", _FakeMeasurer()),
        manifest=manifest,
        **kwargs,
    )


def test_recording_writes_evidence_the_gate_can_read(tmp_path: Path) -> None:
    payload = _record(tmp_path)

    written = json.loads((tmp_path / FIDELITY_EVIDENCE_PATH).read_text(encoding="utf-8"))
    assert set(written["expected"]) == {"desktop", "tablet", "mobile"}
    assert set(written["observed"]) == {"desktop", "tablet", "mobile"}
    assert len(written["captures"]) == 3
    assert payload == written


def test_recorded_evidence_actually_scores_instead_of_reporting_not_scored(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    _record(tmp_path, manifest=manifest)

    report, blockers = evaluate_project_fidelity(tmp_path, manifest)

    assert report["status"] == "scored"
    assert blockers == []


def test_capture_paths_are_recorded_relative_to_the_workspace(tmp_path: Path) -> None:
    payload = _record(tmp_path)

    for entry in payload["captures"]:
        assert not Path(entry["output_path"]).is_absolute()
        assert (tmp_path / entry["output_path"]).exists()


def test_a_breakpoint_that_failed_to_render_is_not_recorded(tmp_path: Path) -> None:
    payload = _record(tmp_path, renderer=_FakeRenderer(failing={BreakpointName.MOBILE}))

    assert set(payload["observed"]) == {"desktop", "tablet"}
    assert any("mobile" in warning for warning in payload["warnings"])


def test_a_breakpoint_that_failed_to_measure_records_neither_side(tmp_path: Path) -> None:
    # Half a comparison is not evidence: recording the design side alone would
    # let the gate score a build against nothing.
    payload = _record(tmp_path, measurer=_FakeMeasurer(failing={BreakpointName.TABLET}))

    assert "tablet" not in payload["observed"]
    assert "tablet" not in payload["expected"]
    assert not any(entry["breakpoint"] == "tablet" for entry in payload["captures"])
    assert any("execution context destroyed" in warning for warning in payload["warnings"])


def test_a_build_with_no_measurable_sections_is_a_warning_not_a_zero(
    tmp_path: Path,
) -> None:
    payload = _record(tmp_path, measurer=_FakeMeasurer(sections=()))

    assert payload["observed"] == {}
    assert any("no measurable sections" in warning for warning in payload["warnings"])


def test_evidence_without_any_scorable_breakpoint_leaves_the_gate_blocking(
    tmp_path: Path,
) -> None:
    _record(tmp_path, measurer=_FakeMeasurer(sections=()))

    report, blockers = evaluate_project_fidelity(tmp_path)

    assert report["status"] == "not_scored"
    assert blockers


def test_a_degraded_build_is_recorded_and_fails_the_gate(tmp_path: Path) -> None:
    degraded = (
        RenderedSection(
            section_id="home.s1",
            order=0,
            bounds=LayoutBox(x=0, y=400, width=320, height=120),
            columns=1,
            background_color="#000000",
            text_color="#777777",
            typography={"heading": RenderedText(family="Arial", size_px=12, weight=300)},
            padding_top=0,
            padding_bottom=0,
            horizontal_overflow_px=64,
            empty_slot_count=4,
            placeholder_leaks=("Lorem ipsum",),
        ),
    )
    manifest = _manifest()
    _record(tmp_path, measurer=_FakeMeasurer(sections=degraded), manifest=manifest)

    report, blockers = evaluate_project_fidelity(tmp_path, manifest)

    assert report["status"] == "scored"
    assert blockers


def test_recording_a_page_the_design_never_described_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ProjectFidelityError, match="has no page"):
        record_project_fidelity_evidence(
            tmp_path,
            _document(),
            page_id="about",
            source_url="https://agency.example/",
            built_url="https://build.example/about",
            renderer=_FakeRenderer(),
            measurer=_FakeMeasurer(),
        )
