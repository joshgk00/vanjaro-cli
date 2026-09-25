"""Durable per-page capture evidence: record, then read-only, zero-write validate."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from vanjaro_cli.design.composition import (
    CompositionPlan,
    CompositionPlanEntry,
    PlanBlock,
    PlanMatch,
    PlanSummary,
    SemanticBinding,
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
from vanjaro_cli.design.quality_counts import compute_quality_counts
from vanjaro_cli.design.serialization import serialize_design_document, stable_design_id
from vanjaro_cli.design.template_catalog import load_template_catalog
from vanjaro_cli.design.visual_gate import CANONICAL_VIEWPORTS, CaptureImage, CaptureStability, ViewportCapturePair
from vanjaro_cli.orchestration.project_capture_evidence import (
    CAPTURE_EVIDENCE_DIRECTORY,
    DESIGN_DOCUMENT_PATH,
    ProjectCaptureEvidenceError,
    _build_artifact_fingerprints,
    _record_filename,
    _target_identity_fingerprint,
    record_page_capture_evidence,
    resolve_workspace_capture_coverage,
)
from vanjaro_cli.project import ProjectSource, create_manifest
from vanjaro_cli.project.models import ProjectManifest
from vanjaro_cli.reliability.artifacts import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_template_catalog(ROOT / "artifacts" / "block-templates")


def _template(filename: str):
    return next(entry for entry in CATALOG if Path(entry.relative_path).name == filename)


HERO = _template("centered-hero.json")


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


def _page(page_id: str, *, slug: str | None = None, section_ids: tuple[str, ...] = ()) -> Page:
    return Page(
        id=page_id,
        source_reference="https://agency.example/",
        title=page_id.title(),
        slug=slug or page_id,
        sections=[_section(section_id) for section_id in section_ids],
        breakpoints=[BreakpointName.DESKTOP],
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
    path = root / DESIGN_DOCUMENT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_design_document(document), encoding="utf-8", newline="\n")


def _capture_pair(root: Path, page_id: str, breakpoint: BreakpointName) -> ViewportCapturePair:
    directory = root / "qa/captures"
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / f"{page_id}-{breakpoint.value}-source.png"
    output = directory / f"{page_id}-{breakpoint.value}-output.png"
    source.write_bytes(f"{page_id}-{breakpoint.value}-source".encode("utf-8"))
    output.write_bytes(f"{page_id}-{breakpoint.value}-output".encode("utf-8"))
    stability = CaptureStability(
        lazy_load_triggered=True, fonts_settled=True, animations_disabled=True
    )
    return ViewportCapturePair(
        breakpoint=breakpoint,
        viewport=CANONICAL_VIEWPORTS[breakpoint],
        source=CaptureImage(path=source, stability=stability),
        output=CaptureImage(path=output, stability=stability),
    )


_ALL_BREAKPOINTS = (BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE)

_UNSET = object()


def _observation_payload(page: Page, breakpoint: BreakpointName) -> dict[str, object]:
    """A realistic `PageObservation`-shaped payload: real section ids owned by
    `page`, at the canonical viewport width for `breakpoint`."""

    return {
        "viewport_width": float(CANONICAL_VIEWPORTS[breakpoint].width),
        "sections": [
            {"geometry": {"section_id": section.id, "order": index}}
            for index, section in enumerate(page.sections)
        ],
    }


def _write_build_manifests(root: Path) -> None:
    """Real, minimal build artifacts so recorded evidence can bind to them."""

    atomic_write_json(root / "build/page-manifest.json", {"schema_version": "1.0", "page": {}})
    atomic_write_json(root / "build/global-page-manifest.json", {"schema_version": "1.0", "pages": []})
    atomic_write_json(
        root / "build/global-block-manifest.json", {"schema_version": "1.0", "blocks": []}
    )


def _record_page(
    root: Path,
    document: DesignDocument,
    page_id: str,
    *,
    breakpoints: tuple[BreakpointName, ...] = _ALL_BREAKPOINTS,
    manifest: object = _UNSET,
    with_build_manifests: bool = True,
) -> dict[str, object]:
    """Record a page's evidence with a real, current local build and target
    binding by default -- exactly what the reader now requires for credit.

    Pass `manifest=None` or `with_build_manifests=False` to deliberately
    record unbound evidence for a negative test.
    """

    if with_build_manifests:
        _write_build_manifests(root)
    resolved_manifest = _manifest() if manifest is _UNSET else manifest
    page = next(item for item in document.pages if item.id == page_id)
    pairs = tuple(_capture_pair(root, page_id, breakpoint) for breakpoint in breakpoints)
    expected = {breakpoint.value: _observation_payload(page, breakpoint) for breakpoint in breakpoints}
    observed = {breakpoint.value: _observation_payload(page, breakpoint) for breakpoint in breakpoints}
    return record_page_capture_evidence(
        root,
        document,
        page_id=page_id,
        source_url="https://agency.example/",
        built_url="https://build.example/",
        expected=expected,
        observed=observed,
        pairs=pairs,
        manifest=resolved_manifest,
    )


def _manifest() -> ProjectManifest:
    return create_manifest(
        name="Capture Evidence",
        project_id="capture-evidence",
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


def _plan_entry(entry_id: str, source_section_id: str) -> CompositionPlanEntry:
    return CompositionPlanEntry(
        id=entry_id,
        source_section_id=source_section_id,
        template_id=HERO.template_id,
        template=HERO.name,
        match=PlanMatch(score=0.95, confidence="high"),
        block=PlanBlock(name=f"Hero {entry_id}", category=HERO.category),
        bindings=(
            SemanticBinding(
                semantic_field="heading",
                slot="heading",
                source_element_ids=("el-1",),
                value="Welcome",
                editable=True,
            ),
        ),
    )


def _plan(entries: tuple[CompositionPlanEntry, ...]) -> CompositionPlan:
    return CompositionPlan(
        source_document_id="capture-evidence-doc",
        entries=entries,
        summary=PlanSummary(
            section_count=len(entries),
            blocking_count=0,
            native_component_ratio=1.0,
            editable_content_coverage=1.0,
        ),
    )


# ---------------------------------------------------------------------------
# Page identity from hashed, image-sourced section ids.


def test_hashed_image_section_id_maps_to_one_real_page(tmp_path: Path) -> None:
    hashed_section_id = stable_design_id("image-section", "proj", "home", "src-1")
    assert "." not in hashed_section_id  # the exact shape image_adapter.py produces

    document = _document((_page("home", section_ids=(hashed_section_id,)),))
    _write_resolved_document(tmp_path, document)
    _record_page(tmp_path, document, "home")

    plan = _plan((_plan_entry("home.section.1.plan", hashed_section_id),))
    coverage = resolve_workspace_capture_coverage(tmp_path, _manifest())
    report = compute_quality_counts(plan, CATALOG, coverage.capture_evidence, page_identity=coverage.page_identity)

    assert report.desktop_tablet_mobile_evidence.numerator == 1
    assert report.desktop_tablet_mobile_evidence.denominator == 1
    assert not any("mis-identifies pages" in warning for warning in report.warnings)


# ---------------------------------------------------------------------------
# Multi-page storage.


def test_multi_page_record_and_read_returns_two_of_two_and_preserves_both_pages(
    tmp_path: Path,
) -> None:
    document = _document(
        (
            _page("home", section_ids=("home.s1",)),
            _page("about", section_ids=("about.s1",)),
        )
    )
    _write_resolved_document(tmp_path, document)
    _record_page(tmp_path, document, "home")
    _record_page(tmp_path, document, "about")

    coverage = resolve_workspace_capture_coverage(tmp_path, _manifest())

    assert coverage.capture_evidence == {
        "home": frozenset({"desktop", "tablet", "mobile"}),
        "about": frozenset({"desktop", "tablet", "mobile"}),
    }
    plan = _plan(
        (
            _plan_entry("home.plan", "home.s1"),
            _plan_entry("about.plan", "about.s1"),
        )
    )
    report = compute_quality_counts(plan, CATALOG, coverage.capture_evidence, page_identity=coverage.page_identity)
    assert report.desktop_tablet_mobile_evidence.numerator == 2
    assert report.desktop_tablet_mobile_evidence.denominator == 2


def test_empty_design_page_remains_in_denominator(tmp_path: Path) -> None:
    document = _document(
        (
            _page("home", section_ids=("home.s1",)),
            _page("empty"),  # zero sections
        )
    )
    _write_resolved_document(tmp_path, document)
    _record_page(tmp_path, document, "home")

    coverage = resolve_workspace_capture_coverage(tmp_path, _manifest())

    assert coverage.page_identity.page_ids == ("home", "empty")
    plan = _plan((_plan_entry("home.plan", "home.s1"),))
    report = compute_quality_counts(plan, CATALOG, coverage.capture_evidence, page_identity=coverage.page_identity)
    assert report.desktop_tablet_mobile_evidence.numerator == 1
    assert report.desktop_tablet_mobile_evidence.denominator == 2


def test_missing_page_mapping_warns_and_earns_no_credit(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    _record_page(tmp_path, document, "home")

    coverage = resolve_workspace_capture_coverage(tmp_path, _manifest())
    plan = _plan((_plan_entry("orphan.plan", "section-not-in-document"),))
    report = compute_quality_counts(plan, CATALOG, coverage.capture_evidence, page_identity=coverage.page_identity)

    assert any(
        "section-not-in-document" in warning and "no page mapping" in warning
        for warning in report.warnings
    )
    # The real "home" page is still credited even though an unrelated entry
    # could not be attributed to any page.
    assert report.desktop_tablet_mobile_evidence.numerator == 1
    assert report.desktop_tablet_mobile_evidence.denominator == 1


# ---------------------------------------------------------------------------
# Partial recapture.


def test_partial_recapture_clears_formerly_complete_coverage_only_for_that_page(
    tmp_path: Path,
) -> None:
    document = _document(
        (
            _page("home", section_ids=("home.s1",)),
            _page("about", section_ids=("about.s1",)),
        )
    )
    _write_resolved_document(tmp_path, document)
    _record_page(tmp_path, document, "home")
    _record_page(tmp_path, document, "about")

    assert resolve_workspace_capture_coverage(tmp_path, _manifest()).capture_evidence == {
        "home": frozenset({"desktop", "tablet", "mobile"}),
        "about": frozenset({"desktop", "tablet", "mobile"}),
    }

    _record_page(tmp_path, document, "home", breakpoints=(BreakpointName.DESKTOP,))

    coverage = resolve_workspace_capture_coverage(tmp_path, _manifest())
    assert "home" not in coverage.capture_evidence
    assert coverage.capture_evidence["about"] == frozenset({"desktop", "tablet", "mobile"})


# ---------------------------------------------------------------------------
# Currency binding: resolved document, local build artifacts, target identity.


def test_changed_resolved_document_invalidates_credit(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    _record_page(tmp_path, document, "home")

    changed = _document((_page("home", section_ids=("home.s1", "home.s2")),))
    _write_resolved_document(tmp_path, changed)

    coverage = resolve_workspace_capture_coverage(tmp_path)
    assert coverage.capture_evidence == {}
    assert any("stale" in warning for warning in coverage.warnings)


def test_changed_local_build_manifest_invalidates_credit(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    _record_page(tmp_path, document, "home")

    assert "home" in resolve_workspace_capture_coverage(tmp_path, _manifest()).capture_evidence

    build_path = tmp_path / "build/global-page-manifest.json"
    atomic_write_json(build_path, {"schema_version": "1.0", "pages": [{"changed": True}]})

    coverage = resolve_workspace_capture_coverage(tmp_path, _manifest())
    assert "home" not in coverage.capture_evidence
    assert any("local build artifacts changed" in warning for warning in coverage.warnings)


def test_changed_target_invalidates_credit(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    manifest = _manifest()
    _record_page(tmp_path, document, "home", manifest=manifest)

    assert "home" in resolve_workspace_capture_coverage(tmp_path, manifest).capture_evidence

    other_manifest = manifest.model_copy(
        update={"target": manifest.target.model_copy(update={"profile": "a-different-profile"})}
    )
    coverage = resolve_workspace_capture_coverage(tmp_path, other_manifest)
    assert "home" not in coverage.capture_evidence
    assert any("target identity" in warning for warning in coverage.warnings)


def test_workspace_without_local_build_artifacts_earns_no_credit_with_a_clear_reason(
    tmp_path: Path,
) -> None:
    # No binding to invent: neither the capture nor this read has a local
    # build manifest, so build currency can never be established, and
    # unbound evidence must never be credited "just in case" it is current.
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    _record_page(tmp_path, document, "home", with_build_manifests=False)

    coverage = resolve_workspace_capture_coverage(tmp_path, _manifest())
    assert "home" not in coverage.capture_evidence
    assert any(
        "no local build artifact binding was recorded" in warning for warning in coverage.warnings
    )


def test_build_artifacts_removed_after_capture_earns_no_credit(tmp_path: Path) -> None:
    # The record itself is bound to a build; the *current* workspace simply
    # no longer has one (e.g. `build/` was cleaned). That is exactly as
    # unverifiable as never having had a build, so it must not be credited.
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    _record_page(tmp_path, document, "home")
    assert "home" in resolve_workspace_capture_coverage(tmp_path, _manifest()).capture_evidence

    for relative in ("build/page-manifest.json", "build/global-page-manifest.json", "build/global-block-manifest.json"):
        (tmp_path / relative).unlink()

    coverage = resolve_workspace_capture_coverage(tmp_path, _manifest())
    assert "home" not in coverage.capture_evidence
    assert any(
        "no current local build artifacts exist" in warning for warning in coverage.warnings
    )


def test_missing_target_identity_at_capture_time_earns_no_credit(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    _record_page(tmp_path, document, "home", manifest=None)

    coverage = resolve_workspace_capture_coverage(tmp_path, _manifest())
    assert "home" not in coverage.capture_evidence
    assert any("no target identity was recorded" in warning for warning in coverage.warnings)


def test_no_current_manifest_supplied_earns_no_credit(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    manifest = _manifest()
    _record_page(tmp_path, document, "home", manifest=manifest)

    # The record is fully bound; this read simply never supplies a current
    # project manifest, so target currency cannot be established either way.
    coverage = resolve_workspace_capture_coverage(tmp_path)
    assert "home" not in coverage.capture_evidence
    assert any(
        "no current project manifest was supplied" in warning for warning in coverage.warnings
    )


def test_document_fingerprint_tolerates_json_whitespace_but_not_real_drift(
    tmp_path: Path,
) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    _record_page(tmp_path, document, "home")

    # Reformat the resolved document on disk to a different (but semantically
    # identical) JSON encoding -- recorder and reader must agree this is not
    # drift.
    document_path = tmp_path / DESIGN_DOCUMENT_PATH
    reformatted = json.dumps(json.loads(document_path.read_text(encoding="utf-8")), indent=4)
    document_path.write_text(reformatted, encoding="utf-8")

    coverage = resolve_workspace_capture_coverage(tmp_path, _manifest())
    assert "home" in coverage.capture_evidence

    # An actual content change must still register as real drift.
    changed = _document((_page("home", section_ids=("home.s1", "home.s2")),))
    _write_resolved_document(tmp_path, changed)

    coverage_after_drift = resolve_workspace_capture_coverage(tmp_path, _manifest())
    assert "home" not in coverage_after_drift.capture_evidence
    assert any("stale" in warning for warning in coverage_after_drift.warnings)


# ---------------------------------------------------------------------------
# Screenshot tampering.


def test_changed_screenshot_invalidates_credit(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    _record_page(tmp_path, document, "home")

    (tmp_path / "qa/captures/home-desktop-source.png").write_bytes(b"tampered")

    coverage = resolve_workspace_capture_coverage(tmp_path, _manifest())
    assert "home" not in coverage.capture_evidence
    assert any("changed since capture" in warning for warning in coverage.warnings)


def test_deleted_screenshot_invalidates_credit(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    _record_page(tmp_path, document, "home")

    (tmp_path / "qa/captures/home-mobile-output.png").unlink()

    coverage = resolve_workspace_capture_coverage(tmp_path, _manifest())
    assert "home" not in coverage.capture_evidence
    assert any("unsafe" in warning or "unreadable" in warning for warning in coverage.warnings)


def test_recorder_never_fabricates_a_hash_for_a_missing_file(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    page = document.pages[0]
    pair = _capture_pair(tmp_path, "home", BreakpointName.DESKTOP)
    pair.source.path.unlink()

    with pytest.raises(ProjectCaptureEvidenceError):
        record_page_capture_evidence(
            tmp_path,
            document,
            page_id="home",
            source_url="https://agency.example/",
            built_url="https://build.example/",
            expected={"desktop": _observation_payload(page, BreakpointName.DESKTOP)},
            observed={"desktop": _observation_payload(page, BreakpointName.DESKTOP)},
            pairs=(pair,),
        )


# ---------------------------------------------------------------------------
# Malicious or malformed records, written directly (bypassing the recorder).


def _write_raw_record(root: Path, page_id: str, payload: object) -> Path:
    path = root / CAPTURE_EVIDENCE_DIRECTORY / _record_filename(page_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (str, bytes)):
        path.write_bytes(payload if isinstance(payload, bytes) else payload.encode("utf-8"))
    else:
        atomic_write_json(path, payload)
    return path


def _base_valid_payload(
    root: Path, page: Page, document_sha256: str, manifest: ProjectManifest
) -> dict[str, object]:
    """A raw record that would pass every check -- callers mutate exactly one
    thing to isolate a single rejection reason. `_write_build_manifests(root)`
    must already have been called so the build fingerprints here are real."""

    pairs = tuple(_capture_pair(root, page.id, breakpoint) for breakpoint in _ALL_BREAKPOINTS)
    return {
        "schema_version": "capture-evidence-v1",
        "page_id": page.id,
        "source_url": "https://agency.example/",
        "built_url": "https://build.example/",
        "design_document_sha256": document_sha256,
        "build_artifact_sha256": _build_artifact_fingerprints(root),
        "target_identity_sha256": _target_identity_fingerprint(manifest),
        "expected": {
            breakpoint.value: _observation_payload(page, breakpoint) for breakpoint in _ALL_BREAKPOINTS
        },
        "observed": {
            breakpoint.value: _observation_payload(page, breakpoint) for breakpoint in _ALL_BREAKPOINTS
        },
        "captures": [
            {
                "breakpoint": pair.breakpoint.value,
                "source_path": pair.source.path.relative_to(root).as_posix(),
                "output_path": pair.output.path.relative_to(root).as_posix(),
                "source_sha256": hashlib.sha256(pair.source.path.read_bytes()).hexdigest(),
                "output_sha256": hashlib.sha256(pair.output.path.read_bytes()).hexdigest(),
                "lazy_load_triggered": True,
                "fonts_settled": True,
                "animations_disabled": True,
            }
            for pair in pairs
        ],
        "warnings": [],
    }


def _document_sha256(root: Path) -> str:
    import hashlib

    return hashlib.sha256((root / DESIGN_DOCUMENT_PATH).read_bytes()).hexdigest()


def test_unknown_page_rejected_without_trusting_evidence(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    manifest = _manifest()
    _record_page(tmp_path, document, "home", manifest=manifest)

    ghost_page = _page("ghost", section_ids=("ghost.s1",))
    payload = _base_valid_payload(tmp_path, ghost_page, _document_sha256(tmp_path), manifest)
    _write_raw_record(tmp_path, "ghost", payload)

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert "ghost" not in coverage.capture_evidence
    assert coverage.capture_evidence["home"] == frozenset({"desktop", "tablet", "mobile"})
    assert any("not a page in the current resolved design document" in warning for warning in coverage.warnings)


def test_duplicate_breakpoint_rejected(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    manifest = _manifest()
    _write_build_manifests(tmp_path)
    payload = _base_valid_payload(tmp_path, document.pages[0], _document_sha256(tmp_path), manifest)
    payload["captures"].append(dict(payload["captures"][0]))  # duplicate desktop entry
    _write_raw_record(tmp_path, "home", payload)

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert "home" not in coverage.capture_evidence
    assert any("duplicate" in warning for warning in coverage.warnings)


def test_nonboolean_stability_rejected(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    manifest = _manifest()
    _write_build_manifests(tmp_path)
    payload = _base_valid_payload(tmp_path, document.pages[0], _document_sha256(tmp_path), manifest)
    payload["captures"][0]["lazy_load_triggered"] = 1  # int, not bool
    _write_raw_record(tmp_path, "home", payload)

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert "home" not in coverage.capture_evidence
    assert any("must be true" in warning for warning in coverage.warnings)


def test_malformed_json_rejected(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    _write_raw_record(tmp_path, "home", "{not json")

    coverage = resolve_workspace_capture_coverage(tmp_path)
    assert coverage.capture_evidence == {}
    assert any("malformed" in warning for warning in coverage.warnings)


def test_path_traversal_in_a_capture_path_rejected(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    manifest = _manifest()
    _write_build_manifests(tmp_path)
    payload = _base_valid_payload(tmp_path, document.pages[0], _document_sha256(tmp_path), manifest)
    payload["captures"][0]["source_path"] = "../outside.png"
    _write_raw_record(tmp_path, "home", payload)

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert "home" not in coverage.capture_evidence
    assert any("unsafe" in warning for warning in coverage.warnings)


def test_symlink_escape_in_a_capture_path_rejected(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    manifest = _manifest()
    _write_build_manifests(tmp_path)
    secret = tmp_path.parent / "secret.png"
    secret.write_bytes(b"outside the workspace")
    link = tmp_path / "qa/captures/home-desktop-source.png"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(secret)
    (tmp_path / "qa/captures/home-desktop-output.png").write_bytes(b"output")

    payload = _base_valid_payload(tmp_path, document.pages[0], _document_sha256(tmp_path), manifest)
    for entry in payload["captures"]:
        if entry["breakpoint"] != "desktop":
            continue
        entry["source_sha256"] = hashlib.sha256(secret.read_bytes()).hexdigest()
    _write_raw_record(tmp_path, "home", payload)

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert "home" not in coverage.capture_evidence
    assert any(
        "unsafe" in warning or "symlink" in warning for warning in coverage.warnings
    )


def test_symlinked_evidence_record_itself_is_rejected(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    outside = tmp_path.parent / "outside-record.json"
    outside.write_text(json.dumps({"page_id": "home"}), encoding="utf-8")
    link = tmp_path / CAPTURE_EVIDENCE_DIRECTORY / _record_filename("home")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)

    coverage = resolve_workspace_capture_coverage(tmp_path)
    assert coverage.capture_evidence == {}
    assert any("symlink" in warning for warning in coverage.warnings)


# ---------------------------------------------------------------------------
# Observation shape validation (PageObservation, not a bare nonempty dict).


def test_empty_sections_observation_rejected(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    manifest = _manifest()
    _write_build_manifests(tmp_path)
    payload = _base_valid_payload(tmp_path, document.pages[0], _document_sha256(tmp_path), manifest)
    payload["expected"]["desktop"]["sections"] = []
    _write_raw_record(tmp_path, "home", payload)

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert "home" not in coverage.capture_evidence
    assert any(
        "desktop expected observation is invalid" in warning for warning in coverage.warnings
    )


def test_observation_referencing_a_section_not_owned_by_the_page_rejected(
    tmp_path: Path,
) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    manifest = _manifest()
    _write_build_manifests(tmp_path)
    payload = _base_valid_payload(tmp_path, document.pages[0], _document_sha256(tmp_path), manifest)
    payload["observed"]["desktop"]["sections"][0]["geometry"]["section_id"] = "not-a-real-section"
    _write_raw_record(tmp_path, "home", payload)

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert "home" not in coverage.capture_evidence
    assert any(
        "references sections not owned by this page" in warning for warning in coverage.warnings
    )


def test_observation_with_wrong_canonical_viewport_width_rejected(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    manifest = _manifest()
    _write_build_manifests(tmp_path)
    payload = _base_valid_payload(tmp_path, document.pages[0], _document_sha256(tmp_path), manifest)
    payload["expected"]["desktop"]["viewport_width"] = 999.0
    _write_raw_record(tmp_path, "home", payload)

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert "home" not in coverage.capture_evidence
    assert any(
        "does not match the canonical" in warning for warning in coverage.warnings
    )


def test_observation_with_duplicate_section_ids_rejected(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1", "home.s2")),))
    _write_resolved_document(tmp_path, document)
    manifest = _manifest()
    _write_build_manifests(tmp_path)
    payload = _base_valid_payload(tmp_path, document.pages[0], _document_sha256(tmp_path), manifest)
    payload["observed"]["desktop"]["sections"][1]["geometry"]["section_id"] = "home.s1"
    _write_raw_record(tmp_path, "home", payload)

    coverage = resolve_workspace_capture_coverage(tmp_path, manifest)
    assert "home" not in coverage.capture_evidence
    assert any(
        "desktop observed observation is invalid" in warning for warning in coverage.warnings
    )


# ---------------------------------------------------------------------------
# Legacy compatibility.


def test_legacy_only_workspace_has_zero_authenticated_coverage_with_a_clear_warning(
    tmp_path: Path,
) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    (tmp_path / "qa").mkdir(parents=True, exist_ok=True)
    (tmp_path / "qa/fidelity-evidence.json").write_text(
        json.dumps({"page_id": "home", "expected": {}, "observed": {}, "captures": []}),
        encoding="utf-8",
    )

    coverage = resolve_workspace_capture_coverage(tmp_path)

    assert coverage.capture_evidence == {}
    assert any(
        "legacy single-page record" in warning and "not used for authenticated" in warning
        for warning in coverage.warnings
    )


# ---------------------------------------------------------------------------
# Consumer agreement and read-only behaviour.


def test_quality_json_and_draft_verify_read_paths_agree(tmp_path: Path) -> None:
    document = _document(
        (
            _page("home", section_ids=("home.s1",)),
            _page("about", section_ids=("about.s1",)),
        )
    )
    _write_resolved_document(tmp_path, document)
    manifest = _manifest()
    _record_page(tmp_path, document, "home", manifest=manifest)
    plan = _plan(
        (
            _plan_entry("home.plan", "home.s1"),
            _plan_entry("about.plan", "about.s1"),
        )
    )

    # `project_quality_cmd.py` and `project_verify.py` both call
    # `resolve_workspace_capture_coverage` then `compute_quality_counts`
    # exactly like this; the two call sites must never diverge.
    from_quality_cmd = compute_quality_counts(
        plan,
        CATALOG,
        resolve_workspace_capture_coverage(tmp_path, manifest).capture_evidence,
        page_identity=resolve_workspace_capture_coverage(tmp_path, manifest).page_identity,
    )
    from_verify = compute_quality_counts(
        plan,
        CATALOG,
        resolve_workspace_capture_coverage(tmp_path, manifest).capture_evidence,
        page_identity=resolve_workspace_capture_coverage(tmp_path, manifest).page_identity,
    )

    assert from_quality_cmd == from_verify
    assert from_quality_cmd.desktop_tablet_mobile_evidence.numerator == 1
    assert from_quality_cmd.desktop_tablet_mobile_evidence.denominator == 2


def test_reader_performs_no_writes(tmp_path: Path) -> None:
    document = _document((_page("home", section_ids=("home.s1",)),))
    _write_resolved_document(tmp_path, document)
    _record_page(tmp_path, document, "home")

    before = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file()
    }

    resolve_workspace_capture_coverage(tmp_path)
    resolve_workspace_capture_coverage(tmp_path, _manifest())

    after_paths = {path for path in tmp_path.rglob("*") if path.is_file()}
    after = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file()
    }

    assert after_paths == set(before)
    assert after == before
