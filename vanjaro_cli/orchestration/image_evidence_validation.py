"""Fail-closed validation at image-evidence workflow boundaries."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from functools import wraps
import os
from pathlib import Path
from typing import ParamSpec, TypeVar

from vanjaro_cli.design.image_evidence import (
    ImageEvidenceSet,
    ImageObservationEvidence,
)
from vanjaro_cli.orchestration.image_acquisition import (
    ImageAcquisitionError,
    acquire_reference_image,
)
from vanjaro_cli.orchestration.image_evidence_workflow_models import (
    PlannedImageEvidence,
    ProjectImageEvidenceError,
    ProjectImageEvidencePlan,
)
from vanjaro_cli.project import ProjectManifest, fingerprint_data


MAX_EVIDENCE_IMAGE_BYTES = 20 * 1024 * 1024
MAX_EVIDENCE_PAGE_BYTES = 40 * 1024 * 1024
_P = ParamSpec("_P")
_T = TypeVar("_T")


def locked_image_evidence_adoption(
    function: Callable[_P, _T],
) -> Callable[_P, _T]:
    """Serialize evidence adoption while leaving provider calls lock-free."""

    @wraps(function)
    def wrapped(root: Path, *args, **kwargs):
        lock_path = root / ".image-evidence.lock"
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise ProjectImageEvidenceError(
                "image_evidence_project_locked",
                "another image evidence result is currently being adopted",
                recommended_action=(
                    "Wait for the other command to finish. If it crashed, review and remove "
                    f"the stale lock at {lock_path.name}."
                ),
            ) from exc
        except OSError as exc:
            raise ProjectImageEvidenceError(
                "image_evidence_lock_failed",
                f"could not create the image evidence adoption lock: {exc}",
                recommended_action="Check project directory permissions and retry.",
            ) from exc
        try:
            os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
            return function(root, *args, **kwargs)
        finally:
            os.close(descriptor)
            lock_path.unlink(missing_ok=True)

    return wrapped


def validate_provider_observations(
    evidence: ImageEvidenceSet,
    items: Sequence[PlannedImageEvidence],
) -> dict[str, ImageObservationEvidence]:
    """Require exactly one correctly bound observation per requested source."""

    expected = {item.source.id for item in items}
    by_source: dict[str, ImageObservationEvidence] = {}
    for observation in evidence.observations:
        metadata = observation.metadata
        source_id = metadata.get("provider_source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ProjectImageEvidenceError(
                "image_evidence_provider_ownership",
                "provider result contains an observation without a source owner",
                recommended_action="Retry; no sidecars were changed.",
            )
        if source_id in by_source:
            raise ProjectImageEvidenceError(
                "image_evidence_provider_ownership",
                f"provider result contains duplicate observations for {source_id!r}",
                source_id=source_id,
                recommended_action="Retry; no sidecars were changed.",
            )
        by_source[source_id] = observation
    actual = set(by_source)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("unexpected: " + ", ".join(extra))
        raise ProjectImageEvidenceError(
            "image_evidence_provider_ownership",
            "provider result source ownership differs from the request ("
            + "; ".join(details)
            + ")",
            recommended_action="Retry; no sidecars were changed.",
        )
    for planned in items:
        observation = by_source[planned.source.id]
        source = planned.source
        viewport = source.viewport
        assert source.page_reference and source.breakpoint and viewport
        identity_matches = (
            observation.source_sha256 == planned.image.sha256
            and observation.page_slug == source.page_reference
            and observation.breakpoint == source.breakpoint
            and observation.viewport == viewport
            and observation.image_width == planned.image.width
            and observation.image_height == planned.image.height
        )
        if not identity_matches:
            raise ProjectImageEvidenceError(
                "image_evidence_provider_identity",
                f"provider result identity differs from source {source.id!r}",
                source_id=source.id,
                recommended_action="Retry; no sidecars were changed.",
            )
    return by_source


def manifest_fingerprint(manifest: ProjectManifest) -> str:
    return fingerprint_data(manifest.model_dump(mode="json"))


def require_manifest_fingerprint(
    plan: ProjectImageEvidencePlan,
    manifest: ProjectManifest,
) -> None:
    if manifest_fingerprint(manifest) != plan.manifest_fingerprint:
        raise ProjectImageEvidenceError(
            "image_evidence_project_changed",
            "project manifest changed while image evidence was being generated",
            recommended_action=(
                "Review the current project state and retry; generated results were not adopted."
            ),
        )


def revalidate_source_images(
    root: Path,
    plan: ProjectImageEvidencePlan,
    generated_source_ids: Sequence[str],
) -> None:
    """Ensure the raster files still match what the provider analyzed."""

    planned = {item.source.id: item for item in plan.items}
    for source_id in generated_source_ids:
        item = planned[source_id]
        try:
            current = acquire_reference_image(root, item.source)
        except ImageAcquisitionError as exc:
            raise ProjectImageEvidenceError(
                exc.code,
                str(exc),
                source_id=exc.source_id,
                recommended_action=exc.recommended_action,
            ) from exc
        identity = (
            current.sha256,
            current.width,
            current.height,
            current.byte_size,
        )
        expected = (
            item.image.sha256,
            item.image.width,
            item.image.height,
            item.image.byte_size,
        )
        if identity != expected:
            raise ProjectImageEvidenceError(
                "image_evidence_source_changed",
                f"image source {source_id!r} changed while evidence was being generated",
                source_id=source_id,
                recommended_action=(
                    "Retry from the current image; generated results were not adopted."
                ),
            )


def enforce_request_size_limits(items: Sequence[PlannedImageEvidence]) -> None:
    """Bound memory/base64 expansion before any provider is configured."""

    by_page: dict[str, int] = defaultdict(int)
    for item in items:
        if item.action == "skip":
            continue
        size = item.image.byte_size
        if size > MAX_EVIDENCE_IMAGE_BYTES:
            raise ProjectImageEvidenceError(
                "image_evidence_image_too_large",
                f"image source {item.source.id!r} is {size} bytes; the limit is "
                f"{MAX_EVIDENCE_IMAGE_BYTES} bytes",
                source_id=item.source.id,
                recommended_action=(
                    "Re-export or optimize the screenshot below 20 MiB, then retry."
                ),
            )
        by_page[item.source.page_reference or ""] += size
    for page, size in by_page.items():
        if size > MAX_EVIDENCE_PAGE_BYTES:
            raise ProjectImageEvidenceError(
                "image_evidence_request_too_large",
                f"image sources for page {page!r} total {size} bytes; the limit is "
                f"{MAX_EVIDENCE_PAGE_BYTES} bytes",
                recommended_action=(
                    "Optimize the page screenshots below 40 MiB total, then retry."
                ),
            )


__all__ = [
    "MAX_EVIDENCE_IMAGE_BYTES",
    "MAX_EVIDENCE_PAGE_BYTES",
    "enforce_request_size_limits",
    "locked_image_evidence_adoption",
    "manifest_fingerprint",
    "require_manifest_fingerprint",
    "revalidate_source_images",
    "validate_provider_observations",
]
