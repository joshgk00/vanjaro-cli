"""One-session capture: same settled fake page for screenshot and DOM."""

from __future__ import annotations

import ast
import hashlib
import inspect
import traceback
from contextlib import contextmanager
from pathlib import Path

import pytest

from vanjaro_cli.design.capture_session import (
    CapturedPage,
    CaptureSessionError,
    CaptureSessionErrorCode,
    PlaywrightCaptureSession,
)
from vanjaro_cli.design.models import Viewport


def _payload(section_id: str | None = "home.s1", **overrides) -> dict:
    sections = []
    if section_id is not None:
        section = {
            "section_id": section_id,
            "order": 0,
            "bounds": {"x": 0, "y": 0, "width": 1280, "height": 400},
            "columns": 1,
            "background_color": "rgb(255, 255, 255)",
            "text_color": "rgb(0, 0, 0)",
            "accent_color": None,
            "typography": {},
            "padding_top": 0,
            "padding_bottom": 0,
            "element_gap": None,
            "horizontal_overflow_px": 0,
            "media": [],
            "text_samples": ["Hello"],
        }
        section.update(overrides)
        sections.append(section)
    return {"console_error_count": None, "sections": sections}


class _FakeResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status


class _FakePage:
    def __init__(
        self,
        payload: dict | None = None,
        *,
        status: int = 200,
        fail_networkidle: bool = False,
        fail_goto: bool = False,
        fail_evaluate: bool = False,
        fail_screenshot: bool = False,
        report_final_url: bool = True,
        preset_url: str | None = None,
        redirect_after_evaluate_to: str | None = None,
    ) -> None:
        self.payload = payload if payload is not None else _payload()
        self.status = status
        self.fail_networkidle = fail_networkidle
        self.fail_goto = fail_goto
        self.fail_evaluate = fail_evaluate
        self.fail_screenshot = fail_screenshot
        self.report_final_url = report_final_url
        self.url = preset_url
        self.redirect_after_evaluate_to = redirect_after_evaluate_to
        self.goto_waits: list[str] = []
        self.calls: list[str] = []
        self.viewport: tuple[int, int] | None = None
        self.screenshot_calls: list[dict] = []
        self.console_handlers: dict[str, object] = {}

    def on(self, event: str, handler) -> None:
        self.console_handlers[event] = handler

    def goto(self, url: str, *, wait_until: str, timeout: int):
        self.goto_waits.append(wait_until)
        if self.fail_goto:
            raise RuntimeError("net::ERR_CONNECTION_REFUSED")
        if wait_until == "networkidle" and self.fail_networkidle:
            raise TimeoutError("networkidle never reached")
        self.calls.append("goto")
        if self.report_final_url and self.url is None:
            self.url = url
        return _FakeResponse(self.status)

    def evaluate(self, script: str):
        if self.fail_evaluate:
            raise RuntimeError("execution context destroyed")
        self.calls.append("evaluate")
        if self.redirect_after_evaluate_to is not None:
            self.url = self.redirect_after_evaluate_to
        return self.payload

    def screenshot(self, *, path: str, full_page: bool) -> None:
        if self.fail_screenshot:
            raise RuntimeError("target closed")
        self.calls.append("screenshot")
        self.screenshot_calls.append({"path": path, "full_page": full_page})
        Path(path).write_bytes(b"fake-png-bytes-" + str(len(self.calls)).encode())


def _session(
    page: _FakePage,
    *,
    settle_error: Exception | None = None,
    redirect_to: str | None = None,
    navigation_timeout_exception: type[BaseException] | None = TimeoutError,
):
    opens: list[tuple[int, int]] = []

    @contextmanager
    def factory(*, viewport):
        opens.append(viewport)
        page.viewport = viewport
        yield page

    def settle(target: _FakePage, timeout_ms: int) -> None:
        if settle_error is not None:
            raise settle_error
        target.calls.append("settle")
        if redirect_to is not None:
            target.url = redirect_to

    session = PlaywrightCaptureSession(
        session_factory=factory,
        settle=settle,
        navigation_timeout_exception=navigation_timeout_exception,
    )
    return session, opens


def _destination(tmp_path: Path) -> Path:
    return tmp_path / "shots" / "home-1280.png"


