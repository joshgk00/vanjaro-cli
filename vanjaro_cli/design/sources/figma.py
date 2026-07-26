"""Figma source request and compatibility adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from vanjaro_cli.design.figma_adapter import (
    ImageFillResolver,
    VectorResolver,
    analyze_figma_document,
)
from vanjaro_cli.design.models import DesignDocument, SourceKind


@dataclass(frozen=True, slots=True)
class FigmaSourceRequest:
    """Already-fetched Figma evidence and optional asset-resolution hooks."""

    payload: Mapping[str, Any]
    file_key: str
    node_id: str | None = None
    image_fill_urls: Mapping[str, str] | None = None
    image_resolver: ImageFillResolver | None = None
    vector_resolver: VectorResolver | None = None
    font_sources: Mapping[str, str] | None = None
    captured_at: datetime | None = None
    adapter_version: str | None = None
    source_kind: SourceKind = field(default=SourceKind.FIGMA, init=False)

    def __post_init__(self) -> None:
        if not self.file_key.strip():
            raise ValueError("file_key must not be empty")


class FigmaSourceAdapter:
    """Route typed Figma evidence through the existing proven analyzer."""

    source_kind = SourceKind.FIGMA
    request_type = FigmaSourceRequest

    def analyze(self, request: FigmaSourceRequest) -> DesignDocument:
        kwargs: dict[str, Any] = {
            "file_key": request.file_key,
            "node_id": request.node_id,
            "image_fill_urls": request.image_fill_urls,
            "image_resolver": request.image_resolver,
            "vector_resolver": request.vector_resolver,
            "font_sources": request.font_sources,
            "captured_at": request.captured_at,
        }
        if request.adapter_version is not None:
            kwargs["adapter_version"] = request.adapter_version
        return analyze_figma_document(request.payload, **kwargs)

