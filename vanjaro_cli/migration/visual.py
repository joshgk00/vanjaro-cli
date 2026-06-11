"""Screenshot-pair capture for visual migration QA.

Captures full-page screenshots of each source page and its migrated Vanjaro
counterpart, plus a manifest the vision-comparison step consumes. Playwright
is an optional dependency (``pip install vanjaro-cli[visual]``) and is only
imported when a capture actually runs.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

__all__ = [
    "VisualCaptureError",
    "build_capture_plan",
    "parse_viewport",
    "render_page_html",
    "rendered_page_session",
    "run_capture",
]

# Substrings that indicate a server-side failure rendered as a page
ERROR_MARKERS = (
    "an error has occurred",
    "server error in",
    "runtime error",
    "404 - file or directory not found",
)

SETTLE_DISABLE_ANIMATIONS_CSS = (
    "*, *::before, *::after {"
    " animation: none !important;"
    " transition: none !important;"
    " caret-color: transparent !important; }"
)


class VisualCaptureError(Exception):
    pass


# Stamps computed backgrounds onto elements as the same data-migrate-*
# attributes that sections.annotate_section_styles produces from static CSS,
# so the section extractor consumes rendered DOM with no downstream changes.
# Elements the browser doesn't paint (inactive tab panes, hidden slides,
# offcanvas menus) get data-migrate-hidden so extraction can drop them —
# serialized DOM otherwise carries entire hidden datasets onto the page.
COMPUTED_STYLE_STAMP_JS = """() => {
    const candidates = document.querySelectorAll(
        'div, section, article, header, footer, main, aside'
    );
    for (const el of candidates) {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden') {
            el.setAttribute('data-migrate-hidden', '1');
            continue;
        }
        const bg = cs.backgroundColor;
        if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
            el.setAttribute('data-migrate-bg', bg);
            el.setAttribute('data-migrate-color', cs.color);
        }
        const match = (cs.backgroundImage || '').match(/url\\(["']?([^"')]+)["']?\\)/);
        if (match && !match[1].startsWith('data:')) {
            el.setAttribute('data-migrate-bg-image', match[1]);
        }
    }
}"""


def parse_viewport(value: str) -> tuple[int, int]:
    """Parse a ``WIDTHxHEIGHT`` string like ``1280x800``."""
    try:
        width_str, height_str = value.lower().split("x", 1)
        width, height = int(width_str), int(height_str)
    except ValueError:
        raise VisualCaptureError(
            f"Invalid viewport '{value}' — expected WIDTHxHEIGHT, e.g. 1280x800."
        )
    if width <= 0 or height <= 0:
        raise VisualCaptureError(f"Viewport dimensions must be positive: '{value}'.")
    return width, height


def slug_for_path(vanjaro_path: str) -> str:
    """Filesystem-safe slug for a Vanjaro page path (``/`` becomes ``home``)."""
    cleaned = vanjaro_path.strip("/").replace("/", "-").lower()
    return cleaned or "home"


def build_capture_plan(
    page_url_map: dict[str, str],
    vanjaro_base_url: str,
    include_paths: list[str] | None = None,
) -> list[dict]:
    """Build one capture entry per distinct Vanjaro page.

    Multiple source URLs can map to the same Vanjaro path (fragment anchors,
    .html aliases). The first fragment-free source URL wins; fragments are
    kept as ``source_fragment`` so the vision step knows the migrated page
    corresponds to one section of the source page.
    """
    base = vanjaro_base_url.rstrip("/")
    entries: dict[str, dict] = {}

    for source_url, vanjaro_path in page_url_map.items():
        if include_paths and vanjaro_path not in include_paths:
            continue
        bare_url, fragment = urldefrag(source_url)
        entry = entries.get(vanjaro_path)
        if entry is None:
            entries[vanjaro_path] = {
                "slug": slug_for_path(vanjaro_path),
                "source_url": bare_url,
                "source_fragment": fragment,
                "vanjaro_path": vanjaro_path,
                "vanjaro_url": base + "/" + vanjaro_path.lstrip("/"),
            }
        elif entry["source_fragment"] and not fragment:
            # Prefer a fragment-free source URL when one exists
            entry["source_url"] = bare_url
            entry["source_fragment"] = ""

    return list(entries.values())


def _settle(page, timeout_ms: int) -> None:
    """Make the page render-stable: fonts loaded, lazy images in, no motion."""
    page.evaluate("() => document.fonts.ready")
    page.add_style_tag(content=SETTLE_DISABLE_ANIMATIONS_CSS)
    # Walk the page to trigger lazy loading, then return to the top
    page.evaluate(
        """async () => {
            const step = window.innerHeight;
            for (let y = 0; y < document.body.scrollHeight; y += step) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 60));
            }
            window.scrollTo(0, 0);
        }"""
    )
    page.wait_for_timeout(min(500, timeout_ms))


def _capture_one(page, url: str, screenshot_path: Path, timeout_ms: int) -> dict:
    """Navigate, settle, screenshot. Returns status/text metrics and warnings."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    warnings: list[str] = []
    try:
        response = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        warnings.append("networkidle timeout — retried with 'load'")
        response = page.goto(url, wait_until="load", timeout=timeout_ms)

    _settle(page, timeout_ms)
    page.screenshot(path=str(screenshot_path), full_page=True)

    status = response.status if response else 0
    body_text = page.evaluate("() => document.body ? document.body.innerText : ''")
    lowered = body_text.lower()
    for marker in ERROR_MARKERS:
        if marker in lowered:
            warnings.append(f"page text contains error marker: '{marker}'")

    if status >= 400:
        warnings.append(f"HTTP {status}")

    return {
        "status": status,
        "text_length": len(body_text),
        "warnings": warnings,
    }


