"""Contract tests for the immutable live/static source-reference types.

These types are pure data: constructing one is the only validation that
happens here. No filesystem or network access is exercised by this module,
and none of these tests need it -- `test_project_capture_plan.py` covers the
read-only local-file validation layer built on top of these contracts.
"""

from __future__ import annotations

import pytest

from vanjaro_cli.design.capture_references import (
    CanvasInterpretation,
    InvalidReferenceError,
    LiveReference,
    StaticReference,
    StaticSourceKind,
)
from vanjaro_cli.design.models import BreakpointName

SHA = "a" * 64


# ---------------------------------------------------------------------------
# LiveReference


def test_live_reference_accepts_a_plain_https_url_and_positive_viewport() -> None:
    reference = LiveReference(
        page_id="home",
        breakpoint=BreakpointName.DESKTOP,
        url="https://agency.example/",
        viewport_width=1440,
        viewport_height=900,
    )
    assert reference.url == "https://agency.example/"
    assert reference.viewport_width == 1440
    assert reference.viewport_height == 900
    assert reference.breakpoint is BreakpointName.DESKTOP


def test_live_reference_accepts_an_arbitrary_valid_viewport_size() -> None:
    # Not every honest live viewport is a canonical breakpoint width; the
    # reference contract itself must not reject a real, positive size just
    # because it is noncanonical -- that judgment belongs to planning.
    reference = LiveReference(
        page_id="home",
        breakpoint=BreakpointName.DESKTOP,
        url="https://agency.example/",
        viewport_width=1280,
        viewport_height=832,
    )
    assert (reference.viewport_width, reference.viewport_height) == (1280, 832)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://agency.example/",
        "javascript:alert(1)",
        "not-a-url",
        "",
        "http://",
        "http://user:pass@agency.example/",
    ],
)
def test_live_reference_rejects_non_http_or_credentialed_urls(url: str) -> None:
    with pytest.raises(InvalidReferenceError):
        LiveReference(
            page_id="home",
            breakpoint=BreakpointName.DESKTOP,
            url=url,
            viewport_width=1440,
            viewport_height=900,
        )


def test_live_reference_rejects_empty_page_id() -> None:
    with pytest.raises(InvalidReferenceError):
        LiveReference(
            page_id="   ",
            breakpoint=BreakpointName.DESKTOP,
            url="https://agency.example/",
            viewport_width=1440,
            viewport_height=900,
        )


@pytest.mark.parametrize("width", [True, False])
def test_live_reference_rejects_bool_viewport_width(width: object) -> None:
    # bool is a subclass of int in Python; a stray True/False must never
    # pass itself off as viewport width 1/0.
    with pytest.raises(InvalidReferenceError):
        LiveReference(
            page_id="home",
            breakpoint=BreakpointName.DESKTOP,
            url="https://agency.example/",
            viewport_width=width,
            viewport_height=900,
        )


@pytest.mark.parametrize("height", [0, -1, -900])
def test_live_reference_rejects_non_positive_viewport_height(height: int) -> None:
    with pytest.raises(InvalidReferenceError):
        LiveReference(
            page_id="home",
            breakpoint=BreakpointName.DESKTOP,
            url="https://agency.example/",
            viewport_width=1440,
            viewport_height=height,
        )


def test_live_reference_is_immutable() -> None:
    reference = LiveReference(
        page_id="home",
        breakpoint=BreakpointName.DESKTOP,
        url="https://agency.example/",
        viewport_width=1440,
        viewport_height=900,
    )
    with pytest.raises(AttributeError):
        reference.viewport_width = 1280  # type: ignore[misc]


# ---------------------------------------------------------------------------
# StaticReference -- image exports


def _image_reference(**overrides: object) -> StaticReference:
    fields: dict[str, object] = dict(
        page_id="home",
        breakpoint=BreakpointName.DESKTOP,
        source_kind=StaticSourceKind.IMAGE,
        local_path="sources/home-desktop.png",
        sha256=SHA,
        canvas_width=1440,
        canvas_height=900,
        viewport_width=1440,
        viewport_height=900,
        interpretation=CanvasInterpretation.VIEWPORT,
    )
    fields.update(overrides)
    return StaticReference(**fields)


def test_image_static_reference_keeps_canvas_and_viewport_dimensions_distinct() -> None:
    reference = _image_reference(canvas_width=1440, canvas_height=5400, viewport_width=1440, viewport_height=900)
    assert (reference.canvas_width, reference.canvas_height) == (1440, 5400)
    assert (reference.viewport_width, reference.viewport_height) == (1440, 900)


def test_image_static_reference_preserves_noncanonical_1280_desktop_metadata() -> None:
    # A real 1280px desktop capture is valid reference metadata in its own
    # right; whether it earns canonical 1440px credit is a planning-layer
    # judgment, not something this contract enforces or blocks.
    reference = _image_reference(canvas_width=1280, canvas_height=800, viewport_width=1280, viewport_height=800)
    assert (reference.viewport_width, reference.viewport_height) == (1280, 800)


