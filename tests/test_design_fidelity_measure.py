"""Contracts for measuring a built page without requiring a browser."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vanjaro_cli.design.fidelity_measure import (
    MEASURE_SCRIPT,
    MeasurementError,
    PlaywrightPageMeasurer,
    parse_measured_page,
)
from vanjaro_cli.design.models import BreakpointName


def _payload(**overrides) -> dict:
    section = {
        "section_id": "home.s1",
        "order": 0,
        "bounds": {"x": 0, "y": 120, "width": 1440, "height": 560},
        "columns": 3,
        "background_color": "rgb(255, 255, 255)",
        "text_color": "rgb(17, 17, 17)",
        "accent_color": "rgb(255, 85, 0)",
        "typography": {
            "heading": {"family": "Inter", "size_px": 48, "weight": 700},
            "body": {"family": "Inter", "size_px": 16, "weight": 400},
        },
        "padding_top": 64,
        "padding_bottom": 64,
        "element_gap": 24,
        "horizontal_overflow_px": 0,
        "media": [],
        "text_samples": ["Services", "We plan and build."],
    }
    section.update(overrides)
    return {"console_error_count": None, "sections": [section]}


def _parse(**overrides):
    return parse_measured_page(_payload(**overrides), viewport_width=1440)


def test_a_measured_section_carries_every_signal_the_metrics_need() -> None:
    section = _parse().sections[0]

    assert section.section_id == "home.s1"
    assert section.bounds is not None and section.bounds.height == 560
    assert section.columns == 3
    assert section.background_color == "#ffffff"
    assert section.typography["heading"].size_px == 48
    assert section.padding_top == 64
    assert section.element_gap == 24


def test_sections_without_an_identity_are_skipped() -> None:
    payload = _payload()
    payload["sections"].append({"order": 1, "bounds": None})

    assert len(parse_measured_page(payload, viewport_width=1440).sections) == 1


def test_a_transparent_background_is_not_reported_as_a_painted_colour() -> None:
    # Transparent means the section inherits what is behind it, which cannot be
    # attributed to this section; reporting it as black would be fabricated.
    assert _parse(background_color="rgba(0, 0, 0, 0)").sections[0].background_color is None


@pytest.mark.parametrize("declared", ["transparent", "none", "", "   "])
def test_non_colours_are_unavailable_rather_than_measured(declared: str) -> None:
    assert _parse(background_color=declared).sections[0].background_color is None


def test_an_opaque_colour_with_alpha_keeps_its_channels() -> None:
    # What partial alpha composites against is not knowable from this element,
    # so the RGB channels are the honest measurement.
    assert _parse(background_color="rgba(0, 0, 0, 0.5)").sections[0].background_color == "#000000"


def test_computed_rgb_is_normalized_to_the_hex_the_palette_contract_requires() -> None:
    # Browsers report rgb(); the design side carries hex. Unit tests using hex
    # fixtures never caught this — only a real page did.
    section = _parse(background_color="rgb(255, 255, 255)", text_color="rgb(17, 17, 17)").sections[0]

    assert section.background_color == "#ffffff"
    assert section.text_color == "#111111"


def test_an_unrecognized_colour_form_is_not_a_measurement() -> None:
    assert _parse(background_color="color(display-p3 1 0 0)").sections[0].background_color is None


def test_measured_zero_padding_survives_the_round_trip() -> None:
    section = _parse(padding_top=0, padding_bottom=0).sections[0]

    assert section.padding_top == 0.0
    assert section.padding_bottom == 0.0


def test_missing_numbers_stay_unavailable() -> None:
    section = _parse(padding_top=None, element_gap=None, columns=None).sections[0]

    assert section.padding_top is None
    assert section.element_gap is None
    assert section.columns is None


def test_bounds_without_a_size_are_not_geometry() -> None:
    assert _parse(bounds={"x": 0, "y": 0}).sections[0].bounds is None


def test_type_samples_with_no_evidence_are_omitted() -> None:
    section = _parse(
        typography={"heading": {"family": None, "size_px": None, "weight": None}}
    ).sections[0]

    assert section.typography == {}


def test_a_zero_sized_image_is_not_an_aspect_ratio_measurement() -> None:
    section = _parse(
        media=[{"rendered_width": 0, "rendered_height": 0, "natural_width": 800}]
    ).sections[0]

    assert section.media == ()


def test_media_carries_intrinsic_size_and_focal_point() -> None:
    section = _parse(
        media=[
            {
                "rendered_width": 800,
                "rendered_height": 450,
                "natural_width": 1600,
                "natural_height": 900,
                "focal_x": 0.5,
                "focal_y": 0.25,
            }
        ]
    ).sections[0]

    assert section.media[0].natural_width == 1600
    assert section.media[0].focal_x == 0.5
    assert section.media[0].focal_y == 0.25


def test_focal_values_outside_the_unit_range_are_rejected() -> None:
    section = _parse(
        media=[{"rendered_width": 8, "rendered_height": 4, "focal_x": 1.8}]
    ).sections[0]

    assert section.media[0].focal_x is None


def test_placeholder_copy_is_detected_with_the_planner_vocabulary() -> None:
    section = _parse(
        text_samples=["Lorem ipsum dolor sit amet", "Real copy", "  "]
    ).sections[0]

    assert section.placeholder_leaks == ("Lorem ipsum dolor sit amet",)


def test_empty_text_slots_are_counted() -> None:
    section = _parse(text_samples=["Services", "", "   ", "Copy"]).sections[0]

    assert section.empty_slot_count == 2


def test_the_measurement_script_selects_outermost_section_roots() -> None:
    # Nested components carry the same attribute; measuring both would score
    # one section twice.
    assert "data-agency-section" in MEASURE_SCRIPT
    assert "closest('[data-agency-section]')" in MEASURE_SCRIPT


class _FakePage:
    def __init__(self, payload, *, fail_networkidle: bool = False) -> None:
        self.payload = payload
        self.fail_networkidle = fail_networkidle
        self.goto_waits: list[str] = []
        self.settled = False

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.goto_waits.append(wait_until)
        if wait_until == "networkidle" and self.fail_networkidle:
            raise TimeoutError("networkidle never reached")

    def evaluate(self, script: str):
        return self.payload


def _measurer(page, **kwargs) -> PlaywrightPageMeasurer:
    @contextmanager
    def factory(*, viewport):
        page.viewport = viewport
        yield page

    def settle(target, timeout_ms):
        target.settled = True

    return PlaywrightPageMeasurer(session_factory=factory, settle=settle, **kwargs)


def test_measuring_settles_the_page_and_uses_the_canonical_viewport() -> None:
    page = _FakePage(_payload())

    result = _measurer(page).measure("https://build.example/", BreakpointName.MOBILE)

    assert page.settled is True
    assert page.viewport == (390, 844)
    assert result.viewport_width == 390
    assert result.sections[0].section_id == "home.s1"


def test_a_networkidle_timeout_falls_back_to_load_rather_than_failing() -> None:
    page = _FakePage(_payload(), fail_networkidle=True)

    result = _measurer(page).measure("https://build.example/", BreakpointName.DESKTOP)

    assert page.goto_waits == ["networkidle", "load"]
    assert result.sections


def test_a_non_object_payload_is_a_measurement_failure_not_an_empty_page() -> None:
    with pytest.raises(MeasurementError, match="non-object payload"):
        _measurer(_FakePage("not-a-mapping")).measure(
            "https://build.example/", BreakpointName.DESKTOP
        )


def test_a_browser_failure_is_reported_as_a_measurement_error() -> None:
    class _Broken(_FakePage):
        def evaluate(self, script: str):
            raise RuntimeError("execution context destroyed")

    with pytest.raises(MeasurementError, match="execution context destroyed"):
        _measurer(_Broken(None)).measure("https://build.example/", BreakpointName.DESKTOP)


def test_console_errors_are_counted_when_the_page_reports_them() -> None:
    class _Chatty(_FakePage):
        def on(self, event: str, handler) -> None:
            if event == "pageerror":
                handler("ReferenceError: x is not defined")

    result = _measurer(_Chatty(_payload())).measure(
        "https://build.example/", BreakpointName.DESKTOP
    )

    assert result.console_error_count == 1


def test_a_page_without_console_listeners_still_measures() -> None:
    result = _measurer(_FakePage(_payload())).measure(
        "https://build.example/", BreakpointName.DESKTOP
    )

    assert result.console_error_count == 0
    assert result.sections


def test_the_measure_script_counts_columns_from_geometry() -> None:
    """`gridTemplateColumns` sees only an explicit grid. The build is Bootstrap
    flex throughout, so the column subscore contributed on no section at any
    breakpoint — a quarter of the layout dimension, dark everywhere.

    The script only runs in a browser, so this pins its intent; the behaviour is
    verified against the live pilot in the progress log.
    """

    script = MEASURE_SCRIPT

    assert "const columnCount = (node, style) =>" in script
    # An explicit grid still states the author's intent and wins.
    assert "gridTemplateColumns.split(' ')" in script
    # Otherwise measure what is actually side by side.
    assert "getBoundingClientRect" in script


def test_the_column_count_guards_against_incidental_pairings() -> None:
    """Columns are siblings of similar width that together span the section. A
    heading beside a badge fails the first guard, two inline links the second."""

    block = MEASURE_SCRIPT[MEASURE_SCRIPT.index("const columnCount") :]

    assert "mean * 0.25" in block
    assert "sectionWidth * 0.5" in block


def test_a_single_stack_reports_one_column_not_unmeasured() -> None:
    """The design side states 1 for a collapsed breakpoint. Reporting null would
    leave the subscore unmeasured exactly where the comparison matters most."""

    block = MEASURE_SCRIPT[MEASURE_SCRIPT.index("const columnCount") :]

    assert "hasContent ? 1 : null" in block


def test_body_copy_is_found_by_shape_not_by_tag() -> None:
    """The source writes <p>; Vanjaro renders <div class="vj-text">, so a `p`
    selector found nothing on the build and typography compared one sample of
    two on every section. A <p> still wins when present, because it states the
    author's intent."""

    block = MEASURE_SCRIPT[MEASURE_SCRIPT.index("const bodyElement") :]

    assert "root.querySelector('p')" in block
    assert "el.children.length" in block
    assert "H[1-6]|A|BUTTON" in block


