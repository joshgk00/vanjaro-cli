"""Normalize CSS colour values to the hex the palette contract requires.

Both sides of a fidelity comparison can now carry browser-dialect colours. The
observed side always did, and since rendered source analysis (VF-210) the design
side does too, because a rendered Design Document records what the browser
computed. One shared normalizer keeps the two sides from drifting apart, which
is the failure mode a second copy would eventually produce.

This module is pure: no network, no filesystem, no model calls.
"""

from __future__ import annotations

import re
from typing import Any


__all__ = ["normalize_css_color"]


_RGB_FUNCTION = re.compile(
    r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([0-9.]+)\s*)?\)$",
    re.IGNORECASE,
)

_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


def normalize_css_color(value: Any) -> str | None:
    """Return a hex colour, or None when the value is not a usable measurement.

    A fully transparent colour is dropped: it means the element inherits
    whatever is behind it, which cannot be attributed to this element, and
    reporting `rgba(0,0,0,0)` as black would fabricate a measurement. Partial
    alpha keeps its RGB channels, because what it composites against is not
    knowable from this element alone.

    An unrecognized colour form returns None rather than a guess. A named
    colour, a `color-mix()`, or an `hsl()` is not converted here — putting a
    fabricated value into a score is worse than scoring one fewer role.
    """

    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.casefold() in {"transparent", "none"}:
        return None
    match = _RGB_FUNCTION.match(text)
    if match:
        alpha = match.group(4)
        if alpha is not None and float(alpha) == 0.0:
            return None
        channels = [int(match.group(index)) for index in (1, 2, 3)]
        if any(channel > 255 for channel in channels):
            return None
        return "#" + "".join(f"{channel:02x}" for channel in channels)
    if _HEX.fullmatch(text):
        return text
    return None
