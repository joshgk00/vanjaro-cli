"""VF-006 — three-breakpoint capture hook."""

from __future__ import annotations

from pathlib import Path

import pytest

from vanjaro_cli.design.fidelity_capture import (
    CaptureOutcome,
    CaptureRequest,
    RenderFailure,
    capture_hook_from_outcome,
    capture_three_breakpoints,
)
from vanjaro_cli.design.models import BreakpointName
from vanjaro_cli.design.visual_gate import (
    CANONICAL_VIEWPORTS,
    CaptureStability,
    VisualGateInputError,
    resolve_visual_captures,
)


def _request(tmp_path: Path) -> CaptureRequest:
    return CaptureRequest(
        page_id="home",
        source_url="https://design.example/home",
        output_url="https://build.example/home",
        output_dir=tmp_path,
    )


def _settled() -> CaptureStability:
    return CaptureStability(
        lazy_load_triggered=True, fonts_settled=True, animations_disabled=True
    )


class FakeRenderer:
    """Records calls and writes real files so path checks are meaningful."""

    def __init__(
        self,
        *,
        fail_breakpoints: set[BreakpointName] | None = None,
        stability: CaptureStability | None = None,
    ) -> None:
        self.fail_breakpoints = fail_breakpoints or set()
        self.stability = stability or _settled()
        self.calls: list[tuple[str, BreakpointName]] = []

    def render(
        self, url: str, breakpoint: BreakpointName, destination: Path
    ) -> CaptureStability:
        self.calls.append((url, breakpoint))
        if breakpoint in self.fail_breakpoints:
            raise RenderFailure(f"navigation timed out at {breakpoint.value}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"png")
        return self.stability


class TestCompleteCapture:
    def test_captures_every_canonical_breakpoint(self, tmp_path: Path) -> None:
        renderer = FakeRenderer()

        outcome = capture_three_breakpoints(_request(tmp_path), renderer)

        assert outcome.complete is True
        assert outcome.warnings == ()
        assert {pair.breakpoint for pair in outcome.pairs} == set(CANONICAL_VIEWPORTS)

    def test_uses_the_canonical_viewport_sizes(self, tmp_path: Path) -> None:
        outcome = capture_three_breakpoints(_request(tmp_path), FakeRenderer())

        sizes = {
            pair.breakpoint: (pair.viewport.width, pair.viewport.height)
            for pair in outcome.pairs
        }

        assert sizes[BreakpointName.DESKTOP] == (1440, 900)
        assert sizes[BreakpointName.TABLET] == (768, 1024)
        assert sizes[BreakpointName.MOBILE] == (390, 844)

    def test_captures_both_source_and_output(self, tmp_path: Path) -> None:
        renderer = FakeRenderer()

        capture_three_breakpoints(_request(tmp_path), renderer)

        urls = {url for url, _ in renderer.calls}
        assert urls == {"https://design.example/home", "https://build.example/home"}
        assert len(renderer.calls) == 6

    def test_written_files_exist_at_distinct_paths(self, tmp_path: Path) -> None:
        outcome = capture_three_breakpoints(_request(tmp_path), FakeRenderer())

        paths = [pair.source.path for pair in outcome.pairs] + [
            pair.output.path for pair in outcome.pairs
        ]

        assert len(set(paths)) == 6
        assert all(path.exists() for path in paths)

    def test_output_feeds_the_gate_capture_contract(self, tmp_path: Path) -> None:
        outcome = capture_three_breakpoints(_request(tmp_path), FakeRenderer())

        resolved = resolve_visual_captures(captures=outcome.pairs)

        assert len(resolved) == 3


class TestSettleEvidence:
    def test_records_settle_evidence_on_every_capture(self, tmp_path: Path) -> None:
        outcome = capture_three_breakpoints(_request(tmp_path), FakeRenderer())

        for pair in outcome.pairs:
            assert pair.source.stability.settled is True
            assert pair.output.stability.settled is True

    @pytest.mark.parametrize(
        "field", ["lazy_load_triggered", "fonts_settled", "animations_disabled"]
    )
    def test_unsettled_capture_is_discarded(self, tmp_path: Path, field: str) -> None:
        values = {
            "lazy_load_triggered": True,
            "fonts_settled": True,
            "animations_disabled": True,
        }
        values[field] = False
        renderer = FakeRenderer(stability=CaptureStability(**values))

        outcome = capture_three_breakpoints(_request(tmp_path), renderer)

        # An unsettled screenshot measures a half-loaded page, which is worse
        # than no measurement, so it must not reach the gate.
        assert outcome.pairs == ()
        assert len(outcome.failed_breakpoints) == 3
        assert all("capture discarded" in warning for warning in outcome.warnings)


class TestPartialFailure:
    def test_one_failed_viewport_preserves_the_others(self, tmp_path: Path) -> None:
        renderer = FakeRenderer(fail_breakpoints={BreakpointName.MOBILE})

        outcome = capture_three_breakpoints(_request(tmp_path), renderer)

        assert {pair.breakpoint for pair in outcome.pairs} == {
            BreakpointName.DESKTOP,
            BreakpointName.TABLET,
        }
        assert outcome.failed_breakpoints == (BreakpointName.MOBILE,)
        assert outcome.complete is False

    def test_failure_is_reported_as_a_warning_not_an_exception(
        self, tmp_path: Path
    ) -> None:
        renderer = FakeRenderer(fail_breakpoints={BreakpointName.TABLET})

        outcome = capture_three_breakpoints(_request(tmp_path), renderer)

        assert any(
            "tablet: navigation timed out" in warning for warning in outcome.warnings
        )

    def test_every_viewport_failing_yields_no_pairs(self, tmp_path: Path) -> None:
        renderer = FakeRenderer(fail_breakpoints=set(CANONICAL_VIEWPORTS))

        outcome = capture_three_breakpoints(_request(tmp_path), renderer)

        assert outcome.pairs == ()
        assert len(outcome.warnings) == 3
        assert outcome.complete is False

    def test_incomplete_capture_is_rejected_by_the_gate(self, tmp_path: Path) -> None:
        renderer = FakeRenderer(fail_breakpoints={BreakpointName.MOBILE})
        outcome = capture_three_breakpoints(_request(tmp_path), renderer)

        # Capture reports what it got; the gate decides it is not enough.
        with pytest.raises(VisualGateInputError):
            resolve_visual_captures(captures=outcome.pairs)


class TestRequestedSubset:
    def test_omitted_breakpoint_is_reported_as_not_requested(
        self, tmp_path: Path
    ) -> None:
        outcome = capture_three_breakpoints(
            _request(tmp_path),
            FakeRenderer(),
            breakpoints=[BreakpointName.DESKTOP],
        )

        assert len(outcome.pairs) == 1
        assert set(outcome.failed_breakpoints) == {
            BreakpointName.TABLET,
            BreakpointName.MOBILE,
        }
        assert any("not requested" in warning for warning in outcome.warnings)
        assert outcome.complete is False


class TestCaptureHook:
    def test_hook_returns_the_pair_for_a_captured_breakpoint(
        self, tmp_path: Path
    ) -> None:
        outcome = capture_three_breakpoints(_request(tmp_path), FakeRenderer())
        hook = capture_hook_from_outcome(outcome)

        pair = hook(BreakpointName.DESKTOP, CANONICAL_VIEWPORTS[BreakpointName.DESKTOP])

        assert pair.breakpoint is BreakpointName.DESKTOP

    def test_hook_raises_for_a_breakpoint_that_failed(self, tmp_path: Path) -> None:
        renderer = FakeRenderer(fail_breakpoints={BreakpointName.MOBILE})
        outcome = capture_three_breakpoints(_request(tmp_path), renderer)
        hook = capture_hook_from_outcome(outcome)

        with pytest.raises(RenderFailure, match="mobile"):
            hook(BreakpointName.MOBILE, CANONICAL_VIEWPORTS[BreakpointName.MOBILE])


class TestDeterminism:
    def test_repeated_capture_produces_the_same_paths(self, tmp_path: Path) -> None:
        first = capture_three_breakpoints(_request(tmp_path), FakeRenderer())
        second = capture_three_breakpoints(_request(tmp_path), FakeRenderer())

        assert [pair.source.path for pair in first.pairs] == [
            pair.source.path for pair in second.pairs
        ]

    def test_empty_outcome_is_valid_and_incomplete(self) -> None:
        outcome = CaptureOutcome()

        assert outcome.pairs == ()
        assert outcome.complete is False
