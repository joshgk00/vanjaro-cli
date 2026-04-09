"""Walk a GrapesJS component tree and rewrite image src / link href attributes.

Phase 3 of the site migration tooling. Given an asset manifest mapping source
image URLs to Vanjaro URLs, and a page URL map mapping source page URLs to
Vanjaro paths, replace references in a content JSON file so nothing still
points at the original site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

__all__ = [
    "RewriteError",
    "RewriteReport",
    "build_asset_lookup",
    "build_page_lookup",
    "rewrite_tree",
]


class RewriteError(ValueError):
    """Raised when the inputs are structurally invalid."""


@dataclass
class RewriteReport:
    """Counts returned from a rewrite pass.

    ``missing_assets`` and ``missing_pages`` use ``dict`` as an insertion-
    ordered set — seeing the same missing URL twice does not double-count it.
    Callers should read them via :meth:`unique_missing_assets` and
    :meth:`unique_missing_pages` to get a concrete list.
    """

    images_rewritten: int = 0
    images_unchanged: int = 0
    links_rewritten: int = 0
    links_unchanged: int = 0
    anchors_skipped: int = 0
    external_skipped: int = 0
    missing_assets: dict[str, None] = field(default_factory=dict)
    missing_pages: dict[str, None] = field(default_factory=dict)

    def record_missing_asset(self, src: str) -> None:
        self.missing_assets[src] = None

    def record_missing_page(self, href: str) -> None:
        self.missing_pages[href] = None

    @property
    def missing_asset_count(self) -> int:
        return len(self.missing_assets)

    @property
    def missing_page_count(self) -> int:
        return len(self.missing_pages)

    def unique_missing_assets(self) -> list[str]:
        return list(self.missing_assets.keys())

    def unique_missing_pages(self) -> list[str]:
        return list(self.missing_pages.keys())

    def as_dict(self) -> dict:
        return {
            "images": {
                "rewritten": self.images_rewritten,
                "unchanged": self.images_unchanged,
                "missing": self.unique_missing_assets(),
            },
            "links": {
                "rewritten": self.links_rewritten,
                "unchanged": self.links_unchanged,
                "anchors": self.anchors_skipped,
                "external": self.external_skipped,
                "missing": self.unique_missing_pages(),
            },
        }


def build_asset_lookup(manifest: list[dict]) -> dict[str, str]:
    """Build a source-URL -> Vanjaro-URL map from an asset manifest.

    Only entries with a populated ``vanjaro_url`` are included. Both the raw
    source URL and its path-only form are stored so that content trees with
    either absolute or relative image references resolve.

    **Collision behavior**: when two absolute URLs share the same path (e.g.
    ``https://cdn.example.com/logo.png`` and ``https://www.example.com/logo.png``),
    the first entry's path-only alias wins and later entries only resolve via
    their absolute form. This is first-wins by manifest order.
    """
    if not isinstance(manifest, list):
        raise RewriteError("Asset manifest must be a JSON array of entries.")

    lookup: dict[str, str] = {}
    for index, entry in enumerate(manifest):
        if not isinstance(entry, dict):
            raise RewriteError(
                f"Asset manifest entry #{index} is not an object."
            )
        source_url = entry.get("source_url")
        vanjaro_url = entry.get("vanjaro_url")
        if not isinstance(source_url, str) or not isinstance(vanjaro_url, str):
            continue
        if not vanjaro_url:
            continue
        lookup[source_url] = vanjaro_url
        path_only = _path_only(source_url)
        if path_only and path_only not in lookup:
            lookup[path_only] = vanjaro_url
    return lookup


def build_page_lookup(page_map: dict[str, str] | None) -> dict[str, str]:
    """Normalize a page URL map so both absolute and path-only keys resolve."""
    if page_map is None:
        return {}
    if not isinstance(page_map, dict):
        raise RewriteError("Page URL map must be a JSON object.")

    lookup: dict[str, str] = {}
    for source, target in page_map.items():
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        if not target:
            continue
        lookup[source] = target
        path_only = _path_only(source)
        if path_only and path_only not in lookup:
            lookup[path_only] = target
        # Accept trailing-slash variants interchangeably.
        if source.endswith("/") and len(source) > 1:
            trimmed = source.rstrip("/")
            lookup.setdefault(trimmed, target)
    return lookup


def rewrite_tree(
    content: dict,
    asset_lookup: dict[str, str],
    page_lookup: dict[str, str],
) -> RewriteReport:
    """Mutate ``content`` in place, rewriting image and link URLs.

    ``content`` can be either a GrapesJS content document (``{"components":
    [...], "styles": [...]}``) or a single component dict. Walks the tree,
    replacing ``attributes.src`` on image components and ``attributes.href``
    on link-like components using the provided lookups.
    """
    if not isinstance(content, dict):
        raise RewriteError("Content must be a JSON object.")

    report = RewriteReport()

    if "components" in content and isinstance(content["components"], list):
        for component in content["components"]:
            _walk(component, asset_lookup, page_lookup, report)
    else:
        _walk(content, asset_lookup, page_lookup, report)

    return report


def _walk(
    node: object,
    asset_lookup: dict[str, str],
    page_lookup: dict[str, str],
    report: RewriteReport,
) -> None:
    if not isinstance(node, dict):
        return

    attributes = node.get("attributes")
    if isinstance(attributes, dict):
        if _is_image_component(node):
            _rewrite_src(attributes, asset_lookup, report)
        if _is_link_component(node):
            _rewrite_href(attributes, page_lookup, report)

    children = node.get("components")
    if isinstance(children, list):
        for child in children:
            _walk(child, asset_lookup, page_lookup, report)


def _is_image_component(node: dict) -> bool:
    return node.get("type") == "image"


def _is_link_component(node: dict) -> bool:
    if node.get("type") in ("link", "button"):
        return True
    if node.get("tagName") == "a":
        return True
    return False


def _rewrite_src(
    attributes: dict,
    asset_lookup: dict[str, str],
    report: RewriteReport,
) -> None:
    src = attributes.get("src")
    if not isinstance(src, str) or not src:
        report.images_unchanged += 1
        return

    replacement = _lookup_url(src, asset_lookup)
    if replacement is None:
        report.images_unchanged += 1
        report.record_missing_asset(src)
        return

    if replacement == src:
        report.images_unchanged += 1
        return

    attributes["src"] = replacement
    report.images_rewritten += 1


def _rewrite_href(
    attributes: dict,
    page_lookup: dict[str, str],
    report: RewriteReport,
) -> None:
    href = attributes.get("href")
    if not isinstance(href, str) or not href:
        report.links_unchanged += 1
        return

    if href.startswith("#"):
        report.anchors_skipped += 1
        return

    scheme = urlparse(href).scheme.lower()
    if scheme and scheme not in ("http", "https"):
        # mailto:, tel:, javascript:, etc. — leave alone.
        report.links_unchanged += 1
        return

    replacement = _lookup_url(href, page_lookup)
    if replacement is None:
        # Not in the page map — treat absolute URLs as external links and
        # relative paths as unmapped internal references.
        if scheme in ("http", "https"):
            report.external_skipped += 1
        else:
            report.links_unchanged += 1
            report.record_missing_page(href)
        return

    if replacement == href:
        report.links_unchanged += 1
        return

    attributes["href"] = replacement
    report.links_rewritten += 1


def _lookup_url(value: str, lookup: dict[str, str]) -> str | None:
    """Try a sequence of normalized forms when matching ``value``."""
    if not lookup:
        return None
    if value in lookup:
        return lookup[value]

    trimmed = value.rstrip("/")
    if trimmed and trimmed != value and trimmed in lookup:
        return lookup[trimmed]

    path_only = _path_only(value)
    if path_only and path_only in lookup:
        return lookup[path_only]

    if path_only:
        trimmed_path = path_only.rstrip("/")
        if trimmed_path and trimmed_path != path_only and trimmed_path in lookup:
            return lookup[trimmed_path]

    return None


def _path_only(url: str) -> str:
    """Return the path component of ``url``, or an empty string if none."""
    parsed = urlparse(url)
    if not parsed.scheme and not parsed.netloc:
        return ""
    return parsed.path or "/"
