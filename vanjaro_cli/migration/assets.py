"""Asset download and manifest generation."""

from __future__ import annotations

import re
import ssl
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

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_waf_session_cache: requests.Session | None = None


def _waf_session() -> requests.Session:
    """Return a lazily-created session that bypasses common WAF TLS fingerprinting.

    Uses OpenSSL cipher string "DEFAULT:@SECLEVEL=1" to allow older cipher
    suites that WAFs accept, combined with browser-like request headers.
    """
    global _waf_session_cache
    if _waf_session_cache is not None:
        return _waf_session_cache

    ssl_context = ssl.create_default_context()
    ssl_context.set_ciphers("DEFAULT:@SECLEVEL=1")

    https_adapter = requests.adapters.HTTPAdapter(max_retries=0)
    https_adapter.init_poolmanager(10, 10, ssl_context=ssl_context)

    session = requests.Session()
    session.mount("https://", https_adapter)
    session.headers.update(_BROWSER_HEADERS)

    _waf_session_cache = session
    return session


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


def _read_response_body(
    response: requests.Response,
    url: str,
    on_warning: Callable[[str], None],
) -> tuple[bytes, str] | None:
    """Stream `response` body with a size cap. Returns (content, content_type) or None."""
    try:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                on_warning(f"Skipped {url}: exceeds {MAX_RESPONSE_BYTES} byte cap")
                return None
            chunks.append(chunk)
    except requests.RequestException as exc:
        on_warning(f"Failed to read body from {url}: {exc}")
        return None
    finally:
        content_type = response.headers.get("Content-Type", "")
        response.close()

    return b"".join(chunks), content_type


def _should_waf_retry(exc: requests.RequestException | None, status_code: int | None) -> bool:
    """Return True when the failure pattern matches a WAF TLS or IP-block."""
    if status_code == 403:
        return True
    if exc is None:
        return False
    return isinstance(exc, (requests.exceptions.SSLError, requests.exceptions.ConnectionError))


def _stream_download(url: str, on_warning: Callable[[str], None]) -> tuple[bytes, str] | None:
    """Download `url` with a size cap. Returns (content, content_type) or None on failure.

    On SSLError, ConnectionError (connection reset), or HTTP 403 — all common
    signs of WAF TLS-fingerprint blocking — retries once with a browser-like
    session that uses cipher string DEFAULT:@SECLEVEL=1.
    """
    try:
        validate_http_url(url)
    except CrawlError as exc:
        on_warning(f"Refusing {url}: {exc}")
        return None

    first_exc: requests.RequestException | None = None
    first_status: int | None = None

    try:
        response = requests.get(
            url,
            timeout=DEFAULT_TIMEOUT,
            stream=True,
            headers={"User-Agent": USER_AGENT},
        )
        if response.status_code == 403:
            first_status = 403
            response.close()
            raise requests.exceptions.HTTPError(response=response)
        response.raise_for_status()
    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        first_exc = exc
    except requests.exceptions.HTTPError as exc:
        if first_status != 403:
            on_warning(f"Failed to download {url}: {exc}")
            return None
    except requests.RequestException as exc:
        on_warning(f"Failed to download {url}: {exc}")
        return None
    else:
        return _read_response_body(response, url, on_warning)

    if not _should_waf_retry(first_exc, first_status):
        on_warning(f"Failed to download {url}: {first_exc}")
        return None

    try:
        session = _waf_session()
        response = session.get(url, timeout=DEFAULT_TIMEOUT, stream=True)
        response.raise_for_status()
    except requests.RequestException as exc:
        on_warning(f"Failed to download {url} (including WAF retry): {exc}")
        return None

    return _read_response_body(response, url, on_warning)


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
