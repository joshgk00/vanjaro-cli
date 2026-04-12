"""Design token extraction from CSS — colors, fonts, spacing, typography.

The extractor is intentionally lenient: it scans raw CSS, ranks values by
frequency, and produces a starting point for the agent to review. To make
that starting point more useful it also:

- Resolves ``:root { --foo: bar }`` custom properties so ``var(--foo)``
  references in declarations get substituted with their actual values
  before ranking.
- Filters known framework default colors (Bootstrap 5 alert palette,
  grayscale utilities, form validation colors, generic neutrals, low-opacity
  overlays) out of the brand-color list so the top results aren't drowned
  in vendor noise.
- Filters generic system font fallbacks (``serif``, ``sans-serif``,
  ``arial``, ``inherit``, ...) out of the font list so the result reflects
  actual brand typography choices.
- Splits colors into ``brand_colors`` (likely brand) and ``neutral_colors``
  (whites/blacks/transparents) so consumers can pick the right ones for
  Vanjaro's primary/secondary/tertiary slots without manual triage.
- Extracts typography details: font weights, sizes, line-heights, and
  letter-spacing values — paired with usage context (headings vs body)
  where determinable from selector names.

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
RGBA_COMPONENTS = re.compile(
    r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*[\d.]+)?\s*\)"
)
RGBA_ALPHA = re.compile(
    r"rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*(\d+(?:\.\d+)?)\s*\)"
)
FONT_FAMILY = re.compile(r"font-family\s*:\s*([^;{}]+)[;}]", re.IGNORECASE)
FONT_WEIGHT = re.compile(r"font-weight\s*:\s*([^;{}]+)[;}]", re.IGNORECASE)
FONT_SIZE = re.compile(r"font-size\s*:\s*([^;{}]+)[;}]", re.IGNORECASE)
LINE_HEIGHT = re.compile(r"line-height\s*:\s*([^;{}]+)[;}]", re.IGNORECASE)
LETTER_SPACING = re.compile(r"letter-spacing\s*:\s*([^;{}]+)[;}]", re.IGNORECASE)
SPACING = re.compile(r"(?:margin|padding)(?:-[a-z]+)?\s*:\s*([^;{}]+)[;}]", re.IGNORECASE)
SPACE_VALUE = re.compile(r"\b\d+(?:\.\d+)?(?:px|rem|em)\b")
# These three regexes run against single-declaration values after trimming, so
# no trailing `\b` is needed — the whole value has already been isolated. The
# `\b` was dropped to let `%` match (it's a non-word char, so `\b` fails when
# the unit sits at end-of-string).
SIZE_VALUE = re.compile(r"\d+(?:\.\d+)?(?:px|rem|em|vw|vh|%)")
LINE_HEIGHT_VALUE = re.compile(r"\d+(?:\.\d+)?(?:px|rem|em|%)?")
LETTER_SPACING_VALUE = re.compile(r"-?\d+(?:\.\d+)?(?:px|rem|em)")

# Match `:root { ... }` blocks (or `html { ... }`) to extract custom properties.
ROOT_BLOCK = re.compile(r"(?::root|html)\s*\{([^}]*)\}", re.IGNORECASE)
# Match `--name: value;` declarations inside a CSS block.
CSS_VAR_DECL = re.compile(r"--([a-zA-Z0-9_-]+)\s*:\s*([^;]+);")
# Match `var(--name)` or `var(--name, fallback)` references in declaration values.
CSS_VAR_REF = re.compile(r"var\(\s*--([a-zA-Z0-9_-]+)(?:\s*,\s*([^)]+))?\s*\)")
# Match CSS rule blocks: `selector { declarations }` — used for usage context detection.
CSS_RULE_BLOCK = re.compile(r"([^{}]+)\{([^}]*)\}", re.DOTALL)

# Heading selectors — when a font/size appears only in heading contexts, tag it "headings".
HEADING_SELECTOR = re.compile(r"\bh[1-6]\b|\.heading|\.title|\.display-", re.IGNORECASE)
BODY_SELECTOR = re.compile(r"\bbody\b|\bp\b|\.text|\.body|\.content|\.paragraph", re.IGNORECASE)

# Bootstrap 5 framework default colors — these show up in nearly every
# Bootstrap site's CSS but have nothing to do with brand identity.
BOOTSTRAP_FRAMEWORK_COLORS = frozenset({
    # Alert palette (BS4/BS5)
    "#d4edda", "#155724", "#c3e6cb",  # success
    "#f8d7da", "#721c24", "#f5c6cb",  # danger
    "#fff3cd", "#856404", "#ffeeba",  # warning
    "#d1ecf1", "#0c5460", "#bee5eb",  # info
    "#cce5ff", "#004085", "#b8daff",  # primary alert
    "#e2e3e5", "#383d41", "#d6d8db",  # secondary alert
    "#fefefe", "#818182", "#fdfdfe",  # light alert
    "#d6d8d9", "#1b1e21", "#c6c8ca",  # dark alert
    # Grayscale utilities (BS5 gray-100 through gray-900)
    "#f8f9fa", "#e9ecef", "#dee2e6", "#ced4da", "#adb5bd",
    "#6c757d", "#495057", "#343a40", "#212529",
    # Form validation colors
    "#198754", "#dc3545", "#ffc107",  # success/danger/warning solid
    "#0d6efd", "#6610f2", "#6f42c1",  # primary/indigo/purple
    "#d63384", "#fd7e14", "#20c997",  # pink/orange/teal
    "#0dcaf0",                         # info/cyan
    # Common BS5 component defaults
    "#f5f5f5", "#e0e0e0", "#cccccc", "#999999", "#666666", "#333333",
})

# Pure white/black variants that rank as neutrals, not brand colors.
# CSS keywords (`inherit`, `currentColor`, etc.) can't reach this filter — they
# never pass the `HEX_COLOR` / `RGB_COLOR` regex that feeds the color pool — so
# they're intentionally absent here.
NEUTRAL_COLOR_LITERALS = frozenset({
    "#fff", "#ffffff",
    "#000", "#000000",
    "transparent",
})

# Minimum alpha threshold — rgba values with alpha below this are treated as
# overlay/hover effects, not intentional brand colors.
LOW_ALPHA_THRESHOLD = 0.3

# CSS keywords that reset typography properties back to defaults. Filtered out
# of font-weight / font-size / line-height / letter-spacing extraction so the
# tokens reflect intentional design choices, not resets.
CSS_RESET_KEYWORDS = frozenset({"inherit", "initial", "unset", "revert"})
CSS_RESET_KEYWORDS_WITH_NORMAL = CSS_RESET_KEYWORDS | {"normal"}

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
    match = RGBA_COMPONENTS.match(normalized)
    if match:
        red, green, blue = (int(component) for component in match.groups())
        if red == green == blue and red in (0, 255):
            return True
    return False


def _is_low_alpha_color(color: str) -> bool:
    """Return True if ``color`` is an rgba value with alpha below threshold.

    Low-opacity colors are typically hover/focus overlays, shadows, or
    transition states — not intentional brand colors. The ``RGBA_ALPHA``
    regex captures a well-formed float (``\\d+(?:\\.\\d+)?``) so a malformed
    alpha value like ``1.2.3`` fails to match and the color is kept rather
    than crashing the lenient extractor.
    """
    match = RGBA_ALPHA.match(color.strip().lower())
    if match:
        return float(match.group(1)) < LOW_ALPHA_THRESHOLD
    return False


def _is_framework_default_color(color: str) -> bool:
    """Return True if ``color`` is a known framework default (Bootstrap, etc.)."""
    return color.strip().lower() in BOOTSTRAP_FRAMEWORK_COLORS


def _is_system_font(family: str) -> bool:
    """Return True if ``family`` is a generic system font fallback."""
    return family.strip().lower() in SYSTEM_FONT_FALLBACKS


def _top_counter(values: list[str], limit: int) -> list[str]:
    """Return the top ``limit`` most common values, preserving frequency order."""
    counts = Counter(values)
    return [value for value, _ in counts.most_common(limit)]


def _primary_brand_family(declaration: str) -> str | None:
    """Return the first non-system, non-var font family from a declaration.

    Returns ``None`` if the declaration's primary family is a system fallback,
    an unresolved ``var()`` reference, or empty. Shared by
    :func:`extract_design_tokens` and :func:`_extract_typography` so the
    filter rules live in a single authoritative spot.
    """
    first = declaration.split(",")[0].strip().strip("'\"")
    if not first or first.startswith("var(") or _is_system_font(first):
        return None
    return first


def _classify_usage(contexts: set[str]) -> str:
    """Map a set of selector contexts to a usage tag."""
    if "heading" in contexts and "body" not in contexts:
        return "headings"
    if "body" in contexts and "heading" not in contexts:
        return "body"
    if contexts:
        return "mixed"
    return "unknown"


def _extract_typography(resolved_css: str) -> dict:
    """Extract font weights, sizes, line-heights, and letter-spacing.

    Returns a dict with:
    - ``font_sizes``: top font-size values ranked by frequency
    - ``font_weights``: unique weight values found, in first-seen order
    - ``line_heights``: top line-height values ranked by frequency
    - ``letter_spacings``: top letter-spacing values ranked by frequency
    - ``fonts``: list of font detail dicts with family, weights, and usage

    Usage is determined by selector context: if a font appears only in
    heading selectors (h1-h6, .heading, .title), it's tagged "headings";
    if in body/paragraph selectors, it's tagged "body"; in both, "mixed";
    in neither, "unknown".

    Everything is collected in a single pass over ``CSS_RULE_BLOCK`` matches
    so each declaration is visited exactly once.
    """
    font_family_context: dict[str, set[str]] = {}
    font_family_weights: dict[str, set[str]] = {}
    font_sizes: list[str] = []
    all_weights: list[str] = []
    line_heights: list[str] = []
    letter_spacings: list[str] = []

    for selector, declarations in CSS_RULE_BLOCK.findall(resolved_css):
        is_heading = bool(HEADING_SELECTOR.search(selector))
        is_body = bool(BODY_SELECTOR.search(selector))

        families_in_block: list[str] = []
        for declaration in FONT_FAMILY.findall(declarations):
            family = _primary_brand_family(declaration)
            if family is None:
                continue
            families_in_block.append(family)
            contexts = font_family_context.setdefault(family, set())
            if is_heading:
                contexts.add("heading")
            if is_body:
                contexts.add("body")

        for weight_value in FONT_WEIGHT.findall(declarations):
            weight = weight_value.strip().lower()
            if weight in CSS_RESET_KEYWORDS:
                continue
            all_weights.append(weight)
            for family in families_in_block:
                font_family_weights.setdefault(family, set()).add(weight)

        for size_value in FONT_SIZE.findall(declarations):
            value = size_value.strip().lower()
            if value in CSS_RESET_KEYWORDS:
                continue
            match = SIZE_VALUE.search(value)
            if match:
                font_sizes.append(match.group(0))

        for line_height_value in LINE_HEIGHT.findall(declarations):
            value = line_height_value.strip().lower()
            if value in CSS_RESET_KEYWORDS_WITH_NORMAL:
                continue
            match = LINE_HEIGHT_VALUE.search(value)
            if match:
                line_heights.append(match.group(0))

        for letter_spacing_value in LETTER_SPACING.findall(declarations):
            value = letter_spacing_value.strip().lower()
            if value in CSS_RESET_KEYWORDS_WITH_NORMAL:
                continue
            match = LETTER_SPACING_VALUE.search(value)
            if match:
                letter_spacings.append(match.group(0))

    font_details = [
        {
            "family": family,
            "weights": sorted(font_family_weights.get(family, set())),
            "usage": _classify_usage(contexts),
        }
        for family, contexts in font_family_context.items()
    ]

    return {
        "font_sizes": _top_counter(font_sizes, limit=10),
        "font_weights": list(dict.fromkeys(all_weights)),
        "line_heights": _top_counter(line_heights, limit=5),
        "letter_spacings": _top_counter(letter_spacings, limit=5),
        "fonts": font_details,
    }


def extract_design_tokens(
    homepage_html: str,
    base_url: str,
    on_warning: Callable[[str], None] | None = None,
) -> dict:
    """Extract colors, fonts, spacing, and typography from a site's CSS.

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
    - ``typography``: structured font detail including weights, sizes,
      line-heights, letter-spacing, and per-font usage context.

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
        if not _is_framework_default_color(c)
        and not _is_neutral_color(c)
        and not _is_low_alpha_color(c)
    ]
    neutral_color_pool = [c for c in normalized_colors if _is_neutral_color(c)]

    top_brand = _top_counter(brand_color_pool, limit=10)
    top_neutral = _top_counter(neutral_color_pool, limit=5)

    font_declarations: list[str] = []
    for declaration in FONT_FAMILY.findall(resolved_css):
        family = _primary_brand_family(declaration)
        if family is not None:
            font_declarations.append(family)
    top_fonts = _top_counter(font_declarations, limit=5)

    spacing_values: list[str] = []
    for declaration in SPACING.findall(resolved_css):
        spacing_values.extend(SPACE_VALUE.findall(declaration))
    top_spacing = _top_counter(spacing_values, limit=10)

    typography = _extract_typography(resolved_css)

    return {
        "colors": top_brand,
        "brand_colors": top_brand,
        "neutral_colors": top_neutral,
        "fonts": top_fonts,
        "spacing": top_spacing,
        "css_variables": variables,
        "typography": typography,
    }
