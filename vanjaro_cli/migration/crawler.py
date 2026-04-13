"""Page discovery and HTML fetching for migration crawls."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

__all__ = [
    "CrawlError",
    "DEFAULT_TIMEOUT",
    "MAX_RESPONSE_BYTES",
    "USER_AGENT",
    "fetch_url_text",
    "discover_pages",
    "infer_page_hierarchy",
    "same_domain",
    "path_matches",
    "slugify_path",
    "validate_http_url",
]

DEFAULT_TIMEOUT = 30
USER_AGENT = "vanjaro-cli-migrate/1.0"
MAX_RESPONSE_BYTES = 25 * 1024 * 1024  # 25 MB per response — guards against OOM on hostile sites
ALLOWED_SCHEMES = frozenset({"http", "https"})
# Schemes ignored during link discovery — everything not in ALLOWED_SCHEMES is dropped,
# but these are called out explicitly because BeautifulSoup often encounters them.
IGNORED_LINK_SCHEMES = frozenset({
    "mailto", "tel", "javascript", "data", "file", "ftp", "sms", "blob", "about",
})
# File extensions we refuse to treat as discoverable pages. A site that links
# directly to an image, document, or archive from an <a href> should not cause
# the crawler to fetch the binary and try to parse it as HTML — that produces
# empty "pages" that crowd out real content under the --max-pages cap.
NON_PAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif", ".bmp", ".ico", ".tiff",
    ".mp4", ".webm", ".mov", ".avi", ".mkv", ".mp3", ".wav", ".ogg", ".flac",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".7z", ".rar",
    ".css", ".js", ".json", ".xml", ".rss", ".atom",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
})

SITEMAP_LOC = re.compile(r"<loc[^>]*>([^<]+)</loc>", re.IGNORECASE)


def _is_page_url(url: str) -> bool:
    """Return False for URLs whose path ends in a known non-page extension.

    Used to drop direct-file links (images, PDFs, zips) from the discoverable
    page list so the crawler doesn't waste its --max-pages budget fetching
    binaries and parsing them as HTML.
    """
    path = urlparse(url).path.lower()
    last_segment = path.rsplit("/", 1)[-1]
    if "." not in last_segment:
        return True
    extension = "." + last_segment.rsplit(".", 1)[-1]
    return extension not in NON_PAGE_EXTENSIONS


class CrawlError(Exception):
    """Raised when a crawl operation fails unrecoverably."""


def validate_http_url(url: str) -> None:
    """Raise CrawlError if `url` is not a well-formed http(s) URL."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        raise CrawlError(f"Refusing non-http(s) URL: {url}")


