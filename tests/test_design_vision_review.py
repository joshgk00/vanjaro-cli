"""Tests for the advisory vision reviewer (VF-101, measurement Layer 2)."""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from pathlib import Path

from vanjaro_cli.design.models import BreakpointName, Viewport
from vanjaro_cli.design.reports import (
    FindingCategory,
    PipelineStage,
    ReportSeverity,
)
from vanjaro_cli.design.vision_review import (
    VisionReviewRequest,
    review_captures,
)
from vanjaro_cli.design.fidelity_capture import CaptureOutcome
from vanjaro_cli.design.visual_gate import (
    CaptureImage,
    CaptureStability,
    ViewportCapturePair,
)


SECTION_IDS = ("home.section.1", "home.section.2")

VIEWPORTS = {
    BreakpointName.DESKTOP: Viewport(width=1440, height=900),
    BreakpointName.TABLET: Viewport(width=768, height=1024),
    BreakpointName.MOBILE: Viewport(width=390, height=844),
}


def _settled() -> CaptureStability:
    return CaptureStability(
        lazy_load_triggered=True, fonts_settled=True, animations_disabled=True
    )


def _pair(breakpoint: BreakpointName) -> ViewportCapturePair:
    return ViewportCapturePair(
        breakpoint=breakpoint,
        viewport=VIEWPORTS[breakpoint],
        source=CaptureImage(path=Path(f"{breakpoint.value}-source.png"), stability=_settled()),
        output=CaptureImage(path=Path(f"{breakpoint.value}-output.png"), stability=_settled()),
    )


def _outcome(*breakpoints: BreakpointName, failed: tuple = ()) -> CaptureOutcome:
    return CaptureOutcome(
        pairs=tuple(_pair(breakpoint) for breakpoint in breakpoints),
        failed_breakpoints=failed,
    )


def _valid_finding(**overrides: object) -> dict[str, object]:
    finding: dict[str, object] = {
        "section_id": "home.section.2",
        "severity": "high",
        "category": "style",
        "pipeline_stage": "style_translation",
        "message": "The hero background renders grey instead of navy.",
        "recommendation": "Check the palette mapping for the hero background slot.",
        "source_file": "vanjaro_cli/design/style_translation.py",
    }
    finding.update(overrides)
    return finding


class StaticProvider:
    def __init__(self, findings: Sequence[Mapping[str, object]]) -> None:
        self._findings = findings
        self.requests: list[VisionReviewRequest] = []

    def review(self, request: VisionReviewRequest) -> Sequence[Mapping[str, object]]:
        self.requests.append(request)
        return self._findings


class FailingProvider:
    def review(self, request: VisionReviewRequest) -> Sequence[Mapping[str, object]]:
        raise RuntimeError("model endpoint unavailable")


def _review(provider, outcome=None):
    return review_captures(
        outcome if outcome is not None else _outcome(BreakpointName.DESKTOP),
        provider,
        page_id="home",
        section_ids=SECTION_IDS,
    )


def test_a_valid_finding_carries_stage_section_breakpoint_and_file() -> None:
    result = _review(StaticProvider([_valid_finding()]))

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.section_id == "home.section.2"
    assert finding.breakpoint is BreakpointName.DESKTOP
    assert finding.severity is ReportSeverity.HIGH
    assert finding.category is FindingCategory.STYLE
    assert finding.pipeline_stage is PipelineStage.STYLE_TRANSLATION
    assert finding.source_file == "vanjaro_cli/design/style_translation.py"
    assert result.warnings == ()


def test_every_captured_breakpoint_is_reviewed_in_canonical_order() -> None:
    provider = StaticProvider([_valid_finding()])

    result = _review(
        provider,
        _outcome(BreakpointName.MOBILE, BreakpointName.DESKTOP, BreakpointName.TABLET),
    )

    assert [request.breakpoint for request in provider.requests] == [
        BreakpointName.DESKTOP,
        BreakpointName.TABLET,
        BreakpointName.MOBILE,
    ]
    assert [finding.breakpoint for finding in result.findings] == [
        BreakpointName.DESKTOP,
        BreakpointName.TABLET,
        BreakpointName.MOBILE,
    ]


