"""`collect_page_capture`: identity-checked, plan-driven, session-shared collection.

Every test drives the real `collect_page_capture` with an injected fake
`CaptureSession` and a fake `target_verifier` -- never a live browser or
portal -- then reads the persisted evidence back through the real shared
reader (`resolve_workspace_capture_coverage`) and, where relevant, the real
`evaluate_project_fidelity`. No test inspects a hand-built result in
isolation from the collector and reader that actually produce it.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import struct

from vanjaro_cli.design.capture_references import (
    CanvasInterpretation,
    StaticReference,
    StaticSourceKind,
)
from vanjaro_cli.design.capture_session import CapturedPage, CaptureSessionError, CaptureSessionErrorCode
from vanjaro_cli.design.fidelity_observation import RenderedPage, RenderedSection
from vanjaro_cli.design.models import (
    BreakpointName,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    NavigationVisibility,
    Page,
    Section,
    SourceKind,
)
from vanjaro_cli.design.visual_gate import CANONICAL_VIEWPORTS, CaptureStability
from vanjaro_cli.orchestration.portal_identity import PortalIdentityError, VerifiedPortal
from vanjaro_cli.orchestration.project_capture_collect import collect_page_capture
from vanjaro_cli.orchestration.project_capture_evidence import resolve_workspace_capture_coverage
from vanjaro_cli.orchestration.project_fidelity import evaluate_project_fidelity
from vanjaro_cli.design.quality_counts import compute_quality_counts, resolve_page_identity
from vanjaro_cli.design.composition import CompositionPlan, PlanSummary
from vanjaro_cli.project import ProjectSource, create_manifest
from vanjaro_cli.project.models import ProjectManifest
from vanjaro_cli.reliability.artifacts import atomic_write_json

TARGET_BASE_URL = "https://build.example"


def _png_bytes(width: int, height: int) -> bytes:
    ihdr = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + b"\x00\x00\x00\x00"


def _empty_plan() -> CompositionPlan:
    return CompositionPlan(
        source_document_id="capture-collect-doc",
        entries=(),
        summary=PlanSummary(
            section_count=0, blocking_count=0, native_component_ratio=0.0,
            editable_content_coverage=0.0,
        ),
    )


class _FakeSession:
    """Fake `CaptureSession`: records every call, never touches a browser."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.behaviors: dict[str, str] = {}
        self.section_ids: dict[str, str] = {}

    def set_section_id(self, url: str, section_id: str) -> None:
        self.section_ids[url] = section_id

    def fail(self, url: str) -> None:
        self.behaviors[url] = "fail"

    def target_mismatch(self, url: str) -> None:
        self.behaviors[url] = "target_mismatch"

    def empty(self, url: str) -> None:
        self.behaviors[url] = "empty"

    def capture(
        self,
        url: str,
        *,
        viewport,
        destination: Path,
        allowed_base_url: str | None = None,
        full_page: bool = True,
        require_sections: bool = True,
    ) -> CapturedPage:
        self.calls.append(
            {
                "url": url,
                "width": viewport.width,
                "height": viewport.height,
                "allowed_base_url": allowed_base_url,
                "require_sections": require_sections,
            }
        )
        behavior = self.behaviors.get(url)
        if behavior == "fail":
            raise CaptureSessionError(
                CaptureSessionErrorCode.NAVIGATION_FAILED, "navigation to the target page failed"
            )
        if behavior == "target_mismatch":
            raise CaptureSessionError(
                CaptureSessionErrorCode.TARGET_REJECTED, "url is outside the allowed base"
            )
        if behavior == "empty" and require_sections:
            raise CaptureSessionError(
                CaptureSessionErrorCode.MISSING_SECTIONS, "captured output has no agency sections"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = f"{url}|{viewport.width}x{viewport.height}".encode("utf-8")
        destination.write_bytes(payload)
        section_id = self.section_ids.get(url, "hero")
        sections = () if behavior == "empty" else (RenderedSection(section_id=section_id, order=0),)
        return CapturedPage(
            url=url,
            viewport=viewport,
            screenshot_path=destination,
            screenshot_sha256=hashlib.sha256(payload).hexdigest(),
            rendered=RenderedPage(viewport_width=float(viewport.width), sections=sections),
            stability=CaptureStability(
                lazy_load_triggered=True, fonts_settled=True, animations_disabled=True
            ),
        )


def _ok_verifier(manifest: ProjectManifest) -> tuple[None, VerifiedPortal]:
    return None, VerifiedPortal(
        profile=manifest.target.profile,
        base_url=TARGET_BASE_URL,
        portal_id=1,
        health_status="ok",
        dnn_version="9.0.2",
        vanjaro_version="1.4.0",
        user_name="tester",
    )


def _failing_verifier(manifest: ProjectManifest) -> tuple[None, VerifiedPortal]:
    raise PortalIdentityError("target URL mismatch: project expects a pinned target")


def _section(section_id: str) -> Section:
    return Section(
        id=section_id,
        order=0,
        semantic_role="feature_cards",
        role_confidence=1,
        candidate_roles=[],
        layout={"kind": "grid", "contained": True, "columns": 3},
        content=[],
        groups=[],
        style={"observations": []},
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )


def _page(
    page_id: str,
    *,
    source_reference: str,
    breakpoints: tuple[BreakpointName, ...] = (BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE),
    section_ids: tuple[str, ...] = ("hero",),
) -> Page:
    return Page(
        id=page_id,
        source_reference=source_reference,
        title=page_id.title(),
        slug=page_id,
        sections=[_section(section_id) for section_id in section_ids],
        breakpoints=list(breakpoints),
        navigation_visibility=NavigationVisibility.VISIBLE,
        provenance=[],
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
    from vanjaro_cli.design.serialization import serialize_design_document
    from vanjaro_cli.orchestration.project_capture_evidence import DESIGN_DOCUMENT_PATH

    path = root / DESIGN_DOCUMENT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_design_document(document), encoding="utf-8", newline="\n")


def _write_build_manifests(root: Path) -> None:
    atomic_write_json(root / "build/page-manifest.json", {"schema_version": "1.0", "page": {}})
    atomic_write_json(root / "build/global-page-manifest.json", {"schema_version": "1.0", "pages": []})
    atomic_write_json(
        root / "build/global-block-manifest.json", {"schema_version": "1.0", "blocks": []}
    )


def _manifest() -> ProjectManifest:
    return create_manifest(
        name="Capture Collect",
        project_id="capture-collect",
        target_profile="client-one",
        expected_base_url=TARGET_BASE_URL,
        expected_portal_id=1,
        sources=[
            ProjectSource(id="live-home", kind=SourceKind.LIVE_HTML, reference="https://agency.example/home")
        ],
        agency_pack_name="clicks-and-mortars",
        agency_pack_version="2.0.0",
        clock=lambda: datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


def _prepare(root: Path, document: DesignDocument) -> ProjectManifest:
    _write_resolved_document(root, document)
    _write_build_manifests(root)
    return _manifest()


# --- canonical live success, full pipeline ----------------------------------


def test_canonical_live_success_full_pipeline(tmp_path: Path) -> None:
    page = _page("home", source_reference="https://agency.example/home")
    document = _document((page,))
    manifest = _prepare(tmp_path, document)
    session = _FakeSession()

    result = collect_page_capture(
        tmp_path, document, manifest,
        page_id="home", built_url=f"{TARGET_BASE_URL}/home",
        capture_session=session, target_verifier=_ok_verifier,
    )

    assert result["status"] == "captured"
    assert result["missing_evidence"] == []
    assert all(entry["status"] == "captured" for entry in result["breakpoints"].values())

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage.capture_evidence["home"] == frozenset({"desktop", "tablet", "mobile"})

    counts = compute_quality_counts(
        _empty_plan(), [], coverage.capture_evidence, page_identity=resolve_page_identity(document)
    )
    assert counts.desktop_tablet_mobile_evidence.numerator == 1

    report, blockers = evaluate_project_fidelity(tmp_path, manifest)
    page_report = report["pages"]["home"]
    assert page_report["status"] == "scored"
    assert page_report["passed"] is True
    assert blockers == []

    # Both screenshot and measurement for every breakpoint came from the one
    # shared capture session -- source (require_sections=False) then output
    # (require_sections=True, restricted to the target base).
    output_calls = [call for call in session.calls if call["require_sections"] is True]
    assert len(output_calls) == 3
    assert all(call["allowed_base_url"] == TARGET_BASE_URL for call in output_calls)


# --- static source never rendered -------------------------------------------


def test_static_source_is_never_rendered(tmp_path: Path) -> None:
    page = _page(
        "home", source_reference="https://agency.example/home",
        breakpoints=(BreakpointName.DESKTOP, BreakpointName.TABLET),
    )
    document = _document((page,))
    manifest = _prepare(tmp_path, document)

    static_bytes = _png_bytes(375, 812)
    local_path = "sources/home-mobile.png"
    (tmp_path / local_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / local_path).write_bytes(static_bytes)
    mobile_reference = StaticReference(
        page_id="home", breakpoint=BreakpointName.MOBILE, source_kind=StaticSourceKind.IMAGE,
        local_path=local_path, sha256=hashlib.sha256(static_bytes).hexdigest(),
        canvas_width=375, canvas_height=812, viewport_width=375, viewport_height=812,
        interpretation=CanvasInterpretation.VIEWPORT,
    )

    session = _FakeSession()
    result = collect_page_capture(
        tmp_path, document, manifest,
        page_id="home", built_url=f"{TARGET_BASE_URL}/home",
        capture_session=session, references=(mobile_reference,), target_verifier=_ok_verifier,
    )

    assert result["breakpoints"]["mobile"]["status"] == "captured"
    assert result["breakpoints"]["mobile"]["source_kind"] == "static"

    # Exactly one call per live breakpoint's source + one output call per
    # breakpoint (desktop, tablet, mobile) = 2 + 3 = 5. The static source's
    # own local file is never passed to the capture session.
    assert len(session.calls) == 5
    assert all("home-mobile.png" not in str(call["url"]) for call in session.calls)
    assert all(local_path not in str(call["url"]) for call in session.calls)

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    mobile_result = coverage.v2_records["home"].breakpoints["mobile"]
    assert mobile_result.valid is True
    assert mobile_result.source_path is None
    assert mobile_result.is_canonical is False


# --- target mismatch: zero writes, zero captures ----------------------------


def test_target_mismatch_aborts_before_any_capture_or_write(tmp_path: Path) -> None:
    page = _page("home", source_reference="https://agency.example/home")
    document = _document((page,))
    manifest = _prepare(tmp_path, document)
    session = _FakeSession()

    result = collect_page_capture(
        tmp_path, document, manifest,
        page_id="home", built_url=f"{TARGET_BASE_URL}/home",
        capture_session=session, target_verifier=_failing_verifier,
    )

    assert result["status"] == "target_mismatch"
    assert session.calls == []
    assert not (tmp_path / "qa" / "capture-evidence").exists()
    assert not (tmp_path / "qa" / "captures").exists()


# --- one failed breakpoint ----------------------------------------------------


def test_one_failed_breakpoint_yields_partial_status(tmp_path: Path) -> None:
    page = _page("home", source_reference="https://agency.example/home")
    document = _document((page,))
    manifest = _prepare(tmp_path, document)
    session = _FakeSession()
    session.fail(f"{TARGET_BASE_URL}/home")

    result = collect_page_capture(
        tmp_path, document, manifest,
        page_id="home", built_url=f"{TARGET_BASE_URL}/home",
        capture_session=session, target_verifier=_ok_verifier,
    )

    assert result["status"] == "failed"
    assert set(result["missing_evidence"]) == {"desktop", "tablet", "mobile"}
    for entry in result["breakpoints"].values():
        assert entry["status"] == "capture_failed"


# --- empty output --------------------------------------------------------------


def test_empty_output_is_output_not_measurable(tmp_path: Path) -> None:
    page = _page(
        "home", source_reference="https://agency.example/home",
        breakpoints=(BreakpointName.DESKTOP,),
    )
    document = _document((page,))
    manifest = _prepare(tmp_path, document)
    session = _FakeSession()
    session.empty(f"{TARGET_BASE_URL}/home")

    result = collect_page_capture(
        tmp_path, document, manifest,
        page_id="home", built_url=f"{TARGET_BASE_URL}/home",
        capture_session=session, target_verifier=_ok_verifier,
    )

    assert result["breakpoints"]["desktop"]["status"] == "output_not_measurable"

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    desktop_result = coverage.v2_records["home"].breakpoints["desktop"]
    assert desktop_result.valid is False
    assert desktop_result.expected is None
    assert desktop_result.observed is None


# --- failed recapture clears old completeness --------------------------------


def test_failed_recapture_clears_old_canonical_completeness(tmp_path: Path) -> None:
    page = _page("home", source_reference="https://agency.example/home")
    document = _document((page,))
    manifest = _prepare(tmp_path, document)

    first_session = _FakeSession()
    collect_page_capture(
        tmp_path, document, manifest,
        page_id="home", built_url=f"{TARGET_BASE_URL}/home",
        capture_session=first_session, target_verifier=_ok_verifier,
    )
    coverage_before = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage_before.capture_evidence["home"] == frozenset({"desktop", "tablet", "mobile"})

    second_session = _FakeSession()
    second_session.fail(f"{TARGET_BASE_URL}/home")
    collect_page_capture(
        tmp_path, document, manifest,
        page_id="home", built_url=f"{TARGET_BASE_URL}/home",
        capture_session=second_session, target_verifier=_ok_verifier,
    )
    coverage_after = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert "home" not in coverage_after.capture_evidence


# --- two-page isolation --------------------------------------------------------


def test_two_page_isolation_via_collector(tmp_path: Path) -> None:
    home = _page("home", source_reference="https://agency.example/home")
    about = _page(
        "about", source_reference="https://agency.example/about", section_ids=("about-hero",)
    )
    document = _document((home, about))
    manifest = _prepare(tmp_path, document)

    session = _FakeSession()
    session.set_section_id(f"{TARGET_BASE_URL}/about", "about-hero")
    for page_id in ("home", "about"):
        collect_page_capture(
            tmp_path, document, manifest,
            page_id=page_id, built_url=f"{TARGET_BASE_URL}/{page_id}",
            capture_session=session, target_verifier=_ok_verifier,
        )

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert coverage.capture_evidence["home"] == frozenset({"desktop", "tablet", "mobile"})
    assert coverage.capture_evidence["about"] == frozenset({"desktop", "tablet", "mobile"})

    failing_session = _FakeSession()
    failing_session.fail(f"{TARGET_BASE_URL}/home")
    collect_page_capture(
        tmp_path, document, manifest,
        page_id="home", built_url=f"{TARGET_BASE_URL}/home",
        capture_session=failing_session, target_verifier=_ok_verifier,
    )

    coverage_after = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert "home" not in coverage_after.capture_evidence
    assert coverage_after.capture_evidence["about"] == frozenset({"desktop", "tablet", "mobile"})


# --- page not found -----------------------------------------------------------


def test_unknown_page_id_reports_page_not_found_with_no_writes(tmp_path: Path) -> None:
    page = _page("home", source_reference="https://agency.example/home")
    document = _document((page,))
    manifest = _prepare(tmp_path, document)
    session = _FakeSession()

    result = collect_page_capture(
        tmp_path, document, manifest,
        page_id="does-not-exist", built_url=f"{TARGET_BASE_URL}/home",
        capture_session=session, target_verifier=_ok_verifier,
    )

    assert result["status"] == "page_not_found"
    assert session.calls == []
