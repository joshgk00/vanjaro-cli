"""Design token extraction from CSS — colors, fonts, spacing.

The extractor is intentionally lenient: it scans raw CSS, ranks values by
frequency, and produces a starting point for the agent to review. To make
that starting point more useful it also:

- Resolves ``:root { --foo: bar }`` custom properties so ``var(--foo)``
  references in declarations get substituted with their actual values
  before ranking.
- Filters known framework default colors (Bootstrap 5 alert palette,
  generic neutrals) out of the brand-color list so the top results aren't
  drowned in vendor noise.
- Filters generic system font fallbacks (``serif``, ``sans-serif``,
  ``arial``, ``inherit``, ...) out of the font list so the result reflects
  actual brand typography choices.
- Splits colors into ``brand_colors`` (likely brand) and ``neutral_colors``
  (whites/blacks/transparents) so consumers can pick the right ones for
  Vanjaro's primary/secondary/tertiary slots without manual triage.

The legacy ``colors`` / ``fonts`` / ``spacing`` lists remain in the output
for backward compatibility — they now contain the filtered, var-resolved
values rather than raw CSS noise.
"""

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

# Match `:root { ... }` blocks (or `html { ... }`) to extract custom properties.
ROOT_BLOCK = re.compile(r"(?::root|html)\s*\{([^}]*)\}", re.IGNORECASE)
# Match `--name: value;` declarations inside a CSS block.
CSS_VAR_DECL = re.compile(r"--([a-zA-Z0-9_-]+)\s*:\s*([^;]+);")
# Match `var(--name)` or `var(--name, fallback)` references in declaration values.
CSS_VAR_REF = re.compile(r"var\(\s*--([a-zA-Z0-9_-]+)(?:\s*,\s*([^)]+))?\s*\)")

# Bootstrap 5 alert palette — these are framework defaults that show up
# in nearly every Bootstrap site's CSS but have nothing to do with brand.
BOOTSTRAP_ALERT_COLORS = frozenset({
    # success
    "#d4edda", "#155724", "#c3e6cb",
    # danger
    "#f8d7da", "#721c24", "#f5c6cb",
    # warning
    "#fff3cd", "#856404", "#ffeeba",
    # info
    "#d1ecf1", "#0c5460", "#bee5eb",
    # primary
    "#cce5ff", "#004085", "#b8daff",
    # secondary
    "#e2e3e5", "#383d41", "#d6d8db",
    # light
    "#fefefe", "#818182", "#fdfdfe",
    # dark
    "#d6d8d9", "#1b1e21", "#c6c8ca",
})

# Pure white/black variants. These rank as neutrals, not brand colors.
NEUTRAL_COLOR_LITERALS = frozenset({
    "#fff", "#ffffff",
    "#000", "#000000",
    "transparent",
})

# Generic system font fallbacks. They appear in every CSS reset block but
# tell us nothing about brand typography.
SYSTEM_FONT_FALLBACKS = frozenset({
    "serif", "sans-serif", "monospace", "cursive", "fantasy",
    "system-ui", "ui-serif", "ui-sans-serif", "ui-monospace",
    "inherit", "initial", "unset", "revert",
    "arial", "helvetica", "helvetica neue", "georgia", "times",
    "times new roman", "courier", "courier new", "verdana", "tahoma",
    "trebuchet ms", "impact", "comic sans ms", "lucida console",
    "segoe ui", "menlo", "monaco", "consolas",
    "-apple-system", "blinkmacsystemfont",
})


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


def _extract_css_variables(css: str) -> dict[str, str]:
    """Find every ``--name: value;`` declaration inside ``:root`` / ``html`` blocks.

    Returns a name → value map (without the leading dashes). Variable
    references inside variable values are NOT recursively resolved here —
    that happens in :func:`_resolve_var_references` so callers can apply
    the substitution to any string.
    """
    variables: dict[str, str] = {}
    for block in ROOT_BLOCK.findall(css):
        for name, value in CSS_VAR_DECL.findall(block):
            variables[name.strip()] = value.strip()
    return variables


def _resolve_var_references(value: str, variables: dict[str, str], depth: int = 0) -> str:
    """Substitute every ``var(--name)`` reference in ``value`` recursively.

    Recursion depth is capped to guard against circular variable definitions
    (e.g. ``--a: var(--b); --b: var(--a);``). Unresolved references fall
    back to the var() call's fallback value if present, otherwise are left
    intact so callers can detect the problem.
    """
    if depth > 8 or "var(" not in value:
        return value

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        fallback = (match.group(2) or "").strip()
        if name in variables:
            return _resolve_var_references(variables[name], variables, depth + 1)
        if fallback:
            return _resolve_var_references(fallback, variables, depth + 1)
        return match.group(0)

    return CSS_VAR_REF.sub(_replace, value)


