"""Acquire project sources and produce one auditable Design Document artifact."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from vanjaro_cli.design.composite import (
    CompositeDesignInput,
    DesignMergeError,
    merge_design_documents as merge_composite_documents,
)
from vanjaro_cli.design.models import DesignDocument, SourceKind
from vanjaro_cli.design.serialization import serialize_design_document
from vanjaro_cli.design.html_adapter import serve_local_directory
from vanjaro_cli.design.sources import (
    FigmaSourceRequest,
    HtmlSourceRequest,
    ImageSourceRequest,
    LegacyCrawlSourceRequest,
    ReferenceImage,
    analyze_source,
)
from vanjaro_cli.figma import FigmaClient, FigmaError, parse_file_key, parse_node_id
from vanjaro_cli.migration.crawler import fetch_url_text
from vanjaro_cli.orchestration.figma_assets import acquire_figma_image_fills
from vanjaro_cli.orchestration.html_assets import acquire_html_assets
from vanjaro_cli.orchestration.image_acquisition import (
    ImageAcquisitionError,
    acquire_reference_image,
    load_image_evidence,
    resolve_evidence_file,
    validate_evidence_identity,
)
from vanjaro_cli.project.models import ProjectManifest, ProjectSource
from vanjaro_cli.project.stage_engine import StageContext, StageResult


class ProjectAnalysisError(ValueError):
    """Raised when project evidence cannot be acquired or combined safely."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "project_analysis_failed",
        source_id: str | None = None,
        recommended_action: str | None = None,
    ) -> None:
        self.code = code
        self.source_id = source_id
        self.recommended_action = recommended_action
        super().__init__(message)

    def as_dict(self) -> dict[str, str | None]:
        return {
            "category": self.code,
            "message": str(self),
            "source_id": self.source_id,
            "recommended_action": self.recommended_action,
        }


class _FigmaClient(Protocol):
    def get_file(self, key: str, depth: int | None = None, node_ids: list[str] | None = None) -> dict: ...
    def get_nodes(self, key: str, ids: list[str]) -> dict: ...
    def get_image_fills(self, key: str) -> dict[str, str]: ...
    def download(self, url: str, dest: Path) -> tuple[int, str]: ...


def source_input_files(root: Path, manifest: ProjectManifest) -> tuple[Path, ...]:
    """Return every workspace-local input file that must participate in resumption."""

    root = root.expanduser().resolve()
    paths: list[Path] = []
    for source in manifest.sources:
        if source.kind == SourceKind.IMAGE:
            try:
                image = acquire_reference_image(root, source)
                paths.append(image.relative_path)
                if source.evidence_reference is not None:
                    _, evidence_relative = resolve_evidence_file(root, source)
                    paths.append(evidence_relative)
            except ImageAcquisitionError as exc:
                raise ProjectAnalysisError(
                    str(exc),
                    code=exc.code,
                    source_id=exc.source_id,
                    recommended_action=exc.recommended_action,
                ) from exc
            continue
        local = _local_reference(root, source.reference)
        if local is None:
            continue
        if not local.exists():
            raise ProjectAnalysisError(
                f"source {source.id!r} does not exist: {source.reference}"
            )
        try:
            relative = local.relative_to(root)
        except ValueError as exc:
            raise ProjectAnalysisError(
                f"local source {source.id!r} must be inside the project workspace; "
                "copy it into sources/ and update project.json"
            ) from exc
        if local.is_dir():
            files = sorted(
                (path for path in local.rglob("*") if path.is_file()),
                key=lambda path: path.relative_to(root).as_posix(),
            )
            if not files:
                raise ProjectAnalysisError(
                    f"source directory {source.reference!r} contains no files"
                )
            paths.extend(path.relative_to(root) for path in files)
        elif local.is_file():
            paths.append(relative)
        else:
            raise ProjectAnalysisError(
                f"source {source.id!r} is not a regular file or directory"
            )
    return tuple(dict.fromkeys(paths))


