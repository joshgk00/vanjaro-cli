"""VF-007 — fidelity gate wired into project verification."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from vanjaro_cli.design.fidelity import CURRENT_REGIME_VERSION
from vanjaro_cli.design.fidelity_capture import RenderFailure
from vanjaro_cli.design.fidelity_evaluation import (
    PageObservation,
    SectionObservation,
    score_breakpoint_fidelity,
    score_hook_from_observations,
)
from vanjaro_cli.design.fidelity_color import ColorRole, SectionPalette
from vanjaro_cli.design.fidelity_layout import BoundingBox as LayoutBox, SectionGeometry
from vanjaro_cli.design.fidelity_media import IntegrityObservation
from vanjaro_cli.design.fidelity_observation import RenderedPage, RenderedSection, RenderedText
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
from vanjaro_cli.orchestration.project_fidelity_recording import record_project_fidelity_evidence
from vanjaro_cli.orchestration.project_capture_v2 import (
    BreakpointCaptureAttempt,
    CaptureAttemptStatus,
    record_page_capture_v2,
)
from vanjaro_cli.design.visual_gate import CANONICAL_VIEWPORTS
from vanjaro_cli.project import ProjectSource, create_manifest
from vanjaro_cli.project.models import ProjectManifest
from vanjaro_cli.reliability.artifacts import atomic_write_json

BREAKPOINTS = ("desktop", "tablet", "mobile")


def _section(
    section_id: str = "hero",
    *,
    y: float = 0,
    background: str = "#ffffff",
    leaks: tuple[str, ...] = (),
    with_integrity: bool = False,
) -> SectionObservation:
    integrity = None
    if with_integrity:
        integrity = IntegrityObservation(
            horizontal_overflow_px=0,
            empty_slot_count=0,
            console_error_count=0,
            placeholder_leaks=leaks,
        )
    return SectionObservation(
        geometry=SectionGeometry(
            section_id=section_id,
            order=0,
            bounds=BoundingBox(x=0, y=y, width=1440, height=600),
            columns=3,
        ),
        palette=SectionPalette(colors={ColorRole.BACKGROUND: background}),
        integrity=integrity,
    )


def _page(**kwargs: Any) -> PageObservation:
    return PageObservation(viewport_width=1440, sections=(_section(**kwargs),))


def _write_evidence(
    root: Path,
    *,
    expected: dict[str, Any] | None = None,
    observed: dict[str, Any] | None = None,
    captures: list[dict[str, Any]] | None = None,
    settled: bool = True,
) -> None:
    (root / "qa").mkdir(parents=True, exist_ok=True)
    if captures is None:
        captures = []
        for name in BREAKPOINTS:
            source = f"qa/{name}-source.png"
            output = f"qa/{name}-output.png"
            (root / source).write_bytes(b"png")
            (root / output).write_bytes(b"png")
            captures.append(
                {
                    "breakpoint": name,
                    "source_path": source,
                    "output_path": output,
                    "lazy_load_triggered": settled,
                    "fonts_settled": settled,
                    "animations_disabled": settled,
                }
            )
    payload = {
        "expected": expected if expected is not None else {},
        "observed": observed if observed is not None else {},
        "captures": captures,
    }
    (root / FIDELITY_EVIDENCE_PATH).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _all_breakpoints(page: PageObservation) -> dict[str, Any]:
    return {name: page.model_dump(mode="json") for name in BREAKPOINTS}


class TestPassingBuild:
    def test_matching_build_passes_the_draft_gate(self, tmp_path: Path) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(page),
            observed=_all_breakpoints(page),
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["status"] == "scored"
        assert report["passed"] is True
        assert report["overall_score"] == 100.0
        assert blockers == []

    def test_report_carries_per_section_and_per_viewport_detail(
        self, tmp_path: Path
    ) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(page),
            observed=_all_breakpoints(page),
        )

        report, _ = evaluate_project_fidelity(tmp_path)

        assert {entry["breakpoint"] for entry in report["viewport_scores"]} == set(
            BREAKPOINTS
        )
        assert [entry["section_id"] for entry in report["section_scores"]] == ["hero"]

    def test_report_is_json_serializable(self, tmp_path: Path) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(page),
            observed=_all_breakpoints(page),
        )

        report, _ = evaluate_project_fidelity(tmp_path)

        assert json.loads(json.dumps(report))["status"] == "scored"


class TestDegradedBuild:
    def test_shifted_and_recoloured_build_fails_the_gate(self, tmp_path: Path) -> None:
        expected = _page(with_integrity=True)
        degraded = _page(y=900, background="#101010", with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(expected),
            observed=_all_breakpoints(degraded),
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["passed"] is False
        assert report["overall_score"] < 75
        assert any("visual fidelity gate failed" in blocker for blocker in blockers)

    def test_placeholder_leak_fails_an_otherwise_perfect_build(
        self, tmp_path: Path
    ) -> None:
        expected = _page(with_integrity=True)
        leaked = _page(with_integrity=True, leaks=("Lorem ipsum",))
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(expected),
            observed=_all_breakpoints(leaked),
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["overall_score"] == 0.0
        assert report["passed"] is False
        assert blockers

    def test_missing_section_fails_the_gate(self, tmp_path: Path) -> None:
        expected = PageObservation(
            viewport_width=1440,
            sections=(_section("hero"), _section("cta")),
        )
        built = _page()
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(expected),
            observed=_all_breakpoints(built),
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["passed"] is False
        assert blockers


class TestMissingEvidence:
    def test_absent_evidence_file_is_a_blocker_not_a_pass(self, tmp_path: Path) -> None:
        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["status"] == "not_scored"
        assert blockers == [
            f"visual fidelity was not scored: no evidence recorded at {FIDELITY_EVIDENCE_PATH}"
        ]

    def test_evidence_without_observations_is_a_blocker(self, tmp_path: Path) -> None:
        _write_evidence(tmp_path)

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["status"] == "not_scored"
        assert blockers

    def test_evidence_without_captures_is_a_blocker(self, tmp_path: Path) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(page),
            observed=_all_breakpoints(page),
            captures=[],
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["status"] == "not_scored"
        assert "no settled captures" in report["reason"]
        assert blockers

    def test_unsettled_captures_are_rejected(self, tmp_path: Path) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(page),
            observed=_all_breakpoints(page),
            settled=False,
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["status"] == "not_scored"
        assert blockers

    def test_incomplete_breakpoints_are_rejected(self, tmp_path: Path) -> None:
        page = _page(with_integrity=True)
        only_desktop = {"desktop": page.model_dump(mode="json")}
        (tmp_path / "qa").mkdir(parents=True, exist_ok=True)
        (tmp_path / "qa/desktop-source.png").write_bytes(b"png")
        (tmp_path / "qa/desktop-output.png").write_bytes(b"png")
        _write_evidence(
            tmp_path,
            expected=only_desktop,
            observed=only_desktop,
            captures=[
                {
                    "breakpoint": "desktop",
                    "source_path": "qa/desktop-source.png",
                    "output_path": "qa/desktop-output.png",
                    "lazy_load_triggered": True,
                    "fonts_settled": True,
                    "animations_disabled": True,
                }
            ],
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["status"] == "not_scored"
        assert blockers


class TestMalformedEvidence:
    def test_unknown_breakpoint_is_rejected(self, tmp_path: Path) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected={"widescreen": page.model_dump(mode="json")},
            observed={"widescreen": page.model_dump(mode="json")},
        )

        with pytest.raises(ProjectFidelityError, match="unknown breakpoint"):
            evaluate_project_fidelity(tmp_path)

    def test_invalid_json_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "qa").mkdir(parents=True, exist_ok=True)
        (tmp_path / FIDELITY_EVIDENCE_PATH).write_text("{not json", encoding="utf-8")

        with pytest.raises(ProjectFidelityError, match="could not be read"):
            evaluate_project_fidelity(tmp_path)

    def test_invalid_observation_shape_is_rejected(self, tmp_path: Path) -> None:
        _write_evidence(
            tmp_path,
            expected={"desktop": {"viewport_width": -5, "sections": []}},
            observed={"desktop": {"viewport_width": 1440, "sections": []}},
        )

        with pytest.raises(ProjectFidelityError, match="are invalid"):
            evaluate_project_fidelity(tmp_path)


class TestEvaluationLayer:
    def test_section_absent_from_build_fails_every_dimension(self) -> None:
        expected = PageObservation(
            viewport_width=1440, sections=(_section("hero"), _section("cta"))
        )
        built = _page()

        scores = score_breakpoint_fidelity(
            expected, built, breakpoint=BreakpointName.DESKTOP
        )
        missing = next(s for s in scores.sections if s.section_id == "cta")

        assert missing.score == 0.0
        assert all(entry.score == 0.0 for entry in missing.dimensions)

    def test_scores_carry_the_current_regime(self) -> None:
        page = _page()

        scores = score_breakpoint_fidelity(
            page, page, breakpoint=BreakpointName.DESKTOP
        )

        assert scores.regime_version == CURRENT_REGIME_VERSION

    def test_hook_raises_for_an_unmeasured_breakpoint(self) -> None:
        page = _page()
        hook = score_hook_from_observations(
            {BreakpointName.DESKTOP: page}, {BreakpointName.DESKTOP: page}
        )

        class _Capture:
            breakpoint = BreakpointName.MOBILE

        with pytest.raises(ValueError, match="unmeasured breakpoint"):
            hook(_Capture())

    def test_duplicate_section_ids_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            PageObservation(
                viewport_width=1440, sections=(_section("hero"), _section("hero"))
            )


class TestDeterminism:
    def test_repeated_evaluation_is_identical(self, tmp_path: Path) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(page),
            observed=_all_breakpoints(page),
        )

        first, first_blockers = evaluate_project_fidelity(tmp_path)
        second, second_blockers = evaluate_project_fidelity(tmp_path)

        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
        assert first_blockers == second_blockers


# ---------------------------------------------------------------------------
# Multi-page workspace aggregation (per-page evidence under qa/capture-evidence/).


def _multi_page_document(*page_ids: str) -> DesignDocument:
    def _section(page_id: str) -> Section:
        heading = ContentElement(
            id=f"{page_id}-h",
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
        return Section(
            id=f"{page_id}.s1",
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

    pages = [
        Page(
            id=page_id,
            source_reference="https://agency.example/",
            title=page_id.title(),
            slug=page_id,
            sections=[_section(page_id)],
            breakpoints=[BreakpointName.DESKTOP],
            navigation_visibility=NavigationVisibility.VISIBLE,
            provenance=[],
        )
        for page_id in page_ids
    ]
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
        pages=pages,
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1.0, unsupported_traits=[]),
    )


class _MultiPageRenderer:
    def render(self, url: str, breakpoint: BreakpointName, destination: Path):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"png")
        return CaptureStability(
            lazy_load_triggered=True, fonts_settled=True, animations_disabled=True
        )


class _MultiPageMeasurer:
    _widths = {
        BreakpointName.DESKTOP: 1440.0,
        BreakpointName.TABLET: 768.0,
        BreakpointName.MOBILE: 390.0,
    }

    def __init__(self, page_id: str) -> None:
        self.page_id = page_id

    def measure(self, url: str, breakpoint: BreakpointName) -> RenderedPage:
        width = self._widths[breakpoint]
        return RenderedPage(
            viewport_width=width,
            sections=(
                RenderedSection(
                    section_id=f"{self.page_id}.s1",
                    order=0,
                    bounds=LayoutBox(x=0, y=0, width=width, height=560),
                    columns=3,
                    background_color="#ffffff",
                    text_color="#111111",
                    typography={"heading": RenderedText(family="Inter", size_px=48, weight=700)},
                    padding_top=64,
                    padding_bottom=64,
                    horizontal_overflow_px=0,
                    empty_slot_count=0,
                ),
            ),
            console_error_count=0,
        )


def _write_resolved_document(root: Path, document: DesignDocument) -> None:
    path = root / "plans/resolved-design-document.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_design_document(document), encoding="utf-8", newline="\n")


def _manifest() -> ProjectManifest:
    return create_manifest(
        name="Multi Page Fidelity",
        project_id="multi-page-fidelity",
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


def _record_multi_page(
    root: Path, document: DesignDocument, page_id: str, *, manifest: ProjectManifest | None
) -> None:
    _write_build_manifests(root)
    record_project_fidelity_evidence(
        root,
        document,
        page_id=page_id,
        source_url=f"https://agency.example/{page_id}",
        built_url=f"https://build.example/{page_id}",
        renderer=_MultiPageRenderer(),
        measurer=_MultiPageMeasurer(page_id),
        manifest=manifest,
    )


class TestWorkspaceMultiPage:
    def test_a_page_with_no_recorded_evidence_is_a_blocker_not_a_silent_pass(
        self, tmp_path: Path
    ) -> None:
        manifest = _manifest()
        document = _multi_page_document("home", "about")
        _write_resolved_document(tmp_path, document)
        _record_multi_page(tmp_path, document, "home", manifest=manifest)
        # "about" is a real current design page but was never captured.

        report, blockers = evaluate_project_fidelity(tmp_path, manifest)

        assert report["status"] == "partially_scored"
        assert report["pages"]["home"]["status"] == "scored"
        assert report["pages"]["about"]["status"] == "not_scored"
        assert any("about" in blocker for blocker in blockers)

    def test_a_stale_page_is_a_blocker_even_though_it_was_once_captured(
        self, tmp_path: Path
    ) -> None:
        manifest = _manifest()
        document = _multi_page_document("home", "about")
        _write_resolved_document(tmp_path, document)
        _record_multi_page(tmp_path, document, "home", manifest=manifest)
        _record_multi_page(tmp_path, document, "about", manifest=manifest)

        first, _ = evaluate_project_fidelity(tmp_path, manifest)
        assert first["status"] == "scored"

        changed = _multi_page_document("home", "about", "contact")
        _write_resolved_document(tmp_path, changed)

        report, blockers = evaluate_project_fidelity(tmp_path, manifest)

        assert report["status"] != "scored"
        assert report["pages"]["home"]["status"] == "not_scored"
        assert report["pages"]["about"]["status"] == "not_scored"
        assert any("home" in blocker for blocker in blockers)
        assert any("about" in blocker for blocker in blockers)

    def test_multi_page_workspace_scores_when_every_current_page_is_current(
        self, tmp_path: Path
    ) -> None:
        manifest = _manifest()
        document = _multi_page_document("home", "about")
        _write_resolved_document(tmp_path, document)
        _record_multi_page(tmp_path, document, "home", manifest=manifest)
        _record_multi_page(tmp_path, document, "about", manifest=manifest)

        report, blockers = evaluate_project_fidelity(tmp_path, manifest)

        assert report["status"] == "scored"
        assert report["legacy"] is False
        assert blockers == []


# ---------------------------------------------------------------------------
# Source-aware `capture-evidence-v2` consumption, alongside legacy v1 pages.


def _v2_observation(page_id: str, width: float) -> dict[str, object]:
    return {
        "viewport_width": width,
        "sections": [{"geometry": {"section_id": f"{page_id}.s1", "order": 0}}],
    }


def _v2_canonical_attempt(root: Path, page_id: str, breakpoint: BreakpointName) -> BreakpointCaptureAttempt:
    directory = root / "qa/captures"
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / f"v2-{page_id}-{breakpoint.value}-source.png"
    output = directory / f"v2-{page_id}-{breakpoint.value}-output.png"
    source.write_bytes(f"{page_id}-{breakpoint.value}-source".encode("utf-8"))
    output.write_bytes(f"{page_id}-{breakpoint.value}-output".encode("utf-8"))
    settled = {"lazy_load_triggered": True, "fonts_settled": True, "animations_disabled": True}
    width = float(CANONICAL_VIEWPORTS[breakpoint].width)
    return BreakpointCaptureAttempt(
        breakpoint=breakpoint,
        status=CaptureAttemptStatus.CAPTURED,
        viewport_width=CANONICAL_VIEWPORTS[breakpoint].width,
        viewport_height=CANONICAL_VIEWPORTS[breakpoint].height,
        source_kind="live",
        source_path=source.relative_to(root).as_posix(),
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        source_stability=dict(settled),
        output_path=output.relative_to(root).as_posix(),
        output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        output_stability=dict(settled),
        expected=_v2_observation(page_id, width),
        observed=_v2_observation(page_id, width),
    )


def _not_declared(breakpoint: BreakpointName) -> BreakpointCaptureAttempt:
    return BreakpointCaptureAttempt(
        breakpoint=breakpoint, status=CaptureAttemptStatus.REFERENCE_NOT_DECLARED,
        diagnostics=(f"{breakpoint.value}: no reference declared",),
    )


class TestWorkspaceSourceAwareV2:
    def test_v2_page_with_no_valid_comparisons_is_not_scored(self, tmp_path: Path) -> None:
        manifest = _manifest()
        document = _multi_page_document("home")
        _write_resolved_document(tmp_path, document)
        _write_build_manifests(tmp_path)

        record_page_capture_v2(
            tmp_path, document, manifest,
            page_id="home", built_url="https://build.example/home",
            attempts=(
                _not_declared(BreakpointName.DESKTOP),
                _not_declared(BreakpointName.TABLET),
                _not_declared(BreakpointName.MOBILE),
            ),
        )

        report, blockers = evaluate_project_fidelity(tmp_path, manifest)
        page_report = report["pages"]["home"]
        assert page_report["status"] == "not_scored"
        assert page_report["schema_version"] == "capture-evidence-v2"
        assert page_report["release_completeness"]["canonical_complete"] is False
        assert blockers

    def test_v1_and_v2_pages_coexist_in_one_workspace_report(self, tmp_path: Path) -> None:
        manifest = _manifest()
        document = _multi_page_document("home", "about")
        _write_resolved_document(tmp_path, document)
        _record_multi_page(tmp_path, document, "home", manifest=manifest)

        _write_build_manifests(tmp_path)
        attempts = tuple(
            _v2_canonical_attempt(tmp_path, "about", breakpoint)
            for breakpoint in (BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE)
        )
        record_page_capture_v2(
            tmp_path, document, manifest,
            page_id="about", built_url="https://build.example/about",
            attempts=attempts,
        )

        report, blockers = evaluate_project_fidelity(tmp_path, manifest)

        assert report["pages"]["home"]["status"] == "scored"
        assert report["pages"]["home"].get("schema_version") != "capture-evidence-v2"
        assert report["pages"]["about"]["status"] == "scored"
        assert report["pages"]["about"]["schema_version"] == "capture-evidence-v2"
        assert report["pages"]["about"]["release_completeness"]["canonical_complete"] is True
        assert report["status"] == "scored"
        assert blockers == []