def fetch_url_text(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Fetch a URL and return the response text.

    Enforces http(s) scheme, caps response body at MAX_RESPONSE_BYTES, and
    decodes using the server-supplied charset. Raises CrawlError on any failure.
    """
    validate_http_url(url)
    try:
        response = requests.get(
            url,
            timeout=timeout,
            stream=True,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise CrawlError(f"Failed to fetch {url}: {exc}") from exc

    try:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise CrawlError(
                    f"Response from {url} exceeds {MAX_RESPONSE_BYTES} byte cap"
                )
            chunks.append(chunk)
    except requests.RequestException as exc:
        raise CrawlError(f"Failed to read body from {url}: {exc}") from exc
    finally:
        response.close()

    encoding = response.encoding or "utf-8"
    return b"".join(chunks).decode(encoding, errors="replace")


def same_domain(url: str, base_url: str) -> bool:
    """Return True if `url` is on the same host as `base_url`."""
    return urlparse(url).netloc == urlparse(base_url).netloc


def path_matches(
    path: str,
    include_patterns: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
) -> bool:
    """Apply glob include/exclude rules to a URL path (case-insensitive)."""
    path_lower = path.lower()
    include_lower = tuple(p.lower() for p in include_patterns)
    exclude_lower = tuple(p.lower() for p in exclude_patterns)
    if include_lower and not any(fnmatch.fnmatchcase(path_lower, p) for p in include_lower):
        return False
    if any(fnmatch.fnmatchcase(path_lower, p) for p in exclude_lower):
        return False
    return True


def slugify_path(path: str) -> str:
    """Turn a URL path into a flat directory slug. '/' becomes 'home'."""
    cleaned = path.strip("/").replace("/", "-")
    if not cleaned:
        return "home"
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in cleaned).strip("-") or "home"


def _normalize_path(path: str) -> str:
    """Return a canonical form of ``path`` for parent-slug comparison.

    Strips trailing slashes (except on the root), strips a trailing ``.html``
    /``.htm``/``.php``/``.aspx`` extension, and lowercases the whole value.
    Two URL paths that point at the same logical page (``/services`` and
    ``/services.html``, ``/Services/`` and ``/services``) collapse to the
    same normalized form so parent inference can match them.
    """
    normalized = path.lower().rstrip("/") or "/"
    for extension in (".html", ".htm", ".php", ".aspx"):
        if normalized.endswith(extension):
            normalized = normalized[: -len(extension)] or "/"
            break
    return normalized


def infer_page_hierarchy(pages: list[dict]) -> list[dict]:
    """Annotate each page dict with a ``parent_slug`` inferred from URL paths.

    For each page, walks up its URL path segment-by-segment looking for a
    shallower page whose path matches a prefix — ``/services/web-design``
    finds ``/services`` as its parent, not the root. Root pages (``/``) and
    pages whose parent isn't in the inventory get ``parent_slug = None``.
    Mutates ``pages`` in place and returns the same list.
    """
    path_to_slug: dict[str, str] = {}
    for page in pages:
        path = page.get("path")
        slug = page.get("slug")
        if isinstance(path, str) and isinstance(slug, str):
            path_to_slug[_normalize_path(path)] = slug

    for page in pages:
        path = page.get("path")
        slug = page.get("slug")
        if not isinstance(path, str) or not isinstance(slug, str):
            continue

        normalized = _normalize_path(path)
        if normalized == "/":
            page["parent_slug"] = None
            continue

        # The site root ("/") is never considered a parent: DNN treats
        # top-level pages as siblings of home, not children of it.
        segments = normalized.strip("/").split("/")
        parent_slug: str | None = None
        for depth in range(len(segments) - 1, 0, -1):
            candidate = "/" + "/".join(segments[:depth])
            if candidate in path_to_slug and path_to_slug[candidate] != slug:
                parent_slug = path_to_slug[candidate]
                break

        page["parent_slug"] = parent_slug

    return pages


def _extract_links_from_html(html: str, base_url: str) -> list[str]:
    """Extract same-domain navigation and body links from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith("#"):
            continue
        href_scheme = href.split(":", 1)[0].lower() if ":" in href else ""
        if href_scheme and href_scheme in IGNORED_LINK_SCHEMES:
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ALLOWED_SCHEMES:
            continue
        if same_domain(absolute, base_url):
            # Drop fragments so /#section doesn't dedupe against /
            clean = parsed._replace(fragment="").geturl()
            if _is_page_url(clean):
                found.append(clean)

    return found


def _parse_sitemap(xml_text: str) -> list[str]:
    """Parse sitemap.xml content and return the list of URLs.

    Uses a regex instead of ElementTree so malicious sitemaps (billion-laughs,
    external entities) can't attack the parser.
    """
    return [match.strip() for match in SITEMAP_LOC.findall(xml_text)]


def discover_pages(
    start_url: str,
    max_pages: int,
    include_patterns: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
    on_warning: Callable[[str], None] | None = None,
) -> tuple[list[str], str]:
    """Discover page URLs starting from `start_url`.

    Returns (ordered_unique_urls, homepage_html). The homepage is always first.
    Sitemap fetch failures other than 404 are reported via `on_warning`.
    """
    validate_http_url(start_url)

    # Normalize the start URL so it matches what shows up in discovered links.
    # A bare domain like "https://example.com" must become "https://example.com/"
    # or `urljoin` will produce a different URL than BeautifulSoup's <a href="/"> link.
    parsed_start = urlparse(start_url)
    if not parsed_start.path:
        parsed_start = parsed_start._replace(path="/")
    normalized_start = parsed_start._replace(fragment="").geturl()

    homepage_html = fetch_url_text(normalized_start)
    discovered: list[str] = []
    seen: set[str] = set()

    def _add(url: str) -> None:
        if url in seen:
            return
        if not _is_page_url(url):
            return
        parsed = urlparse(url)
        path = parsed.path or "/"
        if not path_matches(path, include_patterns, exclude_patterns):
            return
        seen.add(url)
        discovered.append(url)

    _add(normalized_start)

    for link in _extract_links_from_html(homepage_html, normalized_start):
        _add(link)

    sitemap_url = urljoin(normalized_start, "/sitemap.xml")
    try:
        sitemap_text = fetch_url_text(sitemap_url)
    except CrawlError as exc:
        if on_warning and "404" not in str(exc):
            on_warning(f"Sitemap fetch failed: {exc}")
    else:
        for url in _parse_sitemap(sitemap_text):
            if same_domain(url, normalized_start):
                _add(url)

    return discovered[:max_pages], homepage_html
