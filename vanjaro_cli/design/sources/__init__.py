"""Public source-adapter API and built-in registry."""

from __future__ import annotations

from vanjaro_cli.design.sources.base import (
    DesignSourceAdapter,
    SourceAdapterError,
    SourceAnalysisRequest,
)
from vanjaro_cli.design.sources.figma import FigmaSourceAdapter, FigmaSourceRequest
from vanjaro_cli.design.sources.html import HtmlSourceAdapter, HtmlSourceRequest
from vanjaro_cli.design.sources.image import (
    ImageSourceAdapter,
    ImageSourceRequest,
    ReferenceImage,
)
from vanjaro_cli.design.sources.legacy import (
    LegacyCrawlSourceAdapter,
    LegacyCrawlSourceRequest,
)
from vanjaro_cli.design.sources.registry import SourceAdapterRegistry


DEFAULT_SOURCE_ADAPTERS = SourceAdapterRegistry(
    (
        HtmlSourceAdapter(),
        FigmaSourceAdapter(),
        ImageSourceAdapter(),
        LegacyCrawlSourceAdapter(),
    )
)


def analyze_source(request: SourceAnalysisRequest):
    """Analyze a source through the default deterministic adapter registry."""

    return DEFAULT_SOURCE_ADAPTERS.analyze(request)


__all__ = [
    "DEFAULT_SOURCE_ADAPTERS",
    "DesignSourceAdapter",
    "FigmaSourceAdapter",
    "FigmaSourceRequest",
    "HtmlSourceAdapter",
    "HtmlSourceRequest",
    "ImageSourceRequest",
    "ImageSourceAdapter",
    "LegacyCrawlSourceAdapter",
    "LegacyCrawlSourceRequest",
    "ReferenceImage",
    "SourceAdapterError",
    "SourceAdapterRegistry",
    "SourceAnalysisRequest",
    "analyze_source",
]
