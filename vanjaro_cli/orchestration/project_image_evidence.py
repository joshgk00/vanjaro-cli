"""Audited project workflow for generating image evidence sidecars."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import ValidationError

from vanjaro_cli.design.image_evidence import ImageEvidenceSet
from vanjaro_cli.design.models import SourceKind
from vanjaro_cli.evidence import (
    EvidenceImageInput,
    ImageEvidenceGenerationRequest,
    ImageEvidenceProvider,
    ImageEvidenceProviderError,
)
from vanjaro_cli.orchestration.image_acquisition import (
    ImageAcquisitionError,
    acquire_reference_image,
    load_image_evidence,
    validate_evidence_identity,
)
from vanjaro_cli.orchestration.image_evidence_workflow_models import (
    PlannedImageEvidence,
    ProjectImageEvidenceError,
    ProjectImageEvidencePlan,
    ProjectImageEvidenceResult,
)
from vanjaro_cli.orchestration.image_evidence_validation import (
    enforce_request_size_limits,
    locked_image_evidence_adoption,
    manifest_fingerprint,
    require_manifest_fingerprint,
    revalidate_source_images,
    validate_provider_observations,
)
from vanjaro_cli.project import (
    AuditEvent,
    ProjectManifest,
    ProjectSource,
    ProjectStage,
    ProjectWorkspaceError,
    artifact_path,
    fingerprint_data,
    invalidate_stage_state,
    load_manifest,
    write_manifest,
)


def plan_project_image_evidence(
    root: Path,
    *,
    source_ids: Sequence[str] = (),
    overwrite: bool = False,
) -> ProjectImageEvidencePlan:
    """Validate local images and determine sidecar actions without writes or API calls."""

    root = root.expanduser().resolve()
    manifest = load_manifest(root)
    selected = _select_sources(manifest, source_ids)
    items: list[PlannedImageEvidence] = []
    for source in selected:
        try:
            image = acquire_reference_image(root, source)
        except ImageAcquisitionError as exc:
            raise _acquisition_error(exc) from exc
        reference = source.evidence_reference or f"sources/{source.id}.evidence.json"
        path = _evidence_output_path(root, source, reference)
        action = "generate"
        if path.exists():
            if not path.is_file():
                raise ProjectImageEvidenceError(
                    "image_evidence_not_file",
                    f"image evidence output for {source.id!r} is not a regular file: {reference}",
                    source_id=source.id,
                    recommended_action="Choose a workspace-local .json file path.",
                )
            if overwrite:
                action = "overwrite"
            else:
                candidate = source.model_copy(update={"evidence_reference": reference})
                try:
                    evidence = load_image_evidence(path, candidate)
                    validate_evidence_identity(evidence, candidate, image)
                except ImageAcquisitionError as exc:
                    raise ProjectImageEvidenceError(
                        exc.code,
                        str(exc),
                        source_id=exc.source_id,
                        recommended_action=(
                            f"Retry with --overwrite after reviewing the stale sidecar for {source.id}."
                        ),
                    ) from exc
                action = "skip"
        items.append(
            PlannedImageEvidence(
                source=source,
                image=image,
                evidence_reference=reference.replace("\\", "/"),
                action=action,
            )
        )
    _require_complete_page_refresh(items)
    enforce_request_size_limits(items)
    references = [item.evidence_reference.casefold() for item in items]
    if len(references) != len(set(references)):
        raise ProjectImageEvidenceError(
            "image_evidence_output_collision",
            "multiple image sources resolve to the same evidence sidecar path",
            recommended_action="Assign a unique .evidence.json path to every image source.",
        )
    return ProjectImageEvidencePlan(
        project_id=manifest.project.id,
        manifest_fingerprint=manifest_fingerprint(manifest),
        items=tuple(items),
    )


def generate_project_image_evidence(
    root: Path,
    provider: ImageEvidenceProvider | None,
    *,
    source_ids: Sequence[str] = (),
    overwrite: bool = False,
    generated_by: str,
    clock: Callable[[], datetime] | None = None,
) -> ProjectImageEvidenceResult:
    """Generate, validate, snapshot, and atomically adopt project image evidence."""

    root = root.expanduser().resolve()
    now = (clock or _utc_now)()
    if now.utcoffset() is None:
        raise ProjectImageEvidenceError(
            "image_evidence_clock_invalid",
            "image evidence generation clock must include a timezone",
            recommended_action="Use a timezone-aware UTC clock.",
        )
    author = generated_by.strip()
    if not author:
        raise ProjectImageEvidenceError(
            "image_evidence_author_missing",
            "image evidence generation requires an operator identity",
            recommended_action="Pass --by with the responsible operator name.",
        )
    plan = plan_project_image_evidence(
        root, source_ids=source_ids, overwrite=overwrite
    )
    targets = [item for item in plan.items if item.action != "skip"]
    skipped = tuple(item.source.id for item in plan.items if item.action == "skip")
    if not targets:
        return ProjectImageEvidenceResult(
            plan=plan,
            generated_sources=(),
            skipped_sources=skipped,
            artifacts=(),
            provider=None,
            model=None,
            response_ids=(),
            request_fingerprints=(),
            invalidated_stages=(),
        )
    if provider is None:
        raise ProjectImageEvidenceError(
            "image_evidence_provider_missing",
            "image evidence generation requires a provider when sidecars need generation",
            recommended_action="Configure the selected provider and retry.",
        )

    groups: dict[str, list[PlannedImageEvidence]] = defaultdict(list)
    for item in targets:
        assert item.source.page_reference is not None
        groups[item.source.page_reference].append(item)

    generated: dict[str, tuple[ImageEvidenceSet, str, str, str | None, str]] = {}
    response_ids: list[str] = []
    fingerprints: list[str] = []
    provider_name: str | None = None
    model_name: str | None = None
    for page_slug in sorted(groups):
        items = sorted(
            groups[page_slug],
            key=lambda item: (item.source.breakpoint.value, item.source.id),
        )
        request = ImageEvidenceGenerationRequest(
            project_id=plan.project_id,
            images=tuple(_provider_input(item) for item in items),
            captured_at=now,
        )
        try:
            result = provider.generate(request)
        except ImageEvidenceProviderError as exc:
            raise ProjectImageEvidenceError(
                exc.code,
                str(exc),
                recommended_action=exc.recommended_action,
            ) from exc
        except (ValidationError, ValueError, OSError) as exc:
            if isinstance(exc, ProjectImageEvidenceError):
                raise
            raise ProjectImageEvidenceError(
                "image_evidence_provider_failed",
                f"image evidence provider failed: {exc}",
                recommended_action="Review provider configuration and retry; no sidecars were changed.",
            ) from exc
        provider_name = result.provider
        model_name = result.model
        if result.response_id:
            response_ids.append(result.response_id)
        fingerprints.append(result.request_fingerprint)
        by_source = validate_provider_observations(result.evidence, items)
        for planned in items:
            observation = by_source[planned.source.id]
            generated[planned.source.id] = (
                ImageEvidenceSet(
                    producer=result.evidence.producer,
                    observations=[observation],
                ),
                planned.evidence_reference,
                result.provider,
                result.response_id,
                result.request_fingerprint,
            )

    return _adopt_generated_evidence(
        root,
        plan,
        generated,
        author=author,
        now=now,
        provider_name=provider_name,
        model_name=model_name,
        response_ids=tuple(response_ids),
        fingerprints=tuple(fingerprints),
        skipped=skipped,
    )


@locked_image_evidence_adoption
def _adopt_generated_evidence(
    root: Path,
    plan: ProjectImageEvidencePlan,
    generated: dict[str, tuple[ImageEvidenceSet, str, str, str | None, str]],
    *,
    author: str,
    now: datetime,
    provider_name: str | None,
    model_name: str | None,
    response_ids: tuple[str, ...],
    fingerprints: tuple[str, ...],
    skipped: tuple[str, ...],
) -> ProjectImageEvidenceResult:
    manifest = load_manifest(root).model_copy(deep=True)
    require_manifest_fingerprint(plan, manifest)
    revalidate_source_images(root, plan, tuple(generated))
    temporary: list[Path] = []
    temporary_by_destination: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    created: list[Path] = []
    artifacts: list[str] = []
    try:
        for source_id, (evidence, reference, _provider, _response, _fingerprint) in generated.items():
            destination = artifact_path(root, reference)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = destination.with_name(
                f".{destination.name}.{source_id}.{uuid4().hex}.tmp"
            )
            temp.write_text(evidence.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
            temporary.append(temp)
            temporary_by_destination[destination] = temp
        stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for source_id, (_evidence, reference, _provider, _response, _fingerprint) in generated.items():
            destination = artifact_path(root, reference)
            if destination.exists():
                old_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
                backup_relative = (
                    f"history/evidence/{stamp}-{source_id}-{old_hash[:8]}-"
                    f"{uuid4().hex[:8]}.json"
                )
                backup = artifact_path(root, backup_relative)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
                backups[destination] = backup
                artifacts.append(backup_relative)
            else:
                created.append(destination)
            temp = temporary_by_destination[destination]
            temp.replace(destination)
            temporary.remove(temp)
            artifacts.append(reference)

        sources = []
        for source in manifest.sources:
            generated_item = generated.get(source.id)
            sources.append(
                source.model_copy(update={"evidence_reference": generated_item[1]})
                if generated_item is not None
                else source
            )
        invalidated = invalidate_stage_state(
            manifest,
            ProjectStage.ANALYZE,
            now=now,
            resolved_by=author,
            approval_note="Superseded because generated image evidence changed analysis input.",
        )
        manifest.sources = sources
        aggregate_fingerprint = fingerprint_data(sorted(fingerprints))
        manifest.audit.append(
            AuditEvent(
                id=f"event-{len(manifest.audit) + 1:05d}-image-evidence-generated",
                occurred_at=now,
                kind="image_evidence_generated",
                message=(
                    f"{author} generated image evidence for {len(generated)} source(s) "
                    f"with {provider_name or 'provider'} model {model_name or 'unknown'}; "
                    f"invalidated: {', '.join(invalidated) or 'no completed stages'}."
                ),
                stage=ProjectStage.ANALYZE,
                fingerprint=aggregate_fingerprint,
                artifacts=artifacts,
            )
        )
        manifest.project = manifest.project.model_copy(
            update={"updated_at": max(manifest.project.updated_at, now)}
        )
        require_manifest_fingerprint(plan, load_manifest(root))
        write_manifest(root, ProjectManifest.model_validate(manifest.model_dump()))
    except Exception:
        for temp in temporary:
            temp.unlink(missing_ok=True)
        for destination in created:
            destination.unlink(missing_ok=True)
        for destination, backup in backups.items():
            shutil.copy2(backup, destination)
            backup.unlink(missing_ok=True)
        raise

    return ProjectImageEvidenceResult(
        plan=plan,
        generated_sources=tuple(sorted(generated)),
        skipped_sources=skipped,
        artifacts=tuple(artifacts),
        provider=provider_name,
        model=model_name,
        response_ids=response_ids,
        request_fingerprints=fingerprints,
        invalidated_stages=invalidated,
    )


def _select_sources(
    manifest: ProjectManifest, source_ids: Sequence[str]
) -> list[ProjectSource]:
    images = [source for source in manifest.sources if source.kind == SourceKind.IMAGE]
    if not images:
        raise ProjectImageEvidenceError(
            "image_source_missing",
            "project contains no image sources",
            recommended_action="Initialize or add an image source before generating evidence.",
        )
    if not source_ids:
        return images
    requested = set(source_ids)
    known = {source.id: source for source in manifest.sources}
    unknown = sorted(requested - set(known))
    if unknown:
        raise ProjectImageEvidenceError(
            "image_source_unknown",
            "unknown project source ID(s): " + ", ".join(unknown),
            recommended_action="Use `vanjaro project status` and project.json to select valid image source IDs.",
        )
    non_images = sorted(source_id for source_id in requested if known[source_id].kind != SourceKind.IMAGE)
    if non_images:
        raise ProjectImageEvidenceError(
            "image_source_kind_invalid",
            "selected source ID(s) are not images: " + ", ".join(non_images),
            recommended_action="Select only sources whose kind is image.",
        )
    selected = [source for source in images if source.id in requested]
    selected_pages = {source.page_reference for source in selected}
    omitted = sorted(
        source.id
        for source in images
        if source.page_reference in selected_pages and source.id not in requested
    )
    if omitted:
        raise ProjectImageEvidenceError(
            "image_evidence_incomplete_page_selection",
            "selected pages omit image breakpoint source(s): " + ", ".join(omitted),
            recommended_action=(
                "Select every image source for the page together, or omit --source to generate all."
            ),
        )
    return selected


def _require_complete_page_refresh(items: Sequence[PlannedImageEvidence]) -> None:
    by_page: dict[str, list[PlannedImageEvidence]] = defaultdict(list)
    for item in items:
        by_page[item.source.page_reference or ""].append(item)
    for page, values in by_page.items():
        actions = {item.action for item in values}
        if "skip" in actions and len(actions) > 1:
            raise ProjectImageEvidenceError(
                "image_evidence_partial_page",
                f"page {page!r} mixes retained and regenerated breakpoint evidence",
                recommended_action=(
                    "Regenerate every selected breakpoint for the page together with --overwrite "
                    "so section IDs and responsive correspondence remain consistent."
                ),
            )


def _evidence_output_path(root: Path, source: ProjectSource, reference: str) -> Path:
    if urlsplit(reference).scheme:
        raise ProjectImageEvidenceError(
            "image_evidence_remote_unsupported",
            f"image evidence output for {source.id!r} must be workspace-local: {reference}",
            source_id=source.id,
            recommended_action="Use a path under the project sources/ directory.",
        )
    if Path(reference).suffix.casefold() != ".json":
        raise ProjectImageEvidenceError(
            "image_evidence_type_unsupported",
            f"image evidence output for {source.id!r} must use a .json path: {reference}",
            source_id=source.id,
            recommended_action="Use a workspace-local .evidence.json path.",
        )
    try:
        return artifact_path(root, reference)
    except ProjectWorkspaceError as exc:
        raise ProjectImageEvidenceError(
            "image_evidence_outside_workspace",
            str(exc),
            source_id=source.id,
            recommended_action="Use a path under the project sources/ directory.",
        ) from exc


def _provider_input(item: PlannedImageEvidence) -> EvidenceImageInput:
    source = item.source
    assert source.page_reference and source.breakpoint and source.viewport
    return EvidenceImageInput(
        source_id=source.id,
        path=item.image.relative_path,
        mime_type=item.image.mime_type,
        payload=_read_planned_image(item),
        sha256=item.image.sha256,
        page_slug=source.page_reference,
        breakpoint=source.breakpoint,
        viewport=source.viewport,
        image_width=item.image.width,
        image_height=item.image.height,
    )


def _read_planned_image(item: PlannedImageEvidence) -> bytes:
    try:
        return item.image.path.read_bytes()
    except OSError as exc:
        raise ProjectImageEvidenceError(
            "image_read_failed",
            f"cannot read image source {item.source.id!r}: {exc}",
            source_id=item.source.id,
            recommended_action="Check file permissions and retry.",
        ) from exc


def _acquisition_error(exc: ImageAcquisitionError) -> ProjectImageEvidenceError:
    return ProjectImageEvidenceError(
        exc.code,
        str(exc),
        source_id=exc.source_id,
        recommended_action=exc.recommended_action,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "PlannedImageEvidence",
    "ProjectImageEvidenceError",
    "ProjectImageEvidencePlan",
    "ProjectImageEvidenceResult",
    "generate_project_image_evidence",
    "plan_project_image_evidence",
]
