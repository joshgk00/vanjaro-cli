"""Measure a built page in the browser for fidelity scoring (VF-009).

`fidelity_observation` defines what an observed section looks like; this module
obtains the numbers. The browser reads raw values, and every judgement about
what those values mean happens here in Python:

* **The page reports, Python decides.** The injected script returns geometry,
  computed styles, and text — no thresholds, no classification. Placeholder
  detection in particular reuses the planner's audited vocabulary rather than
  duplicating a second copy of it in JavaScript, where it could drift unseen.
* **Absence survives the round trip.** A value the page cannot supply comes back
  as ``null`` and stays ``None``, so the metrics report it unavailable instead of
  scoring a default.

The Playwright session is the one `fidelity_capture` already uses — same settle
guarantees (fonts loaded, animation disabled, lazy images walked). The session
factory is injectable so the parsing and sequencing logic is testable without a
browser.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
from typing import Any

from vanjaro_cli.design.css_color import normalize_css_color
from vanjaro_cli.design.fidelity_layout import BoundingBox
from vanjaro_cli.design.fidelity_observation import (
    RenderedMedia,
    RenderedPage,
    RenderedSection,
    RenderedText,
)
from vanjaro_cli.design.models import BreakpointName
from vanjaro_cli.design.visual_gate import CANONICAL_VIEWPORTS

__all__ = [
    "MEASURE_SCRIPT",
    "MeasurementError",
    "PlaywrightPageMeasurer",
    "parse_measured_page",
]


class MeasurementError(RuntimeError):
    """Raised when a page cannot be measured at one viewport."""


# Kept identical to the planner's vocabulary; placeholder copy that ships is a
# release-blocking defect, so both detectors must agree on what counts.
_PLACEHOLDER_RE = re.compile(
    r"(?:placehold\.co|placeholder(?:\s+(?:text|image))?|lorem\s+ipsum|example\.com)",
    re.IGNORECASE,
)

# Returns raw values only. Anything requiring a judgement is left to Python.
MEASURE_SCRIPT = """
() => {
  const roots = [];
  document.querySelectorAll('[data-agency-section]').forEach((node) => {
    if (!node.parentElement || !node.parentElement.closest('[data-agency-section]')) {
      roots.push(node);
    }
  });
  const num = (value) => {
    const parsed = parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const typeOf = (node) => {
    if (!node) return null;
    const style = getComputedStyle(node);
    return {
      family: style.fontFamily || null,
      size_px: num(style.fontSize),
      weight: num(style.fontWeight),
    };
  };
  return {
    console_error_count: null,
    sections: roots.map((node, index) => {
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      const action = node.querySelector('a, button');
      const columns = style.gridTemplateColumns && style.gridTemplateColumns !== 'none'
        ? style.gridTemplateColumns.split(' ').filter((part) => part.length).length
        : null;
      return {
        section_id: node.getAttribute('data-agency-section'),
        order: index,
        bounds: {
          x: rect.x + window.scrollX,
          y: rect.y + window.scrollY,
          width: rect.width,
          height: rect.height,
        },
        columns: columns,
        background_color: style.backgroundColor || null,
        text_color: style.color || null,
        accent_color: action ? getComputedStyle(action).color : null,
        typography: {
          heading: typeOf(node.querySelector('h1, h2, h3, h4, h5, h6')),
          body: typeOf(node.querySelector('p')),
        },
        padding_top: num(style.paddingTop),
        padding_bottom: num(style.paddingBottom),
        element_gap: num(style.rowGap),
        horizontal_overflow_px: Math.max(0, node.scrollWidth - node.clientWidth),
        media: Array.from(node.querySelectorAll('img')).map((image) => {
          const box = image.getBoundingClientRect();
          const position = getComputedStyle(image).objectPosition || '';
          const parts = position.split(' ');
          return {
            rendered_width: box.width,
            rendered_height: box.height,
            natural_width: image.naturalWidth || null,
            natural_height: image.naturalHeight || null,
            focal_x: parts[0] && parts[0].endsWith('%') ? parseFloat(parts[0]) / 100 : null,
            focal_y: parts[1] && parts[1].endsWith('%') ? parseFloat(parts[1]) / 100 : null,
          };
        }),
        text_samples: Array.from(
          node.querySelectorAll('h1, h2, h3, h4, h5, h6, p, li, a, button')
        ).map((element) => element.textContent.trim()),
      };
    }),
  };
}
"""


def parse_measured_page(
    payload: Mapping[str, Any],
    *,
    viewport_width: float,
    console_error_count: int | None = None,
) -> RenderedPage:
    """Convert a raw measurement payload into a `RenderedPage`.

    Pure: every rule about what a measurement means lives here, so the browser
    script stays a dumb reader and this stays testable without one.
    """

    sections = [
        _section(entry)
        for entry in payload.get("sections", [])
        if isinstance(entry, Mapping) and entry.get("section_id")
    ]
    reported = payload.get("console_error_count")
    if console_error_count is None and isinstance(reported, int):
        console_error_count = reported
    return RenderedPage(
        viewport_width=viewport_width,
        sections=tuple(sections),
        console_error_count=console_error_count,
    )


def _section(entry: Mapping[str, Any]) -> RenderedSection:
    samples = [value for value in entry.get("text_samples", []) if isinstance(value, str)]
    return RenderedSection(
        section_id=str(entry["section_id"]),
        order=int(entry.get("order") or 0),
        bounds=_bounds(entry.get("bounds")),
        columns=_columns(entry.get("columns")),
        background_color=_color(entry.get("background_color")),
        text_color=_color(entry.get("text_color")),
        accent_color=_color(entry.get("accent_color")),
        typography=_typography(entry.get("typography")),
        padding_top=_length(entry.get("padding_top")),
        padding_bottom=_length(entry.get("padding_bottom")),
        element_gap=_length(entry.get("element_gap")),
        media=_media(entry.get("media")),
        horizontal_overflow_px=_length(entry.get("horizontal_overflow_px")),
        empty_slot_count=sum(1 for value in samples if not value.strip()),
        placeholder_leaks=_placeholder_leaks(samples),
    )


def _bounds(value: Any) -> BoundingBox | None:
    if not isinstance(value, Mapping):
        return None
    numbers = {key: _length(value.get(key)) for key in ("x", "y", "width", "height")}
    if numbers["width"] is None or numbers["height"] is None:
        return None
    return BoundingBox(
        x=numbers["x"] or 0.0,
        y=numbers["y"] or 0.0,
        width=numbers["width"],
        height=numbers["height"],
    )


def _columns(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    columns = int(value)
    return columns if columns >= 1 else None


def _color(value: Any) -> str | None:
    """Normalize a computed colour to hex, or report it as unmeasured.

    The browser's dialect is translated here, at the boundary where it arrives.
    The rules live in `css_color` because the design side needs the same ones
    since rendered analysis began recording computed values.
    """

    return normalize_css_color(value)
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
    if re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", text):
        return text
    # An unrecognized colour form is not a measurement; guessing one would put
    # a fabricated value into the score.
    return None


def _typography(value: Any) -> dict[str, RenderedText]:
    if not isinstance(value, Mapping):
        return {}
    samples: dict[str, RenderedText] = {}
    for key in ("heading", "body"):
        entry = value.get(key)
        if not isinstance(entry, Mapping):
            continue
        family = entry.get("family")
        size = _length(entry.get("size_px"))
        weight = entry.get("weight")
        sample = RenderedText(
            family=family.strip() if isinstance(family, str) and family.strip() else None,
            size_px=size if size and size > 0 else None,
            weight=_weight(weight),
        )
        if sample.family or sample.size_px or sample.weight:
            samples[key] = sample
    return samples


def _weight(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    weight = int(value)
    return weight if 1 <= weight <= 1000 else None


def _media(value: Any) -> tuple[RenderedMedia, ...]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        return ()
    media: list[RenderedMedia] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        width = _length(entry.get("rendered_width"))
        height = _length(entry.get("rendered_height"))
        # A zero-sized image is not a measurement of an aspect ratio.
        if not width or not height:
            continue
        media.append(
            RenderedMedia(
                rendered_width=width,
                rendered_height=height,
                natural_width=_length(entry.get("natural_width")) or None,
                natural_height=_length(entry.get("natural_height")) or None,
                focal_x=_fraction(entry.get("focal_x")),
                focal_y=_fraction(entry.get("focal_y")),
            )
        )
    return tuple(media)


def _placeholder_leaks(samples: Iterable[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in samples:
        if value.strip() and _PLACEHOLDER_RE.search(value):
            seen.setdefault(value.strip(), None)
    return tuple(seen)


def _length(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number >= 0 else None


def _fraction(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if 0.0 <= number <= 1.0 else None


class PlaywrightPageMeasurer:
    """Default measurer reusing the settled Playwright session from capture."""

    def __init__(
        self,
        *,
        timeout_seconds: int = 45,
        session_factory: Callable[..., AbstractContextManager[Any]] | None = None,
        settle: Callable[[Any, int], None] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self._session_factory = session_factory
        self._settle = settle

    def measure(self, url: str, breakpoint: BreakpointName) -> RenderedPage:
        session_factory, settle = self._dependencies()
        viewport = CANONICAL_VIEWPORTS[breakpoint]
        timeout_ms = self.timeout_seconds * 1000
        errors: list[str] = []

        try:
            with session_factory(viewport=(viewport.width, viewport.height)) as page:
                _subscribe_to_console_errors(page, errors)
                try:
                    page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                except Exception:
                    page.goto(url, wait_until="load", timeout=timeout_ms)
                settle(page, timeout_ms)
                payload = page.evaluate(MEASURE_SCRIPT)
        except Exception as error:  # noqa: BLE001 - surfaced as a measurement failure
            raise MeasurementError(f"{type(error).__name__}: {error}") from error

        if not isinstance(payload, Mapping):
            raise MeasurementError("measurement script returned a non-object payload")
        return parse_measured_page(
            payload,
            viewport_width=float(viewport.width),
            console_error_count=len(errors),
        )

    def _dependencies(self):
        if self._session_factory is not None and self._settle is not None:
            return self._session_factory, self._settle
        # Imported lazily so the pure scoring path never requires Playwright.
        from vanjaro_cli.migration.visual import _settle, rendered_page_session

        return self._session_factory or rendered_page_session, self._settle or _settle


def _subscribe_to_console_errors(page: Any, sink: list[str]) -> None:
    """Record console errors when the page supports listeners.

    A page object without `on` still measures; it simply reports no console
    evidence, which the integrity metric treats as unavailable.
    """

    listen = getattr(page, "on", None)
    if not callable(listen):
        return
    listen("console", lambda message: _record_console(message, sink))
    listen("pageerror", lambda error: sink.append(str(error)))


def _record_console(message: Any, sink: list[str]) -> None:
    kind = getattr(message, "type", None)
    if callable(kind):
        kind = kind()
    if kind == "error":
        sink.append(str(getattr(message, "text", "console error")))