def run_project_analysis(
    context: StageContext,
    *,
    html_fetcher: Callable[[str], str] | None = None,
    figma_client_factory: Callable[[], _FigmaClient] | None = None,
    render: bool = False,
) -> StageResult:
    """Analyze all declared inputs, retain per-source evidence, and merge deterministically.

    ``render`` drives HTML sources through a browser so the Design Document
    carries measured geometry and computed styles. Without it the fidelity
    metrics have no design-side evidence for colour, typography, spacing, or
    media, and layout scores without its bounds subscore.
    """

    fetch_html = html_fetcher or fetch_url_text
    make_figma_client = figma_client_factory or FigmaClient
    analyzed: list[tuple[ProjectSource, DesignDocument]] = []
    serialized_sources: list[
        tuple[ProjectSource, DesignDocument, str, tuple[str, ...]]
    ] = []
    for source in context.manifest.sources:
        try:
            document, acquired_artifacts = _analyze_source(
                context.root,
                source,
                project_id=context.manifest.project.id,
                captured_at=context.manifest.project.created_at,
                html_fetcher=fetch_html,
                figma_client_factory=make_figma_client,
                render=render,
            )
        except ImageAcquisitionError as exc:
            raise ProjectAnalysisError(
                str(exc),
                code=exc.code,
                source_id=exc.source_id,
                recommended_action=exc.recommended_action,
            ) from exc
        except (FigmaError, OSError, ValueError, TypeError) as exc:
            if isinstance(exc, ProjectAnalysisError):
                raise
            raise ProjectAnalysisError(f"source {source.id!r} failed: {exc}") from exc
        document = _annotate_document(document, source)
        serialized = serialize_design_document(document)
        analyzed.append((source, document))
        serialized_sources.append(
            (source, document, serialized, acquired_artifacts)
        )

    combined = merge_design_documents(context.manifest.project.id, analyzed)
    combined_serialized = serialize_design_document(combined)
    artifacts: list[str] = []
    index_sources: list[dict[str, Any]] = []
    for source, document, serialized, acquired_artifacts in serialized_sources:
        artifacts.extend(acquired_artifacts)
        relative = f"analysis/sources/{source.id}.design-document.json"
        _atomic_write_text(context.root / relative, serialized)
        artifacts.append(relative)
        index_sources.append(
            {
                "id": source.id,
                "kind": source.kind.value,
                "reference": source.reference,
                "page_reference": source.page_reference,
                "artifact": relative,
                "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                "pages": len(document.pages),
                "sections": sum(len(page.sections) for page in document.pages),
                "assets": len(document.assets),
                "warnings": len(document.warnings),
            }
        )

    combined_path = "analysis/design-document.json"
    index_path = "analysis/source-index.json"
    report_path = "analysis/analysis-report.json"
    _atomic_write_text(context.root / combined_path, combined_serialized)
    index = {
        "schema_version": "1.0",
        "project_id": context.manifest.project.id,
        "combined_artifact": combined_path,
        "combined_sha256": hashlib.sha256(combined_serialized.encode("utf-8")).hexdigest(),
        "sources": index_sources,
    }
    report = {
        "schema_version": "1.0",
        "project_id": context.manifest.project.id,
        "source_count": len(analyzed),
        "pages": len(combined.pages),
        "sections": sum(len(page.sections) for page in combined.pages),
        "assets": len(combined.assets),
        "warnings": len(combined.warnings),
        "unsupported_traits": combined.analysis.unsupported_traits,
        "section_confidence_mean": combined.analysis.section_confidence_mean,
    }
    _atomic_write_json(context.root / index_path, index)
    _atomic_write_json(context.root / report_path, report)
    artifacts.extend((combined_path, index_path, report_path))
    return StageResult(
        artifacts=tuple(artifacts),
        message=(
            f"Analyzed {len(analyzed)} source(s) into {report['pages']} page(s) and "
            f"{report['sections']} section(s)."
        ),
    )


def merge_design_documents(
    project_id: str,
    analyzed: Sequence[tuple[ProjectSource, DesignDocument]],
) -> DesignDocument:
    """Adapt project source records to the pure composite-design service."""

    try:
        return merge_composite_documents(
            project_id,
            [
                CompositeDesignInput(
                    source_id=source.id,
                    page_reference=source.page_reference,
                    document=document,
                )
                for source, document in analyzed
            ],
        )
    except DesignMergeError as exc:
        raise ProjectAnalysisError(str(exc)) from exc