@contextmanager
def rendered_page_session(viewport: tuple[int, int] = (1280, 800)):
    """Yield a Playwright page for rendered crawling; closes the browser after."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise VisualCaptureError(
            "Playwright is not installed. Run `pip install playwright` then "
            "`python -m playwright install chromium` to enable rendered crawling."
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]}
        )
        try:
            yield context.new_page()
        finally:
            browser.close()


def render_page_html(page, url: str, timeout_seconds: int = 45) -> str:
    """Load ``url`` and return the post-JS DOM with computed styles stamped.

    Captures what a static fetch can't: JS-rendered sections (sliders,
    carousels) and effective backgrounds painted via descendant selectors or
    background images.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    timeout_ms = timeout_seconds * 1000
    try:
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        page.goto(url, wait_until="load", timeout=timeout_ms)
    _settle(page, timeout_ms)
    page.evaluate(COMPUTED_STYLE_STAMP_JS)
    return page.content()


def run_capture(
    plan: list[dict],
    output_dir: Path,
    viewport: tuple[int, int],
    cookies: dict[str, str] | None = None,
    vanjaro_base_url: str = "",
    timeout_seconds: int = 45,
) -> dict:
    """Capture all screenshot pairs in ``plan`` and write a manifest.

    Returns the manifest dict (also written to ``manifest.json`` in
    ``output_dir``).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise VisualCaptureError(
            "Playwright is not installed. Run `pip install playwright` then "
            "`python -m playwright install chromium` to enable visual capture."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    timeout_ms = timeout_seconds * 1000
    pages_report: list[dict] = []
    vanjaro_hashes: dict[str, list[str]] = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]}
        )
        if cookies and vanjaro_base_url:
            context.add_cookies(
                [
                    {"name": name, "value": value, "url": vanjaro_base_url}
                    for name, value in cookies.items()
                ]
            )
        page = context.new_page()

        for entry in plan:
            slug = entry["slug"]
            source_file = output_dir / f"source-{slug}.png"
            vanjaro_file = output_dir / f"vanjaro-{slug}.png"
            report = {**entry}

            try:
                source_result = _capture_one(
                    page, entry["source_url"], source_file, timeout_ms
                )
            except Exception as exc:  # noqa: BLE001 — per-page isolation: one bad page must not kill the run
                source_result = {"status": 0, "text_length": 0, "warnings": [f"capture failed: {exc}"]}
            try:
                vanjaro_result = _capture_one(
                    page, entry["vanjaro_url"], vanjaro_file, timeout_ms
                )
            except Exception as exc:  # noqa: BLE001
                vanjaro_result = {"status": 0, "text_length": 0, "warnings": [f"capture failed: {exc}"]}

            if vanjaro_file.exists():
                digest = hashlib.sha256(vanjaro_file.read_bytes()).hexdigest()
                vanjaro_hashes.setdefault(digest, []).append(slug)

            report.update(
                {
                    "source_screenshot": source_file.name,
                    "vanjaro_screenshot": vanjaro_file.name,
                    "source_status": source_result["status"],
                    "vanjaro_status": vanjaro_result["status"],
                    "source_text_length": source_result["text_length"],
                    "vanjaro_text_length": vanjaro_result["text_length"],
                    "warnings": source_result["warnings"] + vanjaro_result["warnings"],
                }
            )
            pages_report.append(report)

        browser.close()

    global_warnings: list[str] = []
    for digest, slugs in vanjaro_hashes.items():
        if len(slugs) > 1:
            global_warnings.append(
                f"Vanjaro pages render identically ({', '.join(slugs)}) — "
                "possible blank or error pages."
            )

    manifest = {
        "viewport": f"{viewport[0]}x{viewport[1]}",
        "vanjaro_base_url": vanjaro_base_url,
        "pages": pages_report,
        "warnings": global_warnings,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
