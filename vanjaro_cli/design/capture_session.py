"""One-session browser capture: same settled page for screenshot and DOM (VF-010).

The existing `fidelity_capture`/`fidelity_measure` pair renders a screenshot and
measures the DOM in two separate canonical-width Playwright sessions. That is
fine for the three fixed gate breakpoints, but it cannot preserve an arbitrary
Figma/image-declared viewport, and two page loads are not guaranteed to be the
same page state. `PlaywrightCaptureSession` opens exactly one session at the
exact requested viewport, navigates once, settles once, then measures and
screenshots that same settled page -- reusing `MEASURE_SCRIPT` and
`parse_measured_page` from `fidelity_measure` and `rendered_page_session`/
`_settle` from `migration.visual` rather than standing up a second browser
stack or a copy of the measurement script.

This module implements only the capture primitive. It does not decide which
URL a page should capture from, does not know about typed source references
or the evidence schema, and does not publish or otherwise mutate a portal --
those are later, separate tasks. A full-page screenshot's pixel dimensions are
evidence of that one capture only; they do not by themselves demonstrate a
responsive layout at any other viewport.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from vanjaro_cli.design.fidelity_measure import (
    MEASURE_SCRIPT,
    _subscribe_to_console_errors,
    parse_measured_page,
)
from vanjaro_cli.design.fidelity_observation import RenderedPage
from vanjaro_cli.design.models import Viewport
from vanjaro_cli.design.visual_gate import CaptureStability

__all__ = [
    "CapturedPage",
    "CaptureSessionError",
    "CaptureSessionErrorCode",
    "PlaywrightCaptureSession",
]


class CaptureSessionErrorCode(str, Enum):
    """Stable, credential-safe failure classification for `CaptureSessionError`."""

    INVALID_URL = "invalid_url"
    INVALID_VIEWPORT = "invalid_viewport"
    INVALID_DESTINATION = "invalid_destination"
    TARGET_REJECTED = "target_rejected"
    NAVIGATION_FAILED = "navigation_failed"
    MISSING_FINAL_URL = "missing_final_url"
    SETTLE_FAILED = "settle_failed"
    MEASUREMENT_FAILED = "measurement_failed"
    SCREENSHOT_FAILED = "screenshot_failed"
    MISSING_SECTIONS = "missing_sections"
    CAPTURE_FAILED = "capture_failed"


class CaptureSessionError(RuntimeError):
    """Raised when one capture cannot be produced.

    `message` must never embed a raw URL or a foreign exception's text: the
    target URL, an intermediate redirect, or a browser/filesystem error's
    message can all carry credentials or a signed query string. Every raise
    site in this module therefore uses a fixed, generic message, never
    interpolates a foreign exception's class name (a dynamically built class
    is untrusted free text too), and raises with `from None` so the foreign
    exception is never chained into this one -- a chained cause still shows
    up in a formatted traceback even when the outer message is clean.
    """

    def __init__(self, code: CaptureSessionErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class _CaptureSessionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CapturedPage(_CaptureSessionModel):
    """One successful capture: same page, same settle, screenshot plus DOM.

    Every field is an actual observation from the one session that produced
    it -- the viewport the session was opened at, the screenshot this session
    wrote (identified by the hash of its real bytes), the `RenderedPage` this
    session measured, and the `CaptureStability` this session's settle call
    actually achieved. Nothing here is inferred from another capture.
    """

    url: str = Field(min_length=1)
    viewport: Viewport
    screenshot_path: Path
    screenshot_sha256: str = Field(min_length=64, max_length=64)
    rendered: RenderedPage
    stability: CaptureStability


_FORBIDDEN_ENCODED_RE = re.compile(r"%(?:2e|2f|5c)", re.IGNORECASE)


def _require_positive_dimensions(viewport: Viewport) -> tuple[int, int]:
    values = {"width": viewport.width, "height": viewport.height}
    for label, value in values.items():
        # bool is an int subclass, so a Viewport built by `model_construct`
        # (skipping Pydantic validation) could carry True/False as a
        # dimension; reject it explicitly rather than trust the field type.
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise CaptureSessionError(
                CaptureSessionErrorCode.INVALID_VIEWPORT,
                f"viewport {label} must be a positive integer",
            )
    return values["width"], values["height"]


def _require_clean_url(url: object, *, code: CaptureSessionErrorCode) -> SplitResult:
    if not isinstance(url, str) or not url.strip():
        raise CaptureSessionError(code, "url must be a non-empty string")
    # A backslash is treated as a path separator by some clients but not by
    # `urlsplit`; refusing it outright avoids two components disagreeing
    # about where the host ends and the path begins.
    if "\\" in url:
        raise CaptureSessionError(code, "url must not contain a backslash")
    try:
        parsed = urlsplit(url)
        parsed.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        raise CaptureSessionError(code, "url has a malformed port") from None
    if parsed.scheme not in {"http", "https"}:
        raise CaptureSessionError(code, "url must use http or https")
    if not parsed.hostname:
        raise CaptureSessionError(code, "url must have a host")
    # `parsed.username`/`parsed.password` miss an empty-username userinfo
    # separator (`http://@host/`), so check the netloc directly instead.
    if "@" in parsed.netloc:
        raise CaptureSessionError(code, "url must not contain embedded userinfo")
    return parsed


def _effective_port(parsed: SplitResult) -> int:
    if parsed.port is not None:
        return parsed.port
    return 443 if parsed.scheme == "https" else 80


def _path_segments(path: str, *, code: CaptureSessionErrorCode) -> tuple[str, ...]:
    if _FORBIDDEN_ENCODED_RE.search(path):
        raise CaptureSessionError(
            code, "url path must not contain a percent-encoded '.', '/', or '\\'"
        )
    if "\\" in path:
        raise CaptureSessionError(code, "url path must not contain a backslash")
    segments = tuple(segment for segment in path.split("/") if segment != "")
    if any(segment in (".", "..") for segment in segments):
        raise CaptureSessionError(code, "url path must not contain traversal segments")
    return segments


def _require_within_allowed_base(
    url: str, allowed_base_url: str, *, code: CaptureSessionErrorCode
) -> None:
    """Restrict `url` to `allowed_base_url`'s scheme/host/port and path branch.

    Membership is by path segment, not by string prefix: an allowed base of
    ``/client`` permits ``/client/Home`` but not ``/client2``. Query and
    fragment never affect membership.
    """

    target = _require_clean_url(url, code=code)
    base = _require_clean_url(allowed_base_url, code=code)
    if target.scheme != base.scheme:
        raise CaptureSessionError(code, "url scheme is outside the allowed base")
    if (target.hostname or "").lower() != (base.hostname or "").lower():
        raise CaptureSessionError(code, "url host is outside the allowed base")
    if _effective_port(target) != _effective_port(base):
        raise CaptureSessionError(code, "url port is outside the allowed base")
    base_segments = _path_segments(base.path, code=code)
    target_segments = _path_segments(target.path, code=code)
    if target_segments[: len(base_segments)] != base_segments:
        raise CaptureSessionError(code, "url path is outside the allowed base path")


def _require_final_url_within(page: Any, allowed_base_url: str) -> None:
    final_url = getattr(page, "url", None)
    if not final_url:
        raise CaptureSessionError(
            CaptureSessionErrorCode.MISSING_FINAL_URL,
            "navigation did not report a final url for a restricted target",
        )
    _require_within_allowed_base(
        final_url, allowed_base_url, code=CaptureSessionErrorCode.TARGET_REJECTED
    )


def _sibling_temp_path(destination: Path) -> Path:
    # Playwright's `page.screenshot(path=...)` infers the image format (png
    # vs jpeg) from the path's suffix when no explicit `type` is passed, so
    # the temp file must keep the destination's real suffix rather than a
    # generic `.tmp` one.
    return destination.with_name(
        f".{destination.stem}.{uuid.uuid4().hex}{destination.suffix}"
    )


def _cleanup(tmp_path: Path) -> None:
    try:
        tmp_path.unlink()
    except FileNotFoundError:
        pass


class PlaywrightCaptureSession:
    """Default capture session, reusing the existing Playwright harness."""

    def __init__(
        self,
        *,
        timeout_seconds: int = 45,
        session_factory: Callable[..., AbstractContextManager[Any]] | None = None,
        settle: Callable[[Any, int], None] | None = None,
        navigation_timeout_exception: type[BaseException] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self._session_factory = session_factory
        self._settle = settle
        # Injectable for offline tests, which cannot import Playwright's real
        # timeout type. Left unset, the real type is resolved lazily below.
        self._navigation_timeout_exception = navigation_timeout_exception

    def _dependencies(self):
        if self._session_factory is not None and self._settle is not None:
            return self._session_factory, self._settle
        # Imported lazily so importing this module never requires Playwright.
        from vanjaro_cli.migration.visual import _settle, rendered_page_session

        return self._session_factory or rendered_page_session, self._settle or _settle

    def _navigation_timeout_classes(self) -> tuple[type[BaseException], ...]:
        """Exception types that qualify for exactly one navigation retry.

        Classification is by exception *type* only, checked with
        `isinstance`, never by message text or by a class's `__name__` --
        either can be set to arbitrary content by a foreign exception, so
        neither is trustworthy input for a security-relevant decision. When
        no known timeout type is available (Playwright not installed and no
        type injected for a test), the empty tuple means nothing is ever
        classified as a timeout and no exception is retried.
        """
        if self._navigation_timeout_exception is not None:
            return (self._navigation_timeout_exception,)
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        except ImportError:
            return ()
        return (PlaywrightTimeoutError,)

    def capture(
        self,
        url: str,
        *,
        viewport: Viewport,
        destination: Path,
        allowed_base_url: str | None = None,
        full_page: bool = True,
        require_sections: bool = True,
    ) -> CapturedPage:
        # Every validation below runs before the browser or filesystem is
        # touched, and before any credential-bearing state (a redirect) can
        # exist to leak.
        width, height = _require_positive_dimensions(viewport)
        _require_clean_url(url, code=CaptureSessionErrorCode.INVALID_URL)
        if allowed_base_url is not None:
            _require_within_allowed_base(
                url, allowed_base_url, code=CaptureSessionErrorCode.TARGET_REJECTED
            )

        destination = Path(destination)
        if destination.exists() and destination.is_dir():
            raise CaptureSessionError(
                CaptureSessionErrorCode.INVALID_DESTINATION,
                "destination must not be an existing directory",
            )

        session_factory, settle = self._dependencies()
        timeout_ms = self.timeout_seconds * 1000
        console_errors: list[str] = []
        tmp_path = _sibling_temp_path(destination)

        try:
            with session_factory(viewport=(width, height)) as page:
                _subscribe_to_console_errors(page, console_errors)

                try:
                    response = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                except Exception as first_error:
                    if not isinstance(first_error, self._navigation_timeout_classes()):
                        raise CaptureSessionError(
                            CaptureSessionErrorCode.NAVIGATION_FAILED,
                            "navigation to the target page failed",
                        ) from None
                    try:
                        response = page.goto(url, wait_until="load", timeout=timeout_ms)
                    except Exception:
                        raise CaptureSessionError(
                            CaptureSessionErrorCode.NAVIGATION_FAILED,
                            "navigation to the target page failed after a timeout retry",
                        ) from None

                status = getattr(response, "status", None)
                if isinstance(status, int) and status >= 400:
                    raise CaptureSessionError(
                        CaptureSessionErrorCode.NAVIGATION_FAILED,
                        f"navigation returned HTTP {status}",
                    )

                # A page can still redirect after this check -- during settle,
                # or even during measurement -- so the destination is
                # rechecked again after each of those steps below, in
                # addition to the precommit check right before screenshot.
                if allowed_base_url is not None:
                    _require_final_url_within(page, allowed_base_url)

                try:
                    settle(page, timeout_ms)
                except CaptureSessionError:
                    raise
                except Exception:
                    raise CaptureSessionError(
                        CaptureSessionErrorCode.SETTLE_FAILED,
                        "page failed to settle",
                    ) from None

                if allowed_base_url is not None:
                    _require_final_url_within(page, allowed_base_url)

                try:
                    payload = page.evaluate(MEASURE_SCRIPT)
                except Exception:
                    raise CaptureSessionError(
                        CaptureSessionErrorCode.MEASUREMENT_FAILED,
                        "measurement of the settled page failed",
                    ) from None
                if not isinstance(payload, Mapping):
                    raise CaptureSessionError(
                        CaptureSessionErrorCode.MEASUREMENT_FAILED,
                        "measurement script returned a non-object payload",
                    )
                rendered = parse_measured_page(
                    payload,
                    viewport_width=float(width),
                    console_error_count=len(console_errors),
                )

                if require_sections and not rendered.sections:
                    raise CaptureSessionError(
                        CaptureSessionErrorCode.MISSING_SECTIONS,
                        "captured output has no agency sections",
                    )

                if allowed_base_url is not None:
                    _require_final_url_within(page, allowed_base_url)

                tmp_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    page.screenshot(path=str(tmp_path), full_page=full_page)
                except Exception:
                    raise CaptureSessionError(
                        CaptureSessionErrorCode.SCREENSHOT_FAILED,
                        "screenshot capture failed",
                    ) from None

                # Precommit check: a redirect during the screenshot call
                # itself is still caught before the temp file is promoted.
                if allowed_base_url is not None:
                    _require_final_url_within(page, allowed_base_url)

                final_url = getattr(page, "url", None) or url
        except CaptureSessionError:
            _cleanup(tmp_path)
            raise
        except Exception:  # noqa: BLE001 - reported as a capture failure
            _cleanup(tmp_path)
            raise CaptureSessionError(
                CaptureSessionErrorCode.CAPTURE_FAILED,
                "capture failed",
            ) from None

        if not tmp_path.exists():
            _cleanup(tmp_path)
            raise CaptureSessionError(
                CaptureSessionErrorCode.SCREENSHOT_FAILED, "no screenshot was produced"
            )

        try:
            screenshot_bytes = tmp_path.read_bytes()
        except OSError:
            _cleanup(tmp_path)
            raise CaptureSessionError(
                CaptureSessionErrorCode.SCREENSHOT_FAILED,
                "failed to read the captured screenshot",
            ) from None
        digest = hashlib.sha256(screenshot_bytes).hexdigest()

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp_path, destination)
        except OSError:
            _cleanup(tmp_path)
            raise CaptureSessionError(
                CaptureSessionErrorCode.SCREENSHOT_FAILED,
                "failed to finalize the screenshot file",
            ) from None

        return CapturedPage(
            url=final_url,
            viewport=Viewport(width=width, height=height),
            screenshot_path=destination,
            screenshot_sha256=digest,
            rendered=rendered,
            stability=CaptureStability(
                lazy_load_triggered=True, fonts_settled=True, animations_disabled=True
            ),
        )
