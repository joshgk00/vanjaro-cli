"""Theme palette loading and nearest-slot color matching.

Hand-built Vanjaro sites carry almost no inline color: bands use theme
palette classes (``bg-primary``, ``bg-info``, ``text-light`` …) so a theme
change cascades across the whole site. This module maps a crawled hex/rgb
color back to the closest palette slot so migrated sections can wear the
same classes instead of frozen inline colors.
"""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.utils.color import parse_color, rgb_distance

__all__ = [
    "PALETTE_SLOTS",
    "PaletteError",
    "load_palette",
    "nearest_palette_slot",
]


class PaletteError(Exception):
    """Raised when a palette file can't be read or has the wrong shape."""


# The Vanjaro theme palette slots, in the order their Bootstrap-style classes
# render (bg-{slot} / text-{slot}). tertiary/quaternary have no Bootstrap
# default but Vanjaro themes register bg-tertiary / bg-quaternary.
PALETTE_SLOTS = (
    "primary",
    "secondary",
    "tertiary",
    "quaternary",
    "success",
    "info",
    "warning",
    "danger",
    "light",
    "dark",
)


def load_palette(path: str | Path) -> dict[str, tuple[int, int, int]]:
    """Load a palette JSON ({slot: hex}) into {slot: (r, g, b)}.

    Unknown slot names and unparseable colors are skipped rather than
    failing the load — a palette exported from one theme may omit slots a
    later theme adds, and a half-usable palette still maps most bands.
    """
    json_path = Path(path)
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise PaletteError(f"Cannot read palette file {json_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise PaletteError(f"Palette file {json_path} must be a JSON object of slot->color.")

    palette: dict[str, tuple[int, int, int]] = {}
    for slot, color in raw.items():
        if slot not in PALETTE_SLOTS or not isinstance(color, str):
            continue
        rgb = parse_color(color)
        if rgb is not None:
            palette[slot] = rgb
    return palette


# RGB Euclidean distance below which two colors count as the "same" slot.
# 40 is roughly the gap between visually distinct brand colors (a navy and a
# royal blue sit ~70 apart), so a band painted with a brand color snaps to
# its slot while a genuinely different color falls through to an inline rule.
DEFAULT_MAX_DISTANCE = 40.0


def nearest_palette_slot(
    color: str,
    palette: dict[str, tuple[int, int, int]],
    max_distance: float = DEFAULT_MAX_DISTANCE,
) -> str | None:
    """Return the palette slot whose color is closest to ``color``.

    Matches by RGB Euclidean distance; returns None when nothing falls within
    ``max_distance`` (the color is distinct enough to keep as an inline rule).
    """
    target = parse_color(color)
    if target is None or not palette:
        return None

    best_slot: str | None = None
    best_distance = max_distance
    for slot, rgb in palette.items():
        distance = rgb_distance(target, rgb)
        if distance <= best_distance:
            best_distance = distance
            best_slot = slot
    return best_slot
