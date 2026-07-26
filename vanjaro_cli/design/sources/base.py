"""Typed contracts shared by design-source adapters.

Source adapters own evidence extraction.  Their only shared output is the
versioned :class:`DesignDocument`; downstream matching and planning must not
branch on adapter-specific payloads.
"""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar, runtime_checkable

from vanjaro_cli.design.models import DesignDocument, SourceKind


class SourceAdapterError(ValueError):
    """Raised when a source request cannot be dispatched safely."""


@runtime_checkable
class SourceAnalysisRequest(Protocol):
    """Minimum request shape required by the adapter registry."""

    @property
    def source_kind(self) -> SourceKind:
        """Return the source kind used for deterministic dispatch."""


RequestT = TypeVar("RequestT", bound=SourceAnalysisRequest)


class DesignSourceAdapter(Protocol, Generic[RequestT]):
    """Pure source-evidence adapter contract."""

    source_kind: SourceKind
    request_type: type[RequestT]

    def analyze(self, request: RequestT) -> DesignDocument:
        """Convert one typed source request into Design Document v1."""

