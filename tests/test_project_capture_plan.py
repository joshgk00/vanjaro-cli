"""Tests for `plan_project_capture`: pure metadata planning plus read-only local checks.

Every test here either builds a `DesignDocument` by hand (live/Figma cases,
where the point is to prove nothing is fabricated) or, for the image case,
builds one through the real `ImageSourceAdapter` so at least one test proves
the plan resolves metadata the actual image adapter emits, not an invented
shape that merely happens to agree with the planner.
"""

from __future__ import annotations

import hashlib
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

from vanjaro_cli.design.capture_references import (
    CanvasInterpretation,
    StaticReference,
    StaticSourceKind,
)
from vanjaro_cli.design.image_evidence import ImageEvidenceSet
from vanjaro_cli.design.figma_adapter import analyze_figma_document
from vanjaro_cli.design.models import (
    BoundingBox,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    BreakpointName,
    EvidenceStatus,
    NavigationVisibility,
    ObservationMethod,
    Page,
    Provenance,
    SourceKind,
)
from vanjaro_cli.design.sources import ImageSourceAdapter, ImageSourceRequest, ReferenceImage
from vanjaro_cli.orchestration.project_capture_plan import (
    REQUIRED_BREAKPOINTS,
    ReferenceStatus,
    plan_project_capture,
)

CAPTURED_AT = datetime(2026, 8, 4, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures shared across sections.


def _page(
    page_id: str,
    *,
    source_reference: str,
    breakpoints: tuple[BreakpointName, ...] = (),
    metadata: dict | None = None,
    provenance: tuple[Provenance, ...] = (),
) -> Page:
    return Page(
        id=page_id,
        source_reference=source_reference,
        title=page_id.title(),
        slug=page_id,
        sections=[],
        breakpoints=list(breakpoints),
        navigation_visibility=NavigationVisibility.VISIBLE,
        provenance=list(provenance),
        metadata=metadata or {},
    )


def _figma_page_provenance(
    *, file_key: str, frame_node_id: str, breakpoint: BreakpointName = BreakpointName.DESKTOP,
    bounds: tuple[int, int] | None = None,
) -> Provenance:
    """A real Figma page's own (base) frame provenance, always directly observed.

    `bounds`, when given, is the frame's own directly-observed (width, height)
    -- the same shape `analyze_figma_document` records from a real frame's
    `absoluteBoundingBox`. Tests that exercise frame-dimension validation must
    supply it explicitly; it is never fabricated here.
    """

    return Provenance(
        source_kind=SourceKind.FIGMA,
        method=ObservationMethod.API,
        file_key=file_key,
        frame_node_id=frame_node_id,
        viewport=breakpoint,
        bounds=BoundingBox(x=0, y=0, width=bounds[0], height=bounds[1]) if bounds else None,
    )


def _document(source_kind: SourceKind, pages: tuple[Page, ...], *, source_metadata: dict | None = None) -> DesignDocument:
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=source_kind,
            identifier="fixture",
            captured_at=CAPTURED_AT,
            adapter_version="1.0.0",
            metadata=source_metadata or {},
        ),
        tokens=DesignTokens(),
        assets=[],
        pages=list(pages),
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1.0, unsupported_traits=[]),
    )


def _png_bytes(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes(5)
    )


def _breakpoint_plan(plan, page_id: str, breakpoint: BreakpointName):
    page_plan = next(item for item in plan.pages if item.page_id == page_id)
    return next(item for item in page_plan.breakpoints if item.breakpoint == breakpoint)


# ---------------------------------------------------------------------------
# Live HTML source: reference only follows explicit URL provenance.


def test_live_reference_derived_for_every_declared_breakpoint(tmp_path: Path) -> None:
    page = _page(
        "home",
        source_reference="https://agency.example/",
        breakpoints=(BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE),
    )
    document = _document(SourceKind.LIVE_HTML, (page,))

    plan = plan_project_capture(tmp_path, document)

    assert len(plan.pages) == 1
    assert [item.breakpoint for item in plan.pages[0].breakpoints] == list(REQUIRED_BREAKPOINTS)
    for breakpoint in REQUIRED_BREAKPOINTS:
        entry = _breakpoint_plan(plan, "home", breakpoint)
        assert entry.status is ReferenceStatus.VALID
        assert entry.reference.url == "https://agency.example/"
        assert entry.reference.page_id == "home"
        assert entry.is_canonical_viewport is True