def _analyze_source(
    root: Path,
    source: ProjectSource,
    *,
    project_id: str,
    captured_at: Any,
    html_fetcher: Callable[[str], str],
    figma_client_factory: Callable[[], _FigmaClient],
    render: bool = False,
) -> tuple[DesignDocument, tuple[str, ...]]:
    local = _local_reference(root, source.reference)
    if source.kind == SourceKind.LIVE_HTML:
        if local is None:
            html = html_fetcher(source.reference)
            source_url = source.reference
            render_url = source.reference
        else:
            html = local.read_text(encoding="utf-8")
            source_url = _string_metadata(source, "source_url") or local.as_uri()
            render_url = local.as_uri()
        request_fields = {
            "html": html,
            "source_url": source_url,
            "title": _string_metadata(source, "title"),
            "slug": source.page_reference or _string_metadata(source, "slug"),
            "render": render,
        }
        if render and local is not None:
            # Serve the saved copy rather than rendering it from `file://`: its
            # stylesheets are usually root-relative and cannot resolve without a
            # site root, so a file render paints browser defaults and describes
            # nothing the author chose. Loopback only, and it reaches no network.
            with serve_local_directory(local) as served_url:
                document = analyze_source(
                    HtmlSourceRequest(**request_fields, render_url=served_url)
                )
        else:
            document = analyze_source(
                HtmlSourceRequest(**request_fields, render_url=render_url)
            )
        return acquire_html_assets(root=root, source_id=source.id, document=document)
    if source.kind == SourceKind.FIGMA:
        node_id = _string_metadata(source, "node_id")
        if node_id:
            node_id = parse_node_id(node_id)
        elif local is None:
            node_id = parse_node_id(source.reference)
        if local is not None:
            payload = json.loads(local.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ProjectAnalysisError("Figma JSON source must contain an object")
            file_key = _string_metadata(source, "file_key") or source.id
            fill_urls = None
            client = None
        else:
            file_key = parse_file_key(source.reference)
            client = figma_client_factory()
            payload = (
                client.get_nodes(file_key, [node_id])
                if node_id
                else client.get_file(file_key)
            )
            fill_urls = client.get_image_fills(file_key)
        document = analyze_source(
            FigmaSourceRequest(
                payload=payload,
                file_key=file_key,
                node_id=node_id,
                image_fill_urls=fill_urls,
            )
        )
        if client is None or fill_urls is None:
            return document, ()
        return acquire_figma_image_fills(
            root=root,
            source_id=source.id,
            document=document,
            fill_urls=fill_urls,
            client=client,
        )
    if source.kind == SourceKind.LEGACY_SECTIONS:
        if local is None or not local.is_dir():
            raise ProjectAnalysisError(
                "legacy_sections source must reference a workspace-local crawl directory"
            )
        return (
            analyze_source(LegacyCrawlSourceRequest(migration_directory=local)),
            (),
        )
    if source.kind == SourceKind.IMAGE:
        image = acquire_reference_image(root, source)
        evidence_path, _ = resolve_evidence_file(root, source)
        evidence = load_image_evidence(evidence_path, source)
        validate_evidence_identity(evidence, source, image)
        assert (
            source.viewport is not None
            and source.breakpoint is not None
            and source.page_reference is not None
        )
        return (
            analyze_source(
                ImageSourceRequest(
                    images=(
                        ReferenceImage(
                            path=image.relative_path,
                            page_slug=source.page_reference,
                            breakpoint=source.breakpoint,
                            viewport_width=source.viewport.width,
                            viewport_height=source.viewport.height,
                            sha256=image.sha256,
                        ),
                    ),
                    project_id=project_id,
                    evidence=evidence,
                    captured_at=captured_at,
                )
            ),
            (),
        )
    raise ProjectAnalysisError(f"unsupported project source kind: {source.kind.value}")


def _annotate_document(document: DesignDocument, source: ProjectSource) -> DesignDocument:
    metadata = {
        **document.source.metadata,
        "project_source_id": source.id,
        "project_page_reference": source.page_reference,
    }
    pages = [
        page.model_copy(
            update={
                "metadata": {
                    **page.metadata,
                    "project_source_id": source.id,
                    "project_page_reference": source.page_reference,
                }
            }
        )
        for page in document.pages
    ]
    return document.model_copy(
        update={
            "source": document.source.model_copy(update={"metadata": metadata}),
            "pages": pages,
        }
    )


def _local_reference(root: Path, reference: str) -> Path | None:
    path = Path(reference).expanduser()
    if path.is_absolute():
        return path.resolve()
    parsed = urlsplit(reference)
    if parsed.scheme in {"http", "https"}:
        return None
    if parsed.scheme:
        raise ProjectAnalysisError(
            f"unsupported source reference scheme {parsed.scheme!r}: {reference}"
        )
    return (root / path).resolve()


def _string_metadata(source: ProjectSource, key: str) -> str | None:
    value = source.metadata.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _atomic_write_json(path: Path, value: object) -> None:
    _atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


__all__ = [
    "ProjectAnalysisError",
    "merge_design_documents",
    "run_project_analysis",
    "source_input_files",
]
