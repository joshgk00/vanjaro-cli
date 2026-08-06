"""Live HTML and legacy-crawl adapters for Design Document v1.

This module is intentionally a compatibility layer over the established
migration extractors. It preserves current crawl behavior while converting
flat legacy arrays into source-neutral elements and relationship-aware repeat
groups. Ambiguous relationships are retained at reduced confidence and are
reported instead of guessed silently.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from pydantic import JsonValue

from vanjaro_cli.design.html_boundaries import (
    append_missing_video_sections as _append_missing_video_sections,
    enrich_faq_relationships as _enrich_faq_relationships,
    interaction_kinds_by_section as _interaction_kinds_by_section,
    prepare_static_sections as _prepare_static_sections,
)
from vanjaro_cli.design.html_ownership import (
    CANONICAL_VIEWPORTS,
    enrich_section_from_static_dom as _enrich_section_from_static_dom,
)
from vanjaro_cli.design.html_primitives import (
    content_element as _element,
    layout_for_section as _layout_for_section,
    register_asset as _register_asset,
)
from vanjaro_cli.design.models import (
    BoundingBox,
    BreakpointName,
    DesignDocument,
    DesignWarning,
    StyleProperty,
    Viewport,
)
from vanjaro_cli.migration.crawler import CrawlError, fetch_url_text, same_domain
from vanjaro_cli.migration.sections import extract_page_title, extract_sections
from vanjaro_cli.migration.visual import (
    VisualCaptureError,
    render_page_html,
    rendered_page_session,
)

__all__ = [
    "CANONICAL_VIEWPORTS",
    "HtmlAdapterError",
    "HtmlPageInput",
    "RenderedCaptureResult",
    "RenderedPageObservation",
    "RenderedSectionObservation",
    "StylesheetCache",
    "analyze_html_pages",
    "capture_rendered_observations",
    "serve_local_directory",
    "convert_legacy_crawl",
    "design_document_from_html",
]


_ROLE_BY_LEGACY_TYPE = {
    "hero": "hero",
    "cards": "feature_cards",
    "testimonial": "testimonials",
    "cta": "call_to_action",
    "content": "rich_text",
    "contact": "contact",
    "bio": "biography",
    "gallery": "gallery",
    "blog_cards": "blog_cards",
    "faq": "faq",
    "pricing": "pricing",
    "stats": "stats",
    "split": "split_media",
}

_REPEAT_KIND_BY_TYPE = {
    "cards": "card",
    "testimonial": "testimonial",
    "gallery": "gallery_item",
    "blog_cards": "blog_post",
    "faq": "faq_item",
    "pricing": "pricing_plan",
    "stats": "stat",
}

_STYLE_CONTENT_KEYS = {
    "background_color": StyleProperty.BACKGROUND_COLOR,
    "background_image": StyleProperty.BACKGROUND_IMAGE,
    "text_color": StyleProperty.TEXT_COLOR,
}

_RENDERED_STYLE_KEYS = {style_property.value: style_property for style_property in StyleProperty}

_RENDERED_OBSERVATION_JS = r"""() => {
    // Mirrors the build-side measure script so both sides of the typography
    // comparison are sampled the same way. Section-level computed font values
    // describe the section box, not its heading, so sampling per element is the
    // only way this dimension can be measured rather than assumed.
    const typeOf = (el) => {
        if (!el) return null;
        const s = getComputedStyle(el);
        return {
            font_family: s.fontFamily || null,
            font_size: s.fontSize || null,
            font_weight: s.fontWeight || null,
        };
    };
    const candidates = [];
    const seen = new Set();
    const add = (el) => {
        if (!el || seen.has(el)) return;
        if (el.closest('header, footer, dialog, [role="dialog"]')) return;
        seen.add(el);
        candidates.push(el);
    };
    // Sectioning elements at any depth, not only as direct children of main or
    // body. A real Vanjaro or DNN page nests its sections inside layout divs and
    // has no <main> at all, so the direct-child query matched nothing: a live
    // themed site with 13 <section> elements produced zero candidates, and
    // rendered analysis silently yielded nothing on every real page.
    const sectioning = Array.from(document.querySelectorAll('section, article'));
    sectioning
        .filter((el) => !sectioning.some((other) => other !== el && other.contains(el)))
        .forEach(add);
    if (!candidates.length) {
        const main = document.querySelector('main, [role="main"]');
        if (main) Array.from(main.children).forEach(add);
    }
    // Page chrome, added explicitly. The body query above cannot reach a nav
    // inside a header, so the design side carried no styles and no geometry for
    // it at all: the nav section scored on two of six dimensions while every
    // body section scored five. Chrome is a section the design describes, so it
    // needs measuring like any other. Pairing is by selector, so a candidate
    // with no static counterpart is simply unmatched.
    // The outermost chrome element is the one the static extractor treats as the
    // section, and it is where the author puts the id, so it is what pairing
    // matches on. An inner nav is only used when no header wraps it.
    const chrome = [];
    document.querySelectorAll('header, footer').forEach((el) => chrome.push(el));
    document.querySelectorAll('body > nav').forEach((el) => {
        if (!el.closest('header, footer')) chrome.push(el);
    });
    chrome.forEach((el) => {
        if (el.closest('dialog, [role="dialog"]')) return;
        if (seen.has(el)) return;
        seen.add(el);
        candidates.push(el);
    });
    // A section with a transparent background still shows a painted colour: the
    // nearest ancestor that paints one. Reading the element's own value leaves
    // background unmeasured on every section of an unstyled source, which is
    // absence of a *decision*, not absence of a colour. Walking up measures what
    // the visitor actually sees. If nothing in the chain paints, that is honestly
    // unmeasured and stays null.
    // Body copy, defined by what it is rather than by one tag. The source writes
    // <p>; Vanjaro renders <div class="vj-text">, so a `p` selector found nothing
    // on the build and typography compared one sample of two on every section.
    // A <p> still wins when present, because it states the author's intent.
    const bodyElement = (root) => {
      const direct = root.querySelector('p');
      if (direct) return direct;
      const nodes = root.querySelectorAll('*');
      for (let i = 0; i < nodes.length; i += 1) {
        const el = nodes[i];
        if (el.children.length) continue;
        if (/^(H[1-6]|A|BUTTON|SCRIPT|STYLE|IMG|SVG)$/.test(el.tagName)) continue;
        if (!(el.textContent || '').trim()) continue;
        return el;
      }
      return null;
    };
    // Inter-element rhythm, measured rather than read from `row-gap`. That
    // property only applies to flex and grid containers and computes to `normal`
    // everywhere else, so both sides reported nothing on every section while the
    // spacing between elements was plainly visible. The median vertical distance
    // between consecutive visible children measures the rhythm the dimension
    // actually names. A declared gap still wins, because it states intent.
    const elementGap = (root, style) => {
      const declared = parseFloat(style.rowGap);
      if (Number.isFinite(declared)) return declared;
      // Descend through single-child wrappers. The source lays its elements out
      // as direct children; the build wraps them in a container, so measuring the
      // section's own children found one box and no rhythm at all. The gap lives
      // wherever the content actually sits.
      let host = root;
      for (let depth = 0; depth < 4; depth += 1) {
        const visible = Array.from(host.children).filter((el) => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.height > 0;
        });
        if (visible.length !== 1) break;
        host = visible[0];
      }
      const kids = Array.from(host.children).filter((el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      });
      if (kids.length < 2) return null;
      const gaps = [];
      for (let i = 1; i < kids.length; i += 1) {
        const previous = kids[i - 1].getBoundingClientRect();
        const current = kids[i].getBoundingClientRect();
        const gap = current.top - previous.bottom;
        if (gap >= 0) gaps.push(gap);
      }
      if (!gaps.length) return null;
      gaps.sort((a, b) => a - b);
      const middle = Math.floor(gaps.length / 2);
      return gaps.length % 2 ? gaps[middle] : (gaps[middle - 1] + gaps[middle]) / 2;
    };
    const effectiveBackground = (el) => {
        let node = el;
        while (node) {
            const value = getComputedStyle(node).backgroundColor;
            if (value && value !== 'transparent' && value !== 'rgba(0, 0, 0, 0)') {
                return value;
            }
            node = node.parentElement;
        }
        return null;
    };
    const px = (value) => value || null;
    const snapshots = candidates.map((el, index) => {
        const cs = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        const columns = cs.display === 'grid' && cs.gridTemplateColumns !== 'none'
            ? cs.gridTemplateColumns.split(/\s+/).filter(Boolean).length
            : null;
        return {
            selector: el.id ? `#${CSS.escape(el.id)}` : `rendered-section-${index + 1}`,
            bounds: {x: rect.x, y: rect.y + window.scrollY, width: rect.width, height: rect.height},
            hidden: cs.display === 'none' || cs.visibility === 'hidden',
            typography: {
                heading: typeOf(el.querySelector('h1, h2, h3, h4, h5, h6')),
                body: typeOf(bodyElement(el)),
            },
            action: (() => {
                const a = el.querySelector('a, button');
                if (!a) return null;
                const s = getComputedStyle(a);
                return {
                    text_color: s.color || null,
                    background_color: effectiveBackground(a),
                };
            })(),
            styles: {
                background_color: effectiveBackground(el),
                background_image: cs.backgroundImage,
                background_position: cs.backgroundPosition,
                text_color: cs.color,
                font_family: cs.fontFamily,
                font_size: px(cs.fontSize),
                font_weight: cs.fontWeight,
                line_height: cs.lineHeight,
                letter_spacing: cs.letterSpacing,
                width: px(cs.width),
                height: px(cs.height),
                min_height: px(cs.minHeight),
                max_width: px(cs.maxWidth),
                margin: cs.margin,
                padding: cs.padding,
                row_gap: (() => {
                    const gap = elementGap(el, cs);
                    return gap === null ? cs.rowGap : gap + 'px';
                })(),
                column_gap: cs.columnGap,
                text_align: cs.textAlign,
                item_align: cs.alignItems,
                border: cs.border,
                border_radius: cs.borderRadius,
                box_shadow: cs.boxShadow,
                object_fit: cs.objectFit,
                object_position: cs.objectPosition,
                position: cs.position,
                transform: cs.transform,
                opacity: cs.opacity,
                display: cs.display,
                visibility: cs.visibility,
                flex_direction: cs.flexDirection,
                flex_wrap: cs.flexWrap,
                order: cs.order,
                column_count: columns
            }
        };
    });
    const nav = document.querySelector('header nav, nav');
    let navigationCollapsed = null;
    if (nav) {
        const navStyle = getComputedStyle(nav);
        const toggle = document.querySelector(
            'header button[aria-expanded], .navbar-toggler, .menu-toggle, [data-menu-toggle]'
        );
        const toggleVisible = toggle && getComputedStyle(toggle).display !== 'none';
        navigationCollapsed = navStyle.display === 'none' || Boolean(toggleVisible);
    }
    // A stylesheet that declared itself and did not load means this render is
    // missing the design it was supposed to measure. A saved page whose sheets
    // are root-relative cannot resolve them from a file:// URI, so the browser
    // paints browser defaults and the evidence looks measured while describing
    // nothing the author chose.
    // A root-relative stylesheet cannot resolve from a file:// document: there
    // is no site root to resolve against. The browser still creates a sheet
    // object, so `link.sheet` is truthy and reading `cssRules` throws the same
    // way a legitimately cross-origin sheet does — neither is a usable signal.
    // The address is.
    let unresolvedStylesheets = 0;
    const isFile = location.protocol === 'file:';
    document.querySelectorAll('link[rel~="stylesheet"]').forEach((link) => {
        const href = link.getAttribute('href') || '';
        if (isFile) {
            // A failed file:// load still yields a truthy `link.sheet` whose
            // cssRules throw exactly as a cross-origin sheet's do, so only the
            // address distinguishes it: there is no site root to resolve against.
            if (href.startsWith('/') && !href.startsWith('//')) unresolvedStylesheets += 1;
            return;
        }
        // Served over http, a sheet that did not load leaves `link.sheet` null,
        // which catches a 404 for an asset the saved copy never included —
        // invisible to the address test, because the address is now resolvable.
        if (!link.sheet) unresolvedStylesheets += 1;
    });
    return {
        sections: snapshots,
        navigation_collapsed: navigationCollapsed,
        unresolved_stylesheets: unresolvedStylesheets,
    };
}"""


class HtmlAdapterError(ValueError):
    """Raised when an HTML or legacy crawl artifact cannot be adapted safely."""


class _RenderedBrowserPage(Protocol):
    """Small Playwright page surface used by the rendered adapter."""

    def evaluate(self, expression: str) -> JsonValue:
        """Evaluate JavaScript and return a JSON-compatible result."""


@dataclass(frozen=True)
class HtmlPageInput:
    """One statically fetched HTML page supplied to the adapter."""

    url: str
    html: str
    title: str | None = None
    slug: str | None = None
    parent_slug: str | None = None


@dataclass(frozen=True)
class RenderedSectionObservation:
    """Geometry and computed styles for one rendered section candidate."""

    selector: str
    bounds: BoundingBox
    hidden: bool
    styles: Mapping[str, JsonValue] = field(default_factory=dict)
    # Per-element font samples, keyed "heading" and "body". The section's own
    # computed font describes the section box, not its heading, so the
    # typography dimension needs these to be measured rather than assumed.
    typography: Mapping[str, Mapping[str, JsonValue]] = field(default_factory=dict)
    # First action element's colours. The accent role is read from an action
    # element's own style, so without this the design side can never supply one.
    action: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderedPageObservation:
    """Independent browser evidence for one page and breakpoint."""

    breakpoint: BreakpointName
    viewport: Viewport
    html: str
    sections: tuple[RenderedSectionObservation, ...]
    navigation_collapsed: bool | None = None


@dataclass(frozen=True)
class RenderedCaptureResult:
    """Successful viewport captures and non-fatal viewport warnings."""

    observations: tuple[RenderedPageObservation, ...]
    warnings: tuple[DesignWarning, ...]


def _normalize_stylesheet_url(url: str) -> str:
    """Normalize a stylesheet URL for cross-page cache keys."""

    def normalize_port(scheme: str, netloc: str) -> str:
        lowered = netloc.casefold()
        if scheme == "http" and lowered.endswith(":80"):
            return lowered[:-3]
        if scheme == "https" and lowered.endswith(":443"):
            return lowered[:-4]
        return lowered

    clean, _ = urldefrag(url)
    parsed = urlsplit(clean)
    scheme = parsed.scheme.casefold()
    return urlunsplit(
        (scheme, normalize_port(scheme, parsed.netloc), parsed.path or "/", parsed.query, "")
    )


class StylesheetCache:
    """Fetch same-domain stylesheets once while retaining page-specific CSS."""

    def __init__(self, fetch: Callable[[str], str] = fetch_url_text) -> None:
        self._fetch = fetch
        self._cache: dict[str, str | None] = {}

    @property
    def cached_urls(self) -> tuple[str, ...]:
        """Return normalized cached URLs in deterministic insertion order."""

        return tuple(self._cache)

    def collect(
        self,
        html: str,
        page_url: str,
        on_warning: Callable[[str], None] | None = None,
    ) -> str:
        """Return inline and linked CSS used by this page.

        Failed linked stylesheets are cached as unavailable, but a warning is
        emitted for every affected page so the gap retains page and URL context.
        """

        warn = on_warning or (lambda _message: None)
        soup = BeautifulSoup(html, "html.parser")
        chunks = [style.string for style in soup.find_all("style") if style.string]

        for link in soup.find_all("link", rel=True):
            rels = {str(value).casefold() for value in link.get("rel", [])}
            href = link.get("href")
            if "stylesheet" not in rels or not href:
                continue
            absolute = _normalize_stylesheet_url(urljoin(page_url, str(href)))
            if not same_domain(absolute, page_url):
                continue
            was_cached = absolute in self._cache
            if not was_cached:
                try:
                    self._cache[absolute] = self._fetch(absolute)
                except (CrawlError, OSError, ValueError) as exc:
                    self._cache[absolute] = None
                    warn(
                        f"Page {page_url}: failed to fetch stylesheet {absolute}: {exc}"
                    )
            cached = self._cache[absolute]
            if cached is None:
                if was_cached:
                    warn(
                        f"Page {page_url}: stylesheet unavailable {absolute}"
                    )
                continue
            chunks.append(cached)

        return "\n".join(chunks)


@contextmanager
def serve_local_directory(path: Path):
    """Serve one saved page's directory on loopback and yield its URL.

    A saved page's stylesheets are usually root-relative, and a root-relative
    URL cannot resolve from a `file://` document — there is no site root. The
    browser then paints its own defaults and the render describes nothing the
    author chose. Serving the copy gives those paths a root to resolve against,
    so assets saved alongside the page load exactly as they did on the site.

    Loopback only, an ephemeral port, the source directory alone, and shut down
    on exit: this resolves the page's own references and reaches no network.
    """

    directory = path.parent if path.is_file() else path
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        name = path.name if path.is_file() else ""
        yield f"http://127.0.0.1:{port}/{name}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def capture_rendered_observations(
    url: str,
    *,
    viewports: Mapping[BreakpointName, Viewport] = CANONICAL_VIEWPORTS,
    timeout_seconds: int = 45,
    session_factory: Callable[
        [tuple[int, int]], AbstractContextManager[_RenderedBrowserPage]
    ] = rendered_page_session,
    render: Callable[[_RenderedBrowserPage, str, int], str] = render_page_html,
) -> RenderedCaptureResult:
    """Capture independent geometry/style evidence at requested breakpoints.

    The existing rendered helper settles fonts, walks the page to trigger lazy
    loading, disables motion, and stamps hidden/background evidence. A failure
    at one viewport becomes a warning and never discards successful captures.
    """

    observations: list[RenderedPageObservation] = []
    warnings: list[DesignWarning] = []

    for breakpoint, viewport in viewports.items():
        try:
            with session_factory((viewport.width, viewport.height)) as page:
                # Neither `link.sheet` nor `cssRules` distinguishes a stylesheet
                # that 404'd over http: Chromium creates a sheet object either
                # way. The response status does, and only the session can see it.
                failed_styles: list[str] = []
                listen = getattr(page, "on", None)
                if callable(listen):
                    def _record(response, _sink=failed_styles):
                        try:
                            if response.status >= 400 and (
                                ".css" in response.url.lower()
                                or "stylesheet" in (response.request.resource_type or "")
                            ):
                                _sink.append(response.url)
                        except Exception:  # noqa: BLE001 - telemetry must never fail a capture
                            pass

                    listen("response", _record)
                html = render(page, url, timeout_seconds)
                raw_snapshot = page.evaluate(_RENDERED_OBSERVATION_JS)
                if not isinstance(raw_snapshot, dict):
                    raise HtmlAdapterError("rendered observation script returned no object")
                raw_sections = raw_snapshot.get("sections", [])
                if not isinstance(raw_sections, list):
                    raise HtmlAdapterError("rendered observation sections must be a list")
                sections: list[RenderedSectionObservation] = []
                for index, raw_section in enumerate(raw_sections):
                    if not isinstance(raw_section, dict):
                        continue
                    raw_bounds = raw_section.get("bounds", {})
                    raw_styles = raw_section.get("styles", {})
                    if not isinstance(raw_bounds, dict) or not isinstance(raw_styles, dict):
                        continue
                    raw_type = raw_section.get("typography")
                    typography = {
                        str(key): {
                            str(field_name): field_value
                            for field_name, field_value in sample.items()
                        }
                        for key, sample in (raw_type or {}).items()
                        if isinstance(sample, dict)
                    } if isinstance(raw_type, dict) else {}
                    sections.append(
                        RenderedSectionObservation(
                            selector=str(
                                raw_section.get("selector")
                                or f"rendered-section-{index + 1}"
                            ),
                            bounds=BoundingBox.model_validate(raw_bounds),
                            hidden=bool(raw_section.get("hidden", False)),
                            styles={str(key): value for key, value in raw_styles.items()},
                            typography=typography,
                            action=(
                                {
                                    str(key): value
                                    for key, value in raw_section["action"].items()
                                }
                                if isinstance(raw_section.get("action"), dict)
                                else {}
                            ),
                        )
                    )
                unresolved = raw_snapshot.get("unresolved_stylesheets")
                if not isinstance(unresolved, int):
                    unresolved = 0
                unresolved += len(dict.fromkeys(failed_styles))
                if unresolved > 0:
                    warnings.append(
                        DesignWarning(
                            code="rendered_stylesheets_unresolved",
                            message=(
                                f"{unresolved} stylesheet(s) declared by {url} did not load at "
                                f"{breakpoint.value}; the render shows browser defaults, so its "
                                "colour, typography and spacing describe nothing the author chose"
                            ),
                            path=url,
                        )
                    )
                collapsed = raw_snapshot.get("navigation_collapsed")
                observations.append(
                    RenderedPageObservation(
                        breakpoint=breakpoint,
                        viewport=viewport,
                        html=html,
                        sections=tuple(sections),
                        navigation_collapsed=(
                            collapsed if isinstance(collapsed, bool) else None
                        ),
                    )
                )
        except (VisualCaptureError, HtmlAdapterError, ValueError, OSError) as exc:
            warnings.append(
                DesignWarning(
                    code="rendered_viewport_failed",
                    message=f"Rendered {breakpoint.value} capture failed for {url}: {exc}",
                    path=url,
                )
            )
        except Exception as exc:  # noqa: BLE001 - Playwright exposes browser-specific errors
            warnings.append(
                DesignWarning(
                    code="rendered_viewport_failed",
                    message=f"Rendered {breakpoint.value} capture failed for {url}: {exc}",
                    path=url,
                )
            )

    return RenderedCaptureResult(tuple(observations), tuple(warnings))


def _legacy_provenance(
    source_url: str,
    *,
    method: str,
    selector: str | None = None,
    breakpoint: BreakpointName | None = None,
    bounds: BoundingBox | None = None,
    source_attribute: str | None = None,
) -> dict[str, JsonValue]:
    provenance: dict[str, JsonValue] = {
        "source_kind": "legacy_sections" if method == "legacy" else "live_html",
        "method": method,
        "source_url": source_url,
    }
    if selector:
        provenance["css_selector"] = selector
    if breakpoint:
        provenance["viewport"] = breakpoint.value
    if bounds:
        provenance["bounds"] = bounds.model_dump(mode="json")
    if source_attribute:
        provenance["source_attribute"] = source_attribute
    return provenance


def _warning(
    code: str, message: str, path: str, *, severity: str = "warning"
) -> dict[str, JsonValue]:
    return {"code": code, "message": message, "severity": severity, "path": path}


def _slug_from_url(url: str) -> str:
    path = urlsplit(url).path.strip("/")
    if not path:
        return "home"
    slug = re.sub(r"[^a-z0-9]+", "-", path.casefold()).strip("-")
    return slug or "home"


def _tokens_from_legacy(raw: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(raw, dict):
        return {"raw": {}}

    colors: dict[str, JsonValue] = {}
    named_colors = raw.get("colors")
    if isinstance(named_colors, dict):
        for name, value in named_colors.items():
            colors[str(name)] = {"value": value, "provenance": []}
    for collection_name in ("brand_colors", "neutral_colors"):
        values = raw.get(collection_name)
        if isinstance(values, list):
            for index, value in enumerate(values):
                colors[f"{collection_name}_{index + 1}"] = {
                    "value": value,
                    "provenance": [],
                }

    typography: list[dict[str, JsonValue]] = []
    fonts = raw.get("fonts")
    if isinstance(fonts, list):
        typography.extend(
            {
                "role": f"font_{index + 1}",
                "font_family": str(value),
                "provenance": [],
            }
            for index, value in enumerate(fonts)
        )
    elif isinstance(fonts, dict):
        for role, value in fonts.items():
            if isinstance(value, dict):
                family = value.get("family") or value.get("name")
            else:
                family = value
            if family:
                typography.append(
                    {
                        "role": str(role),
                        "font_family": str(family),
                        "provenance": [],
                    }
                )

    return {
        "colors": colors,
        "typography": typography,
        "spacing": {},
        "raw": raw,
    }


_TYPE_SAMPLE_KINDS = {"heading": "heading", "body": "text"}


def _attach_type_samples(
    elements: list[dict[str, JsonValue]],
    samples: Mapping[str, Mapping[str, JsonValue]],
    provenance: dict[str, JsonValue],
) -> None:
    """Give the first heading and first body element their measured fonts.

    The typography metric reads each element's own style, while a rendered
    crawl records computed values on the section box. Without this the design
    side has no type evidence at all and the dimension scores nothing, on every
    section of every breakpoint.

    Only the first element of each kind is stamped, matching what the browser
    sampled: `querySelector` returns the first match, so claiming the value for
    later elements would assert a measurement that was never taken.
    """

    rendered_provenance = {**provenance, "method": "rendered"}
    for key, kind in _TYPE_SAMPLE_KINDS.items():
        sample = samples.get(key)
        if not isinstance(sample, Mapping):
            continue
        target = next(
            (element for element in elements if element.get("kind") == kind), None
        )
        if target is None:
            continue
        observations = [
            {
                "property": prop,
                "value": value,
                "status": "observed",
                "confidence": 1.0,
                "provenance": [rendered_provenance],
            }
            for prop in ("font_family", "font_size", "font_weight")
            for value in (sample.get(prop),)
            if value not in (None, "")
        ]
        if observations:
            style = target.setdefault("style", {"observations": [], "raw": {}})
            style["observations"] = observations


_ACTION_ELEMENT_KINDS = ("button", "link")


def _attach_action_sample(
    elements: list[dict[str, JsonValue]],
    sample: Mapping[str, JsonValue],
    provenance: dict[str, JsonValue],
) -> None:
    """Give the first action element its measured colours.

    The accent role is read from an action element's own style, so a design
    document without it can never supply an accent and the colour dimension
    compares one role of three. Only the first element is stamped, matching the
    `querySelector` the browser used.
    """

    rendered_provenance = {**provenance, "method": "rendered"}
    target = next(
        (
            element
            for element in elements
            if element.get("kind") in _ACTION_ELEMENT_KINDS
        ),
        None,
    )
    if target is None:
        return
    observations = [
        {
            "property": prop,
            "value": value,
            "status": "observed",
            "confidence": 1.0,
            "provenance": [rendered_provenance],
        }
        for prop in ("background_color", "text_color")
        for value in (sample.get(prop),)
        if value not in (None, "")
    ]
    if observations:
        style = target.setdefault("style", {"observations": [], "raw": {}})
        style["observations"] = observations


def _style_from_content(
    content: Mapping[str, JsonValue],
    provenance: dict[str, JsonValue],
    rendered_styles: Mapping[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    observations: dict[str, dict[str, JsonValue]] = {}
    for content_key, style_property in _STYLE_CONTENT_KEYS.items():
        value = content.get(content_key)
        if value not in (None, ""):
            observations[style_property.value] = {
                "property": style_property.value,
                "value": value,
                "status": "observed",
                "confidence": 0.65,
                "provenance": [provenance],
            }

    if rendered_styles is not None:
        rendered_provenance = {**provenance, "method": "rendered"}
        for key, value in rendered_styles.items():
            style_property = _RENDERED_STYLE_KEYS.get(key)
            if style_property is None or value in (None, ""):
                continue
            observations[style_property.value] = {
                "property": style_property.value,
                "value": value,
                "status": "observed",
                "confidence": 1.0,
                "provenance": [rendered_provenance],
            }
    return {"observations": list(observations.values()), "raw": {}}


def _content_values(content: Mapping[str, JsonValue], key: str) -> list[JsonValue]:
    value = content.get(key, [])
    return value if isinstance(value, list) else []


def _repeat_alignment(
    section_type: str, content: Mapping[str, JsonValue]
) -> tuple[int, dict[str, int], int]:
    counts = {
        "title": len(_content_values(content, "headings")),
        "body": len(_content_values(content, "paragraphs")),
        "media": len(_content_values(content, "images")),
        "action": max(
            len(_content_values(content, "buttons")),
            len(_content_values(content, "links")),
        ),
    }
    heading_offset = 0
    if section_type == "faq" and counts["title"] == counts["body"] + 1:
        heading_offset = 1
        counts["title"] -= 1
    nonzero = [count for count in counts.values() if count]
    return (max(nonzero, default=0), counts, heading_offset)


def _section_from_legacy(
    raw_section: Mapping[str, JsonValue],
    *,
    page_id: str,
    section_index: int,
    source_url: str,
    method: str,
    assets: dict[str, dict[str, JsonValue]],
    rendered_by_breakpoint: Mapping[BreakpointName, RenderedSectionObservation],
    rendered_viewports: Mapping[BreakpointName, Viewport],
    extra_interactions: Sequence[str],
    warnings: list[dict[str, JsonValue]],
    artifact_path: str,
) -> dict[str, JsonValue]:
    section_type = str(raw_section.get("type") or "content")
    template = str(raw_section.get("template") or "")
    raw_content = raw_section.get("content")
    content: Mapping[str, JsonValue]
    if isinstance(raw_content, dict):
        content = raw_content
    else:
        content = {}
        warnings.append(
            _warning(
                "legacy_content_malformed",
                "Legacy section content was not an object; an empty section was retained.",
                artifact_path,
            )
        )

    section_id = f"{page_id}.section.{section_index + 1}"
    desktop = rendered_by_breakpoint.get(BreakpointName.DESKTOP)
    static_selector = raw_section.get("_static_selector")
    provenance = _legacy_provenance(
        source_url,
        method="rendered" if desktop else method,
        selector=(
            desktop.selector
            if desktop
            else artifact_path
            if method == "legacy"
            else str(static_selector)
            if static_selector
            else None
        ),
        breakpoint=BreakpointName.DESKTOP if desktop else None,
        bounds=desktop.bounds if desktop else None,
        source_attribute=artifact_path if method == "legacy" else None,
    )
    static_role = raw_section.get("_static_role")
    legacy_role = _ROLE_BY_LEGACY_TYPE.get(section_type, section_type or "other")
    semantic_role = (
        str(static_role)
        if static_role and (str(static_role) != "rich_text" or legacy_role == "rich_text")
        else legacy_role
    )
    role_confidence = (
        0.95
        if static_role
        else 0.85
        if section_type in _ROLE_BY_LEGACY_TYPE
        else 0.55
    )
    elements: list[dict[str, JsonValue]] = []
    element_fields: dict[str, list[str | list[str] | None]] = {
        "title": [],
        "body": [],
        "media": [],
        "action": [],
    }
    group_id = f"{section_id}.items" if section_type in _REPEAT_KIND_BY_TYPE else None
    repeat_count, repeat_counts, heading_offset = _repeat_alignment(section_type, content)
    relationship_confidence = 0.9
    meaningful_counts = [count for count in repeat_counts.values() if count]
    if group_id and meaningful_counts and len(set(meaningful_counts)) > 1:
        relationship_confidence = 0.6
        warnings.append(
            _warning(
                "legacy_relationship_ambiguous",
                (
                    f"Legacy {section_type} arrays have unequal item counts "
                    f"{repeat_counts}; positional bindings were retained at reduced confidence."
                ),
                artifact_path,
            )
        )
    if group_id and repeat_count > 1 and _content_values(content, "list_items"):
        relationship_confidence = min(relationship_confidence, 0.6)
        warnings.append(
            _warning(
                "legacy_repeat_fields_unbound",
                (
                    "Legacy list items do not identify their owning repeat item; "
                    "they were retained without a positional group binding."
                ),
                artifact_path,
            )
        )

    order = 0
    headings = _content_values(content, "headings")
    for index, heading in enumerate(headings):
        is_section_title = bool(group_id and heading_offset and index == 0)
        role = "section_title" if is_section_title else (
            "item_title" if group_id else ("section_title" if index == 0 else "heading")
        )
        owner = None if is_section_title else group_id
        element_id = f"{section_id}.heading.{index + 1}"
        elements.append(
            _element(
                element_id,
                "heading",
                role,
                order,
                provenance,
                value=heading,
                attributes={"heading_level": 2 if index == 0 else 3},
                group_id=owner,
                confidence=relationship_confidence if owner else 0.85,
            )
        )
        if owner:
            element_fields["title"].append(element_id)
        order += 1

    for index, paragraph in enumerate(_content_values(content, "paragraphs")):
        element_id = f"{section_id}.text.{index + 1}"
        elements.append(
            _element(
                element_id,
                "text",
                "item_body" if group_id else "section_body",
                order,
                provenance,
                value=paragraph,
                group_id=group_id,
                confidence=relationship_confidence if group_id else 0.85,
            )
        )
        element_fields["body"].append(element_id)
        order += 1

    for index, raw_image in enumerate(_content_values(content, "images")):
        image = raw_image if isinstance(raw_image, dict) else {}
        source = image.get("src")
        source_value = str(source) if source else None
        alt = str(image.get("alt") or "")
        asset_id = _register_asset(
            assets,
            source_url=source_value,
            alt_text=alt,
            role="decorative" if image.get("role") == "background" else "editorial",
            provenance=[provenance],
        )
        element_id = f"{section_id}.image.{index + 1}"
        elements.append(
            _element(
                element_id,
                "image",
                "item_media" if group_id else "section_media",
                order,
                provenance,
                value=source_value,
                attributes={
                    "alt": alt,
                    **({"caption": image["caption"]} if image.get("caption") else {}),
                },
                asset_id=asset_id,
                group_id=group_id,
                confidence=relationship_confidence if group_id else 0.85,
            )
        )
        element_fields["media"].append(element_id)
        order += 1

    buttons = _content_values(content, "buttons")
    links = _content_values(content, "links")
    action_count = max(len(buttons), len(links))
    for index in range(action_count):
        button = buttons[index] if index < len(buttons) else None
        link = links[index] if index < len(links) else None
        action_ids: list[str] = []
        for action_kind, raw_action in (("button", button), ("link", link)):
            if not isinstance(raw_action, dict):
                continue
            label = raw_action.get("text") or raw_action.get("label") or ""
            href = raw_action.get("href")
            element_id = f"{section_id}.{action_kind}.{index + 1}"
            elements.append(
                _element(
                    element_id,
                    action_kind,
                    "item_action" if group_id else (
                        "primary_action" if action_kind == "button" else "link"
                    ),
                    order,
                    provenance,
                    value=label,
                    attributes={"href": href} if href else {},
                    group_id=group_id,
                    confidence=relationship_confidence if group_id else 0.85,
                )
            )
            action_ids.append(element_id)
            order += 1
        if not action_ids:
            element_fields["action"].append(None)
            continue
        element_fields["action"].append(
            action_ids[0] if len(action_ids) == 1 else action_ids
        )

    for index, item in enumerate(_content_values(content, "list_items")):
        elements.append(
            _element(
                f"{section_id}.list-item.{index + 1}",
                "list_item",
                "feature" if section_type == "pricing" else "list_item",
                order,
                provenance,
                value=item,
                confidence=0.8,
            )
        )
        order += 1

    for index, raw_quote in enumerate(_content_values(content, "blockquotes")):
        quote = raw_quote if isinstance(raw_quote, dict) else {"text": raw_quote}
        elements.append(
            _element(
                f"{section_id}.quote.{index + 1}",
                "quote",
                "testimonial_quote",
                order,
                provenance,
                value=quote.get("text"),
                attributes={"author": quote.get("citation") or ""},
                group_id=group_id,
                confidence=relationship_confidence,
            )
        )
        order += 1

    video_ids: list[str] = []
    for index, raw_video in enumerate(_content_values(content, "videos")):
        video = raw_video if isinstance(raw_video, dict) else {"src": raw_video}
        element_id = f"{section_id}.video.{index + 1}"
        video_ids.append(element_id)
        elements.append(
            _element(
                element_id,
                "video",
                "section_video",
                order,
                provenance,
                value=video.get("src"),
                attributes={"embed_type": video.get("type") or "unknown"},
                confidence=0.9,
            )
        )
        order += 1

    form_ids: list[str] = []
    for index, raw_field in enumerate(_content_values(content, "form_fields")):
        form_field = raw_field if isinstance(raw_field, dict) else {"name": str(raw_field)}
        element_id = f"{section_id}.form-field.{index + 1}"
        form_ids.append(element_id)
        elements.append(
            _element(
                element_id,
                "form_placeholder",
                "form_field",
                order,
                provenance,
                attributes={
                    **form_field,
                    "form_action": content.get("form_action") or "",
                },
                confidence=0.9,
            )
        )
        order += 1

    for index, table in enumerate(_content_values(content, "tables")):
        elements.append(
            _element(
                f"{section_id}.table.{index + 1}",
                "other",
                "table",
                order,
                provenance,
                value=table,
                confidence=0.8,
            )
        )
        order += 1

    groups: list[dict[str, JsonValue]] = []
    if group_id and repeat_count:
        items: list[dict[str, JsonValue]] = []
        for item_index in range(repeat_count):
            fields: dict[str, JsonValue] = {}
            for field_name, element_ids in element_fields.items():
                if item_index < len(element_ids) and element_ids[item_index] is not None:
                    fields[field_name] = element_ids[item_index]
            items.append(
                {
                    "id": f"{group_id}.{item_index + 1}",
                    "fields": fields,
                    "provenance": [provenance],
                }
            )
        groups.append(
            {
                "id": group_id,
                "kind": _REPEAT_KIND_BY_TYPE[section_type],
                "items": items,
                "provenance": [provenance],
            }
        )

    interaction_kinds = list(dict.fromkeys(extra_interactions))
    if section_type == "faq":
        interaction_kinds.append("accordion")
    if video_ids:
        interaction_kinds.append("video_embed")
    if form_ids:
        interaction_kinds.append("form")
    interaction_kinds = list(dict.fromkeys(interaction_kinds))
    interactions: list[dict[str, JsonValue]] = []
    for interaction_index, kind in enumerate(interaction_kinds):
        targets = video_ids if kind == "video_embed" else form_ids if kind == "form" else []
        native_known = kind in {"accordion", "tabs", "carousel", "menu", "video_embed", "form"}
        interactions.append(
            {
                "id": f"{section_id}.interaction.{interaction_index + 1}",
                "kind": kind,
                "target_element_ids": targets,
                "native_representation_known": native_known,
                "status": "observed",
                "details": {
                    "form_fields": len(form_ids) if kind == "form" else 0,
                    "raw_scripts_copied": False,
                },
                "provenance": [provenance],
                "confidence": 0.9,
            }
        )
        if not native_known:
            warnings.append(
                _warning(
                    "unsupported_interaction",
                    f"No native Vanjaro representation is declared for {kind}.",
                    artifact_path,
                )
            )

    responsive: list[dict[str, JsonValue]] = []
    desktop_styles = desktop.styles if desktop else {}
    for breakpoint, observation in rendered_by_breakpoint.items():
        changed_styles = (
            {}
            if breakpoint == BreakpointName.DESKTOP
            else {
                key: value
                for key, value in observation.styles.items()
                if desktop_styles.get(key) != value
            }
        )
        style = _style_from_content({}, _legacy_provenance(
            source_url,
            method="rendered",
            selector=observation.selector,
            breakpoint=breakpoint,
            bounds=observation.bounds,
        ), changed_styles)
        layout_changes: dict[str, JsonValue] = {}
        if "column_count" in changed_styles and changed_styles["column_count"] is not None:
            layout_changes["columns"] = changed_styles["column_count"]
        responsive.append(
            {
                "breakpoint": breakpoint.value,
                "viewport": rendered_viewports[breakpoint].model_dump(mode="json"),
                "status": "observed",
                "layout_changes": layout_changes,
                "style": style,
                "hidden": observation.hidden,
                "provenance": [
                    _legacy_provenance(
                        source_url,
                        method="rendered",
                        selector=observation.selector,
                        breakpoint=breakpoint,
                        bounds=observation.bounds,
                    )
                ],
            }
        )

    background_image = content.get("background_image")
    if isinstance(background_image, str) and background_image:
        _register_asset(
            assets,
            source_url=background_image,
            role="decorative",
            provenance=[provenance],
        )

    result: dict[str, JsonValue] = {
        "id": section_id,
        "order": section_index,
        "semantic_role": semantic_role,
        "role_confidence": role_confidence,
        "candidate_roles": [{"role": semantic_role, "score": role_confidence}],
        "layout": _layout_for_section(section_type, template, repeat_count),
        "content": elements,
        "regions": [],
        "groups": groups,
        "style": _style_from_content(
            content, provenance, desktop.styles if desktop else None
        ),
        "responsive": responsive,
        "decorative_layers": [],
        "interactions": interactions,
        "provenance": [provenance],
        "metadata": {
            "legacy_type": section_type,
            "legacy_template": template,
            "relationship_confidence": relationship_confidence,
        },
    }
    static_html = raw_section.get("_static_html")
    if isinstance(static_html, str) and static_html:
        _enrich_section_from_static_dom(
            result,
            static_html,
            source_url=source_url,
            assets=assets,
            provenance=provenance,
        )
    # After enrichment, which replaces the content list wholesale. Stamping
    # before this point loses the samples silently.
    if desktop and (desktop.typography or desktop.action):
        content = result.get("content")
        if isinstance(content, list):
            if desktop.typography:
                _attach_type_samples(content, desktop.typography, provenance)
            if desktop.action:
                _attach_action_sample(content, desktop.action, provenance)
    return result


def _navigation_metadata(
    observations: Sequence[RenderedPageObservation],
) -> dict[str, JsonValue]:
    states = {
        observation.breakpoint.value: observation.navigation_collapsed
        for observation in observations
        if observation.navigation_collapsed is not None
    }
    return {"navigation_collapsed": states} if states else {}


def _drop_dangling_interaction_targets(section: dict[str, JsonValue]) -> None:
    """Keep interaction targets pointing at elements the section actually has.

    Interaction targets are built from the raw crawl, where a video carries a
    `.video.N` identifier. Element identifiers are rebuilt from the classified
    semantic role, so a video the classifier reads as section media becomes
    `.section-media.N` and the original target no longer resolves — which the
    Design Document validator rightly rejects.

    The interaction itself is still real: the page does embed a video. Only the
    unresolvable pointer is dropped, so the observation survives without
    claiming an element that is not there.
    """

    content = section.get("content")
    interactions = section.get("interactions")
    if not isinstance(content, list) or not isinstance(interactions, list):
        return
    existing = {
        element["id"]
        for element in content
        if isinstance(element, dict) and isinstance(element.get("id"), str)
    }
    for interaction in interactions:
        if not isinstance(interaction, dict):
            continue
        targets = interaction.get("target_element_ids")
        if not isinstance(targets, list):
            continue
        interaction["target_element_ids"] = [
            target for target in targets if target in existing
        ]


def _pair_rendered_sections(
    raw_sections: Sequence[Mapping[str, JsonValue]],
    observation: RenderedPageObservation,
) -> dict[int, RenderedSectionObservation]:
    """Map static section indexes to the rendered sections that are the same section.

    The browser and the static parser do not always find the same sections: the
    observation script skips anything inside a header or footer, so a page whose
    nav sits outside ``main`` yields one fewer rendered section. Pairing those
    two lists by position then shifts every section's geometry onto its
    neighbour — a measurement of the wrong element, which scores worse than no
    measurement because it looks like evidence.

    Identity wins when both sides expose it. Position is used only when the two
    lists are the same length, where it is the only correspondence available and
    cannot be silently off by one.
    """

    rendered_by_selector: dict[str, RenderedSectionObservation] = {}
    duplicated: set[str] = set()
    for rendered in observation.sections:
        if not rendered.selector.startswith("#"):
            continue
        if rendered.selector in rendered_by_selector:
            duplicated.add(rendered.selector)
            continue
        rendered_by_selector[rendered.selector] = rendered
    for selector in duplicated:
        rendered_by_selector.pop(selector, None)

    paired: dict[int, RenderedSectionObservation] = {}
    for index, raw_section in enumerate(raw_sections):
        static_selector = raw_section.get("_static_selector")
        if not static_selector:
            continue
        rendered = rendered_by_selector.get(str(static_selector))
        if rendered is not None:
            paired[index] = rendered
    if paired:
        return paired

    if len(observation.sections) == len(raw_sections):
        return dict(enumerate(observation.sections))
    return {}


def _build_document(
    *,
    source_kind: str,
    source_identifier: str,
    captured_at: datetime,
    pages_data: Sequence[tuple[HtmlPageInput, Sequence[Mapping[str, JsonValue]], str]],
    tokens: JsonValue,
    initial_assets: Sequence[Mapping[str, JsonValue]],
    global_metadata: Mapping[str, JsonValue],
    rendered_observations: Mapping[str, Sequence[RenderedPageObservation]],
    initial_warnings: Sequence[DesignWarning | Mapping[str, JsonValue]],
) -> DesignDocument:
    warnings: list[dict[str, JsonValue]] = [
        warning.model_dump(mode="json") if isinstance(warning, DesignWarning) else dict(warning)
        for warning in initial_warnings
    ]
    assets: dict[str, dict[str, JsonValue]] = {}
    for raw_asset in initial_assets:
        source_url_value = raw_asset.get("source_url")
        local_file = raw_asset.get("local_file") or raw_asset.get("file")
        mime_type_value = raw_asset.get("content_type") or raw_asset.get("mime_type")
        _register_asset(
            assets,
            source_url=str(source_url_value) if source_url_value else None,
            local_path=f"assets/{local_file}" if local_file else None,
            mime_type=str(mime_type_value) if mime_type_value else None,
            alt_text=str(raw_asset.get("alt_text")) if raw_asset.get("alt_text") else None,
            provenance=[
                _legacy_provenance(
                    source_identifier,
                    method="legacy" if source_kind == "legacy_sections" else "static",
                    source_attribute="assets/manifest.json",
                )
            ],
        )

    page_ids_by_slug = {
        page_input.slug or _slug_from_url(page_input.url): (
            page_input.slug or _slug_from_url(page_input.url)
        )
        for page_input, _sections, _method in pages_data
    }
    pages: list[dict[str, JsonValue]] = []
    confidence_values: list[float] = []

    for page_index, (page_input, raw_sections, method) in enumerate(pages_data):
        slug = page_input.slug or _slug_from_url(page_input.url)
        page_id = slug
        observations = list(rendered_observations.get(page_input.url, ()))
        observations_by_breakpoint = {
            observation.breakpoint: observation for observation in observations
        }
        interaction_kinds = _interaction_kinds_by_section(
            observations_by_breakpoint.get(
                BreakpointName.DESKTOP,
                RenderedPageObservation(
                    BreakpointName.DESKTOP,
                    CANONICAL_VIEWPORTS[BreakpointName.DESKTOP],
                    page_input.html,
                    (),
                ),
            ).html,
            raw_sections,
        )
        paired_by_breakpoint = {
            breakpoint: _pair_rendered_sections(raw_sections, observation)
            for breakpoint, observation in observations_by_breakpoint.items()
        }
        sections: list[dict[str, JsonValue]] = []
        for section_index, raw_section in enumerate(raw_sections):
            rendered_for_section = {
                breakpoint: paired[section_index]
                for breakpoint, paired in paired_by_breakpoint.items()
                if section_index in paired
            }
            rendered_viewports_for_section = {
                breakpoint: observations_by_breakpoint[breakpoint].viewport
                for breakpoint, paired in paired_by_breakpoint.items()
                if section_index in paired
            }
            missing = [
                breakpoint.value
                for breakpoint, paired in paired_by_breakpoint.items()
                if section_index not in paired
            ]
            if missing:
                warnings.append(
                    _warning(
                        "rendered_section_unmatched",
                        f"Section {section_index + 1} had no rendered match at {missing}.",
                        page_input.url,
                    )
                )
            section = _section_from_legacy(
                raw_section,
                page_id=page_id,
                section_index=section_index,
                source_url=page_input.url,
                method=method,
                assets=assets,
                rendered_by_breakpoint=rendered_for_section,
                rendered_viewports=rendered_viewports_for_section,
                extra_interactions=interaction_kinds.get(section_index, ()),
                warnings=warnings,
                artifact_path=str(raw_section.get("_artifact_path") or page_input.url),
            )
            _drop_dangling_interaction_targets(section)
            confidence_values.append(float(section["role_confidence"]))
            sections.append(section)

        provenance = _legacy_provenance(page_input.url, method=method)
        breakpoints = (
            [observation.breakpoint.value for observation in observations]
            if observations
            else [
                breakpoint.value
                for breakpoint in (BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE)
                if breakpoint == BreakpointName.DESKTOP
                or any(
                    any(item.get("breakpoint") == breakpoint.value for item in section.get("responsive", []))
                    for section in sections
                )
            ]
        )
        parent_page_id = (
            page_ids_by_slug.get(page_input.parent_slug)
            if page_input.parent_slug
            else None
        )
        if page_input.parent_slug and parent_page_id is None:
            warnings.append(
                _warning(
                    "missing_parent_page",
                    f"Page {slug} references missing parent {page_input.parent_slug}.",
                    page_input.url,
                )
            )
        pages.append(
            {
                "id": page_id,
                "source_reference": page_input.url,
                "title": page_input.title or slug.replace("-", " ").title(),
                "slug": "" if slug == "home" else slug,
                "parent_page_id": parent_page_id,
                "sections": sections,
                "breakpoints": breakpoints,
                "navigation_visibility": "visible",
                "seo": {"title": page_input.title} if page_input.title else None,
                "provenance": [provenance],
                "metadata": _navigation_metadata(observations),
            }
        )

    mean = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    source_metadata: dict[str, JsonValue] = {}
    if global_metadata:
        source_metadata["global_artifacts"] = dict(global_metadata)
        source_metadata["global_provenance"] = [
            {
                "kind": str(kind),
                "artifact": artifact,
                "source_url": source_identifier,
            }
            for kind, artifact in global_metadata.items()
        ]
    return DesignDocument.model_validate(
        {
            "schema_version": "1.0",
            "source": {
                "kind": source_kind,
                "identifier": source_identifier,
                "captured_at": captured_at,
                "adapter_version": "1.0",
                "metadata": source_metadata,
            },
            "tokens": _tokens_from_legacy(tokens),
            "assets": list(assets.values()),
            "pages": pages,
            "warnings": warnings,
            "analysis": {
                "section_confidence_mean": mean,
                "unsupported_traits": sorted(
                    {
                        warning["code"]
                        for warning in warnings
                        if warning["code"] in {
                            "unsupported_interaction",
                            "rendered_viewport_failed",
                            "legacy_relationship_ambiguous",
                        }
                    }
                ),
            },
        }
    )


def design_document_from_html(
    html: str,
    source_url: str,
    *,
    css_text: str | None = None,
    title: str | None = None,
    slug: str | None = None,
    captured_at: datetime | None = None,
    rendered_observations: Sequence[RenderedPageObservation] = (),
    rendered_warnings: Sequence[DesignWarning] = (),
) -> DesignDocument:
    """Convert one static HTML page, optionally enriched by rendered evidence."""

    desktop = next(
        (
            observation
            for observation in rendered_observations
            if observation.breakpoint == BreakpointName.DESKTOP
        ),
        None,
    )
    extraction_html = desktop.html if desktop else html
    sections = extract_sections(extraction_html, source_url, css_text=css_text)
    _enrich_faq_relationships(extraction_html, sections)
    _append_missing_video_sections(extraction_html, source_url, sections)
    sections = _prepare_static_sections(extraction_html, sections)
    soup = BeautifulSoup(extraction_html, "html.parser")
    page = HtmlPageInput(
        url=source_url,
        html=html,
        title=title or extract_page_title(soup) or _slug_from_url(source_url).title(),
        slug=slug,
    )
    return _build_document(
        source_kind="live_html",
        source_identifier=source_url,
        captured_at=captured_at or datetime.now(timezone.utc),
        pages_data=[(page, sections, "static")],
        tokens={},
        initial_assets=[],
        global_metadata={},
        rendered_observations={source_url: rendered_observations},
        initial_warnings=list(rendered_warnings),
    )


def analyze_html_pages(
    pages: Sequence[HtmlPageInput],
    *,
    source_identifier: str | None = None,
    stylesheet_cache: StylesheetCache | None = None,
    captured_at: datetime | None = None,
    rendered_observations: Mapping[str, Sequence[RenderedPageObservation]] | None = None,
) -> DesignDocument:
    """Analyze multiple static pages with shared and page-specific stylesheets."""

    if not pages:
        raise HtmlAdapterError("at least one HTML page is required")
    cache = stylesheet_cache or StylesheetCache()
    warning_models: list[DesignWarning] = []
    observations = rendered_observations or {}
    pages_data: list[tuple[HtmlPageInput, Sequence[Mapping[str, JsonValue]], str]] = []

    for page in pages:
        css = cache.collect(
            page.html,
            page.url,
            lambda message, page_url=page.url: warning_models.append(
                DesignWarning(
                    code="stylesheet_fetch_failed",
                    message=message,
                    path=page_url,
                )
            ),
        )
        page_observations = observations.get(page.url, ())
        desktop = next(
            (
                observation
                for observation in page_observations
                if observation.breakpoint == BreakpointName.DESKTOP
            ),
            None,
        )
        extraction_html = desktop.html if desktop else page.html
        sections = extract_sections(extraction_html, page.url, css_text=css)
        _enrich_faq_relationships(extraction_html, sections)
        _append_missing_video_sections(extraction_html, page.url, sections)
        sections = _prepare_static_sections(extraction_html, sections)
        pages_data.append((page, sections, "static"))

    return _build_document(
        source_kind="live_html",
        source_identifier=source_identifier or pages[0].url,
        captured_at=captured_at or datetime.now(timezone.utc),
        pages_data=pages_data,
        tokens={},
        initial_assets=[],
        global_metadata={},
        rendered_observations=observations,
        initial_warnings=warning_models,
    )


def _read_json(path: Path) -> JsonValue:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HtmlAdapterError(f"Could not read legacy artifact {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HtmlAdapterError(
            f"Invalid JSON in legacy artifact {path} at line {exc.lineno}: {exc.msg}"
        ) from exc


def convert_legacy_crawl(
    migration_directory: str | Path,
    *,
    captured_at: datetime | None = None,
) -> DesignDocument:
    """Convert an existing migration directory without modifying its artifacts."""

    root = Path(migration_directory)
    inventory_path = root / "site-inventory.json"
    raw_inventory = _read_json(inventory_path)
    if not isinstance(raw_inventory, dict):
        raise HtmlAdapterError(f"Legacy inventory {inventory_path} must contain an object")

    source_url = str(raw_inventory.get("source_url") or "")
    if not source_url:
        raise HtmlAdapterError(f"Legacy inventory {inventory_path} is missing source_url")

    initial_warnings: list[dict[str, JsonValue]] = []
    pages_data: list[tuple[HtmlPageInput, Sequence[Mapping[str, JsonValue]], str]] = []
    raw_pages = raw_inventory.get("pages", [])
    if not isinstance(raw_pages, list):
        raise HtmlAdapterError(f"Legacy inventory {inventory_path} pages must be a list")

    for page_index, raw_page in enumerate(raw_pages):
        if not isinstance(raw_page, dict):
            initial_warnings.append(
                _warning(
                    "legacy_page_malformed",
                    f"Skipped non-object page entry at index {page_index}.",
                    str(inventory_path),
                )
            )
            continue
        page_url = str(raw_page.get("url") or source_url)
        slug = str(raw_page.get("slug") or _slug_from_url(page_url))
        raw_entries = raw_page.get("sections", [])
        entries = raw_entries if isinstance(raw_entries, list) else []
        sections: list[Mapping[str, JsonValue]] = []
        for section_index, raw_entry in enumerate(entries):
            if not isinstance(raw_entry, dict) or not raw_entry.get("file"):
                initial_warnings.append(
                    _warning(
                        "legacy_section_entry_malformed",
                        f"Skipped malformed section entry {section_index} for page {slug}.",
                        str(inventory_path),
                    )
                )
                continue
            section_path = root / str(raw_entry["file"])
            try:
                raw_section = _read_json(section_path)
            except HtmlAdapterError as exc:
                initial_warnings.append(
                    _warning(
                        "legacy_section_unreadable",
                        str(exc),
                        str(section_path),
                    )
                )
                continue
            if not isinstance(raw_section, dict):
                initial_warnings.append(
                    _warning(
                        "legacy_section_malformed",
                        "Legacy section root was not an object and was skipped.",
                        str(section_path),
                    )
                )
                continue
            sections.append({**raw_section, "_artifact_path": str(raw_entry["file"])})
        pages_data.append(
            (
                HtmlPageInput(
                    url=page_url,
                    html="",
                    title=str(raw_page.get("title") or slug.replace("-", " ").title()),
                    slug=slug,
                    parent_slug=(
                        str(raw_page["parent_slug"])
                        if raw_page.get("parent_slug")
                        else None
                    ),
                ),
                sections,
                "legacy",
            )
        )

    assets: Sequence[Mapping[str, JsonValue]] = []
    raw_assets = raw_inventory.get("assets")
    if isinstance(raw_assets, dict) and raw_assets.get("manifest"):
        manifest_path = root / str(raw_assets["manifest"])
        try:
            manifest = _read_json(manifest_path)
            if isinstance(manifest, list):
                assets = [item for item in manifest if isinstance(item, dict)]
        except HtmlAdapterError as exc:
            initial_warnings.append(
                _warning("legacy_asset_manifest_unreadable", str(exc), str(manifest_path))
            )

    tokens: JsonValue = {}
    tokens_path = root / "design-tokens.json"
    if tokens_path.exists():
        try:
            tokens = _read_json(tokens_path)
        except HtmlAdapterError as exc:
            initial_warnings.append(
                _warning("legacy_tokens_unreadable", str(exc), str(tokens_path))
            )

    crawled_at = captured_at
    if crawled_at is None and raw_inventory.get("crawled_at"):
        try:
            crawled_at = datetime.fromisoformat(
                str(raw_inventory["crawled_at"]).replace("Z", "+00:00")
            )
        except ValueError:
            initial_warnings.append(
                _warning(
                    "legacy_capture_time_invalid",
                    "Legacy crawled_at was invalid; conversion time was used.",
                    str(inventory_path),
                )
            )
    if crawled_at is not None and crawled_at.tzinfo is None:
        crawled_at = crawled_at.replace(tzinfo=timezone.utc)

    raw_global = raw_inventory.get("global")
    global_metadata = raw_global if isinstance(raw_global, dict) else {}
    return _build_document(
        source_kind="legacy_sections",
        source_identifier=source_url,
        captured_at=crawled_at or datetime.now(timezone.utc),
        pages_data=pages_data,
        tokens=tokens,
        initial_assets=assets,
        global_metadata=global_metadata,
        rendered_observations={},
        initial_warnings=initial_warnings,
    )
