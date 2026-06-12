"""Color primitives shared across block composition and theme-palette matching.

Pure string/tuple functions with no project dependencies. Lives in its own
module so ``block_compose`` and ``theme_palette`` can both import from it at
top level without the import cycle that arose when one reached into the other.
"""

from __future__ import annotations

import re
from functools import lru_cache

__all__ = [
    "parse_color",
    "rgb_distance",
]

_HEX_COLOR = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB_COLOR = re.compile(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")


@lru_cache(maxsize=512)
def parse_color(value: str) -> tuple[int, int, int] | None:
    """Parse a ``#rgb`` / ``#rrggbb`` / ``rgb()`` color into an (r, g, b) tuple.

    Returns None for anything unparseable (named colors, gradients, empty).
    Cached because sections repeat the same band colors across a crawl.
    """
    value = value.strip()
    rgb_match = _RGB_COLOR.match(value)
    if rgb_match:
        return tuple(int(rgb_match.group(i)) for i in (1, 2, 3))  # type: ignore[return-value]
    hex_match = _HEX_COLOR.match(value)
    if not hex_match:
        return None
    hex_part = hex_match.group(1)
    if len(hex_part) == 3:
        hex_part = "".join(c * 2 for c in hex_part)
    return tuple(int(hex_part[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """Euclidean distance between two (r, g, b) tuples."""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5