def test_live_reference_missing_declared_breakpoint_stays_not_declared(tmp_path: Path) -> None:
    page = _page("home", source_reference="https://agency.example/", breakpoints=(BreakpointName.DESKTOP,))
    document = _document(SourceKind.LIVE_HTML, (page,))

    plan = plan_project_capture(tmp_path, document)

    desktop = _breakpoint_plan(plan, "home", BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.VALID
    for breakpoint in (BreakpointName.TABLET, BreakpointName.MOBILE):
        entry = _breakpoint_plan(plan, "home", breakpoint)
        assert entry.status is ReferenceStatus.NOT_DECLARED
        assert entry.reference is None
        assert entry.diagnostics
        assert "no reference declared" in entry.diagnostics[0]


def test_live_reference_never_fabricated_from_a_non_http_source_reference(tmp_path: Path) -> None:
    page = _page("home", source_reference="urn:internal:home", breakpoints=(BreakpointName.DESKTOP,))
    document = _document(SourceKind.LIVE_HTML, (page,))

    plan = plan_project_capture(tmp_path, document)

    desktop = _breakpoint_plan(plan, "home", BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.NOT_DECLARED
    assert desktop.reference is None


# ---------------------------------------------------------------------------
# Image source: metadata resolved from evidence produced by the real adapter.


def _image_evidence_payload(*, sha256: str, width: int, height: int, breakpoint: str = "desktop") -> dict:
    return {
        "schema_version": "1.0",
        "producer": {"name": "capture-plan-fixture", "version": "1.0"},
        "observations": [
            {
                "source_sha256": sha256,
                "captured_at": CAPTURED_AT.isoformat(),
                "page_slug": "home",
                "page_title": "Home",
                "breakpoint": breakpoint,
                "viewport": {"width": width, "height": height},
                "image_width": width,
                "image_height": height,
                "sections": [
                    {
                        "id": "hero",
                        "order": 0,
                        "semantic_role": "hero",
                        "role_confidence": 0.9,
                        "bounds": {"x": 0, "y": 0, "width": width, "height": height},
                        "layout": {"kind": "stack", "contained": True},
                    }
                ],
            }
        ],
    }


def _image_document(tmp_path: Path, *, width: int, height: int, relative_path: str = "sources/home-desktop.png") -> DesignDocument:
    """Build a real DesignDocument through `ImageSourceAdapter`, with a matching real file on disk."""

    payload = _png_bytes(width, height)
    (tmp_path / relative_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / relative_path).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    evidence = ImageEvidenceSet.model_validate(
        _image_evidence_payload(sha256=digest, width=width, height=height)
    )
    request = ImageSourceRequest(
        images=(
            ReferenceImage(
                path=Path(relative_path),
                page_slug="home",
                breakpoint=BreakpointName.DESKTOP,
                viewport_width=width,
                viewport_height=height,
                sha256=digest,
            ),
        ),
        project_id="capture-plan-fixture",
        evidence=evidence,
        captured_at=CAPTURED_AT,
    )
    return ImageSourceAdapter().analyze(request)


def test_image_adapter_metadata_resolves_into_a_valid_desktop_reference(tmp_path: Path) -> None:
    document = _image_document(tmp_path, width=1440, height=900)
    page_id = document.pages[0].id

    plan = plan_project_capture(tmp_path, document)

    desktop = _breakpoint_plan(plan, page_id, BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.VALID
    assert isinstance(desktop.reference, StaticReference)
    assert desktop.reference.source_kind is StaticSourceKind.IMAGE
    assert desktop.reference.local_path == "sources/home-desktop.png"
    assert (desktop.reference.canvas_width, desktop.reference.canvas_height) == (1440, 900)
    assert desktop.is_canonical_viewport is True


def test_image_source_missing_tablet_and_mobile_stay_not_declared_even_with_a_valid_desktop(
    tmp_path: Path,
) -> None:
    document = _image_document(tmp_path, width=1440, height=900)
    page_id = document.pages[0].id

    plan = plan_project_capture(tmp_path, document)

    assert _breakpoint_plan(plan, page_id, BreakpointName.DESKTOP).status is ReferenceStatus.VALID
    for breakpoint in (BreakpointName.TABLET, BreakpointName.MOBILE):
        entry = _breakpoint_plan(plan, page_id, breakpoint)
        assert entry.status is ReferenceStatus.NOT_DECLARED
        assert entry.reference is None
    # The three-breakpoint denominator is never shrunk by a source that only
    # ever declared one of them.
    page_plan = next(item for item in plan.pages if item.page_id == page_id)
    assert len(page_plan.breakpoints) == 3


def test_noncanonical_1280_desktop_image_reference_is_valid_but_not_canonical(tmp_path: Path) -> None:
    document = _image_document(tmp_path, width=1280, height=800)
    page_id = document.pages[0].id

    plan = plan_project_capture(tmp_path, document)

    desktop = _breakpoint_plan(plan, page_id, BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.VALID
    assert desktop.declared_viewport == (1280, 800)
    assert desktop.is_canonical_viewport is False


def test_tampered_image_bytes_invalidate_a_previously_declared_reference(tmp_path: Path) -> None:
    document = _image_document(tmp_path, width=1440, height=900)
    page_id = document.pages[0].id

    (tmp_path / "sources/home-desktop.png").write_bytes(_png_bytes(1440, 900) + b"tampered")

    plan = plan_project_capture(tmp_path, document)
    desktop = _breakpoint_plan(plan, page_id, BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.INVALID
    assert any("changed" in message for message in desktop.diagnostics)


# ---------------------------------------------------------------------------
# Figma source: never fabricated; only an explicit, already-acquired export counts.


def test_figma_source_never_fabricates_a_reference_from_its_url(tmp_path: Path) -> None:
    page = _page(
        "home",
        source_reference="https://www.figma.com/file/abc123/Home",
        breakpoints=(BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE),
    )
    document = _document(SourceKind.FIGMA, (page,))

    plan = plan_project_capture(tmp_path, document)

    for breakpoint in REQUIRED_BREAKPOINTS:
        entry = _breakpoint_plan(plan, "home", breakpoint)
        assert entry.status is ReferenceStatus.NOT_DECLARED
        assert entry.reference is None


def test_figma_explicit_export_fills_its_declared_breakpoint_and_leaves_others_not_declared(
    tmp_path: Path,
) -> None:
    page = _page(
        "home",
        source_reference="https://www.figma.com/file/abc123/Home",
        provenance=(
            _figma_page_provenance(file_key="abc123", frame_node_id="12:34", bounds=(1440, 900)),
        ),
    )
    document = _document(SourceKind.FIGMA, (page,))

    export_path = "sources/figma/home-desktop.png"
    payload = _png_bytes(1440, 900)
    (tmp_path / export_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / export_path).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    reference = StaticReference(
        page_id="home",
        breakpoint=BreakpointName.DESKTOP,
        source_kind=StaticSourceKind.FIGMA,
        local_path=export_path,
        sha256=digest,
        canvas_width=1440,
        canvas_height=900,
        viewport_width=1440,
        viewport_height=900,
        interpretation=CanvasInterpretation.VIEWPORT,
        file_key="abc123",
        frame_node_id="12:34",
    )

    plan = plan_project_capture(tmp_path, document, references=(reference,))

    desktop = _breakpoint_plan(plan, "home", BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.VALID
    assert desktop.reference.file_key == "abc123"
    assert desktop.reference.frame_node_id == "12:34"
    for breakpoint in (BreakpointName.TABLET, BreakpointName.MOBILE):
        entry = _breakpoint_plan(plan, "home", breakpoint)
        assert entry.status is ReferenceStatus.NOT_DECLARED
        assert entry.reference is None


def test_full_page_explicit_interpretation_is_preserved_through_the_plan(tmp_path: Path) -> None:
    page = _page(
        "home",
        source_reference="https://www.figma.com/file/abc123/Home",
        provenance=(
            _figma_page_provenance(file_key="abc123", frame_node_id="12:34", bounds=(1440, 6200)),
        ),
    )
    document = _document(SourceKind.FIGMA, (page,))

    export_path = "sources/figma/home-full.png"
    payload = _png_bytes(1440, 6200)
    (tmp_path / export_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / export_path).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    reference = StaticReference(
        page_id="home",
        breakpoint=BreakpointName.DESKTOP,
        source_kind=StaticSourceKind.FIGMA,
        local_path=export_path,
        sha256=digest,
        canvas_width=1440,
        canvas_height=6200,
        viewport_width=1440,
        viewport_height=900,
        interpretation=CanvasInterpretation.FULL_PAGE,
        file_key="abc123",
        frame_node_id="12:34",
    )

    plan = plan_project_capture(tmp_path, document, references=(reference,))
    desktop = _breakpoint_plan(plan, "home", BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.VALID
    assert desktop.reference.interpretation is CanvasInterpretation.FULL_PAGE
    assert (desktop.reference.canvas_width, desktop.reference.canvas_height) == (1440, 6200)
    assert desktop.reference.viewport_width == 1440 and desktop.reference.viewport_height == 900


# ---------------------------------------------------------------------------
# Figma source, real adapter: only actually-observed frame ownership counts.


def _figma_text(node_id: str, characters: str, *, x: int, y: int, width: int = 400, height: int = 50) -> dict:
    return {
        "id": node_id,
        "type": "TEXT",
        "name": "Heading",
        "characters": characters,
        "absoluteBoundingBox": {"x": x, "y": y, "width": width, "height": height},
    }


def _figma_frame(frame_id: str, name: str, *, x: int, width: int, height: int, text_id: str) -> dict:
    return {
        "id": frame_id,
        "type": "FRAME",
        "name": name,
        "absoluteBoundingBox": {"x": x, "y": 0, "width": width, "height": height},
        "children": [
            {
                "id": f"{frame_id}:hero",
                "type": "FRAME",
                "name": "Hero",
                "absoluteBoundingBox": {"x": x, "y": 0, "width": width, "height": height // 2},
                "children": [_figma_text(text_id, "Welcome", x=x + 20, y=40)],
            }
        ],
    }


def _paired_figma_payload() -> dict:
    """A minimal real Figma payload: one page family, desktop + mobile frames."""

    return {
        "document": {
            "id": "0:0",
            "type": "DOCUMENT",
            "children": [
                {
                    "id": "1:0",
                    "type": "CANVAS",
                    "name": "Website",
                    "children": [
                        _figma_frame(
                            "1:1", "Home / Desktop", x=0, width=1440, height=900, text_id="1:2"
                        ),
                        _figma_frame(
                            "2:1", "Home / Mobile", x=1600, width=375, height=812, text_id="2:2"
                        ),
                    ],
                }
            ],
        }
    }


def _unpaired_figma_payload() -> dict:
    """A minimal real Figma payload with only a desktop frame -- no real mobile pair."""

    return {
        "document": {
            "id": "0:0",
            "type": "DOCUMENT",
            "children": [
                {
                    "id": "1:0",
                    "type": "CANVAS",
                    "name": "Website",
                    "children": [
                        _figma_frame(
                            "1:1", "Home / Desktop", x=0, width=1440, height=900, text_id="1:2"
                        ),
                    ],
                }
            ],
        }
    }


def _figma_export_reference(
    *, page_id: str, breakpoint: BreakpointName, file_key: str, frame_node_id: str, path: str,
    payload: bytes, width: int, height: int,
) -> StaticReference:
    return StaticReference(
        page_id=page_id,
        breakpoint=breakpoint,
        source_kind=StaticSourceKind.FIGMA,
        local_path=path,
        sha256=hashlib.sha256(payload).hexdigest(),
        canvas_width=width,
        canvas_height=height,
        viewport_width=width,
        viewport_height=height,
        interpretation=CanvasInterpretation.VIEWPORT,
        file_key=file_key,
        frame_node_id=frame_node_id,
    )


def test_real_figma_adapter_paired_desktop_and_mobile_exports_are_valid(tmp_path: Path) -> None:
    document = analyze_figma_document(
        _paired_figma_payload(), file_key="paired-fixture", captured_at=CAPTURED_AT
    )
    page = document.pages[0]

    desktop_provenance = page.provenance[0]
    assert desktop_provenance.file_key == "paired-fixture"
    assert desktop_provenance.frame_node_id == "1:1"
    mobile_observation = next(
        observation
        for observation in page.sections[0].responsive
        if observation.breakpoint == BreakpointName.MOBILE
    )
    assert mobile_observation.status is EvidenceStatus.OBSERVED
    mobile_provenance = mobile_observation.provenance[0]
    assert mobile_provenance.frame_node_id == "2:1"

    # Realistic 1x exports matching the real frames' own observed dimensions
    # -- a desktop 1440x900 and a mobile 375x812, never a resized thumbnail
    # and never the generic 390-wide canonical default.
    desktop_payload = _png_bytes(1440, 900)
    mobile_payload = _png_bytes(375, 812)
    (tmp_path / "sources").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sources/desktop.png").write_bytes(desktop_payload)
    (tmp_path / "sources/mobile.png").write_bytes(mobile_payload)

    desktop_reference = _figma_export_reference(
        page_id=page.id,
        breakpoint=BreakpointName.DESKTOP,
        file_key=desktop_provenance.file_key,
        frame_node_id=desktop_provenance.frame_node_id,
        path="sources/desktop.png",
        payload=desktop_payload,
        width=1440, height=900,
    )
    mobile_reference = _figma_export_reference(
        page_id=page.id,
        breakpoint=BreakpointName.MOBILE,
        file_key=mobile_provenance.file_key,
        frame_node_id=mobile_provenance.frame_node_id,
        path="sources/mobile.png",
        payload=mobile_payload,
        width=375, height=812,
    )

    plan = plan_project_capture(
        tmp_path, document, references=(desktop_reference, mobile_reference)
    )
    page_plan = next(item for item in plan.pages if item.page_id == page.id)
    assert _breakpoint_plan(plan, page.id, BreakpointName.DESKTOP).status is ReferenceStatus.VALID
    assert _breakpoint_plan(plan, page.id, BreakpointName.MOBILE).status is ReferenceStatus.VALID


def test_real_figma_adapter_rejects_export_with_wrong_frame_identity(tmp_path: Path) -> None:
    document = analyze_figma_document(
        _paired_figma_payload(), file_key="paired-fixture", captured_at=CAPTURED_AT
    )
    page = document.pages[0]

    payload = _png_bytes(16, 16)
    (tmp_path / "sources").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sources/wrong.png").write_bytes(payload)

    # The mobile frame's real id is "2:1"; claiming the desktop frame's id
    # for the mobile breakpoint must never be accepted.
    reference = _figma_export_reference(
        page_id=page.id,
        breakpoint=BreakpointName.MOBILE,
        file_key="paired-fixture",
        frame_node_id="1:1",
        path="sources/wrong.png",
        payload=payload,
        width=16, height=16,
    )

    plan = plan_project_capture(tmp_path, document, references=(reference,))
    mobile = _breakpoint_plan(plan, page.id, BreakpointName.MOBILE)
    assert mobile.status is ReferenceStatus.INVALID
    assert any("not backed by an observed frame" in message for message in mobile.diagnostics)


def test_real_figma_adapter_rejects_inferred_only_mobile_variant(tmp_path: Path) -> None:
    document = analyze_figma_document(
        _unpaired_figma_payload(), file_key="unpaired-fixture", captured_at=CAPTURED_AT
    )
    page = document.pages[0]

    mobile_observation = next(
        observation
        for observation in page.sections[0].responsive
        if observation.breakpoint == BreakpointName.MOBILE
    )
    assert mobile_observation.status is EvidenceStatus.INFERRED
    inferred_provenance = mobile_observation.provenance[0]
    # The adapter fabricates this fallback by repeating the desktop frame's
    # own id -- that repetition must never be mistaken for real ownership.
    assert inferred_provenance.frame_node_id == page.provenance[0].frame_node_id

    payload = _png_bytes(16, 16)
    (tmp_path / "sources").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sources/inferred.png").write_bytes(payload)

    reference = _figma_export_reference(
        page_id=page.id,
        breakpoint=BreakpointName.MOBILE,
        file_key=inferred_provenance.file_key,
        frame_node_id=inferred_provenance.frame_node_id,
        path="sources/inferred.png",
        payload=payload,
        width=16, height=16,
    )

    plan = plan_project_capture(tmp_path, document, references=(reference,))
    mobile = _breakpoint_plan(plan, page.id, BreakpointName.MOBILE)
    assert mobile.status is ReferenceStatus.INVALID
    assert any("not backed by an observed frame" in message for message in mobile.diagnostics)


# ---------------------------------------------------------------------------
# Figma frame-level dimension binding: a declared viewport/canvas must match
# the real, directly-observed frame -- never a section's bounds, never a
# scaled thumbnail, and never guessed when evidence is missing or conflicts.


def _no_matched_section_figma_payload() -> dict:
    """Desktop and mobile frames whose sections never pair: different roles,
    different text, no positional correspondence. Proves frame-level
    ownership never depends on a successful section match.
    """

    return {
        "document": {
            "id": "0:0",
            "type": "DOCUMENT",
            "children": [
                {
                    "id": "1:0",
                    "type": "CANVAS",
                    "name": "Website",
                    "children": [
                        {
                            "id": "1:1",
                            "type": "FRAME",
                            "name": "Home / Desktop",
                            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1440, "height": 900},
                            "children": [
                                {
                                    "id": "1:1:hero",
                                    "type": "FRAME",
                                    "name": "Hero",
                                    "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1440, "height": 450},
                                    "children": [_figma_text("1:2", "Welcome to the site", x=20, y=40)],
                                }
                            ],
                        },
                        {
                            "id": "2:1",
                            "type": "FRAME",
                            "name": "Home / Mobile",
                            "absoluteBoundingBox": {"x": 1600, "y": 0, "width": 375, "height": 812},
                            "children": [
                                {
                                    "id": "2:1:footer",
                                    "type": "FRAME",
                                    "name": "Footer",
                                    "absoluteBoundingBox": {"x": 1600, "y": 700, "width": 375, "height": 112},
                                    "children": [_figma_text("2:2", "Contact support at help desk", x=1620, y=740)],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    }


def test_figma_scaled_thumbnail_export_is_rejected_not_resized(tmp_path: Path) -> None:
    """A half-scale thumbnail of the real 1440x900 frame must never be silently rescaled."""

    page = _page(
        "home",
        source_reference="https://www.figma.com/file/abc123/Home",
        provenance=(
            _figma_page_provenance(file_key="abc123", frame_node_id="12:34", bounds=(1440, 900)),
        ),
    )
    document = _document(SourceKind.FIGMA, (page,))

    export_path = "sources/figma/home-thumbnail.png"
    payload = _png_bytes(720, 450)
    (tmp_path / export_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / export_path).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    reference = StaticReference(
        page_id="home",
        breakpoint=BreakpointName.DESKTOP,
        source_kind=StaticSourceKind.FIGMA,
        local_path=export_path,
        sha256=digest,
        canvas_width=720,
        canvas_height=450,
        viewport_width=720,
        viewport_height=450,
        interpretation=CanvasInterpretation.VIEWPORT,
        file_key="abc123",
        frame_node_id="12:34",
    )

    plan = plan_project_capture(tmp_path, document, references=(reference,))
    desktop = _breakpoint_plan(plan, "home", BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.INVALID
    assert any(
        "does not equal the observed frame dimensions" in message for message in desktop.diagnostics
    )


def test_figma_reference_without_observed_frame_bounds_is_rejected(tmp_path: Path) -> None:
    """Ownership alone is not enough: a frame with no recorded bounds is never guessed valid."""

    page = _page(
        "home",
        source_reference="https://www.figma.com/file/abc123/Home",
        provenance=(_figma_page_provenance(file_key="abc123", frame_node_id="12:34"),),
    )
    document = _document(SourceKind.FIGMA, (page,))

    export_path = "sources/figma/home-desktop.png"
    payload = _png_bytes(1440, 900)
    (tmp_path / export_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / export_path).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    reference = StaticReference(
        page_id="home",
        breakpoint=BreakpointName.DESKTOP,
        source_kind=StaticSourceKind.FIGMA,
        local_path=export_path,
        sha256=digest,
        canvas_width=1440,
        canvas_height=900,
        viewport_width=1440,
        viewport_height=900,
        interpretation=CanvasInterpretation.VIEWPORT,
        file_key="abc123",
        frame_node_id="12:34",
    )

    plan = plan_project_capture(tmp_path, document, references=(reference,))
    desktop = _breakpoint_plan(plan, "home", BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.INVALID
    assert any("no observed frame dimensions" in message for message in desktop.diagnostics)


def test_figma_conflicting_observed_frame_dimensions_are_rejected_as_ambiguous(tmp_path: Path) -> None:
    """Two directly-observed records disagreeing on a frame's size are never resolved by picking one."""

    page = _page(
        "home",
        source_reference="https://www.figma.com/file/abc123/Home",
        provenance=(
            _figma_page_provenance(file_key="abc123", frame_node_id="12:34", bounds=(1440, 900)),
            _figma_page_provenance(file_key="abc123", frame_node_id="12:34", bounds=(1441, 900)),
        ),
    )
    document = _document(SourceKind.FIGMA, (page,))

    export_path = "sources/figma/home-desktop.png"
    payload = _png_bytes(1440, 900)
    (tmp_path / export_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / export_path).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    reference = StaticReference(
        page_id="home",
        breakpoint=BreakpointName.DESKTOP,
        source_kind=StaticSourceKind.FIGMA,
        local_path=export_path,
        sha256=digest,
        canvas_width=1440,
        canvas_height=900,
        viewport_width=1440,
        viewport_height=900,
        interpretation=CanvasInterpretation.VIEWPORT,
        file_key="abc123",
        frame_node_id="12:34",
    )

    plan = plan_project_capture(tmp_path, document, references=(reference,))
    desktop = _breakpoint_plan(plan, "home", BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.INVALID
    assert any("ambiguous" in message for message in desktop.diagnostics)


def test_figma_section_bounds_are_never_substituted_for_frame_bounds(tmp_path: Path) -> None:
    """The hero section is half the frame's height; only the frame's own bounds may validate."""

    document = analyze_figma_document(
        _paired_figma_payload(), file_key="paired-fixture", captured_at=CAPTURED_AT
    )
    page = document.pages[0]
    desktop_provenance = page.provenance[0]
    assert desktop_provenance.bounds is not None
    assert (desktop_provenance.bounds.width, desktop_provenance.bounds.height) == (1440, 900)

    # 1440x450 is the hero section's own height (frame height // 2 in
    # `_figma_frame`), not the frame's.
    payload = _png_bytes(1440, 450)
    (tmp_path / "sources").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sources/section-sized.png").write_bytes(payload)

    reference = _figma_export_reference(
        page_id=page.id,
        breakpoint=BreakpointName.DESKTOP,
        file_key=desktop_provenance.file_key,
        frame_node_id=desktop_provenance.frame_node_id,
        path="sources/section-sized.png",
        payload=payload,
        width=1440, height=450,
    )

    plan = plan_project_capture(tmp_path, document, references=(reference,))
    desktop = _breakpoint_plan(plan, page.id, BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.INVALID
    assert any(
        "does not equal the observed frame dimensions" in message for message in desktop.diagnostics
    )


def test_figma_frame_level_ownership_survives_when_no_section_pairs(tmp_path: Path) -> None:
    """A real mobile frame with no matched section is still validatable by its own frame identity."""

    document = analyze_figma_document(
        _no_matched_section_figma_payload(), file_key="unpaired-sections-fixture", captured_at=CAPTURED_AT
    )
    page = document.pages[0]
    assert page.sections[0].responsive == []

    mobile_frame_provenance = next(
        item for item in page.provenance if item.viewport == BreakpointName.MOBILE
    )
    assert mobile_frame_provenance.frame_node_id == "2:1"
    assert mobile_frame_provenance.bounds is not None
    assert (mobile_frame_provenance.bounds.width, mobile_frame_provenance.bounds.height) == (375, 812)

    payload = _png_bytes(375, 812)
    (tmp_path / "sources").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sources/mobile.png").write_bytes(payload)

    reference = _figma_export_reference(
        page_id=page.id,
        breakpoint=BreakpointName.MOBILE,
        file_key=mobile_frame_provenance.file_key,
        frame_node_id=mobile_frame_provenance.frame_node_id,
        path="sources/mobile.png",
        payload=payload,
        width=375, height=812,
    )

    plan = plan_project_capture(tmp_path, document, references=(reference,))
    mobile = _breakpoint_plan(plan, page.id, BreakpointName.MOBILE)
    assert mobile.status is ReferenceStatus.VALID


def test_real_figma_adapter_full_page_export_matches_the_frame_exactly(tmp_path: Path) -> None:
    """A FULL_PAGE canvas must equal the real frame's own dimensions, not the assumed viewport."""

    document = analyze_figma_document(
        _paired_figma_payload(), file_key="paired-fixture", captured_at=CAPTURED_AT
    )
    page = document.pages[0]
    desktop_provenance = page.provenance[0]

    payload = _png_bytes(1440, 900)  # the real frame's own, full dimensions
    (tmp_path / "sources").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sources/full.png").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    reference = StaticReference(
        page_id=page.id,
        breakpoint=BreakpointName.DESKTOP,
        source_kind=StaticSourceKind.FIGMA,
        local_path="sources/full.png",
        sha256=digest,
        canvas_width=1440,
        canvas_height=900,
        viewport_width=1440,
        viewport_height=700,  # explicit, shorter assumed viewing height
        interpretation=CanvasInterpretation.FULL_PAGE,
        file_key=desktop_provenance.file_key,
        frame_node_id=desktop_provenance.frame_node_id,
    )

    plan = plan_project_capture(tmp_path, document, references=(reference,))
    desktop = _breakpoint_plan(plan, page.id, BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.VALID


# ---------------------------------------------------------------------------
# Declared canvas interpretation: never resized, always internally consistent.


def test_viewport_interpretation_requires_canvas_to_equal_viewport(tmp_path: Path) -> None:
    page = _page("home", source_reference="https://agency.example/")
    document = _document(SourceKind.LIVE_HTML, (page,))
    payload = _png_bytes(1440, 2000)
    (tmp_path / "sources").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sources/mismatch.png").write_bytes(payload)
    reference = StaticReference(
        page_id="home",
        breakpoint=BreakpointName.DESKTOP,
        source_kind=StaticSourceKind.IMAGE,
        local_path="sources/mismatch.png",
        sha256=hashlib.sha256(payload).hexdigest(),
        canvas_width=1440,
        canvas_height=2000,
        viewport_width=1440,
        viewport_height=900,
        interpretation=CanvasInterpretation.VIEWPORT,
    )

    plan = plan_project_capture(tmp_path, document, references=(reference,))
    desktop = _breakpoint_plan(plan, "home", BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.INVALID
    assert any("VIEWPORT" in message for message in desktop.diagnostics)


def test_full_page_interpretation_rejects_a_narrower_or_shorter_canvas(tmp_path: Path) -> None:
    page = _page("home", source_reference="https://agency.example/")
    document = _document(SourceKind.LIVE_HTML, (page,))
    payload = _png_bytes(1024, 700)
    (tmp_path / "sources").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sources/short.png").write_bytes(payload)
    reference = StaticReference(
        page_id="home",
        breakpoint=BreakpointName.DESKTOP,
        source_kind=StaticSourceKind.IMAGE,
        local_path="sources/short.png",
        sha256=hashlib.sha256(payload).hexdigest(),
        canvas_width=1024,
        canvas_height=700,
        viewport_width=1440,
        viewport_height=900,
        interpretation=CanvasInterpretation.FULL_PAGE,
    )

    plan = plan_project_capture(tmp_path, document, references=(reference,))
    desktop = _breakpoint_plan(plan, "home", BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.INVALID
    assert any("FULL_PAGE" in message for message in desktop.diagnostics)


# ---------------------------------------------------------------------------
# Image-adapter metadata: ambiguity and malformed declarations are invalid,
# not silently treated as absent.


def test_ambiguous_image_metadata_candidates_reject_instead_of_choosing_first(
    tmp_path: Path,
) -> None:
    document = _image_document(tmp_path, width=1440, height=900)
    page_id = document.pages[0].id
    duplicate_entries = list(document.source.metadata["images"])
    duplicate_entries.append(dict(duplicate_entries[0]))
    document = document.model_copy(
        update={
            "source": document.source.model_copy(
                update={"metadata": {**document.source.metadata, "images": duplicate_entries}}
            )
        }
    )

    plan = plan_project_capture(tmp_path, document)

    desktop = _breakpoint_plan(plan, page_id, BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.INVALID
    assert any("ambiguous" in message for message in desktop.diagnostics)


def test_malformed_declared_image_metadata_is_invalid_not_missing(tmp_path: Path) -> None:
    document = _image_document(tmp_path, width=1440, height=900)
    page_id = document.pages[0].id
    entries = list(document.source.metadata["images"])
    malformed = dict(entries[0])
    malformed.pop("viewport", None)
    document = document.model_copy(
        update={
            "source": document.source.model_copy(
                update={"metadata": {**document.source.metadata, "images": [malformed]}}
            )
        }
    )

    plan = plan_project_capture(tmp_path, document)

    desktop = _breakpoint_plan(plan, page_id, BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.INVALID
    assert desktop.diagnostics
    assert "no reference declared" not in desktop.diagnostics[0]


# ---------------------------------------------------------------------------
# Explicit reference ownership: exact binding, duplicates, and unknown pages.


def _valid_image_reference(page_id: str, breakpoint: BreakpointName, path: str, payload: bytes) -> StaticReference:
    digest = hashlib.sha256(payload).hexdigest()
    return StaticReference(
        page_id=page_id,
        breakpoint=breakpoint,
        source_kind=StaticSourceKind.IMAGE,
        local_path=path,
        sha256=digest,
        canvas_width=1440,
        canvas_height=900,
        viewport_width=1440,
        viewport_height=900,
        interpretation=CanvasInterpretation.VIEWPORT,
    )


def test_explicit_reference_unknown_page_is_rejected_diagnostically_without_crashing(tmp_path: Path) -> None:
    page = _page("home", source_reference="https://agency.example/", breakpoints=(BreakpointName.DESKTOP,))
    document = _document(SourceKind.LIVE_HTML, (page,))

    payload = _png_bytes(1440, 900)
    (tmp_path / "sources/ghost.png").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "sources/ghost.png").write_bytes(payload)
    ghost = _valid_image_reference("ghost-page", BreakpointName.DESKTOP, "sources/ghost.png", payload)

    plan = plan_project_capture(tmp_path, document, references=(ghost,))

    assert any("unknown page" in message for message in plan.diagnostics)
    # The real page is unaffected by the rejected reference for an unrelated page.
    assert _breakpoint_plan(plan, "home", BreakpointName.DESKTOP).status is ReferenceStatus.VALID


def test_conflicting_explicit_reference_ownership_is_rejected_for_both_entries(tmp_path: Path) -> None:
    page = _page("home", source_reference="https://agency.example/")
    document = _document(SourceKind.LIVE_HTML, (page,))

    payload_a = _png_bytes(1440, 900)
    payload_b = _png_bytes(1280, 800)
    (tmp_path / "sources").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sources/a.png").write_bytes(payload_a)
    (tmp_path / "sources/b.png").write_bytes(payload_b)
    first = _valid_image_reference("home", BreakpointName.DESKTOP, "sources/a.png", payload_a)
    second = StaticReference(
        page_id="home",
        breakpoint=BreakpointName.DESKTOP,
        source_kind=StaticSourceKind.IMAGE,
        local_path="sources/b.png",
        sha256=hashlib.sha256(payload_b).hexdigest(),
        canvas_width=1280,
        canvas_height=800,
        viewport_width=1280,
        viewport_height=800,
        interpretation=CanvasInterpretation.VIEWPORT,
    )

    plan = plan_project_capture(tmp_path, document, references=(first, second))

    assert any("duplicate" in message for message in plan.diagnostics)
    desktop = _breakpoint_plan(plan, "home", BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.INVALID
    assert desktop.reference is None


def test_explicit_static_reference_binds_exact_page_frame_breakpoint_and_hash(tmp_path: Path) -> None:
    page = _page("home", source_reference="https://agency.example/")
    document = _document(SourceKind.LIVE_HTML, (page,))
    payload = _png_bytes(768, 1024)
    (tmp_path / "sources").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sources/tablet.png").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    reference = StaticReference(
        page_id="home",
        breakpoint=BreakpointName.TABLET,
        source_kind=StaticSourceKind.IMAGE,
        local_path="sources/tablet.png",
        sha256=digest,
        canvas_width=768,
        canvas_height=1024,
        viewport_width=768,
        viewport_height=1024,
        interpretation=CanvasInterpretation.VIEWPORT,
    )

    plan = plan_project_capture(tmp_path, document, references=(reference,))

    tablet = _breakpoint_plan(plan, "home", BreakpointName.TABLET)
    assert tablet.status is ReferenceStatus.VALID
    assert tablet.reference.sha256 == digest
    assert tablet.reference.page_id == "home"
    assert tablet.reference.breakpoint is BreakpointName.TABLET
    assert tablet.is_canonical_viewport is True
    # Desktop and mobile were never claimed by this reference.
    for breakpoint in (BreakpointName.DESKTOP, BreakpointName.MOBILE):
        assert _breakpoint_plan(plan, "home", breakpoint).status is ReferenceStatus.NOT_DECLARED


# ---------------------------------------------------------------------------
# Local file validation: missing files and workspace/symlink escapes.


def test_missing_local_static_reference_file_is_rejected_diagnostically(tmp_path: Path) -> None:
    page = _page("home", source_reference="https://agency.example/")
    document = _document(SourceKind.LIVE_HTML, (page,))
    reference = _valid_image_reference("home", BreakpointName.DESKTOP, "sources/does-not-exist.png", b"unused")

    plan = plan_project_capture(tmp_path, document, references=(reference,))

    desktop = _breakpoint_plan(plan, "home", BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.INVALID
    assert desktop.diagnostics


@pytest.mark.skipif(os.name == "nt", reason="symlink escape uses a POSIX symlink")
def test_symlink_escape_in_a_static_reference_path_is_rejected_diagnostically(tmp_path: Path) -> None:
    page = _page("home", source_reference="https://agency.example/")
    document = _document(SourceKind.LIVE_HTML, (page,))

    secret = tmp_path.parent / "secret-capture-plan.png"
    payload = _png_bytes(1440, 900)
    secret.write_bytes(payload)
    link = tmp_path / "sources" / "escape.png"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(secret)

    reference = _valid_image_reference("home", BreakpointName.DESKTOP, "sources/escape.png", payload)

    plan = plan_project_capture(tmp_path, document, references=(reference,))

    desktop = _breakpoint_plan(plan, "home", BreakpointName.DESKTOP)
    assert desktop.status is ReferenceStatus.INVALID
    assert any("escapes" in message for message in desktop.diagnostics)


# ---------------------------------------------------------------------------
# Plan structure: complete page/breakpoint enumeration.


def test_plan_enumerates_every_document_page_exactly_once(tmp_path: Path) -> None:
    pages = (
        _page("home", source_reference="https://agency.example/", breakpoints=(BreakpointName.DESKTOP,)),
        _page("about", source_reference="not-a-url"),
    )
    document = _document(SourceKind.LIVE_HTML, pages)

    plan = plan_project_capture(tmp_path, document)

    assert sorted(item.page_id for item in plan.pages) == ["about", "home"]
    for page_plan in plan.pages:
        assert [entry.breakpoint for entry in page_plan.breakpoints] == list(REQUIRED_BREAKPOINTS)


# ---------------------------------------------------------------------------
# Zero writes, zero network, zero credential/browser/portal access.


def test_planning_performs_zero_writes(tmp_path: Path) -> None:
    document = _image_document(tmp_path, width=1440, height=900)

    before = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file()
    }

    plan_project_capture(tmp_path, document)
    plan_project_capture(tmp_path, document, references=())

    after_paths = {path for path in tmp_path.rglob("*") if path.is_file()}
    after = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file()
    }
    assert after_paths == set(before)
    assert after == before


def test_planning_never_opens_a_network_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    document = _image_document(tmp_path, width=1440, height=900)

    def _forbidden_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("plan_project_capture must never open a network connection")

    monkeypatch.setattr(socket.socket, "connect", _forbidden_connect)

    plan = plan_project_capture(tmp_path, document)
    assert plan.pages  # still produced a real plan without any network access


def test_module_never_imports_config_auth_client_or_browser_dependencies() -> None:
    import vanjaro_cli.orchestration.project_capture_plan as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    forbidden = [
        "vanjaro_cli.config",
        "vanjaro_cli.auth",
        "vanjaro_cli.client",
        "playwright",
        "import requests",
    ]
    for token in forbidden:
        assert token not in source, f"unexpected dependency on {token!r}"