class TestExactViewport:
    @pytest.mark.parametrize("width,height", [(1280, 800), (375, 812)])
    def test_opens_one_session_at_the_exact_requested_viewport(
        self, tmp_path: Path, width: int, height: int
    ) -> None:
        page = _FakePage()
        session, opens = _session(page)

        result = session.capture(
            "https://build.example/home",
            viewport=Viewport(width=width, height=height),
            destination=_destination(tmp_path),
        )

        assert opens == [(width, height)]
        assert result.viewport.width == width
        assert result.viewport.height == height

    def test_only_one_session_is_ever_opened(self, tmp_path: Path) -> None:
        page = _FakePage()
        session, opens = _session(page)

        session.capture(
            "https://build.example/home",
            viewport=Viewport(width=1280, height=800),
            destination=_destination(tmp_path),
        )

        assert len(opens) == 1


class TestSameSettledPage:
    def test_navigate_settle_measure_screenshot_happen_in_order_on_one_page(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage()
        session, _ = _session(page)

        session.capture(
            "https://build.example/home",
            viewport=Viewport(width=1280, height=800),
            destination=_destination(tmp_path),
        )

        assert page.calls == ["goto", "settle", "evaluate", "screenshot"]

    def test_networkidle_timeout_falls_back_to_load(self, tmp_path: Path) -> None:
        page = _FakePage(fail_networkidle=True)
        session, _ = _session(page)

        session.capture(
            "https://build.example/home",
            viewport=Viewport(width=1280, height=800),
            destination=_destination(tmp_path),
        )

        assert page.goto_waits == ["networkidle", "load"]


class TestAllowedBaseUrlContainment:
    def test_a_child_path_under_the_allowed_base_is_permitted(self, tmp_path: Path) -> None:
        page = _FakePage(preset_url="https://portal.example/client/Home")
        session, _ = _session(page)

        result = session.capture(
            "https://portal.example/client/Home",
            viewport=Viewport(width=1280, height=800),
            destination=_destination(tmp_path),
            allowed_base_url="https://portal.example/client",
        )

        assert result.url == "https://portal.example/client/Home"

    @pytest.mark.parametrize(
        "bad_url",
        [
            "https://portal.example/client2",  # sibling path, not a child
            "https://evil.example/client/Home",  # different host
            "http://portal.example/client/Home",  # different scheme
            "https://portal.example:8443/client/Home",  # different effective port
            "https://portal.example/client%2e%2e/secret",  # encoded traversal
            "https://portal.example/client/../secret",  # literal traversal
        ],
    )
    def test_initial_url_outside_the_allowed_base_is_rejected(
        self, tmp_path: Path, bad_url: str
    ) -> None:
        page = _FakePage()
        session, opens = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                bad_url,
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
                allowed_base_url="https://portal.example/client",
            )

        assert excinfo.value.code == CaptureSessionErrorCode.TARGET_REJECTED
        # Rejected before any browser session is opened.
        assert opens == []

    def test_a_redirect_outside_the_allowed_base_is_refused_before_dom_or_screenshot(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage(preset_url="https://evil.example/stolen")
        session, _ = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://portal.example/client/Home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
                allowed_base_url="https://portal.example/client",
            )

        assert excinfo.value.code == CaptureSessionErrorCode.TARGET_REJECTED
        assert "evaluate" not in page.calls
        assert "screenshot" not in page.calls

    def test_a_redirect_that_happens_during_settle_is_caught_before_commit(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage(preset_url="https://portal.example/client/Home")
        session, _ = _session(page, redirect_to="https://evil.example/late-redirect")
        destination = _destination(tmp_path)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://portal.example/client/Home",
                viewport=Viewport(width=1280, height=800),
                destination=destination,
                allowed_base_url="https://portal.example/client",
            )

        assert excinfo.value.code == CaptureSessionErrorCode.TARGET_REJECTED
        assert not destination.exists()

    def test_a_redirect_discovered_only_after_measurement_is_refused_before_screenshot(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage(
            preset_url="https://portal.example/client/Home",
            redirect_after_evaluate_to="https://evil.example/late-redirect",
        )
        session, _ = _session(page)
        destination = _destination(tmp_path)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://portal.example/client/Home",
                viewport=Viewport(width=1280, height=800),
                destination=destination,
                allowed_base_url="https://portal.example/client",
            )

        assert excinfo.value.code == CaptureSessionErrorCode.TARGET_REJECTED
        assert "screenshot" not in page.calls
        assert not destination.exists()
        # The redirect is caught before the temp file's directory is even
        # created, since that happens right before the screenshot call.
        assert not destination.parent.exists()

    def test_missing_final_url_is_refused_for_a_restricted_target(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage(report_final_url=False)
        session, _ = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://portal.example/client/Home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
                allowed_base_url="https://portal.example/client",
            )

        assert excinfo.value.code == CaptureSessionErrorCode.MISSING_FINAL_URL

    def test_no_restriction_is_applied_when_allowed_base_url_is_none(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage(preset_url="https://anywhere.example/whatever")
        session, _ = _session(page)

        result = session.capture(
            "https://build.example/home",
            viewport=Viewport(width=1280, height=800),
            destination=_destination(tmp_path),
        )

        assert result.url == "https://anywhere.example/whatever"


class TestInitialUrlValidation:
    @pytest.mark.parametrize(
        "bad_url",
        [
            "ftp://build.example/home",
            "not-a-url",
            "https://user:pass@build.example/home",
            "https://build.example:notaport/home",
            "https://build.example/ho\\me",
        ],
    )
    def test_a_malformed_or_unsafe_url_is_rejected_before_any_browser_session(
        self, tmp_path: Path, bad_url: str
    ) -> None:
        page = _FakePage()
        session, opens = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                bad_url,
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
            )

        assert excinfo.value.code == CaptureSessionErrorCode.INVALID_URL
        assert opens == []


