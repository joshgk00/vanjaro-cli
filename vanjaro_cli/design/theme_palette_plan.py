"""Deterministic proposed-palette selection from DesignDocument color tokens."""

from __future__ import annotations

import colorsys
import re

from vanjaro_cli.design.models import DesignDocument
from vanjaro_cli.design.theme_plan_models import ThemePlanWarning
from vanjaro_cli.utils.color import parse_color


PALETTE_ORDER = (
    "primary", "secondary", "tertiary", "quaternary", "success", "info",
    "warning", "danger", "light", "dark",
)
_CORE_PALETTE_ORDER = (
    "primary", "secondary", "tertiary", "quaternary", "light", "dark"
)
_SEMANTIC_COLOR_ALIASES = {
    "primary": ("primary", "brandprimary", "brandcolor", "brand"),
    "secondary": ("secondary", "brandsecondary"),
    "tertiary": ("tertiary", "accent", "accentone"),
    "quaternary": ("quaternary", "accenttwo"),
    "success": ("success", "statussuccess"),
    "info": ("info", "statusinfo"),
    "warning": ("warning", "statuswarning"),
    "danger": ("danger", "error", "statusdanger", "statuserror"),
    "light": ("light", "white"),
    "dark": ("dark", "black"),
}
_Color = tuple[str, str, tuple[int, int, int], float, float]


def plan_palette(
    document: DesignDocument,
) -> tuple[dict[str, str], dict[str, list[str]], list[ThemePlanWarning]]:
    """Propose portable slots while flagging every heuristic or unused token."""

    colors: list[_Color] = []
    warnings: list[ThemePlanWarning] = []
    for token_id, token in sorted(document.tokens.colors.items()):
        path = f"tokens.colors.{token_id}"
        if not isinstance(token.value, str) or parse_color(token.value) is None:
            warnings.append(
                ThemePlanWarning(
                    code="UNRESOLVED_COLOR_TOKEN",
                    message=f"Color token '{token_id}' is not a supported concrete CSS color.",
                    token_paths=[path],
                )
            )
            continue
        rgb = parse_color(token.value)
        assert rgb is not None
        if any(channel < 0 or channel > 255 for channel in rgb):
            warnings.append(
                ThemePlanWarning(
                    code="UNRESOLVED_COLOR_TOKEN",
                    message=f"Color token '{token_id}' has an out-of-range RGB channel.",
                    token_paths=[path],
                )
            )
            continue
        value = _hex(rgb)
        luminance = _relative_luminance(rgb)
        saturation = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))[1]
        colors.append((token_id, value, rgb, luminance, saturation))

    palette: dict[str, str] = {}
    sources: dict[str, list[str]] = {}
    used_ids: set[str] = set()
    for slot in PALETTE_ORDER:
        explicit = _semantic_color(colors, slot, used_ids)
        if explicit is not None:
            _assign_color(slot, explicit, palette, sources, used_ids)

    if "light" not in palette:
        candidates = [item for item in colors if item[0] not in used_ids and item[3] >= 0.82]
        if candidates:
            item = max(candidates, key=lambda candidate: (candidate[3], candidate[1], candidate[0]))
            _assign_color("light", item, palette, sources, used_ids)
            warnings.append(_heuristic_color_warning("light", item))
    if "dark" not in palette:
        candidates = [item for item in colors if item[0] not in used_ids and item[3] <= 0.25]
        if candidates:
            item = min(candidates, key=lambda candidate: (candidate[3], candidate[1], candidate[0]))
            _assign_color("dark", item, palette, sources, used_ids)
            warnings.append(_heuristic_color_warning("dark", item))

    accent_candidates = [
        item
        for item in colors
        if item[0] not in used_ids and 0.06 < item[3] < 0.9 and item[4] >= 0.12
    ]
    accent_candidates.sort(key=_accent_sort_key)
    for slot in ("primary", "secondary", "tertiary", "quaternary"):
        if slot not in palette and accent_candidates:
            item = accent_candidates.pop(0)
            _assign_color(slot, item, palette, sources, used_ids)
            accent_candidates = [
                candidate for candidate in accent_candidates if candidate[1] != item[1]
            ]
            warnings.append(_heuristic_color_warning(slot, item))

    for slot in _CORE_PALETTE_ORDER:
        if slot not in palette:
            warnings.append(
                ThemePlanWarning(
                    code="UNRESOLVED_PALETTE_SLOT",
                    message=f"No design color token could be mapped confidently to '{slot}'.",
                )
            )
    for token_id, value, _rgb, _luminance, _saturation in colors:
        if token_id not in used_ids:
            warnings.append(
                ThemePlanWarning(
                    code="UNRESOLVED_COLOR_TOKEN",
                    message=(
                        f"Color token '{token_id}' ({value}) is not represented by the "
                        "proposed Vanjaro palette and remains available for component styling."
                    ),
                    token_paths=[f"tokens.colors.{token_id}"],
                )
            )
    return palette, sources, warnings


def _heuristic_color_warning(slot: str, item: _Color) -> ThemePlanWarning:
    return ThemePlanWarning(
        code="HEURISTIC_PALETTE_MAPPING",
        message=(
            f"Generic token '{item[0]}' was proposed for '{slot}' using deterministic "
            "color characteristics; its name does not assert that semantic role and the "
            "mapping requires review."
        ),
        token_paths=[f"tokens.colors.{item[0]}"],
    )


def _semantic_color(
    colors: list[_Color], slot: str, used_ids: set[str]
) -> _Color | None:
    aliases = _SEMANTIC_COLOR_ALIASES[slot]
    matches = [
        item
        for item in colors
        if item[0] not in used_ids and _normalized_identifier(item[0]) in aliases
    ]
    if not matches:
        return None
    return min(
        matches,
        key=lambda item: (aliases.index(_normalized_identifier(item[0])), item[0]),
    )


def _assign_color(
    slot: str,
    item: _Color,
    palette: dict[str, str],
    sources: dict[str, list[str]],
    used_ids: set[str],
) -> None:
    palette[slot] = item[1]
    sources[slot] = [f"tokens.colors.{item[0]}"]
    used_ids.add(item[0])


def _accent_sort_key(item: _Color) -> tuple[float, str, str]:
    token_id, value, rgb, luminance, saturation = item
    vividness = saturation * (0.4 + 0.6 * max(rgb) / 255) * (1 - abs(luminance - 0.5))
    return (-vividness, value, token_id)


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02x}" for channel in rgb)


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        normalized = value / 255
        return normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _normalized_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


__all__ = ["PALETTE_ORDER", "plan_palette"]
