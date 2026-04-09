"""Asset download and manifest generation."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from vanjaro_cli.migration.crawler import (
    CrawlError,
    DEFAULT_TIMEOUT,
    MAX_RESPONSE_BYTES,
    USER_AGENT,
    validate_http_url,
)

__all__ = ["download_assets", "safe_filename"]

# Windows reserved device names — writing to any of these opens the device instead of a file.
_WINDOWS_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")
_REPEAT_DOTS = re.compile(r"\.{2,}")
_MAX_FILENAME_LENGTH = 200


def safe_filename(url: str) -> str:
    """Extract a safe filename from an asset URL.

    Strips path components, query strings, and traversal sequences. Rejects
    Windows reserved device names and caps length at 200 chars to stay under
    NAME_MAX on common filesystems.
    """
    parsed = urlparse(url)
    # basename only — no directory components survive
    raw = unquote(Path(parsed.path).name)
    cleaned = _UNSAFE_CHARS.sub("_", raw)
    cleaned = _REPEAT_DOTS.sub(".", cleaned).strip("._-")

    stem = cleaned.rsplit(".", 1)[0].upper() if cleaned else ""
    if not cleaned or stem in _WINDOWS_RESERVED:
        return "asset"
    return cleaned[:_MAX_FILENAME_LENGTH]


def _unique_filename(target_dir: Path, filename: str) -> str:
    """Make `filename` unique within `target_dir` by appending a counter if needed."""
    candidate = target_dir / filename
    if not candidate.exists():
        return filename
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 1
    while (target_dir / f"{stem}-{counter}{suffix}").exists():
        counter += 1
    return f"{stem}-{counter}{suffix}"


def _stream_download(url: str, on_warning: Callable[[str], None]) -> tuple[bytes, str] | None:
    """Download `url` with a size cap. Returns (content, content_type) or None on failure."""
    try:
        validate_http_url(url)
    except CrawlError as exc:
        on_warning(f"Refusing {url}: {exc}")
        return None

    try:
        response = requests.get(
            url,
            timeout=DEFAULT_TIMEOUT,
            stream=True,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        on_warning(f"Failed to download {url}: {exc}")
        return None

    try:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                on_warning(
                    f"Skipped {url}: exceeds {MAX_RESPONSE_BYTES} byte cap"
                )
                return None
            chunks.append(chunk)
    except requests.RequestException as exc:
        on_warning(f"Failed to read body from {url}: {exc}")
        return None
    finally:
        content_type = response.headers.get("Content-Type", "")
        response.close()

    return b"".join(chunks), content_type


def download_assets(
    urls: list[str],
    output_dir: Path,
    on_warning: Callable[[str], None],
) -> list[dict]:
    """Download `urls` to `output_dir/assets/` and return manifest entries.

    Failures for individual assets are reported via `on_warning(message)` and do
    not abort the crawl.
    """
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    url_to_filename: dict[str, str] = {}

    for url in urls:
        if url in url_to_filename:
            continue
        filename = _unique_filename(assets_dir, safe_filename(url))

        result = _stream_download(url, on_warning)
        if result is None:
            continue
        content, content_type = result

        try:
            (assets_dir / filename).write_bytes(content)
        except OSError as exc:
            on_warning(f"Failed to write {filename}: {exc}")
            continue

        url_to_filename[url] = filename
        manifest.append({
            "source_url": url,
            "local_file": filename,
            "filename": filename,
            "size_bytes": len(content),
            "content_type": content_type,
            "vanjaro_url": None,
            "vanjaro_file_id": None,
            "uploaded": False,
        })

    return manifest