def _resolve_variables_in_css(css: str, variables: dict[str, str]) -> str:
    """Apply :func:`_resolve_var_references` across the entire stylesheet."""
    if not variables:
        return css
    return _resolve_var_references(css, variables)


def _is_neutral_color(color: str) -> bool:
    """Return True if ``color`` is a generic black/white/transparent value.

    Detects:
    - Literal whites/blacks (``#fff``, ``#ffffff``, ``#000``, ``#000000``)
    - ``rgba(0, 0, 0, *)`` and ``rgba(255, 255, 255, *)`` at any opacity
    - The literal string ``transparent``
    """
    normalized = color.strip().lower()
    if normalized in NEUTRAL_COLOR_LITERALS:
        return True
    rgba_match = re.match(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*[\d.]+)?\s*\)",
        normalized,
    )
    if rgba_match:
        red, green, blue = (int(component) for component in rgba_match.groups())
        if red == green == blue and red in (0, 255):
            return True
    return False


def _is_framework_default_color(color: str) -> bool:
    """Return True if ``color`` is a known framework default (Bootstrap, etc.)."""
    return color.strip().lower() in BOOTSTRAP_ALERT_COLORS


def _is_system_font(family: str) -> bool:
    """Return True if ``family`` is a generic system font fallback."""
    return family.strip().lower() in SYSTEM_FONT_FALLBACKS


def _top_counter(values: list[str], limit: int) -> list[str]:
    """Return the top ``limit`` most common values, preserving frequency order."""
    counts = Counter(values)
    return [value for value, _ in counts.most_common(limit)]


def extract_design_tokens(
    homepage_html: str,
    base_url: str,
    on_warning: Callable[[str], None] | None = None,
) -> dict:
    """Extract colors, fonts, and spacing from a site's CSS.

    Returns a dict with these keys:

    - ``colors``: top brand colors as a flat list (frequency-ranked,
      framework defaults and pure neutrals removed). This is the list
      callers should hand to ``vanjaro theme set-bulk``.
    - ``brand_colors``: same as ``colors`` but always present even if
      empty, for callers that want the explicit semantic name.
    - ``neutral_colors``: blacks, whites, and transparent values that
      were filtered out of the brand list. Useful when picking text or
      background colors that intentionally need a neutral.
    - ``fonts``: top brand fonts (system fallbacks like ``arial`` and
      ``sans-serif`` removed, ``var(--x)`` references resolved).
    - ``spacing``: top numeric spacing values from margin/padding rules.
    - ``css_variables``: the resolved ``--name`` → value map from
      ``:root`` / ``html`` blocks. Empty when the source CSS doesn't
      define any.

    Stylesheet fetch failures are reported via ``on_warning`` instead of
    aborting. The extraction is intentionally lenient — the agent
    consuming this output is expected to review and refine the result.
    """
    warn = on_warning or _noop_warn
    css_text = _fetch_stylesheets(homepage_html, base_url, warn)

    variables = _extract_css_variables(css_text)
    resolved_css = _resolve_variables_in_css(css_text, variables)

    raw_colors = HEX_COLOR.findall(resolved_css) + RGB_COLOR.findall(resolved_css)
    normalized_colors = [c.lower() for c in raw_colors]

    brand_color_pool = [
        c for c in normalized_colors
        if not _is_framework_default_color(c) and not _is_neutral_color(c)
    ]
    neutral_color_pool = [c for c in normalized_colors if _is_neutral_color(c)]

    top_brand = _top_counter(brand_color_pool, limit=10)
    top_neutral = _top_counter(neutral_color_pool, limit=5)

    font_declarations: list[str] = []
    for declaration in FONT_FAMILY.findall(resolved_css):
        first_family = declaration.split(",")[0].strip().strip("'\"")
        if not first_family:
            continue
        if first_family.startswith("var("):
            # var() reference that didn't resolve — skip it instead of
            # leaking raw CSS into the output.
            continue
        if _is_system_font(first_family):
            continue
        font_declarations.append(first_family)
    top_fonts = _top_counter(font_declarations, limit=5)

    spacing_values: list[str] = []
    for declaration in SPACING.findall(resolved_css):
        spacing_values.extend(SPACE_VALUE.findall(declaration))
    top_spacing = _top_counter(spacing_values, limit=10)

    return {
        "colors": top_brand,
        "brand_colors": top_brand,
        "neutral_colors": top_neutral,
        "fonts": top_fonts,
        "spacing": top_spacing,
        "css_variables": variables,
    }
