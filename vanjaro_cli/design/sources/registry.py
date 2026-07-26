"""Deterministic registry for design-source adapters."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from vanjaro_cli.design.models import DesignDocument, SourceKind
from vanjaro_cli.design.sources.base import (
    DesignSourceAdapter,
    SourceAdapterError,
    SourceAnalysisRequest,
)


class SourceAdapterRegistry:
    """Own source dispatch without coupling callers to concrete adapters."""

    def __init__(self, adapters: Iterable[DesignSourceAdapter[Any]] = ()) -> None:
        self._adapters: dict[SourceKind, DesignSourceAdapter[Any]] = {}
        for adapter in adapters:
            self.register(adapter)

    @property
    def supported_kinds(self) -> tuple[SourceKind, ...]:
        """Return registered kinds in stable enum-value order."""

        return tuple(sorted(self._adapters, key=lambda kind: kind.value))

    def register(
        self, adapter: DesignSourceAdapter[Any], *, replace: bool = False
    ) -> None:
        """Register one adapter and reject accidental behavior replacement."""

        kind = adapter.source_kind
        if kind in self._adapters and not replace:
            raise SourceAdapterError(
                f"source adapter for {kind.value!r} is already registered"
            )
        self._adapters[kind] = adapter

    def get(self, source_kind: SourceKind) -> DesignSourceAdapter[Any]:
        """Resolve an adapter or raise an actionable unsupported-source error."""

        adapter = self._adapters.get(source_kind)
        if adapter is None:
            supported = ", ".join(kind.value for kind in self.supported_kinds) or "none"
            raise SourceAdapterError(
                f"no source adapter is registered for {source_kind.value!r}; "
                f"registered kinds: {supported}"
            )
        return adapter

    def analyze(self, request: SourceAnalysisRequest) -> DesignDocument:
        """Validate request ownership and dispatch it to one adapter."""

        adapter = self.get(request.source_kind)
        if not isinstance(request, adapter.request_type):
            raise SourceAdapterError(
                f"adapter {adapter.__class__.__name__} requires "
                f"{adapter.request_type.__name__}, got {request.__class__.__name__}"
            )
        return adapter.analyze(request)

