"""Offline safety and failure-path tests for the live-portal harness."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from pydantic import JsonValue

from vanjaro_cli.design.live_benchmark import (
    AnonymousPage,
    AnonymousRenderError,
    AnonymousRenderPolicy,
    LiveBenchmarkCleanupError,
    LiveBenchmarkError,
    LiveBenchmarkPayload,
    LivePageTarget,
    run_live_benchmark,
    verify_anonymous_render,
)


GOOD_HTML = """<!doctype html><html><body>
<header data-testid="agency-header">Agency Header</header>
<main><h1>Migration benchmark completed successfully</h1><p>Editable content is visible.</p></main>
<footer data-testid="agency-footer">Agency Footer</footer>
</body></html>"""


class FakeBackend:
    def __init__(
        self,
        *,
        anonymous_page: AnonymousPage | None = None,
        fail_stage: str | None = None,
        isolated: bool = True,
    ) -> None:
        self.anonymous_page = anonymous_page or AnonymousPage(
            url="https://portal.local/vanjaro-benchmark-test",
            status_code=200,
            html=GOOD_HTML,
        )
        self.fail_stage = fail_stage
        self.isolated = isolated
        self.operations: list[tuple] = []

    def _fail(self, stage: str) -> None:
        if self.fail_stage == stage:
            raise RuntimeError(f"injected {stage} failure")

    def create_isolated_page(self, name: str, slug: str) -> LivePageTarget:
        self.operations.append(("create", name, slug))
        self._fail("create")
        return LivePageTarget(
            page_id="page-99",
            url="https://portal.local/vanjaro-benchmark-test",
            name=name,
            isolated=self.isolated,
        )

    def snapshot_page(self, page_id: str) -> object:
        self.operations.append(("snapshot", page_id))
        self._fail("snapshot")
        return {"page_id": page_id, "content": "before"}

    def publish_page(self, page_id: str, payload: Mapping[str, JsonValue]) -> None:
        self.operations.append(("publish", page_id, dict(payload)))
        self._fail("publish")

    def fetch_anonymous(self, url: str) -> AnonymousPage:
        self.operations.append(("fetch", url))
        self._fail("anonymous_fetch")
        return self.anonymous_page

    def restore_page(self, page_id: str, snapshot: object) -> None:
        self.operations.append(("restore", page_id, snapshot))
        self._fail("restore")

    def delete_page(self, page_id: str) -> None:
        self.operations.append(("delete", page_id))
        self._fail("delete")


class FakeCapture:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def __call__(self, target: LivePageTarget, page: AnonymousPage) -> dict[str, JsonValue]:
        self.calls.append((target.page_id, page.url))
        if self.fail:
            raise RuntimeError("injected capture failure")
        return {"desktop": "artifacts/capture-desktop.png"}


def _payload() -> LiveBenchmarkPayload:
    return LiveBenchmarkPayload(page_payload={"components": [{"type": "section"}], "styles": []})


def test_success_creates_unique_page_snapshots_publishes_captures_and_deletes() -> None:
    backend = FakeBackend()
    capture = FakeCapture()
    policy = AnonymousRenderPolicy(
        expected_markers=("agency-header", "agency-footer"),
        source_urls=("https://source.example.org",),
    )

    result = run_live_benchmark(
        backend,
        _payload(),
        capture,
        policy=policy,
        identifier_factory=lambda: "Run 42!",
    )

    assert result.verification.passed
    assert result.capture == {"desktop": "artifacts/capture-desktop.png"}
    assert result.cleanup.action == "delete"
    assert result.cleanup.succeeded
    assert backend.operations[0] == (
        "create",
        "Vanjaro Design Benchmark run-42",
        "vanjaro-benchmark-run-42",
    )
    assert [operation[0] for operation in backend.operations] == [
        "create",
        "snapshot",
        "publish",
        "fetch",
        "delete",
    ]
    assert backend.operations[1][1] == backend.operations[2][1] == backend.operations[-1][1]
    assert backend.operations[2][2] == _payload().page_payload
    assert capture.calls == [("page-99", "https://portal.local/vanjaro-benchmark-test")]


def test_caller_provided_isolated_page_is_restored_never_deleted() -> None:
    backend = FakeBackend()
    target = LivePageTarget(
        page_id="isolated-existing",
        url="https://portal.local/existing-benchmark",
        name="Dedicated Benchmark Page",
        isolated=True,
    )

    result = run_live_benchmark(
        backend,
        _payload(),
        FakeCapture(),
        existing_target=target,
    )

    assert result.cleanup.action == "restore"
    assert [operation[0] for operation in backend.operations] == [
        "snapshot",
        "publish",
        "fetch",
        "restore",
    ]
    assert all(operation[1] == target.page_id for operation in backend.operations if operation[0] != "fetch")


def test_nonisolated_existing_target_is_refused_before_any_portal_call() -> None:
    backend = FakeBackend()
    target = LivePageTarget(
        page_id="home",
        url="https://portal.local/",
        name="Home",
        isolated=False,
    )

    with pytest.raises(LiveBenchmarkError, match="not explicitly marked isolated") as exc_info:
        run_live_benchmark(backend, _payload(), FakeCapture(), existing_target=target)

    assert exc_info.value.stage == "isolation"
    assert backend.operations == []


@pytest.mark.parametrize(
    ("failure_stage", "expected_error_stage", "expected_operations"),
    [
        ("snapshot", "snapshot", ["create", "snapshot", "delete"]),
        ("publish", "publish", ["create", "snapshot", "publish", "delete"]),
        (
            "anonymous_fetch",
            "anonymous_fetch",
            ["create", "snapshot", "publish", "fetch", "delete"],
        ),
    ],
)
def test_created_page_is_deleted_after_every_backend_failure(
    failure_stage: str,
    expected_error_stage: str,
    expected_operations: list[str],
) -> None:
    backend = FakeBackend(fail_stage=failure_stage)

    with pytest.raises(LiveBenchmarkError) as exc_info:
        run_live_benchmark(backend, _payload(), FakeCapture())

    assert exc_info.value.stage == expected_error_stage
    assert [operation[0] for operation in backend.operations] == expected_operations


def test_created_page_is_deleted_when_capture_fails() -> None:
    backend = FakeBackend()

    with pytest.raises(LiveBenchmarkError) as exc_info:
        run_live_benchmark(backend, _payload(), FakeCapture(fail=True))

    assert exc_info.value.stage == "capture"
    assert [operation[0] for operation in backend.operations][-1] == "delete"


def test_partial_publish_to_existing_target_is_restored_in_finally() -> None:
    backend = FakeBackend(fail_stage="publish")
    target = LivePageTarget(
        page_id="isolated-existing",
        url="https://portal.local/existing-benchmark",
        name="Dedicated Benchmark Page",
        isolated=True,
    )

    with pytest.raises(LiveBenchmarkError, match="publish"):
        run_live_benchmark(backend, _payload(), FakeCapture(), existing_target=target)

    assert [operation[0] for operation in backend.operations] == ["snapshot", "publish", "restore"]


def test_render_violations_are_captured_then_page_is_deleted() -> None:
    page = AnonymousPage(
        url="https://portal.local/benchmark",
        status_code=200,
        html="<html><body><h1>Your Headline Here</h1><p>Enough text to pass the blank threshold.</p></body></html>",
    )
    backend = FakeBackend(anonymous_page=page)
    capture = FakeCapture()

    with pytest.raises(AnonymousRenderError) as exc_info:
        run_live_benchmark(backend, _payload(), capture)

    assert "placeholder_remaining" in {item.code for item in exc_info.value.verification.violations}
    assert capture.calls
    assert backend.operations[-1] == ("delete", "page-99")


def test_verifier_detects_status_blank_source_placeholder_wrapper_and_marker() -> None:
    page = AnonymousPage(
        url="https://portal.local/benchmark",
        status_code=500,
        html=(
            '<div data-block-guid="abc">Lorem ipsum '
            '<img src="https://SOURCE.example.org/image.jpg"></div>'
        ),
    )
    policy = AnonymousRenderPolicy(
        minimum_visible_text_chars=40,
        source_urls=("https://source.example.org",),
        expected_markers=("rendered-global-header",),
    )

    result = verify_anonymous_render(page, policy)
    codes = {violation.code for violation in result.violations}

    assert not result.passed
    assert codes == {
        "anonymous_status_invalid",
        "anonymous_render_blank",
        "source_url_remaining",
        "placeholder_remaining",
        "global_wrapper_unresolved",
        "expected_marker_missing",
    }


def test_delete_failure_attempts_snapshot_restore_and_surfaces_cleanup_error() -> None:
    backend = FakeBackend(fail_stage="delete")

    with pytest.raises(LiveBenchmarkCleanupError) as exc_info:
        run_live_benchmark(backend, _payload(), FakeCapture())

    assert exc_info.value.cleanup.action == "delete"
    assert not exc_info.value.cleanup.succeeded
    assert exc_info.value.cleanup.fallback_restore_attempted
    assert [operation[0] for operation in backend.operations][-2:] == ["delete", "restore"]


def test_restore_failure_surfaces_cleanup_error_without_deleting_existing_page() -> None:
    backend = FakeBackend(fail_stage="restore")
    target = LivePageTarget(
        page_id="isolated-existing",
        url="https://portal.local/existing-benchmark",
        name="Dedicated Benchmark Page",
        isolated=True,
    )

    with pytest.raises(LiveBenchmarkCleanupError) as exc_info:
        run_live_benchmark(backend, _payload(), FakeCapture(), existing_target=target)

    assert exc_info.value.cleanup.action == "restore"
    assert not exc_info.value.cleanup.succeeded
    assert not any(operation[0] == "delete" for operation in backend.operations)


def test_backend_returning_nonisolated_created_page_is_deleted() -> None:
    backend = FakeBackend(isolated=False)

    with pytest.raises(LiveBenchmarkError, match="backend returned a page") as exc_info:
        run_live_benchmark(backend, _payload(), FakeCapture())

    assert exc_info.value.stage == "isolation"
    assert [operation[0] for operation in backend.operations] == ["create", "delete"]