def test_full_page_interpretation_is_explicit_and_not_inferred_from_dimensions() -> None:
    # A full-page capture's canvas is taller than any single viewport, but
    # nothing here infers that from the numbers -- the caller must say so.
    reference = _image_reference(
        canvas_width=1440,
        canvas_height=6200,
        viewport_width=1440,
        viewport_height=900,
        interpretation=CanvasInterpretation.FULL_PAGE,
    )
    assert reference.interpretation is CanvasInterpretation.FULL_PAGE

    viewport_reference = _image_reference(
        canvas_width=1440, canvas_height=900, interpretation=CanvasInterpretation.VIEWPORT
    )
    assert viewport_reference.interpretation is CanvasInterpretation.VIEWPORT


def test_static_reference_requires_an_explicit_canvasinterpretation_enum_member() -> None:
    with pytest.raises(InvalidReferenceError):
        _image_reference(interpretation="full_page")  # a raw string is not the enum


def test_static_reference_requires_interpretation_argument() -> None:
    with pytest.raises(TypeError):
        StaticReference(
            page_id="home",
            breakpoint=BreakpointName.DESKTOP,
            source_kind=StaticSourceKind.IMAGE,
            local_path="sources/home-desktop.png",
            sha256=SHA,
            canvas_width=1440,
            canvas_height=900,
            viewport_width=1440,
            viewport_height=900,
        )


@pytest.mark.parametrize("width", [True, False])
def test_static_reference_rejects_bool_canvas_width(width: object) -> None:
    with pytest.raises(InvalidReferenceError):
        _image_reference(canvas_width=width)


@pytest.mark.parametrize("value", [0, -1])
def test_static_reference_rejects_non_positive_canvas_or_viewport_dimensions(value: int) -> None:
    with pytest.raises(InvalidReferenceError):
        _image_reference(canvas_height=value)
    with pytest.raises(InvalidReferenceError):
        _image_reference(viewport_width=value)


@pytest.mark.parametrize(
    "bad_hash",
    ["", "not-hex", "a" * 63, "a" * 65, "g" * 64],
)
def test_static_reference_rejects_malformed_sha256(bad_hash: str) -> None:
    with pytest.raises(InvalidReferenceError):
        _image_reference(sha256=bad_hash)


def test_static_reference_normalizes_uppercase_sha256() -> None:
    reference = _image_reference(sha256=SHA.upper())
    assert reference.sha256 == SHA


@pytest.mark.parametrize(
    "bad_path",
    ["", "/etc/passwd", "C:/Windows/system32", "../outside.png", "sources/../../outside.png"],
)
def test_static_reference_rejects_absolute_or_traversal_local_paths(bad_path: str) -> None:
    with pytest.raises(InvalidReferenceError):
        _image_reference(local_path=bad_path)


def test_image_static_reference_rejects_figma_frame_identity() -> None:
    with pytest.raises(InvalidReferenceError):
        _image_reference(file_key="some-figma-file")
    with pytest.raises(InvalidReferenceError):
        _image_reference(frame_node_id="1:23")


# ---------------------------------------------------------------------------
# StaticReference -- Figma exports


def _figma_reference(**overrides: object) -> StaticReference:
    fields: dict[str, object] = dict(
        page_id="home",
        breakpoint=BreakpointName.DESKTOP,
        source_kind=StaticSourceKind.FIGMA,
        local_path="sources/figma/home-desktop.png",
        sha256=SHA,
        canvas_width=1440,
        canvas_height=900,
        viewport_width=1440,
        viewport_height=900,
        interpretation=CanvasInterpretation.VIEWPORT,
        file_key="abc123figmafile",
        frame_node_id="12:34",
    )
    fields.update(overrides)
    return StaticReference(**fields)


def test_figma_static_reference_keeps_frame_identity_and_source_design_identity_distinct_from_hash() -> None:
    reference = _figma_reference()
    assert reference.file_key == "abc123figmafile"
    assert reference.frame_node_id == "12:34"
    assert reference.sha256 == SHA
    assert reference.file_key != reference.sha256
    assert reference.frame_node_id != reference.sha256


def test_figma_static_reference_requires_file_key_and_frame_node_id() -> None:
    with pytest.raises(InvalidReferenceError):
        _figma_reference(file_key=None)
    with pytest.raises(InvalidReferenceError):
        _figma_reference(frame_node_id=None)
    with pytest.raises(InvalidReferenceError):
        _figma_reference(file_key="   ")


def test_static_reference_rejects_unknown_source_kind() -> None:
    with pytest.raises(InvalidReferenceError):
        _image_reference(source_kind="image")  # a raw string is not the enum
