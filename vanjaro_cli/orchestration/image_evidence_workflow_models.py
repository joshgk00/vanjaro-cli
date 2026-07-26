"""Typed results and errors for the project image-evidence workflow."""

from __future__ import annotations

from dataclasses import dataclass

from vanjaro_cli.orchestration.image_acquisition import AcquiredReferenceImage
from vanjaro_cli.project import ProjectSource


class ProjectImageEvidenceError(ValueError):
    """Categorized project-level evidence generation failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        recommended_action: str,
        source_id: str | None = None,
    ) -> None:
        self.code = code
        self.recommended_action = recommended_action
        self.source_id = source_id
        super().__init__(message)

    def as_dict(self) -> dict[str, str | None]:
        return {
            "category": self.code,
            "message": str(self),
            "source_id": self.source_id,
            "recommended_action": self.recommended_action,
        }


@dataclass(frozen=True, slots=True)
class PlannedImageEvidence:
    source: ProjectSource
    image: AcquiredReferenceImage
    evidence_reference: str
    action: str

    def as_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source.id,
            "page_reference": self.source.page_reference,
            "breakpoint": self.source.breakpoint.value if self.source.breakpoint else None,
            "image": self.image.relative_path.as_posix(),
            "image_sha256": self.image.sha256,
            "evidence_reference": self.evidence_reference,
            "action": self.action,
        }


@dataclass(frozen=True, slots=True)
class ProjectImageEvidencePlan:
    project_id: str
    manifest_fingerprint: str
    items: tuple[PlannedImageEvidence, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "manifest_fingerprint": self.manifest_fingerprint,
            "items": [item.as_dict() for item in self.items],
            "generate_count": sum(item.action != "skip" for item in self.items),
            "skip_count": sum(item.action == "skip" for item in self.items),
        }


@dataclass(frozen=True, slots=True)
class ProjectImageEvidenceResult:
    plan: ProjectImageEvidencePlan
    generated_sources: tuple[str, ...]
    skipped_sources: tuple[str, ...]
    artifacts: tuple[str, ...]
    provider: str | None
    model: str | None
    response_ids: tuple[str, ...]
    request_fingerprints: tuple[str, ...]
    invalidated_stages: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            **self.plan.as_dict(),
            "generated_sources": list(self.generated_sources),
            "skipped_sources": list(self.skipped_sources),
            "artifacts": list(self.artifacts),
            "provider": self.provider,
            "model": self.model,
            "response_ids": list(self.response_ids),
            "request_fingerprints": list(self.request_fingerprints),
            "invalidated_stages": list(self.invalidated_stages),
        }


__all__ = [
    "PlannedImageEvidence",
    "ProjectImageEvidenceError",
    "ProjectImageEvidencePlan",
    "ProjectImageEvidenceResult",
]
