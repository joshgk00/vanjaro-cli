"""Real-browser tests for the capture settle step (RT-35).

A native lazy image far down a tall page must be in the settled page. Playwright
and Chromium are optional here: each test skips when no browser can launch.
"""

from __future__ import annotations

import base64
import http.server
import socketserver
import sys
import threading
import time
from collections.abc import Iterator

import pytest

from vanjaro_cli.migration.visual import render_page_html

_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_SLOW_SECONDS = 1.5
_HANG_RELEASE_SECONDS = 30
_PAGE_PATH = "/page.html"


class _Handler(http.server.BaseHTTPRequestHandler):
    """Serves the page under test and one-pixel PNGs named ``<behaviour>-<n>.png``."""

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        if self.path == _PAGE_PATH:
            self._send("text/html", self.server.html.encode())
            return
        behaviour = self.path.lstrip("/").split("-", 1)[0]
        if behaviour == "slow":
            self.server.release.wait(_SLOW_SECONDS)
        elif behaviour == "hang":
            self.server.release.wait(_HANG_RELEASE_SECONDS)
        elif behaviour == "missing":
            self.send_error(404)
            return
        self._send("image/png", _PIXEL)

    def _send(self, content_type: str, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass  # the page closed while a deliberately slow response was pending

    def log_message(self, *args: object) -> None:
        pass


class _Site(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.release = threading.Event()
        self.html = ""

    @property
    def page_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}{_PAGE_PATH}"


@pytest.fixture
def site() -> Iterator[_Site]:
    server = _Site()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        server.release.set()
        server.shutdown()
        server.server_close()


def _playwright_modules() -> set[str]:
    return {name for name in sys.modules if name == "playwright" or name.startswith("playwright.")}


@pytest.fixture
def page() -> Iterator[object]:
    # test_project_capture_cmd asserts a dry run never imports playwright, so
    # this fixture hands sys.modules back as it found it.
    already_imported = _playwright_modules()
    try:
        sync_api = pytest.importorskip("playwright.sync_api")
        with sync_api.sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch()
            except sync_api.Error as error:
                pytest.skip(f"no browser available: {error}")
            try:
                yield browser.new_page(viewport={"width": 1440, "height": 900})
            finally:
                browser.close()
    finally:
        for name in _playwright_modules() - already_imported:
            del sys.modules[name]


def _tall_page(sources: list[str], gap: int = 3000) -> str:
    """One lazy image per two-and-a-half screens, each with a reserved size."""
    body = "".join(
        f'<div style="height:{gap}px"></div>'
        f'<img loading="lazy" src="{source}" style="display:block;width:100px;height:100px">'
        for source in sources
    )
    return f"<html><body style='margin:0'>{body}</body></html>"


def _loaded_widths(page: object) -> list[int]:
    return page.evaluate("[...document.images].map(image => image.naturalWidth)")


def test_render_waits_for_slow_lazy_images_far_below_the_fold(page, site) -> None:
    site.html = _tall_page([f"slow-{n}.png" for n in range(8)])

    render_page_html(page, site.page_url, timeout_seconds=30)

    assert _loaded_widths(page) == [1] * 8


def test_render_loads_lazy_images_in_a_sideways_scroller(page, site) -> None:
    track = "".join(
        f'<img loading="lazy" src="ok-{n}.png" style="flex:none;width:300px;height:100px">'
        for n in range(12)
    )
    site.html = (
        "<html><body style='margin:0'>"
        f"<div style='display:flex;overflow-x:auto;width:600px'>{track}</div>"
        "<div style='height:3000px'></div></body></html>"
    )

    render_page_html(page, site.page_url, timeout_seconds=30)

    assert _loaded_widths(page) == [1] * 12


def test_render_returns_when_an_image_never_answers(page, site) -> None:
    site.html = _tall_page(["ok-0.png", "hang-1.png", "ok-2.png"])

    started = time.monotonic()
    render_page_html(page, site.page_url, timeout_seconds=2)
    elapsed = time.monotonic() - started

    assert elapsed < _HANG_RELEASE_SECONDS / 2
    assert _loaded_widths(page) == [1, 0, 1]


def test_render_survives_a_broken_image_and_loads_the_rest(page, site) -> None:
    site.html = _tall_page(["ok-0.png", "missing-1.png", "ok-2.png"])

    render_page_html(page, site.page_url, timeout_seconds=30)

    assert _loaded_widths(page) == [1, 0, 1]


def test_render_keeps_the_authored_loading_attribute_in_the_returned_html(page, site) -> None:
    site.html = _tall_page([f"ok-{n}.png" for n in range(4)])

    html = render_page_html(page, site.page_url, timeout_seconds=30)

    assert html.count('loading="lazy"') == 4
    assert 'loading="eager"' not in html
    assert page.evaluate("window.scrollY") == 0