def test_a_provider_failure_yields_no_findings_and_a_warning() -> None:
    """A diagnostic layer that can fail the run makes an advisory signal load-bearing."""

    result = _review(FailingProvider())

    assert result.findings == ()
    assert len(result.warnings) == 1
    assert "model endpoint unavailable" in result.warnings[0]


def test_a_failure_at_one_breakpoint_does_not_lose_the_others() -> None:
    class OneBadBreakpoint:
        def review(self, request: VisionReviewRequest):
            if request.breakpoint is BreakpointName.TABLET:
                raise RuntimeError("timeout")
            return [_valid_finding()]

    result = _review(
        OneBadBreakpoint(),
        _outcome(BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE),
    )

    assert [finding.breakpoint for finding in result.findings] == [
        BreakpointName.DESKTOP,
        BreakpointName.MOBILE,
    ]
    assert any("tablet" in warning for warning in result.warnings)


def test_a_finding_naming_an_unknown_section_is_dropped() -> None:
    """A finding pointing at a section that does not exist sends work nowhere real."""

    result = _review(StaticProvider([_valid_finding(section_id="home.section.99")]))

    assert result.findings == ()
    assert any("unknown section" in warning for warning in result.warnings)


def test_an_unrecognized_severity_category_or_stage_is_dropped() -> None:
    result = _review(
        StaticProvider(
            [
                _valid_finding(severity="catastrophic"),
                _valid_finding(category="vibes"),
                _valid_finding(pipeline_stage="wishful_thinking"),
            ]
        )
    )

    assert result.findings == ()
    assert len(result.warnings) == 3
    assert all("unrecognized" in warning for warning in result.warnings)


def test_a_finding_without_a_message_or_recommendation_is_dropped() -> None:
    result = _review(
        StaticProvider([_valid_finding(message="  "), _valid_finding(recommendation="")])
    )

    assert result.findings == ()
    assert len(result.warnings) == 2


def test_a_non_object_finding_is_dropped_without_raising() -> None:
    result = _review(StaticProvider(["not a finding", _valid_finding()]))

    assert len(result.findings) == 1
    assert any("was not an object" in warning for warning in result.warnings)


def test_a_provider_returning_a_bare_string_is_rejected() -> None:
    class StringProvider:
        def review(self, request: VisionReviewRequest):
            return "the page looks fine"

    result = _review(StringProvider())

    assert result.findings == ()
    assert any("no finding list" in warning for warning in result.warnings)


def test_an_uncaptured_breakpoint_is_reported_as_unreviewed() -> None:
    result = _review(
        StaticProvider([]),
        _outcome(BreakpointName.DESKTOP, failed=(BreakpointName.MOBILE,)),
    )

    assert result.findings == ()
    assert any("no capture at mobile" in warning for warning in result.warnings)


def test_the_outcome_exposes_nothing_a_gate_could_score() -> None:
    result = _review(StaticProvider([_valid_finding()]))

    assert set(type(result).model_fields) == {"findings", "warnings"}


def test_no_scoring_module_imports_the_vision_reviewer() -> None:
    """Vision output must never reach the primary score (VF-2)."""

    design = Path(__file__).resolve().parents[1] / "vanjaro_cli" / "design"
    scoring_modules = sorted(design.glob("fidelity*.py")) + [design / "visual_gate.py"]
    assert scoring_modules

    for module in scoring_modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported = ()
            if isinstance(node, ast.ImportFrom) and node.module:
                imported = (node.module,)
            elif isinstance(node, ast.Import):
                imported = tuple(alias.name for alias in node.names)
            assert not any(
                "vision_review" in name for name in imported
            ), f"{module.name} imports the vision reviewer"