class TestViewportValidation:
    def test_a_bool_dimension_from_an_unsafely_constructed_viewport_is_rejected(
        self, tmp_path: Path
    ) -> None:
        unsafe_viewport = Viewport.model_construct(width=True, height=800)
        page = _FakePage()
        session, opens = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://build.example/home",
                viewport=unsafe_viewport,
                destination=_destination(tmp_path),
            )

        assert excinfo.value.code == CaptureSessionErrorCode.INVALID_VIEWPORT
        assert opens == []

    def test_a_negative_dimension_from_an_unsafely_constructed_viewport_is_rejected(
        self, tmp_path: Path
    ) -> None:
        unsafe_viewport = Viewport.model_construct(width=1280, height=-1)
        page = _FakePage()
        session, opens = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://build.example/home",
                viewport=unsafe_viewport,
                destination=_destination(tmp_path),
            )

        assert excinfo.value.code == CaptureSessionErrorCode.INVALID_VIEWPORT
        assert opens == []


class TestHttpFailure:
    def test_an_http_error_status_fails_navigation_without_screenshotting(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage(status=500)
        session, _ = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
            )

        assert excinfo.value.code == CaptureSessionErrorCode.NAVIGATION_FAILED
        assert "screenshot" not in page.calls


class TestSectionRequirement:
    def test_an_output_with_no_agency_sections_is_rejected_by_default(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage(payload=_payload(section_id=None))
        session, _ = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
            )

        assert excinfo.value.code == CaptureSessionErrorCode.MISSING_SECTIONS

    def test_a_source_only_capture_may_opt_out_of_the_section_requirement(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage(payload=_payload(section_id=None))
        session, _ = _session(page)

        result = session.capture(
            "https://design.example/home",
            viewport=Viewport(width=1280, height=800),
            destination=_destination(tmp_path),
            require_sections=False,
        )

        assert result.rendered.sections == ()


class TestFailureModes:
    def test_a_settle_failure_yields_no_capture(self, tmp_path: Path) -> None:
        page = _FakePage()
        session, _ = _session(page, settle_error=RuntimeError("page crashed"))

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
            )

        assert excinfo.value.code == CaptureSessionErrorCode.SETTLE_FAILED
        assert "evaluate" not in page.calls
        assert "screenshot" not in page.calls

    def test_a_measurement_failure_yields_no_capture(self, tmp_path: Path) -> None:
        page = _FakePage(fail_evaluate=True)
        session, _ = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
            )

        assert excinfo.value.code == CaptureSessionErrorCode.MEASUREMENT_FAILED
        assert "screenshot" not in page.calls

    def test_a_non_object_measurement_payload_is_a_measurement_failure(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage(payload="not-a-mapping")
        session, _ = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
            )

        assert excinfo.value.code == CaptureSessionErrorCode.MEASUREMENT_FAILED

    def test_a_screenshot_failure_yields_no_capture(self, tmp_path: Path) -> None:
        page = _FakePage(fail_screenshot=True)
        session, _ = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
            )

        assert excinfo.value.code == CaptureSessionErrorCode.SCREENSHOT_FAILED

    def test_a_non_timeout_navigation_failure_is_not_retried(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage(fail_goto=True)
        session, _ = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
            )

        assert excinfo.value.code == CaptureSessionErrorCode.NAVIGATION_FAILED
        # A non-timeout exception (e.g. connection refused) must fail on the
        # first attempt only -- retrying it would double the real-world cost
        # of a genuinely broken target for no benefit.
        assert page.goto_waits == ["networkidle"]

    def test_a_navigation_failure_on_both_attempts_of_a_genuine_timeout_yields_no_capture(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage(fail_networkidle=True, fail_goto=False)

        def flaky_goto(url: str, *, wait_until: str, timeout: int):
            page.goto_waits.append(wait_until)
            raise TimeoutError("still not settled")

        page.goto = flaky_goto  # type: ignore[method-assign]
        session, _ = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
            )

        assert excinfo.value.code == CaptureSessionErrorCode.NAVIGATION_FAILED
        assert page.goto_waits == ["networkidle", "load"]

    def test_an_exception_merely_named_timeouterror_is_not_classified_as_a_timeout(
        self, tmp_path: Path
    ) -> None:
        # A class whose __name__ happens to be "TimeoutError" but is not the
        # type actually configured as the timeout class must not be treated
        # as a timeout -- classification is by type identity, not by name.
        imposter_timeout_error = type("TimeoutError", (RuntimeError,), {})
        page = _FakePage()

        def flaky_goto(url: str, *, wait_until: str, timeout: int):
            page.goto_waits.append(wait_until)
            raise imposter_timeout_error("networkidle never reached")

        page.goto = flaky_goto  # type: ignore[method-assign]
        session, _ = _session(page)  # configured timeout class is builtin TimeoutError

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
            )

        assert excinfo.value.code == CaptureSessionErrorCode.NAVIGATION_FAILED
        assert page.goto_waits == ["networkidle"]

    def test_a_timeout_type_with_an_unrelated_name_is_still_retried(
        self, tmp_path: Path
    ) -> None:
        # The inverse case: a type that does NOT look like a timeout by name
        # but IS the configured timeout class must still be retried.
        class _SlowConnectionSignal(Exception):
            pass

        page = _FakePage()

        def flaky_goto(url: str, *, wait_until: str, timeout: int):
            page.goto_waits.append(wait_until)
            if wait_until == "networkidle":
                raise _SlowConnectionSignal("network too slow")
            page.calls.append("goto")
            if page.report_final_url and page.url is None:
                page.url = url
            return _FakeResponse(page.status)

        page.goto = flaky_goto  # type: ignore[method-assign]
        session, _ = _session(page, navigation_timeout_exception=_SlowConnectionSignal)

        session.capture(
            "https://build.example/home",
            viewport=Viewport(width=1280, height=800),
            destination=_destination(tmp_path),
        )

        assert page.goto_waits == ["networkidle", "load"]

    @pytest.mark.parametrize(
        "page_kwargs,settle_error",
        [
            ({"fail_goto": True}, None),
            ({}, RuntimeError("page crashed")),
            ({"fail_evaluate": True}, None),
            ({"fail_screenshot": True}, None),
        ],
        ids=["navigation", "settle", "measurement", "screenshot"],
    )
    def test_no_leftover_temp_artifact_after_any_capture_failure(
        self, tmp_path: Path, page_kwargs: dict, settle_error: Exception | None
    ) -> None:
        page = _FakePage(**page_kwargs)
        session, _ = _session(page, settle_error=settle_error)
        destination = _destination(tmp_path)

        with pytest.raises(CaptureSessionError):
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=destination,
            )

        remaining = list(destination.parent.iterdir()) if destination.parent.exists() else []
        assert remaining == []


