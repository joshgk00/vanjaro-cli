"""`capture-evidence-v2` per-page records: persist via the real writer, then
re-validate through the shared reader (`resolve_workspace_capture_coverage`)
and score through `evaluate_project_fidelity`, exactly as production code
does. No test constructs a validation result by hand and inspects it in
isolation without also exercising the real read path that produces it.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import struct

from vanjaro_cli.design.capture_references import CanvasInterpretation
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
from vanjaro_cli.design.quality_counts import compute_quality_counts, resolve_page_identity
from vanjaro_cli.design.serialization import serialize_design_document
from vanjaro_cli.design.composition import CompositionPlan, PlanSummary
from vanjaro_cli.design.visual_gate import (
    CANONICAL_VIEWPORTS,
    CaptureImage,
    CaptureStability,
    ViewportCapturePair,
)
from vanjaro_cli.orchestration.project_capture_evidence import (
    CAPTURE_EVIDENCE_DIRECTORY,
    DESIGN_DOCUMENT_PATH,
    _build_artifact_fingerprints,
    _record_filename,
    _target_identity_fingerprint,
    record_page_capture_evidence,
    resolve_workspace_capture_coverage,
)
from vanjaro_cli.orchestration.project_capture_v2 import (
    BreakpointCaptureAttempt,
    CaptureAttemptStatus,
    record_page_capture_v2,
)
from vanjaro_cli.orchestration.project_fidelity import evaluate_project_fidelity
from vanjaro_cli.project import ProjectSource, create_manifest
from vanjaro_cli.project.models import ProjectManifest
from vanjaro_cli.reliability.artifacts import atomic_write_json

SETTLED = {"lazy_load_triggered": True, "fonts_settled": True, "animations_disabled": True}
UNSETTLED_FONTS = {"lazy_load_triggered": True, "fonts_settled": False, "animations_disabled": True}


def _png_bytes(width: int, height: int) -> bytes:
    """Minimal real PNG bytes: signature + an IHDR chunk with real dimensions.

    `image_identity` only reads the IHDR chunk's width/height fields, so the
    CRC and IDAT are never checked -- this is exactly the "real adapter
    output" shape `plan_project_capture`'s file check expects, without a
    zlib-compressed pixel payload.
    """

    ihdr = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + b"\x00\x00\x00\x00"


def _section(section_id: str) -> Section:
    heading = ContentElement(
        id=f"{section_id}-h",
        order=1,
        kind=ContentKind.HEADING,
        role="section_title",
        value="Hello",
        style=StyleSet(
            observations=[StyleObservation(property=StyleProperty.FONT_FAMILY, value="Inter")]
        ),
        provenance=[],
        confidence=1,
    )
    return Section(
        id=section_id,
        order=0,
        semantic_role="feature_cards",
        role_confidence=1,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.GRID, contained=True, columns=3),
        content=[heading],
        groups=[],
        style=StyleSet(
            observations=[
                StyleObservation(property=StyleProperty.BACKGROUND_COLOR, value="#ffffff")
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
                viewport=BreakpointName.DESKTOP,
                bounds=BoundingBox(x=0, y=0, width=1440, height=560),
            )
        ],
    )


def _figma_provenance(
    *, file_key: str, frame_node_id: str, breakpoint: BreakpointName, width: int, height: int
) -> Provenance:
    return Provenance(
        source_kind=SourceKind.FIGMA,
        method=ObservationMethod.API,
        source_url=f"figma://{file_key}/{frame_node_id}",
        viewport=breakpoint,
        file_key=file_key,
        frame_node_id=frame_node_id,
        bounds=BoundingBox(x=0, y=0, width=width, height=height),
    )


def _page(
    page_id: str,
    *,
    section_ids: tuple[str, ...] = ("hero",),
    provenance: tuple[Provenance, ...] = (),
    breakpoints: tuple[BreakpointName, ...] = (BreakpointName.DESKTOP,),
) -> Page:
    return Page(
        id=page_id,
        source_reference="https://agency.example/",
        title=page_id.title(),
        slug=page_id,
        sections=[_section(section_id) for section_id in section_ids],
        breakpoints=list(breakpoints),
        navigation_visibility=NavigationVisibility.VISIBLE,
        provenance=list(provenance),
    )


def _document(pages: tuple[Page, ...]) -> DesignDocument:
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
        pages=list(pages),
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1.0, unsupported_traits=[]),
    )


def _write_resolved_document(root: Path, document: DesignDocument) -> None:
    path = root / DESIGN_DOCUMENT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_design_document(document), encoding="utf-8", newline="\n")


def _write_build_manifests(root: Path) -> None:
    atomic_write_json(root / "build/page-manifest.json", {"schema_version": "1.0", "page": {}})
    atomic_write_json(root / "build/global-page-manifest.json", {"schema_version": "1.0", "pages": []})
    atomic_write_json(
        root / "build/global-block-manifest.json", {"schema_version": "1.0", "blocks": []}
    )


def _manifest(*, target_profile: str = "client-one") -> ProjectManifest:
    return create_manifest(
        name="Capture Evidence v2",
        project_id="capture-evidence-v2",
        target_profile=target_profile,
        expected_base_url="https://build.example",
        expected_portal_id=1,
        sources=[
            ProjectSource(
                id="live-home", kind=SourceKind.LIVE_HTML, reference="https://agency.example/"
            )
        ],
        agency_pack_name="clicks-and-mortars",
        agency_pack_version="2.0.0",
        clock=lambda: datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


def _observation_payload(page: Page, viewport_width: float) -> dict[str, object]:
    return {
        "viewport_width": viewport_width,
        "sections": [
            {"geometry": {"section_id": section.id, "order": index}}
            for index, section in enumerate(page.sections)
        ],
    }


def _write_screenshot(root: Path, name: str, payload: bytes) -> tuple[str, str]:
    path = root / "qa/captures" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return f"qa/captures/{name}", hashlib.sha256(payload).hexdigest()


def _live_attempt(
    root: Path, page: Page, breakpoint: BreakpointName, *, width: int, height: int,
    stability: dict[str, bool] | None = None, output_stability: dict[str, bool] | None = None,
) -> BreakpointCaptureAttempt:
    source_rel, source_hash = _write_screenshot(
        root, f"{breakpoint.value}-{page.id}-source.png", f"src-{page.id}-{breakpoint.value}".encode()
    )
    output_rel, output_hash = _write_screenshot(
        root, f"{breakpoint.value}-{page.id}-output.png", f"out-{page.id}-{breakpoint.value}".encode()
    )
    return BreakpointCaptureAttempt(
        breakpoint=breakpoint,
        status=CaptureAttemptStatus.CAPTURED,
        viewport_width=width,
        viewport_height=height,
        source_kind="live",
        source_path=source_rel,
        source_sha256=source_hash,
        source_stability=dict(stability or SETTLED),
        output_path=output_rel,
        output_sha256=output_hash,
        output_stability=dict(output_stability or SETTLED),
        expected=_observation_payload(page, float(width)),
        observed=_observation_payload(page, float(width)),
    )


def _static_image_attempt(
    root: Path, page: Page, breakpoint: BreakpointName, *, width: int, height: int
) -> BreakpointCaptureAttempt:
    payload = _png_bytes(width, height)
    local_path = f"sources/{page.id}-{breakpoint.value}-image.png"
    (root / local_path).parent.mkdir(parents=True, exist_ok=True)
    (root / local_path).write_bytes(payload)
    output_rel, output_hash = _write_screenshot(
        root, f"{breakpoint.value}-{page.id}-static-output.png", f"out-{page.id}-{breakpoint.value}".encode()
    )
    return BreakpointCaptureAttempt(
        breakpoint=breakpoint,
        status=CaptureAttemptStatus.CAPTURED,
        viewport_width=width,
        viewport_height=height,
        source_kind="static",
        source_sha256=hashlib.sha256(payload).hexdigest(),
        static_source_kind="image",
        static_local_path=local_path,
        static_canvas_width=width,
        static_canvas_height=height,
        static_interpretation=CanvasInterpretation.VIEWPORT.value,
        output_path=output_rel,
        output_sha256=output_hash,
        output_stability=dict(SETTLED),
        expected=_observation_payload(page, float(width)),
        observed=_observation_payload(page, float(width)),
    )


def _static_figma_attempt(
    root: Path,
    page: Page,
    breakpoint: BreakpointName,
    *,
    width: int,
    height: int,
    file_key: str,
    frame_node_id: str,
) -> BreakpointCaptureAttempt:
    payload = _png_bytes(width, height)
    local_path = f"sources/figma/{page.id}-{breakpoint.value}.png"
    (root / local_path).parent.mkdir(parents=True, exist_ok=True)
    (root / local_path).write_bytes(payload)
    output_rel, output_hash = _write_screenshot(
        root, f"{breakpoint.value}-{page.id}-figma-output.png", f"out-{page.id}-{breakpoint.value}".encode()
    )
    return BreakpointCaptureAttempt(
        breakpoint=breakpoint,
        status=CaptureAttemptStatus.CAPTURED,
        viewport_width=width,
        viewport_height=height,
        source_kind="static",
        source_sha256=hashlib.sha256(payload).hexdigest(),
        static_source_kind="figma",
        static_local_path=local_path,
        static_canvas_width=width,
        static_canvas_height=height,
        static_interpretation=CanvasInterpretation.VIEWPORT.value,
        static_file_key=file_key,
        static_frame_node_id=frame_node_id,
        output_path=output_rel,
        output_sha256=output_hash,
        output_stability=dict(SETTLED),
        expected=_observation_payload(page, float(width)),
        observed=_observation_payload(page, float(width)),
    )


def _not_declared_attempt(breakpoint: BreakpointName) -> BreakpointCaptureAttempt:
    return BreakpointCaptureAttempt(
        breakpoint=breakpoint,
        status=CaptureAttemptStatus.REFERENCE_NOT_DECLARED,
        diagnostics=(f"{breakpoint.value}: no reference declared",),
    )


def _failed_attempt(breakpoint: BreakpointName) -> BreakpointCaptureAttempt:
    return BreakpointCaptureAttempt(
        breakpoint=breakpoint,
        status=CaptureAttemptStatus.CAPTURE_FAILED,
        diagnostics=("navigation to the target page failed",),
    )


# --- canonical live success -------------------------------------------------


def test_canonical_live_v2_scores_through_the_full_gate_and_credits_quality(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    page = document.pages[0]
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    attempts = tuple(
        _live_attempt(tmp_path, page, breakpoint, width=CANONICAL_VIEWPORTS[breakpoint].width,
                      height=CANONICAL_VIEWPORTS[breakpoint].height)
        for breakpoint in (BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE)
    )
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=attempts,
    )

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage.capture_evidence["home"] == frozenset({"desktop", "tablet", "mobile"})

    catalog_ids = resolve_page_identity(document)
    counts = compute_quality_counts(
        _empty_plan(), [], coverage.capture_evidence, page_identity=catalog_ids
    )
    assert counts.desktop_tablet_mobile_evidence.numerator == 1
    assert counts.desktop_tablet_mobile_evidence.denominator == 1

    report, blockers = evaluate_project_fidelity(tmp_path, manifest)
    page_report = report["pages"]["home"]
    assert page_report["status"] == "scored"
    assert page_report["schema_version"] == "capture-evidence-v2"
    assert page_report["release_completeness"]["canonical_complete"] is True
    assert page_report["passed"] is True
    assert blockers == []


def _empty_plan() -> CompositionPlan:
    return CompositionPlan(
        source_document_id="capture-v2-doc",
        entries=(),
        summary=PlanSummary(
            section_count=0, blocking_count=0, native_component_ratio=0.0,
            editable_content_coverage=0.0,
        ),
    )


# --- noncanonical static comparisons retained, canonical incomplete --------


def test_noncanonical_static_comparisons_retained_but_canonical_incomplete(tmp_path: Path) -> None:
    file_key, frame_node_id = "figma-file-1", "12:34"
    page = _page(
        "home",
        provenance=(
            _figma_provenance(
                file_key=file_key, frame_node_id=frame_node_id, breakpoint=BreakpointName.MOBILE,
                width=375, height=812,
            ),
        ),
        breakpoints=(BreakpointName.DESKTOP, BreakpointName.MOBILE),
    )
    document = _document((page,))
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    desktop_attempt = _static_image_attempt(tmp_path, page, BreakpointName.DESKTOP, width=1280, height=800)
    mobile_attempt = _static_figma_attempt(
        tmp_path, page, BreakpointName.MOBILE, width=375, height=812,
        file_key=file_key, frame_node_id=frame_node_id,
    )
    tablet_attempt = _not_declared_attempt(BreakpointName.TABLET)

    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=(desktop_attempt, tablet_attempt, mobile_attempt),
    )

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    v2 = coverage.v2_records["home"]
    assert v2.breakpoints["desktop"].valid is True
    assert v2.breakpoints["desktop"].is_canonical is False
    assert v2.breakpoints["desktop"].source_path is None  # never rendered
    assert v2.breakpoints["mobile"].valid is True
    assert v2.breakpoints["mobile"].is_canonical is False
    assert v2.breakpoints["mobile"].source_path is None  # never rendered
    assert v2.breakpoints["tablet"].valid is False
    # A real but noncanonical comparison never earns canonical quality credit.
    assert "home" not in coverage.capture_evidence

    report, blockers = evaluate_project_fidelity(tmp_path, manifest)
    page_report = report["pages"]["home"]
    assert page_report["status"] == "partially_scored"
    assert page_report["release_completeness"]["canonical_complete"] is False
    assert set(page_report["release_completeness"]["missing_or_noncanonical_breakpoints"]) == {
        "desktop", "tablet", "mobile",
    }
    assert any("tablet" in message for message in blockers)


# --- one failed breakpoint, two valid comparisons remain usable ------------


def test_one_failed_breakpoint_leaves_other_comparisons_usable(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    page = document.pages[0]
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    attempts = (
        _live_attempt(tmp_path, page, BreakpointName.DESKTOP, width=1440, height=900),
        _live_attempt(tmp_path, page, BreakpointName.TABLET, width=768, height=1024),
        _failed_attempt(BreakpointName.MOBILE),
    )
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=attempts,
    )

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    v2 = coverage.v2_records["home"]
    assert v2.breakpoints["desktop"].valid is True
    assert v2.breakpoints["tablet"].valid is True
    assert v2.breakpoints["mobile"].valid is False
    assert v2.breakpoints["mobile"].status == "capture_failed"
    # Two of three breakpoints are canonical and valid, but the strict
    # three-canonical-viewport credit still requires all three by name.
    assert coverage.capture_evidence["home"] == frozenset({"desktop", "tablet"})

    report, blockers = evaluate_project_fidelity(tmp_path, manifest)
    page_report = report["pages"]["home"]
    assert page_report["status"] == "partially_scored"
    assert "mobile" in page_report["release_completeness"]["missing_or_noncanonical_breakpoints"]


# --- empty output ------------------------------------------------------------


def test_output_not_measurable_status_carries_no_capture_data(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    page = document.pages[0]
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    attempts = (
        BreakpointCaptureAttempt(
            breakpoint=BreakpointName.DESKTOP, status=CaptureAttemptStatus.OUTPUT_NOT_MEASURABLE,
            diagnostics=("captured output has no agency sections",),
        ),
        _not_declared_attempt(BreakpointName.TABLET),
        _not_declared_attempt(BreakpointName.MOBILE),
    )
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=attempts,
    )
    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    v2 = coverage.v2_records["home"]
    assert v2.breakpoints["desktop"].valid is False
    assert v2.breakpoints["desktop"].status == "output_not_measurable"
    assert not v2.has_valid_comparison()


# --- live/output independently unstable rejection ---------------------------


def test_unstable_live_source_rejects_that_breakpoint(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    page = document.pages[0]
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    attempt = _live_attempt(
        tmp_path, page, BreakpointName.DESKTOP, width=1440, height=900, stability=UNSETTLED_FONTS,
    )
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=(attempt, _not_declared_attempt(BreakpointName.TABLET), _not_declared_attempt(BreakpointName.MOBILE)),
    )
    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage.v2_records["home"].breakpoints["desktop"].valid is False


def test_unstable_output_rejects_even_a_stable_valid_source(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    page = document.pages[0]
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    attempt = _live_attempt(
        tmp_path, page, BreakpointName.DESKTOP, width=1440, height=900, output_stability=UNSETTLED_FONTS,
    )
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=(attempt, _not_declared_attempt(BreakpointName.TABLET), _not_declared_attempt(BreakpointName.MOBILE)),
    )
    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage.v2_records["home"].breakpoints["desktop"].valid is False


# --- changed image hash / figma wrong frame ---------------------------------


def test_changed_static_image_bytes_after_declaration_rejected(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    page = document.pages[0]
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    attempt = _static_image_attempt(tmp_path, page, BreakpointName.DESKTOP, width=1280, height=800)
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=(attempt, _not_declared_attempt(BreakpointName.TABLET), _not_declared_attempt(BreakpointName.MOBILE)),
    )
    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage.v2_records["home"].breakpoints["desktop"].valid is True

    (tmp_path / attempt.static_local_path).write_bytes(_png_bytes(1280, 801))

    coverage_after = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage_after.v2_records["home"].breakpoints["desktop"].valid is False


def test_figma_wrong_frame_rejected(tmp_path: Path) -> None:
    file_key, frame_node_id = "figma-file-1", "12:34"
    page = _page(
        "home",
        provenance=(
            _figma_provenance(
                file_key=file_key, frame_node_id=frame_node_id, breakpoint=BreakpointName.MOBILE,
                width=375, height=812,
            ),
        ),
        breakpoints=(BreakpointName.DESKTOP, BreakpointName.MOBILE),
    )
    document = _document((page,))
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    wrong_frame_attempt = _static_figma_attempt(
        tmp_path, page, BreakpointName.MOBILE, width=375, height=812,
        file_key=file_key, frame_node_id="99:99",
    )
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=(_not_declared_attempt(BreakpointName.DESKTOP), _not_declared_attempt(BreakpointName.TABLET), wrong_frame_attempt),
    )
    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage.v2_records["home"].breakpoints["mobile"].valid is False


# --- stale build/target/design ----------------------------------------------


def test_stale_design_document_rejects_whole_record(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    page = document.pages[0]
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()
    attempts = (
        _live_attempt(tmp_path, page, BreakpointName.DESKTOP, width=1440, height=900),
        _not_declared_attempt(BreakpointName.TABLET),
        _not_declared_attempt(BreakpointName.MOBILE),
    )
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=attempts,
    )

    drifted_document = _document((_page("home", section_ids=("hero", "extra")),))
    _write_resolved_document(tmp_path, drifted_document)

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage.v2_records == {}
    assert any("stale" in warning for warning in coverage.warnings)


def test_stale_build_artifacts_reject_whole_record(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    page = document.pages[0]
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()
    attempts = (
        _live_attempt(tmp_path, page, BreakpointName.DESKTOP, width=1440, height=900),
        _not_declared_attempt(BreakpointName.TABLET),
        _not_declared_attempt(BreakpointName.MOBILE),
    )
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=attempts,
    )

    atomic_write_json(tmp_path / "build/page-manifest.json", {"schema_version": "1.0", "page": {"changed": True}})

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage.v2_records == {}


def test_stale_target_identity_rejects_whole_record(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    page = document.pages[0]
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()
    attempts = (
        _live_attempt(tmp_path, page, BreakpointName.DESKTOP, width=1440, height=900),
        _not_declared_attempt(BreakpointName.TABLET),
        _not_declared_attempt(BreakpointName.MOBILE),
    )
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=attempts,
    )

    other_manifest = _manifest(target_profile="a-different-profile")
    coverage = resolve_workspace_capture_coverage(tmp_path, other_manifest)
    assert coverage.v2_records == {}


def test_absent_manifest_binding_rejects_whole_record(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    page = document.pages[0]
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()
    attempts = (
        _live_attempt(tmp_path, page, BreakpointName.DESKTOP, width=1440, height=900),
        _not_declared_attempt(BreakpointName.TABLET),
        _not_declared_attempt(BreakpointName.MOBILE),
    )
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=attempts,
    )

    coverage = resolve_workspace_capture_coverage(tmp_path, None)
    assert coverage.v2_records == {}
    assert any("no current project manifest" in warning for warning in coverage.warnings)


# --- malformed schema / structure -------------------------------------------


def test_malformed_v2_record_missing_breakpoints_key(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    record_path = tmp_path / CAPTURE_EVIDENCE_DIRECTORY / _record_filename("home")
    payload = {
        "schema_version": "capture-evidence-v2",
        "page_id": "home",
        "built_url": "https://build.example/home",
        "design_document_sha256": hashlib.sha256(serialize_design_document(document).encode()).hexdigest(),
        "build_artifact_sha256": _build_artifact_fingerprints(tmp_path),
        "target_identity_sha256": _target_identity_fingerprint(manifest),
        "warnings": [],
    }
    atomic_write_json(record_path, payload)

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage.v2_records == {}
    assert any("no breakpoints" in warning for warning in coverage.warnings)


def test_duplicate_breakpoint_entries_rejected(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    page = document.pages[0]
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    duplicate = _live_attempt(tmp_path, page, BreakpointName.DESKTOP, width=1440, height=900)
    attempts = (duplicate, duplicate, _not_declared_attempt(BreakpointName.TABLET))
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=attempts,
    )
    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage.v2_records == {}
    assert any("duplicate" in warning for warning in coverage.warnings)


def test_missing_required_breakpoint_rejects_whole_record(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    page = document.pages[0]
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    attempts = (
        _live_attempt(tmp_path, page, BreakpointName.DESKTOP, width=1440, height=900),
        _not_declared_attempt(BreakpointName.TABLET),
    )
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=attempts,
    )
    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage.v2_records == {}
    assert any("missing required breakpoints" in warning for warning in coverage.warnings)


# --- traversal / symlink escape ---------------------------------------------


def test_static_local_path_traversal_rejected(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    page = document.pages[0]
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    attempt = _static_image_attempt(tmp_path, page, BreakpointName.DESKTOP, width=1280, height=800)
    escaping = BreakpointCaptureAttempt(
        breakpoint=attempt.breakpoint, status=attempt.status,
        viewport_width=attempt.viewport_width, viewport_height=attempt.viewport_height,
        source_kind=attempt.source_kind, source_sha256=attempt.source_sha256,
        static_source_kind=attempt.static_source_kind, static_local_path="../outside.png",
        static_canvas_width=attempt.static_canvas_width, static_canvas_height=attempt.static_canvas_height,
        static_interpretation=attempt.static_interpretation,
        output_path=attempt.output_path, output_sha256=attempt.output_sha256,
        output_stability=attempt.output_stability, expected=attempt.expected, observed=attempt.observed,
    )
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=(escaping, _not_declared_attempt(BreakpointName.TABLET), _not_declared_attempt(BreakpointName.MOBILE)),
    )
    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage.v2_records["home"].breakpoints["desktop"].valid is False


# --- v1 and v2 coexist -------------------------------------------------------


def test_v1_and_v2_records_coexist_in_the_same_directory(tmp_path: Path) -> None:
    home = _page("home")
    about = _page("about", section_ids=("about-hero",))
    document = _document((home, about))
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    v2_attempts = tuple(
        _live_attempt(tmp_path, home, breakpoint, width=CANONICAL_VIEWPORTS[breakpoint].width,
                      height=CANONICAL_VIEWPORTS[breakpoint].height)
        for breakpoint in (BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE)
    )
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=v2_attempts,
    )

    pairs = tuple(_v1_capture_pair(tmp_path, "about", breakpoint) for breakpoint in
                   (BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE))
    expected = {bp.value: _observation_payload(about, float(CANONICAL_VIEWPORTS[bp].width)) for bp in
                (BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE)}
    record_page_capture_evidence(
        tmp_path, document, page_id="about", source_url="https://agency.example/",
        built_url="https://build.example/about", expected=expected, observed=expected,
        pairs=pairs, manifest=manifest,
    )

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage.capture_evidence["home"] == frozenset({"desktop", "tablet", "mobile"})
    assert coverage.capture_evidence["about"] == frozenset({"desktop", "tablet", "mobile"})
    assert "home" in coverage.v2_records
    assert "about" in coverage.valid_records
    assert "about" not in coverage.v2_records
    assert "home" not in coverage.valid_records


def _v1_capture_pair(root: Path, page_id: str, breakpoint: BreakpointName) -> ViewportCapturePair:
    directory = root / "qa/captures"
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / f"{page_id}-{breakpoint.value}-source.png"
    output = directory / f"{page_id}-{breakpoint.value}-output.png"
    source.write_bytes(f"{page_id}-{breakpoint.value}-source".encode("utf-8"))
    output.write_bytes(f"{page_id}-{breakpoint.value}-output".encode("utf-8"))
    stability = CaptureStability(lazy_load_triggered=True, fonts_settled=True, animations_disabled=True)
    return ViewportCapturePair(
        breakpoint=breakpoint, viewport=CANONICAL_VIEWPORTS[breakpoint],
        source=CaptureImage(path=source, stability=stability),
        output=CaptureImage(path=output, stability=stability),
    )


# --- two-page isolation on recapture -----------------------------------------


def test_recapturing_one_page_preserves_the_other(tmp_path: Path) -> None:
    home = _page("home")
    about = _page("about", section_ids=("about-hero",))
    document = _document((home, about))
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    for page in (home, about):
        attempts = tuple(
            _live_attempt(tmp_path, page, breakpoint, width=CANONICAL_VIEWPORTS[breakpoint].width,
                          height=CANONICAL_VIEWPORTS[breakpoint].height)
            for breakpoint in (BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE)
        )
        record_page_capture_v2(
            tmp_path, document, manifest, page_id=page.id, built_url=f"https://build.example/{page.id}",
            attempts=attempts,
        )

    coverage_before = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage_before.capture_evidence["home"] == frozenset({"desktop", "tablet", "mobile"})
    assert coverage_before.capture_evidence["about"] == frozenset({"desktop", "tablet", "mobile"})

    # A failed recapture of "home" only.
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=(
            _failed_attempt(BreakpointName.DESKTOP),
            _not_declared_attempt(BreakpointName.TABLET),
            _not_declared_attempt(BreakpointName.MOBILE),
        ),
    )

    coverage_after = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert "home" not in coverage_after.capture_evidence
    assert coverage_after.capture_evidence["about"] == frozenset({"desktop", "tablet", "mobile"})


# --- expected width accurate -------------------------------------------------


def test_expected_width_matches_the_validated_reference_not_canonical(tmp_path: Path) -> None:
    document = _document((_page("home"),))
    page = document.pages[0]
    _write_resolved_document(tmp_path, document)
    _write_build_manifests(tmp_path)
    manifest = _manifest()

    attempt = _static_image_attempt(tmp_path, page, BreakpointName.DESKTOP, width=1280, height=800)
    assert attempt.expected["viewport_width"] == 1280.0
    record_page_capture_v2(
        tmp_path, document, manifest, page_id="home", built_url="https://build.example/home",
        attempts=(attempt, _not_declared_attempt(BreakpointName.TABLET), _not_declared_attempt(BreakpointName.MOBILE)),
    )
    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    result = coverage.v2_records["home"].breakpoints["desktop"]
    assert result.valid is True
    assert result.expected["viewport_width"] == 1280.0
