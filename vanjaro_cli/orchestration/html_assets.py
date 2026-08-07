"""Acquisition of remote images referenced by an HTML source."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import re

from vanjaro_cli.design.models import AssetRecord, DesignDocument, DesignWarning
from vanjaro_cli.migration.assets import download_assets

__all__ = ["acquire_html_assets"]


_ABSOLUTE_HTTP = re.compile(r"^https?:", re.IGNORECASE)

AssetDownloader = Callable[[list[str], Path, Callable[[str], None]], list[dict]]


def _needs_acquisition(asset: AssetRecord) -> bool:
    """Report whether an asset is a remote reference the build cannot use.

    A page in a portal can load a relative path or a data URI. An absolute
    http(s) source is someone else's origin, so the planner blanks it rather
    than hotlinking — which is right, and is why the image has to be fetched
    here instead.
    """

    if asset.local_path:
        return False
    return bool(asset.source_url) and _ABSOLUTE_HTTP.match(asset.source_url or "") is not None


def _stable_name(source_url: str, downloaded_name: str) -> str:
    """Name a workspace asset by its source, not by what was free on disk.

    The crawl downloader avoids collisions by appending a number, which is
    right for a crawl and wrong for a workspace: re-analysing wrote
    `hero-1.png` beside `hero.png` and the directory kept two copies of every
    image. A digest of the source URL is the same on every run, so a re-run
    overwrites in place.
    """

    suffix = "".join(Path(downloaded_name).suffixes[-1:]) or ".bin"
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16] + suffix


def _discard_previous_acquisition(root: Path, manifest_path: Path) -> None:
    """Remove exactly the files a previous acquisition recorded.

    The downloader gives a colliding name a numeric suffix, so re-analysing
    doubled every image on disk instead of replacing it — seventeen assets
    became thirty-four after one `--refresh`. Only paths this source recorded
    in its own manifest are removed; nothing else in the workspace is touched.
    """

    if not manifest_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for entry in manifest.get("assets", []):
        recorded = entry.get("local_path")
        if not isinstance(recorded, str):
            continue
        previous = root / recorded
        if previous.is_file():
            previous.unlink()


def acquire_html_assets(
    *,
    root: Path,
    source_id: str,
    document: DesignDocument,
    downloader: AssetDownloader = download_assets,
) -> tuple[DesignDocument, tuple[str, ...]]:
    """Download every remote image the document references into the workspace.

    Without this a live page analyses with `local_path` unset on every asset,
    and a template whose media field is required cannot bind at all — the plan
    then reports the field as missing when the field is present and only its
    bytes are absent.

    Returns the updated document and the artifacts written. An image that
    cannot be acquired is recorded twice — as a reason on the asset and as a
    document warning — never as a silent drop.
    """

    pending = [asset for asset in document.assets if _needs_acquisition(asset)]
    if not pending:
        return document, ()

    warnings: list[str] = []
    destination = root / "sources" / source_id
    manifest_relative = f"sources/{source_id}/asset-manifest.json"
    _discard_previous_acquisition(root, root / manifest_relative)
    urls = list(dict.fromkeys(str(asset.source_url) for asset in pending))
    entries = downloader(urls, destination, warnings.append)
    by_url = {str(entry["source_url"]): entry for entry in entries}

    acquired: list[dict[str, object]] = []
    assets: list[AssetRecord] = []
    artifacts: list[str] = []
    for asset in document.assets:
        entry = by_url.get(str(asset.source_url)) if _needs_acquisition(asset) else None
        if entry is None:
            if _needs_acquisition(asset):
                assets.append(
                    asset.model_copy(
                        update={"missing_reason": "Image could not be downloaded from its source."}
                    )
                )
            else:
                assets.append(asset)
            continue
        relative = f"sources/{source_id}/assets/{_stable_name(str(asset.source_url), str(entry['local_file']))}"
        path = root / relative
        downloaded = destination / "assets" / str(entry["local_file"])
        # Two elements can share one source, and the download happens once, so
        # the move has already run by the second element that references it.
        if downloaded != path and downloaded.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            downloaded.replace(path)
        acquired.append(
            {
                "asset_id": asset.id,
                "source_url": asset.source_url,
                "downloaded": True,
                "local_path": relative,
                "mime_type": entry.get("content_type") or None,
                "size_bytes": entry.get("size_bytes"),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
            }
        )
        artifacts.append(relative)
        assets.append(
            asset.model_copy(
                update={
                    "local_path": relative,
                    "mime_type": entry.get("content_type") or asset.mime_type,
                    "missing_reason": None,
                }
            )
        )

    manifest_path = root / manifest_relative
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "source_id": source_id,
                "assets": sorted(acquired, key=lambda entry: str(entry["asset_id"])),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts.append(manifest_relative)
    # The downloader's own messages say why; one warning per unresolved asset
    # would repeat them without adding anything the asset record does not
    # already carry as its missing reason.
    document_warnings = list(document.warnings) + [
        DesignWarning(code="html_asset_download_failed", message=message, path=source_id)
        for message in warnings
    ]
    return (
        document.model_copy(update={"assets": assets, "warnings": document_warnings}),
        tuple(artifacts),
    )
