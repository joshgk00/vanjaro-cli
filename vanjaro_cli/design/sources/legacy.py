"""Legacy crawl-artifact request and compatibility adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from vanjaro_cli.design.html_adapter import convert_legacy_crawl
from vanjaro_cli.design.models import DesignDocument, SourceKind


@dataclass(frozen=True, slots=True)
class LegacyCrawlSourceRequest:
    """Existing migration directory to convert without portal or network I/O."""

    migration_directory: Path
    captured_at: datetime | None = None
    source_kind: SourceKind = field(default=SourceKind.LEGACY_SECTIONS, init=False)


class LegacyCrawlSourceAdapter:
    """Route resumable legacy artifacts through the shared source boundary."""

    source_kind = SourceKind.LEGACY_SECTIONS
    request_type = LegacyCrawlSourceRequest

    def analyze(self, request: LegacyCrawlSourceRequest) -> DesignDocument:
        return convert_legacy_crawl(
            request.migration_directory,
            captured_at=request.captured_at,
        )

