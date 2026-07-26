"""Typed request and pure adapter for screenshot/reference-image evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re

from vanjaro_cli.design.image_adapter import design_document_from_image_evidence
from vanjaro_cli.design.image_evidence import ImageEvidenceSet
from vanjaro_cli.design.models import DesignDocument
from vanjaro_cli.design.models import BreakpointName, SourceKind


_SHA256 = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class ReferenceImage:
    """One reference image with explicit page and viewport ownership."""

    path: Path
    page_slug: str
    breakpoint: BreakpointName
    viewport_width: int
    viewport_height: int
    sha256: str

    def __post_init__(self) -> None:
        normalized_slug = self.page_slug.strip().strip("/")
        if not normalized_slug:
            raise ValueError("page_slug must not be empty")
        object.__setattr__(self, "page_slug", normalized_slug)
        if not str(self.path).strip() or self.path == Path("."):
            raise ValueError("reference image path must not be empty")
        if self.viewport_width <= 0 or self.viewport_height <= 0:
            raise ValueError("reference image viewport dimensions must be positive")
        normalized_digest = self.sha256.strip().lower()
        if not _SHA256.fullmatch(normalized_digest):
            raise ValueError("reference image sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "sha256", normalized_digest)


@dataclass(frozen=True, slots=True)
class ImageSourceRequest:
    """Exact image ownership plus already-acquired, versioned evidence."""

    images: tuple[ReferenceImage, ...]
    project_id: str
    evidence: ImageEvidenceSet
    captured_at: datetime | None = None
    source_kind: SourceKind = field(default=SourceKind.IMAGE, init=False)

    def __post_init__(self) -> None:
        normalized_project_id = self.project_id.strip()
        if not normalized_project_id:
            raise ValueError("project_id must not be empty")
        object.__setattr__(self, "project_id", normalized_project_id)
        if not self.images:
            raise ValueError("at least one reference image is required")
        if self.captured_at is not None and self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")


class ImageSourceAdapter:
    """Convert validated image evidence without filesystem or network access."""

    source_kind = SourceKind.IMAGE
    request_type = ImageSourceRequest

    def analyze(self, request: ImageSourceRequest) -> DesignDocument:
        return design_document_from_image_evidence(
            request.images,
            request.evidence,
            project_id=request.project_id,
            captured_at=request.captured_at,
        )


__all__ = ["ImageSourceAdapter", "ImageSourceRequest", "ReferenceImage"]