class TestScreenshotHashing:
    def test_the_hash_is_computed_from_the_actual_written_screenshot_bytes(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage()
        session, _ = _session(page)
        destination = _destination(tmp_path)

        result = session.capture(
            "https://build.example/home",
            viewport=Viewport(width=1280, height=800),
            destination=destination,
        )

        assert result.screenshot_path == destination
        assert result.screenshot_sha256 == hashlib.sha256(destination.read_bytes()).hexdigest()

    def test_no_leftover_temporary_file_remains_after_a_successful_capture(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage()
        session, _ = _session(page)
        destination = _destination(tmp_path)

        session.capture(
            "https://build.example/home",
            viewport=Viewport(width=1280, height=800),
            destination=destination,
        )

        remaining = list(destination.parent.iterdir())
        assert remaining == [destination]


class TestDestinationPreservedOnFailure:
    def test_a_failure_before_screenshot_leaves_preexisting_destination_bytes_untouched(
        self, tmp_path: Path
    ) -> None:
        destination = _destination(tmp_path)
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"old-evidence")
        page = _FakePage()
        session, _ = _session(page, settle_error=RuntimeError("page crashed"))

        with pytest.raises(CaptureSessionError):
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=destination,
            )

        assert destination.read_bytes() == b"old-evidence"
        remaining = list(destination.parent.iterdir())
        assert remaining == [destination]

    def test_a_screenshot_failure_does_not_delete_the_old_destination(
        self, tmp_path: Path
    ) -> None:
        destination = _destination(tmp_path)
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"old-evidence")
        page = _FakePage(fail_screenshot=True)
        session, _ = _session(page)

        with pytest.raises(CaptureSessionError):
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=destination,
            )

        assert destination.read_bytes() == b"old-evidence"


