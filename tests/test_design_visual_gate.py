"""Offline acceptance coverage for the three-breakpoint visual quality gate."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from vanjaro_cli.design.models import BreakpointName, Viewport
from vanjaro_cli.design.visual_gate import (
    CANONICAL_VIEWPORTS,
    CaptureImage,
    CaptureStability,
    GateLevel,
    SectionVisualScore,
    SystemicVisualFinding,
    VisualFindingSeverity,
    VisualGateInputError,
    ViewportCapturePair,
    ViewportVisualScore,
    evaluate_visual_gate,
    resolve_visual_captures,
    run_visual_quality_gate,
    serialize_visual_gate_result,
)


SETTLED = CaptureStability(
    lazy_load_triggered=True,
    fonts_settled=True,
    animations_disabled=True,
)


def _captures(tmp_path: Path) -> tuple[ViewportCapturePair, ...]:
    captures = []
    for breakpoint, viewport in CANONICAL_VIEWPORTS.items():
        source = tmp_path / f"source-{breakpoint.value}.png"
        output = tmp_path / f"output-{breakpoint.value}.png"
        source.write_bytes(b"source fixture")
        output.write_bytes(b"output fixture")
        captures.append(ViewportCapturePair(
            breakpoint=breakpoint,
            viewport=viewport,
            source=CaptureImage(path=source, stability=SETTLED),
            output=CaptureImage(path=output, stability=SETTLED),
        ))
    return tuple(captures)


def _scores(
    *, desktop: float, tablet: float, mobile: float,
    section_score: float | None = None,
) -> tuple[ViewportVisualScore, ...]:
    values = {
        BreakpointName.DESKTOP: desktop,
        BreakpointName.TABLET: tablet,
        BreakpointName.MOBILE: mobile,
    }
    return tuple(
        ViewportVisualScore(
            breakpoint=breakpoint,
            overall_score=score,
            sections=(
                SectionVisualScore(
                    section_id="home.hero",
                    score=score if section_score is None else section_score,
                ),
                SectionVisualScore(
                    section_id="home.features",
                    score=score if section_score is None else section_score,
                ),
            ),
        )
        for breakpoint, score in values.items()
    )


def test_draft_threshold_boundaries_are_inclusive_and_report_aggregates(tmp_path):
    result = evaluate_visual_gate(
        _captures(tmp_path),
        _scores(desktop=75, tablet=75, mobile=75, section_score=60),
        level=GateLevel.DRAFT,
    )
    assert result.passed is True
    assert result.overall_score == 75
    assert result.failures == ()
    assert [(section.section_id, section.score) for section in result.section_scores] == [
        ("home.features", 60), ("home.hero", 60),
    ]
    assert result.section_scores[0].viewport_scores == {
        BreakpointName.DESKTOP: 60,
        BreakpointName.TABLET: 60,
        BreakpointName.MOBILE: 60,
    }


def test_ship_threshold_boundaries_are_inclusive(tmp_path):
    result = evaluate_visual_gate(
        _captures(tmp_path),
        _scores(desktop=90, tablet=90, mobile=75, section_score=75),
        level=GateLevel.SHIP,
    )
    assert result.overall_score == 85
    assert result.passed is True
    assert result.failures == ()


def test_ship_gate_returns_all_threshold_and_systemic_failures(tmp_path):
    finding = SystemicVisualFinding(
        id="fonts-wrong", severity=VisualFindingSeverity.HIGH,
        issue="Heading font is replaced on every page", pipeline_stage="theme",
    )
    result = evaluate_visual_gate(
        _captures(tmp_path),
        _scores(desktop=84.99, tablet=84.99, mobile=74.99, section_score=74.99),
        level=GateLevel.SHIP,
        findings=[finding],
    )
    assert result.passed is False
    codes = [failure.code for failure in result.failures]
    assert codes.count("overall_score_below_threshold") == 1
    assert codes.count("section_score_below_threshold") == 6
    assert codes.count("mobile_score_below_threshold") == 1
    assert codes.count("high_systemic_finding") == 1
    assert next(failure for failure in result.failures if failure.code == "high_systemic_finding").finding_id == "fonts-wrong"


def test_desktop_success_cannot_mask_mobile_ship_failure(tmp_path):
    scores = list(_scores(desktop=100, tablet=100, mobile=70, section_score=80))
    result = evaluate_visual_gate(
        _captures(tmp_path), scores, level=GateLevel.SHIP,
    )
    assert result.overall_score == 90
    assert result.passed is False
    assert [failure.code for failure in result.failures] == [
        "mobile_score_below_threshold"
    ]


def test_high_systemic_finding_blocks_ship_but_not_draft(tmp_path):
    finding = SystemicVisualFinding(
        id="global-spacing", severity=VisualFindingSeverity.HIGH,
        issue="Every section uses the wrong vertical rhythm",
    )
    captures = _captures(tmp_path)
    scores = _scores(desktop=90, tablet=90, mobile=90)
    draft = evaluate_visual_gate(
        captures, scores, level=GateLevel.DRAFT, findings=[finding],
    )
    ship = evaluate_visual_gate(
        captures, scores, level=GateLevel.SHIP, findings=[finding],
    )
    assert draft.passed is True
    assert ship.passed is False
    assert ship.failures[0].code == "high_systemic_finding"


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("lazy_load_triggered", "did not trigger lazy loading"),
        ("fonts_settled", "did not settle fonts"),
        ("animations_disabled", "did not disable animations"),
    ],
)
def test_unsettled_capture_metadata_is_rejected(tmp_path, field, message):
    captures = list(_captures(tmp_path))
    mobile = captures[-1]
    stability = SETTLED.model_copy(update={field: False})
    captures[-1] = mobile.model_copy(update={
        "output": mobile.output.model_copy(update={"stability": stability})
    })
    with pytest.raises(VisualGateInputError, match=message):
        resolve_visual_captures(captures=captures)


def test_missing_viewport_is_rejected_for_captures_and_scores(tmp_path):
    captures = _captures(tmp_path)
    with pytest.raises(VisualGateInputError, match="missing required breakpoints: mobile"):
        resolve_visual_captures(captures=captures[:2])
    with pytest.raises(VisualGateInputError, match="score set is missing required breakpoints: mobile"):
        run_visual_quality_gate(
            captures=captures,
            scores=_scores(desktop=90, tablet=90, mobile=90)[:2],
        )


def test_noncanonical_viewport_and_missing_image_are_rejected(tmp_path):
    captures = list(_captures(tmp_path))
    captures[0] = captures[0].model_copy(update={"viewport": Viewport(width=1280, height=800)})
    with pytest.raises(VisualGateInputError, match="desktop viewport must be 1440x900"):
        resolve_visual_captures(captures=captures)

    captures = list(_captures(tmp_path))
    captures[1].output.path.unlink()
    with pytest.raises(VisualGateInputError, match="tablet output image does not exist"):
        resolve_visual_captures(captures=captures)


def test_capture_and_score_hooks_receive_canonical_breakpoints(tmp_path):
    capture_calls = []
    score_calls = []

    def capture_hook(breakpoint, viewport):
        capture_calls.append((breakpoint, viewport.width, viewport.height))
        source = tmp_path / f"hook-source-{breakpoint.value}.png"
        output = tmp_path / f"hook-output-{breakpoint.value}.png"
        source.write_bytes(b"source")
        output.write_bytes(b"output")
        return ViewportCapturePair(
            breakpoint=breakpoint, viewport=viewport,
            source=CaptureImage(path=source, stability=SETTLED),
            output=CaptureImage(path=output, stability=SETTLED),
        )

    def score_hook(capture):
        score_calls.append(capture.breakpoint)
        return ViewportVisualScore(
            breakpoint=capture.breakpoint, overall_score=90,
            sections=(SectionVisualScore(section_id="home", score=90),),
        )

    result = run_visual_quality_gate(
        capture_hook=capture_hook, score_hook=score_hook,
        level=GateLevel.SHIP,
    )
    assert result.passed is True
    assert capture_calls == [
        (BreakpointName.DESKTOP, 1440, 900),
        (BreakpointName.TABLET, 768, 1024),
        (BreakpointName.MOBILE, 390, 844),
    ]
    assert score_calls == [
        BreakpointName.DESKTOP,
        BreakpointName.TABLET,
        BreakpointName.MOBILE,
    ]


def test_hook_and_direct_inputs_are_mutually_exclusive(tmp_path):
    captures = _captures(tmp_path)
    with pytest.raises(VisualGateInputError, match="captures or capture_hook, not both"):
        resolve_visual_captures(
            captures=captures,
            capture_hook=lambda breakpoint, viewport: captures[0],
        )


def test_duplicate_section_ids_are_rejected():
    with pytest.raises(ValidationError, match="section IDs must be unique"):
        ViewportVisualScore(
            breakpoint=BreakpointName.DESKTOP,
            overall_score=90,
            sections=(
                SectionVisualScore(section_id="Hero", score=90),
                SectionVisualScore(section_id="hero", score=90),
            ),
        )


def test_result_serialization_is_deterministic_for_reordered_inputs(tmp_path):
    captures = _captures(tmp_path)
    scores = _scores(desktop=90, tablet=88, mobile=86)
    findings = [
        SystemicVisualFinding(id="z-last", severity=VisualFindingSeverity.LOW, issue="Minor"),
        SystemicVisualFinding(id="a-first", severity=VisualFindingSeverity.MEDIUM, issue="Review"),
    ]
    first = evaluate_visual_gate(captures, scores, level=GateLevel.SHIP, findings=findings)
    second = evaluate_visual_gate(
        reversed(captures), reversed(scores), level=GateLevel.SHIP,
        findings=reversed(findings),
    )
    assert first == second
    serialized = serialize_visual_gate_result(first)
    assert serialized == serialize_visual_gate_result(second)
    assert serialized.endswith("\n")
    assert serialized.index("a-first") < serialized.index("z-last")
