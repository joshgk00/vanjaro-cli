"""Pure-logic design-token extraction from Figma node JSON.

The target Figma files carry no auto-layout and no shared styles, so tokens
can't be read from ``file.styles`` or ``layoutMode`` — they must be scraped
per node and frequency-ranked. Everything here operates on already-fetched
JSON; no HTTP happens in this module.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterator

__all__ = [
    "build_design_tokens",
    "build_theme_palette",
    "collect_corner_radii",
    "collect_image_fills",
    "collect_solid_fills",
    "collect_text_styles",
    "figma_color_to_hex",
    "iter_nodes",
]


def iter_nodes(node: dict) -> Iterator[dict]:
    """Yield ``node`` and every descendant (depth-first)."""
    yield node
    for child in node.get("children", []) or []:
        yield from iter_nodes(child)


def figma_color_to_hex(color: dict) -> str:
    """Convert a Figma color ({r,g,b} as 0-1 floats) to ``#rrggbb``."""
    channels = (color.get("r", 0), color.get("g", 0), color.get("b", 0))
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in channels)


def _bbox_area(node: dict) -> float:
    box = node.get("absoluteBoundingBox") or {}
    width = box.get("width") or 0
    height = box.get("height") or 0
    return float(width) * float(height)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _luminance(rgb: tuple[int, int, int]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _saturation(rgb: tuple[int, int, int]) -> float:
    """HSL-style saturation on 0-1; 0 for gray, high for vivid colors."""
    high, low = max(rgb), min(rgb)
    if high == low:
        return 0.0
    lightness = (high + low) / 510.0
    delta = (high - low) / 255.0
    return delta / (1 - abs(2 * lightness - 1)) if lightness not in (0, 1) else 0.0


def collect_solid_fills(node: dict) -> dict[str, float]:
    """Return {hex: total-visible-area} for every SOLID fill in the tree.

    Area is bounding-box area weighted by fill opacity, so a large painted
    rectangle outweighs a tiny swatch of the same color.
    """
    areas: dict[str, float] = defaultdict(float)
    for current in iter_nodes(node):
        fills = current.get("fills") or []
        area = _bbox_area(current) or 1.0
        for fill in fills:
            if fill.get("type") != "SOLID" or fill.get("visible") is False:
                continue
            color = fill.get("color")
            if not color:
                continue
            opacity = fill.get("opacity", 1.0)
            areas[figma_color_to_hex(color)] += area * float(opacity)
    return dict(areas)


def collect_text_styles(node: dict) -> list[dict]:
    """Return one style dict per TEXT node with the fields we care about."""
    styles: list[dict] = []
    for current in iter_nodes(node):
        if current.get("type") != "TEXT":
            continue
        style = current.get("style") or {}
        if "fontSize" not in style:
            continue
        styles.append(
            {
                "font_family": style.get("fontFamily"),
                "font_weight": style.get("fontWeight"),
                "font_size": style.get("fontSize"),
                "line_height_px": style.get("lineHeightPx"),
                "letter_spacing": style.get("letterSpacing"),
            }
        )
    return styles


def collect_corner_radii(node: dict) -> list[float]:
    """Return every cornerRadius value found in the tree."""
    radii: list[float] = []
    for current in iter_nodes(node):
        radius = current.get("cornerRadius")
        if isinstance(radius, (int, float)):
            radii.append(float(radius))
    return radii


def collect_image_fills(node: dict) -> list[dict]:
    """Return image-fill descriptors (imageRef + owning node metadata)."""
    fills: list[dict] = []
    seen: set[str] = set()
    for current in iter_nodes(node):
        for fill in current.get("fills") or []:
            if fill.get("type") != "IMAGE":
                continue
            image_ref = fill.get("imageRef")
            if not image_ref:
                continue
            key = f"{current.get('id')}::{image_ref}"
            if key in seen:
                continue
            seen.add(key)
            box = current.get("absoluteBoundingBox") or {}
            fills.append(
                {
                    "image_ref": image_ref,
                    "node_id": current.get("id"),
                    "node_name": current.get("name"),
                    "width": box.get("width"),
                    "height": box.get("height"),
                }
            )
    return fills


def _is_near_white(rgb: tuple[int, int, int]) -> bool:
    return min(rgb) >= 235


def _is_near_black(rgb: tuple[int, int, int]) -> bool:
    # Deliberately generous: brand "dark" colors (deep teal, navy) sit well
    # above pure black but still read as the dark slot in a palette.
    return _luminance(rgb) <= 60


def _rank_colors(fills: dict[str, float]) -> dict[str, str]:
    """Map extracted fills to token color slots by area + saturation.

    Returns a dict that may contain: dark, light, primary, secondary,
    tertiary, quaternary. Missing slots are simply absent.
    """
    colored = {hex_value: (area, _hex_to_rgb(hex_value)) for hex_value, area in fills.items()}
    result: dict[str, str] = {}

    darks = {h: a for h, (a, rgb) in colored.items() if _is_near_black(rgb)}
    if darks:
        result["dark"] = max(darks, key=darks.get)

    lights = {h: a for h, (a, rgb) in colored.items() if _is_near_white(rgb)}
    if lights:
        result["light"] = max(lights, key=lights.get)

    accents = [
        (h, a, rgb)
        for h, (a, rgb) in colored.items()
        if not _is_near_white(rgb) and not _is_near_black(rgb) and _saturation(rgb) >= 0.15
    ]
    # Weight by area and vividness so a bold brand color beats a muted one.
    accents.sort(key=lambda item: item[1] * (0.5 + _saturation(item[2])), reverse=True)
    for slot, (hex_value, _area, _rgb) in zip(
        ("primary", "secondary", "tertiary", "quaternary"), accents
    ):
        result[slot] = hex_value
    return result


def _pick_fonts(text_styles: list[dict]) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (heading_font, body_font, heading_weight, body_weight)."""
    with_size = [s for s in text_styles if isinstance(s.get("font_size"), (int, float))]
    if not with_size:
        return None, None, None, None

    largest = max(with_size, key=lambda s: s["font_size"])
    heading_font = largest.get("font_family")
    heading_weight = largest.get("font_weight")

    body_candidates = [s for s in with_size if 14 <= s["font_size"] <= 18]
    body_pool = body_candidates or with_size
    family_counts: dict[str, int] = defaultdict(int)
    for style in body_pool:
        family = style.get("font_family")
        if family:
            family_counts[family] += 1
    body_font = max(family_counts, key=family_counts.get) if family_counts else None

    weight_counts: dict[int, int] = defaultdict(int)
    for style in body_pool:
        weight = style.get("font_weight")
        if isinstance(weight, (int, float)):
            weight_counts[int(weight)] += 1
    body_weight = max(weight_counts, key=weight_counts.get) if weight_counts else None

    return heading_font, body_font, str(heading_weight) if heading_weight else None, str(body_weight) if body_weight else None


def _font_family_value(font_name: str | None) -> str | None:
    """Add a generic fallback to a bare family name for CSS assignment."""
    if not font_name:
        return None
    return f"{font_name}, sans-serif"


def build_design_tokens(
    node: dict,
    site_name: str | None = None,
    extracted_from: str | None = None,
) -> dict:
    """Build a design-tokens.json dict from a Figma node subtree.

    Fills best-guess values everywhere and records ambiguities in
    ``custom_css_needed`` for the site-builder agent to review.
    """
    fills = collect_solid_fills(node)
    text_styles = collect_text_styles(node)
    radii = collect_corner_radii(node)

    colors = _rank_colors(fills)
    heading_font, body_font, heading_weight, body_weight = _pick_fonts(text_styles)

    notes: list[str] = []
    if not heading_font:
        notes.append("No text nodes found — fonts are placeholders; verify against the design.")
    for missing in ("primary", "secondary", "dark", "light"):
        if missing not in colors:
            notes.append(f"Could not confidently map {missing} color — review and set manually.")

    register: list[dict] = []
    seen_fonts: set[str] = set()
    for font_name in (heading_font, body_font):
        if font_name and font_name not in seen_fonts:
            seen_fonts.add(font_name)
            register.append(
                {
                    "name": font_name,
                    "family": _font_family_value(font_name),
                    "import_url": "",
                }
            )
            notes.append(
                f"Font '{font_name}' needs a real import_url (Google Fonts or @font-face); "
                "the extractor cannot resolve font sources."
            )

    site_font = _font_family_value(body_font) or _font_family_value(heading_font)
    heading_family = _font_family_value(heading_font) or site_font
    body_family = _font_family_value(body_font) or site_font

    unique_radii = sorted(set(radii))
    site_radius = None
    button_radius = None
    if unique_radii:
        # Smallest positive radius reads as the general card/site radius;
        # a very large one (pill) is the button radius.
        positive = [r for r in unique_radii if r > 0]
        if positive:
            site_radius = str(int(positive[0]))
            button_radius = str(int(positive[-1]))

    return {
        "site_name": site_name or node.get("name") or "Untitled",
        "extracted_from": extracted_from or "figma",
        "fonts": {
            "register": register,
            "assignments": {
                "site": site_font,
                "headings": heading_family,
                "paragraphs": body_family,
                "buttons": body_family,
                "menu": body_family,
                "links": body_family,
            },
        },
        "colors": {
            "$primarycolor": colors.get("primary"),
            "$secondarycolor": colors.get("secondary"),
            "$tertiary": colors.get("tertiary"),
            "$lightcolor": colors.get("light"),
            "$darkcolor": colors.get("dark"),
        },
        "typography": {
            "heading_weight": heading_weight or "700",
            "paragraph_weight": body_weight or "400",
            "button_weight": heading_weight or "700",
            "menu_weight": body_weight or "400",
        },
        "spacing": {
            "site_border_radius": site_radius or "8",
            "button_border_radius": button_radius or site_radius or "8",
            "button_padding_top": "12",
            "button_padding_bottom": "12",
            "button_padding_left": "28",
            "button_padding_right": "28",
        },
        "menu": {
            "font_size": "16",
            "link_color": "$darkcolor",
            "hover_color": "$primarycolor",
            "active_color": "$primarycolor",
        },
        "custom_css_needed": notes,
    }


def build_theme_palette(node: dict) -> dict[str, str]:
    """Build a flat {slot: hex} palette, omitting slots we can't map."""
    colors = _rank_colors(collect_solid_fills(node))
    palette: dict[str, str] = {}
    for slot in ("primary", "secondary", "tertiary", "quaternary", "light", "dark"):
        if slot in colors:
            palette[slot] = colors[slot]
    return palette
