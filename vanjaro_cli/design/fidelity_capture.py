"""Three-breakpoint capture for the visual fidelity gate (VF-006).

Produces the source/output screenshot pairs the gate consumes, at the canonical
1440, 768, and 390 pixel viewports. Rendering reuses the existing Playwright
harness in `vanjaro_cli.migration.visual` rather than introducing a second
browser stack: `_settle` already loads fonts, disables animation, and walks the
page to trigger lazy images, which is exactly the stability evidence the gate
requires.

Partial failure is preserved rather than fatal. If the mobile viewport times
out, the desktop and tablet captures remain usable and the failure is reported
as a warning. The gate then refuses to score incomplete evidence, which keeps
the two responsibilities separate: capture reports what it actually got, and
the gate decides whether that is enough.

Browser work sits behind the `PageRenderer` protocol so the sequencing,
warning, and partial-failure logic is testable without a browser.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from vanjaro_cli.design.models import BreakpointName
from vanjaro_cli.design.visual_gate import (
    CANONICAL_VIEWPORTS,
    CaptureImage,
    CaptureStability,
    ViewportCapturePair,
)

__all__ = [
    "CaptureOutcome",
    "CaptureRequest",
    "PageRenderer",
    "PlaywrightPageRenderer",
    "RenderFailure",
    "capture_three_breakpoints",
    "capture_hook_from_outcome",
]


class RenderFailure(RuntimeError):
    """Raised by a renderer when one page at one viewport cannot be captured."""


class _CaptureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CaptureRequest(_CaptureModel):
    """One page to capture from both the design reference and the build."""

    page_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    output_url: str = Field(min_length=1)
    output_dir: Path


class PageRenderer(Protocol):
    """Renders one URL at one viewport and reports settle evidence."""

    def render(
        self, url: str, breakpoint: BreakpointName, destination: Path
    ) -> CaptureStability:
        ...


class CaptureOutcome(_CaptureModel):
    """Captured pairs plus every breakpoint that could not be captured."""

    pairs: tuple[ViewportCapturePair, ...] = ()
    warnings: tuple[str, ...] = ()
    failed_breakpoints: tuple[BreakpointName, ...] = ()

    @property
    def complete(self) -> bool:
        return len(self.pairs) == len(CANONICAL_VIEWPORTS) and not self.failed_breakpoints


def _screenshot_path(request: CaptureRequest, breakpoint: BreakpointName, role: str) -> Path:
    return request.output_dir / f"{request.page_id}-{breakpoint.value}-{role}.png"


def _unsettled_reasons(stability: CaptureStability) -> list[str]:
    reasons = []
    if not stability.lazy_load_triggered:
        reasons.append("lazy load not triggered")
    if not stability.fonts_settled:
        reasons.append("fonts not settled")
    if not stability.animations_disabled:
        reasons.append("animations not disabled")
    return reasons


def capture_three_breakpoints(
    request: CaptureRequest,
    renderer: PageRenderer,
    *,
    breakpoints: Iterable[BreakpointName] | None = None,
) -> CaptureOutcome:
    """Capture source and output at each canonical breakpoint.

    A failure at one viewport does not abort the others. Captures that render
    but are not settled are rejected: an unsettled screenshot silently measures
    a half-loaded page, which is worse than no measurement at all.
    """

    targets = tuple(breakpoints) if breakpoints is not None else tuple(CANONICAL_VIEWPORTS)

    pairs: list[ViewportCapturePair] = []
    warnings: list[str] = []
    failed: list[BreakpointName] = []

    for breakpoint in targets:
        viewport = CANONICAL_VIEWPORTS.get(breakpoint)
        if viewport is None:
            warnings.append(f"{breakpoint.value}: not a canonical gate viewport")
            failed.append(breakpoint)
            continue

        try:
            source_path = _screenshot_path(request, breakpoint, "source")
            output_path = _screenshot_path(request, breakpoint, "output")
            source_stability = renderer.render(request.source_url, breakpoint, source_path)
            output_stability = renderer.render(request.output_url, breakpoint, output_path)
        except RenderFailure as error:
            warnings.append(f"{breakpoint.value}: {error}")
            failed.append(breakpoint)
            continue

        unsettled = _unsettled_reasons(source_stability) + _unsettled_reasons(
            output_stability
        )
        if unsettled:
            warnings.append(
                f"{breakpoint.value}: capture discarded, " + ", ".join(sorted(set(unsettled)))
            )
            failed.append(breakpoint)
            continue

        pairs.append(
            ViewportCapturePair(
                breakpoint=breakpoint,
                viewport=viewport,
                source=CaptureImage(path=source_path, stability=source_stability),
                output=CaptureImage(path=output_path, stability=output_stability),
            )
        )

    missing = [name for name in CANONICAL_VIEWPORTS if name not in targets]
    for name in missing:
        warnings.append(f"{name.value}: not requested")
        failed.append(name)

    return CaptureOutcome(
        pairs=tuple(pairs),
        warnings=tuple(warnings),
        failed_breakpoints=tuple(failed),
    )


def capture_hook_from_outcome(outcome: CaptureOutcome):
    """Adapt captured pairs to the gate's `CaptureHook` signature."""

    by_breakpoint = {pair.breakpoint: pair for pair in outcome.pairs}

    def hook(breakpoint: BreakpointName, viewport) -> ViewportCapturePair:
        pair = by_breakpoint.get(breakpoint)
        if pair is None:
            raise RenderFailure(
                f"no capture available for {breakpoint.value}; "
                "the gate cannot score a viewport that failed to render"
            )
        return pair

    return hook


class PlaywrightPageRenderer:
    """Default renderer reusing the existing Playwright visual harness."""

    def __init__(self, *, timeout_seconds: int = 45) -> None:
        self.timeout_seconds = timeout_seconds

    def render(
        self, url: str, breakpoint: BreakpointName, destination: Path
    ) -> CaptureStability:
        # Imported lazily so the pure planning path never requires Playwright.
        from vanjaro_cli.migration.visual import (
            VisualCaptureError,
            _settle,
            rendered_page_session,
        )

        viewport = CANONICAL_VIEWPORTS[breakpoint]
        destination.parent.mkdir(parents=True, exist_ok=True)
        timeout_ms = self.timeout_seconds * 1000

        try:
            with rendered_page_session(
                viewport=(viewport.width, viewport.height)
            ) as page:
                try:
                    page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                except Exception:
                    page.goto(url, wait_until="load", timeout=timeout_ms)
                _settle(page, timeout_ms)
                page.screenshot(path=str(destination), full_page=True)
        except VisualCaptureError as error:
            raise RenderFailure(str(error)) from error
        except Exception as error:  # noqa: BLE001 - reported as a capture warning
            raise RenderFailure(f"{type(error).__name__}: {error}") from error

        return CaptureStability(
            lazy_load_triggered=True, fonts_settled=True, animations_disabled=True
        )
