"""Walk a GrapesJS component tree and rewrite image src / link href attributes.

Phase 3 of the site migration tooling. Given an asset manifest mapping source
image URLs to Vanjaro URLs, and a page URL map mapping source page URLs to
Vanjaro paths, replace references in a content JSON file so nothing still
points at the original site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from vanjaro_cli.migration.picture import build_picture_box, is_picture_box

__all__ = [
    "RewriteError",
    "RewriteReport",
    "build_asset_lookup",
    "build_variant_lookup",
    "build_page_lookup",
    "rewrite_tree",
    "substitute_css_urls",
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
    images_wrapped: int = 0
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
                "wrapped": self.images_wrapped,
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


def build_variant_lookup(manifest: list[dict]) -> dict[str, list]:
    """Build a ``vanjaro_url -> variants`` map from an asset manifest.

    The map is keyed by the *rewritten* portal URL (the value the image ``src``
    holds after ``build_asset_lookup`` replaces the source URL) so the wrapping
    pass can look up variants by the URL already on the component. Both the raw
    ``vanjaro_url`` and its query-stripped form are keyed, since stored URLs may
    carry a ``?ver=`` cache-buster the component drops or keeps inconsistently.

    Entries with no variants are omitted — only images Vanjaro actually
    generated responsive sizes for can be upgraded to ``<picture>``.
    """
    if not isinstance(manifest, list):
        raise RewriteError("Asset manifest must be a JSON array of entries.")

    lookup: dict[str, list] = {}
    for entry in manifest:
        if not isinstance(entry, dict):
            continue
        vanjaro_url = entry.get("vanjaro_url")
        variants = entry.get("variants")
        if not isinstance(vanjaro_url, str) or not vanjaro_url:
            continue
        if not isinstance(variants, list) or not variants:
            continue
        lookup.setdefault(vanjaro_url, variants)
        stripped = vanjaro_url.split("?", 1)[0]
        if stripped and stripped != vanjaro_url:
            lookup.setdefault(stripped, variants)
    return lookup


def build_page_lookup(page_map: dict[str, str] | None) -> dict[str, str]:
    """Normalize a page URL map so both absolute and path-only keys resolve.

    Known Vanjaro target paths (the *values* of ``page_map``) are also added
    as identity entries (``"/about" → "/about"``). That way, when a block
    library plan hard-codes a Vanjaro-format href like ``/about`` in a
    button, the rewriter treats it as an already-correct pass-through
    instead of flagging it as a missing internal reference.
    """
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

    # Add identity mappings for each distinct target so pre-rewritten
    # Vanjaro-format hrefs pass through as `links_unchanged`.
    for target in {t for t in page_map.values() if isinstance(t, str) and t}:
        lookup.setdefault(target, target)
        if target.endswith("/") and len(target) > 1:
            lookup.setdefault(target.rstrip("/"), target)

    return lookup


def rewrite_tree(
    content: dict,
    asset_lookup: dict[str, str],
    page_lookup: dict[str, str],
    variant_lookup: dict[str, list] | None = None,
) -> RewriteReport:
    """Mutate ``content`` in place, rewriting image and link URLs.

    ``content`` can be either a GrapesJS content document (``{"components":
    [...], "styles": [...]}``) or a single component dict. Walks the tree,
    replacing ``attributes.src`` on image components and ``attributes.href``
    on link-like components using the provided lookups.

    When ``variant_lookup`` is supplied, plain image components whose rewritten
    URL maps to manifest variants are replaced in place with a responsive
    ``picture-box`` tree (``<picture>`` with WebP + original-format srcsets).
    Images with no variants stay as plain ``<img>``.
    """
    if not isinstance(content, dict):
        raise RewriteError("Content must be a JSON object.")

    report = RewriteReport()

    if "components" in content and isinstance(content["components"], list):
        components = content["components"]
        for component in components:
            _walk(component, asset_lookup, page_lookup, report, variant_lookup)
        if variant_lookup:
            _wrap_images_in_list(components, variant_lookup, report)
    else:
        _walk(content, asset_lookup, page_lookup, report, variant_lookup)

    # Style rules carry section background images as url(...) values — the
    # component walk never sees them, so without this pass migrated hero
    # backgrounds keep hot-linking the source CDN.
    styles = content.get("styles")
    if isinstance(styles, list):
        for rule in styles:
            if not isinstance(rule, dict):
                continue
            style = rule.get("style")
            if not isinstance(style, dict):
                continue
            for prop, value in style.items():
                if isinstance(value, str) and "url(" in value.lower():
                    style[prop] = substitute_css_urls(value, asset_lookup, report)

    return report


def _walk(
    node: object,
    asset_lookup: dict[str, str],
    page_lookup: dict[str, str],
    report: RewriteReport,
    variant_lookup: dict[str, list] | None = None,
) -> None:
    if not isinstance(node, dict):
        return

    attributes = node.get("attributes")
    if isinstance(attributes, dict):
        if _is_image_component(node):
            _rewrite_src(attributes, asset_lookup, report)
        if _is_link_component(node):
            _rewrite_href(attributes, page_lookup, report)
        _rewrite_style_urls(attributes, asset_lookup, report)

    children = node.get("components")
    if isinstance(children, list):
        for child in children:
            _walk(child, asset_lookup, page_lookup, report, variant_lookup)
        if variant_lookup and not is_picture_box(node):
            _wrap_images_in_list(children, variant_lookup, report)


def _wrap_images_in_list(
    components: list,
    variant_lookup: dict[str, list],
    report: RewriteReport,
) -> None:
    """Replace plain image components in ``components`` with picture-box trees.

    Runs after ``src`` rewriting, so each image's ``src`` already points at its
    Vanjaro portal URL. An image is upgraded only when its rewritten URL maps to
    manifest variants; images with no variants (external, SVG, upload failure)
    are left as plain ``<img>``.
    """
    for index, child in enumerate(components):
        if not isinstance(child, dict) or not _is_image_component(child):
            continue
        if is_picture_box(child):
            continue
        attributes = child.get("attributes")
        if not isinstance(attributes, dict):
            continue
        rewritten_url = attributes.get("src")
        if not isinstance(rewritten_url, str) or not rewritten_url:
            continue
        variants = variant_lookup.get(rewritten_url)
        if not variants:
            continue
        picture_box = build_picture_box(child, rewritten_url, variants)
        if picture_box is not None:
            components[index] = picture_box
            report.images_wrapped += 1


# Quote group is captured and back-referenced on the close so a quoted
# reference stays quoted (with its original quote character) and an
# unquoted one stays unquoted; IGNORECASE covers authored ``URL(...)``.
_STYLE_URL = re.compile(r"url\(\s*(['\"]?)([^'\")]+)\1\s*\)", re.IGNORECASE)


def substitute_css_urls(
    css_value: str,
    asset_lookup: dict[str, str],
    report: RewriteReport,
) -> str:
    """Rewrite every url(...) reference in a CSS value string.

    Handles multiple ``url(...)`` tokens in one value (e.g. a layered
    background), quoted and unquoted forms, and a case-insensitive
    ``URL(...)`` function name. A reference with no entry in
    ``asset_lookup`` is left exactly as written -- callers rely on this to
    keep unmigrated references explicit rather than silently dropped.
    """

    def _substitute(match: re.Match) -> str:
        quote = match.group(1)
        original = match.group(2)
        replacement = _lookup_url(original, asset_lookup)
        if replacement is None:
            report.record_missing_asset(original)
            return match.group(0)
        if replacement != original:
            report.images_rewritten += 1
        else:
            report.images_unchanged += 1
        return f"url({quote}{replacement}{quote})"

    return _STYLE_URL.sub(_substitute, css_value)


def _rewrite_style_urls(
    attributes: dict,
    asset_lookup: dict[str, str],
    report: RewriteReport,
) -> None:
    """Rewrite url(...) references in inline style attributes.

    Section background images land as ``background-image:url(...)`` in the
    style attribute, outside the src/href fields the component walk covers.
    """
    style = attributes.get("style")
    if not isinstance(style, str) or "url(" not in style.lower():
        return

    attributes["style"] = substitute_css_urls(style, asset_lookup, report)


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
