"""HTML source request and compatibility adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from vanjaro_cli.design.html_adapter import design_document_from_html
from vanjaro_cli.design.models import DesignDocument, SourceKind


@dataclass(frozen=True, slots=True)
class HtmlSourceRequest:
    """Evidence required to analyze one live/static HTML page."""

    html: str
    source_url: str
    title: str | None = None
    slug: str | None = None
    captured_at: datetime | None = None
    source_kind: SourceKind = field(default=SourceKind.LIVE_HTML, init=False)

    def __post_init__(self) -> None:
        if not self.source_url.strip():
            raise ValueError("source_url must not be empty")


class HtmlSourceAdapter:
    """Route typed HTML evidence through the existing proven analyzer."""

    source_kind = SourceKind.LIVE_HTML
    request_type = HtmlSourceRequest

    def analyze(self, request: HtmlSourceRequest) -> DesignDocument:
        return design_document_from_html(
            request.html,
            request.source_url,
            title=request.title,
            slug=request.slug,
            captured_at=request.captured_at,
        )

