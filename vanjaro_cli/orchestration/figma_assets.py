"""Acquire stable local copies of Figma image-fill assets for project builds."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Protocol

from vanjaro_cli.design.models import DesignDocument


_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


class FigmaAssetDownloadClient(Protocol):
    def download(self, url: str, dest: Path) -> tuple[int, str]: ...


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


__all__ = ["FigmaAssetDownloadClient", "acquire_figma_image_fills"]