def test_both_scripts_define_body_copy_the_same_way() -> None:
    """Three dimensions have now been dark because the two sides sampled
    different things. They must agree by construction."""

    from vanjaro_cli.design import html_adapter

    for script in (MEASURE_SCRIPT, html_adapter._RENDERED_OBSERVATION_JS):
        block = script[script.index("const bodyElement") :]
        assert "root.querySelector('p')" in block
        assert "H[1-6]|A|BUTTON" in block


def test_element_gap_is_measured_not_read_from_row_gap() -> None:
    """`row-gap` applies only to flex and grid containers and computes to
    `normal` everywhere else, so both sides reported nothing on every section
    while the spacing between elements was plainly visible."""

    block = MEASURE_SCRIPT[MEASURE_SCRIPT.index("const elementGap") :]

    assert "parseFloat(style.rowGap)" in block
    assert "current.top - previous.bottom" in block


def test_a_declared_gap_still_wins() -> None:
    """It states intent; the geometric median is the fallback."""

    block = MEASURE_SCRIPT[MEASURE_SCRIPT.index("const elementGap") :]
    declared = block.index("Number.isFinite(declared)")
    measured = block.index("current.top - previous.bottom")

    assert declared < measured


def test_both_scripts_measure_the_gap_the_same_way() -> None:
    from vanjaro_cli.design import html_adapter

    for script in (MEASURE_SCRIPT, html_adapter._RENDERED_OBSERVATION_JS):
        block = script[script.index("const elementGap") :]
        assert "current.top - previous.bottom" in block
        assert "gaps.sort" in block


def test_a_single_child_reports_no_gap() -> None:
    """One element has no rhythm; reporting zero would be a measurement of
    something that was never spaced."""

    block = MEASURE_SCRIPT[MEASURE_SCRIPT.index("const elementGap") :]

    assert "kids.length < 2" in block
