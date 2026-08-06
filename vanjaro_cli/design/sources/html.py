"""HTML source request and compatibility adapter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from vanjaro_cli.design.html_adapter import (
    RenderedCaptureResult,
    RenderedPageObservation,
    capture_rendered_observations,
    design_document_from_html,
)
from vanjaro_cli.design.models import DesignDocument, DesignWarning, SourceKind


RenderedCapture = Callable[[str], RenderedCaptureResult]

__all__ = ["HtmlSourceAdapter", "HtmlSourceRequest", "RenderedCapture"]


@dataclass(frozen=True, slots=True)
class HtmlSourceRequest:
    """Evidence required to analyze one live/static HTML page."""

    html: str
    source_url: str
    title: str | None = None
    slug: str | None = None
    captured_at: datetime | None = None
    render: bool = False
    render_url: str | None = None
    source_kind: SourceKind = field(default=SourceKind.LIVE_HTML, init=False)

    def __post_init__(self) -> None:
        if not self.source_url.strip():
            raise ValueError("source_url must not be empty")
        if self.render_url is not None and not self.render_url.strip():
            raise ValueError("render_url must not be empty when provided")

    @property
    def effective_render_url(self) -> str:
        """The address a browser should load when rendered evidence is wanted."""

        return self.render_url or self.source_url


class HtmlSourceAdapter:
    """Route typed HTML evidence through the existing proven analyzer.

    Static parsing is the default. When a request asks to render, the browser
    supplies geometry and computed styles that a static parse cannot: without
    them the colour, typography, spacing, and media dimensions have nothing on
    the design side to compare against, and layout loses its bounds subscore.
    """

    source_kind = SourceKind.LIVE_HTML
    request_type = HtmlSourceRequest

    def __init__(self, capture: RenderedCapture = capture_rendered_observations) -> None:
        self._capture = capture

    def analyze(self, request: HtmlSourceRequest) -> DesignDocument:
        observations: tuple[RenderedPageObservation, ...] = ()
        warnings: tuple[DesignWarning, ...] = ()
        if request.render:
            captured = self._capture(request.effective_render_url)
            observations = captured.observations
            warnings = captured.warnings
        return design_document_from_html(
            request.html,
            request.source_url,
            title=request.title,
            slug=request.slug,
            captured_at=request.captured_at,
            rendered_observations=observations,
            rendered_warnings=warnings,
        )
