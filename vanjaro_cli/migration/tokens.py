"""Design token extraction from CSS — colors, fonts, spacing."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from vanjaro_cli.migration.crawler import CrawlError, fetch_url_text, same_domain

__all__ = ["extract_design_tokens"]

HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{3,4}){1,2}\b")
RGB_COLOR = re.compile(r"rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+(?:\s*,\s*[\d.]+)?\s*\)")
FONT_FAMILY = re.compile(r"font-family\s*:\s*([^;{}]+)[;}]", re.IGNORECASE)
SPACING = re.compile(r"(?:margin|padding)(?:-[a-z]+)?\s*:\s*([^;{}]+)[;}]", re.IGNORECASE)
SPACE_VALUE = re.compile(r"\b\d+(?:\.\d+)?(?:px|rem|em)\b")


def _noop_warn(_: str) -> None:
    pass


def _fetch_stylesheets(
    homepage_html: str,
    base_url: str,
    on_warning: Callable[[str], None],
) -> str:
    """Concatenate all same-domain linked stylesheets and inline <style> blocks."""
    soup = BeautifulSoup(homepage_html, "html.parser")
    chunks: list[str] = []

    for style in soup.find_all("style"):
        if style.string:
            chunks.append(style.string)

    for link in soup.find_all("link", rel=True):
        rels = link.get("rel", [])
        if "stylesheet" not in rels:
            continue
        href = link.get("href")
        if not href:
            continue
        absolute = urljoin(base_url, href)
        if not same_domain(absolute, base_url):
            continue
        try:
            chunks.append(fetch_url_text(absolute))
        except CrawlError as exc:
            on_warning(f"Failed to fetch stylesheet {absolute}: {exc}")
            continue

    return "\n".join(chunks)


def _top_counter(values: list[str], limit: int) -> list[str]:
    """Return the top `limit` most common values from a list, preserving order."""
    counts = Counter(values)
    return [value for value, _ in counts.most_common(limit)]


def extract_design_tokens(
    homepage_html: str,
    base_url: str,
    on_warning: Callable[[str], None] | None = None,
) -> dict:
    """Extract colors, fonts, and spacing from a site's CSS.

    Returns a dict with `colors`, `fonts`, and `spacing` lists. The extraction is
    regex-based and intentionally lenient — the agent reviews the output. Stylesheet
    fetch failures are reported via `on_warning` instead of aborting.
    """
    warn = on_warning or _noop_warn
    css_text = _fetch_stylesheets(homepage_html, base_url, warn)

    colors = HEX_COLOR.findall(css_text) + RGB_COLOR.findall(css_text)
    top_colors = _top_counter([c.lower() for c in colors], limit=10)

    font_declarations: list[str] = []
    for match in FONT_FAMILY.findall(css_text):
        first_family = match.split(",")[0].strip().strip("'\"")
        if first_family:
            font_declarations.append(first_family)
    top_fonts = _top_counter(font_declarations, limit=5)

    spacing_values: list[str] = []
    for match in SPACING.findall(css_text):
        spacing_values.extend(SPACE_VALUE.findall(match))
    top_spacing = _top_counter(spacing_values, limit=10)

    return {
        "colors": top_colors,
        "fonts": top_fonts,
        "spacing": top_spacing,
    }