class TestCredentialSafety:
    def test_rejecting_an_embedded_credential_url_does_not_echo_it(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage()
        session, _ = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://alice:s3cr3t-p4ss@build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
            )

        assert "s3cr3t-p4ss" not in str(excinfo.value)
        assert "alice" not in str(excinfo.value)

    def test_a_redirect_carrying_a_signed_query_string_is_not_echoed(
        self, tmp_path: Path
    ) -> None:
        page = _FakePage(preset_url="https://evil.example/steal?token=TOPSECRET123")
        session, _ = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://portal.example/client/Home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
                allowed_base_url="https://portal.example/client",
            )

        assert "TOPSECRET123" not in str(excinfo.value)
        assert "evil.example" not in str(excinfo.value)

    def test_a_foreign_exception_message_is_not_serialized_verbatim(
        self, tmp_path: Path
    ) -> None:
        class _LeakyError(RuntimeError):
            def __str__(self) -> str:
                return "failed at https://build.example/home?apikey=LEAKED"

        page = _FakePage()
        session, _ = _session(page, settle_error=_LeakyError())

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
            )

        assert "LEAKED" not in str(excinfo.value)

    def test_a_foreign_exception_is_not_chained_into_the_capture_error(
        self, tmp_path: Path
    ) -> None:
        # str(exception) alone can miss a leak: `raise ... from error` chains
        # the original exception as __cause__, and a formatted traceback
        # prints that chain's own message regardless of how clean the outer
        # CaptureSessionError's message is.
        secret = "s3cr3t-chained-token"

        class _LeakyError(RuntimeError):
            def __str__(self) -> str:
                return f"failed at https://build.example/home?apikey={secret}"

        page = _FakePage()
        session, _ = _session(page, settle_error=_LeakyError())

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
            )

        assert excinfo.value.__cause__ is None
        assert excinfo.value.__suppress_context__ is True
        formatted = "".join(
            traceback.format_exception(excinfo.type, excinfo.value, excinfo.tb)
        )
        assert secret not in formatted

    def test_a_screenshot_boundary_exception_is_not_chained_into_the_capture_error(
        self, tmp_path: Path
    ) -> None:
        secret = "s3cr3t-screenshot-token"

        class _LeakyError(RuntimeError):
            def __str__(self) -> str:
                return f"target closed at https://build.example/home?apikey={secret}"

        class _LeakyPage(_FakePage):
            def screenshot(self, *, path: str, full_page: bool) -> None:
                raise _LeakyError()

        page = _LeakyPage()
        session, _ = _session(page)

        with pytest.raises(CaptureSessionError) as excinfo:
            session.capture(
                "https://build.example/home",
                viewport=Viewport(width=1280, height=800),
                destination=_destination(tmp_path),
            )

        assert excinfo.value.__cause__ is None
        formatted = "".join(
            traceback.format_exception(excinfo.type, excinfo.value, excinfo.tb)
        )
        assert secret not in formatted


class TestNoBrowserDependencyAtImport:
    def test_the_module_never_imports_playwright_or_migration_visual_at_top_level(
        self,
    ) -> None:
        from vanjaro_cli.design import capture_session as capture_session_module

        source = inspect.getsource(capture_session_module)
        tree = ast.parse(source)

        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "playwright" not in alias.name
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "playwright" not in module
                assert "migration.visual" not in module
