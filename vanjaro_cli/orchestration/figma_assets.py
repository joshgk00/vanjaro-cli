"""Acquire stable local copies of Figma image-fill assets for project builds."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Protocol

from vanjaro_cli.design.models import AssetKind, DesignDocument
from vanjaro_cli.figma import FigmaError


_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


# Figma carries node ids in the request URL, and instance-child ids are long
# (`I156:908;39:17`), so a large batch can exceed the URL length limit.
_VECTOR_EXPORT_BATCH_SIZE = 40
_VECTOR_WARNING_CODE = "FIGMA_VECTOR_EXPORT_UNRESOLVED"


class FigmaAssetDownloadClient(Protocol):
    def download(self, url: str, dest: Path) -> tuple[int, str]: ...


class FigmaVectorExportClient(FigmaAssetDownloadClient, Protocol):
    def get_image_renders(
        self, key: str, ids: list[str], scale: float = 2, image_format: str = "png",
    ) -> dict: ...


def acquire_figma_image_fills(
    *,
    root: Path,
    source_id: str,
    document: DesignDocument,
    fill_urls: Mapping[str, str],
    client: FigmaAssetDownloadClient,
) -> tuple[DesignDocument, tuple[str, ...]]:
    """Download every referenced original fill and return updated local paths."""

    destination = root / "sources" / source_id / "assets"
    acquired: dict[str, dict[str, object]] = {}
    artifacts: list[str] = []
    assets = []
    for asset in document.assets:
        image_ref = asset.metadata.get("figma_image_ref")
        if not isinstance(image_ref, str):
            assets.append(asset)
            continue
        signed_url = fill_urls.get(image_ref)
        if not signed_url:
            acquired[image_ref] = {
                "asset_id": asset.id,
                "source_url": asset.source_url,
                "downloaded": False,
                "missing_reason": "Figma did not return an original image-fill URL.",
            }
            assets.append(asset)
            continue

        destination.mkdir(parents=True, exist_ok=True)
        temporary = destination / f".{asset.id}.download"
        size_bytes, content_type = client.download(signed_url, temporary)
        prefix = temporary.read_bytes()[:16]
        suffix = _extension(content_type, prefix)
        final = destination / f"{asset.id}{suffix}"
        temporary.replace(final)
        relative = final.relative_to(root).as_posix()
        digest = hashlib.sha256(final.read_bytes()).hexdigest()
        artifacts.append(relative)
        acquired[image_ref] = {
            "asset_id": asset.id,
            "source_url": asset.source_url,
            "downloaded": True,
            "local_path": relative,
            "mime_type": content_type or None,
            "size_bytes": size_bytes,
            "sha256": digest,
        }
        assets.append(
            asset.model_copy(
                update={
                    "local_path": relative,
                    "mime_type": content_type or asset.mime_type,
                    "missing_reason": None,
                }
            )
        )

    manifest_relative = f"sources/{source_id}/asset-manifest.json"
    manifest_path = root / manifest_relative
    _atomic_write_text(
        manifest_path,
        json.dumps(
            {
                "schema_version": "1.0",
                "source_id": source_id,
                "assets": [acquired[key] for key in sorted(acquired)],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    artifacts.append(manifest_relative)
    return document.model_copy(update={"assets": assets}), tuple(artifacts)


def acquire_figma_vector_exports(
    *,
    root: Path,
    source_id: str,
    file_key: str,
    document: DesignDocument,
    client: FigmaVectorExportClient,
) -> tuple[DesignDocument, tuple[str, ...]]:
    """Render each unresolved vector asset as one SVG and store it locally.

    The adapter points every vector asset at the node Figma should render: the
    whole icon or logo group, not its fragments. Figma's render endpoint is
    asked for those nodes in batches. A node it will not render keeps its
    unresolved warning and a reason, so a missing icon is never silent.
    """

    pending = [
        asset for asset in document.assets
        if asset.kind == AssetKind.SVG
        and not asset.local_path
        and isinstance(asset.metadata.get("figma_node_id"), str)
    ]
    if not pending:
        return document, ()

    node_ids = sorted({str(asset.metadata["figma_node_id"]) for asset in pending})
    signed_urls: dict[str, str | None] = {}
    batch_errors: dict[str, str] = {}
    for start in range(0, len(node_ids), _VECTOR_EXPORT_BATCH_SIZE):
        batch = node_ids[start:start + _VECTOR_EXPORT_BATCH_SIZE]
        try:
            rendered = client.get_image_renders(file_key, batch, image_format="svg")
        except FigmaError as exc:
            for node_id in batch:
                batch_errors[node_id] = str(exc)
            continue
        images = rendered.get("images")
        for node_id in batch:
            url = images.get(node_id) if isinstance(images, Mapping) else None
            signed_urls[node_id] = url if isinstance(url, str) and url else None

    destination = root / "sources" / source_id / "assets"
    artifacts: list[str] = []
    entries: dict[str, dict[str, object]] = {}
    resolved_node_ids: set[str] = set()
    updated: dict[str, object] = {}
    for asset in pending:
        node_id = str(asset.metadata["figma_node_id"])
        signed_url = signed_urls.get(node_id)
        reason = batch_errors.get(node_id) or (
            None if signed_url else "Figma did not render this vector node as an SVG."
        )
        if signed_url:
            destination.mkdir(parents=True, exist_ok=True)
            temporary = destination / f".{asset.id}.download"
            try:
                size_bytes, content_type = client.download(signed_url, temporary)
            except FigmaError as exc:
                reason = str(exc)
            else:
                prefix = temporary.read_bytes()[:16]
                final = destination / f"{asset.id}{_extension(content_type, prefix)}"
                temporary.replace(final)
                relative = final.relative_to(root).as_posix()
                artifacts.append(relative)
                resolved_node_ids.add(node_id)
                entries[node_id] = {
                    "asset_id": asset.id,
                    "figma_node_id": node_id,
                    "downloaded": True,
                    "local_path": relative,
                    "mime_type": content_type or "image/svg+xml",
                    "size_bytes": size_bytes,
                    "sha256": hashlib.sha256(final.read_bytes()).hexdigest(),
                }
                updated[asset.id] = asset.model_copy(update={
                    "source_url": f"figma://{file_key}/node/{node_id}",
                    "local_path": relative,
                    "mime_type": content_type or "image/svg+xml",
                    "missing_reason": None,
                    "metadata": {**asset.metadata, "original_available": True},
                })
                continue
        entries[node_id] = {
            "asset_id": asset.id, "figma_node_id": node_id,
            "downloaded": False, "missing_reason": reason,
        }
        updated[asset.id] = asset.model_copy(update={"missing_reason": reason})

    warnings = [
        warning for warning in document.warnings
        if not (
            warning.code == _VECTOR_WARNING_CODE
            and warning.path.removeprefix("figma.nodes[").removesuffix("]") in resolved_node_ids
        )
    ]
    remaining_codes = {warning.code for warning in warnings}
    traits = [
        trait for trait in document.analysis.unsupported_traits
        if trait != _VECTOR_WARNING_CODE or _VECTOR_WARNING_CODE in remaining_codes
    ]
    manifest_relative = f"sources/{source_id}/asset-manifest.json"
    _merge_manifest_entries(root / manifest_relative, source_id, entries.values())
    artifacts.append(manifest_relative)
    return (
        document.model_copy(update={
            "assets": [updated.get(asset.id, asset) for asset in document.assets],
            "warnings": warnings,
            "analysis": document.analysis.model_copy(update={"unsupported_traits": traits}),
        }),
        tuple(artifacts),
    )


def _merge_manifest_entries(path: Path, source_id: str, entries: object) -> None:
    existing: list[object] = []
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        existing = list(loaded.get("assets", []))
    _atomic_write_text(
        path,
        json.dumps(
            {"schema_version": "1.0", "source_id": source_id, "assets": [*existing, *entries]},
            ensure_ascii=False, indent=2, sort_keys=True,
        ) + "\n",
    )


def _extension(content_type: str, first_bytes: bytes) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().casefold()
    if normalized in _EXTENSIONS:
        return _EXTENSIONS[normalized]
    if first_bytes.startswith(b"\x89PNG"):
        return ".png"
    if first_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if first_bytes.lstrip().lower().startswith(b"<svg"):
        return ".svg"
    return ".bin"


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


__all__ = [
    "FigmaAssetDownloadClient",
    "FigmaVectorExportClient",
    "acquire_figma_image_fills",
    "acquire_figma_vector_exports",
]
