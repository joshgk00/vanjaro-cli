"""Safety-first live-portal benchmark orchestration with injectable I/O.

The harness intentionally exposes only page-scoped backend operations. Theme,
branding, portal settings, and unrelated page enumeration are not part of the
protocol, which keeps accidental mutations outside the benchmark target out of
reach.
"""

from __future__ import annotations

import html as html_module
import re
import uuid
from collections.abc import Callable, Mapping
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue

__all__ = [
    "AnonymousPage",
    "AnonymousRenderError",
    "AnonymousRenderPolicy",
    "CaptureHook",
    "CleanupReport",
    "LiveBenchmarkCleanupError",
    "LiveBenchmarkError",
    "LiveBenchmarkPayload",
    "LiveBenchmarkResult",
    "LivePageTarget",
    "PortalBenchmarkBackend",
    "RenderVerification",
    "RenderViolation",
    "run_live_benchmark",
    "verify_anonymous_render",
]


class _LiveModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


DEFAULT_PLACEHOLDER_PATTERNS = (
    r"\blorem ipsum\b",
    r"\byour headline here\b",
    r"\bbrief description of (?:this|the)\b",
    r"\bproject title\b",
    r"(?:via\.)?placeholder\.com",
    r"placehold\.co",
    r"\bexample\.com\b",
    r"\btemplate placeholder\b",
)

DEFAULT_UNRESOLVED_WRAPPER_PATTERNS = (
    r"data-block-guid\s*=",
    r"data-global-block-id\s*=",
    r"globalblockwrapper",
)


class LivePageTarget(_LiveModel):
    """One page explicitly isolated for destructive benchmark operations."""

    page_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    name: str = Field(min_length=1)
    isolated: bool


class LiveBenchmarkPayload(_LiveModel):
    """Opaque generated page payload passed unchanged to the portal backend."""

    page_payload: dict[str, JsonValue]


class AnonymousPage(_LiveModel):
    url: str = Field(min_length=1)
    status_code: int
    html: str
    headers: dict[str, str] = Field(default_factory=dict)


class AnonymousRenderPolicy(_LiveModel):
    expected_status: int = 200
    minimum_visible_text_chars: int = Field(default=32, ge=0)
    source_urls: tuple[str, ...] = ()
    placeholder_patterns: tuple[str, ...] = DEFAULT_PLACEHOLDER_PATTERNS
    unresolved_wrapper_patterns: tuple[str, ...] = DEFAULT_UNRESOLVED_WRAPPER_PATTERNS
    expected_markers: tuple[str, ...] = ()


class RenderViolation(_LiveModel):
    code: str
    message: str
    evidence: str | None = None


class RenderVerification(_LiveModel):
    passed: bool
    status_code: int
    visible_text_chars: int = Field(ge=0)
    violations: tuple[RenderViolation, ...]


class CleanupReport(_LiveModel):
    action: str
    attempted: bool
    succeeded: bool
    fallback_restore_attempted: bool = False
    errors: tuple[str, ...] = ()


class LiveBenchmarkResult(_LiveModel):
    target: LivePageTarget
    verification: RenderVerification
    capture: dict[str, JsonValue]
    cleanup: CleanupReport


@runtime_checkable
class PortalBenchmarkBackend(Protocol):
    """Page-scoped portal operations required by the harness."""

    def create_isolated_page(self, name: str, slug: str) -> LivePageTarget:
        """Create a disposable page and return its anonymous URL."""

    def snapshot_page(self, page_id: str) -> object:
        """Capture enough state to restore the page after partial publication."""

    def publish_page(self, page_id: str, payload: Mapping[str, JsonValue]) -> None:
        """Replace the target page content and publish it."""

    def fetch_anonymous(self, url: str) -> AnonymousPage:
        """Fetch the public page without authenticated cookies."""

    def restore_page(self, page_id: str, snapshot: object) -> None:
        """Restore a caller-provided target or deletion fallback."""

    def delete_page(self, page_id: str) -> None:
        """Delete a page created by this benchmark run."""


@runtime_checkable
class CaptureHook(Protocol):
    """Hook used by DT-304 or callers to capture screenshots/artifacts."""

    def __call__(
        self,
        target: LivePageTarget,
        anonymous_page: AnonymousPage,
    ) -> Mapping[str, JsonValue]: ...


class LiveBenchmarkError(RuntimeError):
    """A page-scoped benchmark stage failed."""

    def __init__(self, stage: str, message: str, target: LivePageTarget | None = None) -> None:
        self.stage = stage
        self.target = target
        target_suffix = f" for page {target.page_id}" if target is not None else ""
        super().__init__(f"live benchmark {stage} failed{target_suffix}: {message}")


class AnonymousRenderError(LiveBenchmarkError):
    """Anonymous render failed one or more quality/safety checks."""

    def __init__(self, target: LivePageTarget, verification: RenderVerification) -> None:
        self.verification = verification
        codes = ", ".join(violation.code for violation in verification.violations)
        super().__init__("anonymous_verification", f"render violations: {codes}", target)


class LiveBenchmarkCleanupError(LiveBenchmarkError):
    """Cleanup failed; the target may require manual isolation review."""

    def __init__(
        self,
        target: LivePageTarget,
        cleanup: CleanupReport,
        primary_error: BaseException | None,
    ) -> None:
        self.cleanup = cleanup
        self.primary_error = primary_error
        detail = "; ".join(cleanup.errors) or "unknown cleanup error"
        super().__init__("cleanup", detail, target)


def _visible_text(html: str) -> str:
    without_noncontent = re.sub(
        r"<(?:script|style|template)\b[^>]*>.*?</(?:script|style|template)>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    without_tags = re.sub(r"<[^>]+>", " ", without_noncontent)
    return " ".join(html_module.unescape(without_tags).split())


def _first_pattern_match(pattern: str, value: str) -> str | None:
    match = re.search(pattern, value, flags=re.IGNORECASE)
    return match.group(0)[:200] if match else None


def verify_anonymous_render(
    anonymous_page: AnonymousPage,
    policy: AnonymousRenderPolicy,
) -> RenderVerification:
    """Check status, visible output, source leakage, and unresolved placeholders."""

    violations: list[RenderViolation] = []
    if anonymous_page.status_code != policy.expected_status:
        violations.append(
            RenderViolation(
                code="anonymous_status_invalid",
                message=(
                    f"anonymous render returned {anonymous_page.status_code}; "
                    f"expected {policy.expected_status}"
                ),
                evidence=str(anonymous_page.status_code),
            )
        )
    visible_text = _visible_text(anonymous_page.html)
    if len(visible_text) < policy.minimum_visible_text_chars:
        violations.append(
            RenderViolation(
                code="anonymous_render_blank",
                message=(
                    f"visible text contains {len(visible_text)} characters; "
                    f"minimum is {policy.minimum_visible_text_chars}"
                ),
                evidence=visible_text[:200],
            )
        )

    html_casefold = anonymous_page.html.casefold()
    for source_url in policy.source_urls:
        normalized = source_url.strip().casefold().rstrip("/")
        if normalized and normalized in html_casefold:
            violations.append(
                RenderViolation(
                    code="source_url_remaining",
                    message="anonymous render still references the source site",
                    evidence=source_url,
                )
            )
    for pattern in policy.placeholder_patterns:
        evidence = _first_pattern_match(pattern, anonymous_page.html)
        if evidence:
            violations.append(
                RenderViolation(
                    code="placeholder_remaining",
                    message=f"anonymous render contains placeholder content matching {pattern!r}",
                    evidence=evidence,
                )
            )
    for pattern in policy.unresolved_wrapper_patterns:
        evidence = _first_pattern_match(pattern, anonymous_page.html)
        if evidence:
            violations.append(
                RenderViolation(
                    code="global_wrapper_unresolved",
                    message=f"anonymous render contains an unresolved global-block wrapper matching {pattern!r}",
                    evidence=evidence,
                )
            )
    for marker in policy.expected_markers:
        if marker not in anonymous_page.html:
            violations.append(
                RenderViolation(
                    code="expected_marker_missing",
                    message="anonymous render is missing a required generated marker",
                    evidence=marker,
                )
            )
    return RenderVerification(
        passed=not violations,
        status_code=anonymous_page.status_code,
        visible_text_chars=len(visible_text),
        violations=tuple(violations),
    )


def _safe_token(raw: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "-", raw.casefold()).strip("-")
    if not token:
        raise ValueError("benchmark identifier must contain at least one letter or number")
    return token[:48]


def _cleanup_target(
    backend: PortalBenchmarkBackend,
    target: LivePageTarget,
    *,
    created_by_harness: bool,
    snapshot: object | None,
    snapshot_taken: bool,
    publish_attempted: bool,
) -> CleanupReport:
    errors: list[str] = []
    fallback_restore = False
    if created_by_harness:
        try:
            backend.delete_page(target.page_id)
            return CleanupReport(action="delete", attempted=True, succeeded=True)
        except Exception as exc:  # Cleanup must attempt fallback before surfacing.
            errors.append(f"delete failed: {exc}")
            if snapshot_taken:
                fallback_restore = True
                try:
                    backend.restore_page(target.page_id, snapshot)
                except Exception as restore_exc:
                    errors.append(f"fallback restore failed: {restore_exc}")
            return CleanupReport(
                action="delete",
                attempted=True,
                succeeded=False,
                fallback_restore_attempted=fallback_restore,
                errors=tuple(errors),
            )

    if publish_attempted and snapshot_taken:
        try:
            backend.restore_page(target.page_id, snapshot)
            return CleanupReport(action="restore", attempted=True, succeeded=True)
        except Exception as exc:
            return CleanupReport(
                action="restore",
                attempted=True,
                succeeded=False,
                errors=(f"restore failed: {exc}",),
            )
    return CleanupReport(action="none", attempted=False, succeeded=True)


def run_live_benchmark(
    backend: PortalBenchmarkBackend,
    payload: LiveBenchmarkPayload,
    capture_hook: CaptureHook,
    *,
    policy: AnonymousRenderPolicy | None = None,
    existing_target: LivePageTarget | None = None,
    identifier_factory: Callable[[], str] | None = None,
    name_prefix: str = "Vanjaro Design Benchmark",
) -> LiveBenchmarkResult:
    """Publish, verify, capture, and always remove or restore one isolated page."""

    if existing_target is not None and not existing_target.isolated:
        raise LiveBenchmarkError(
            "isolation",
            "caller-provided target is not explicitly marked isolated",
            existing_target,
        )

    target = existing_target
    created_by_harness = existing_target is None
    snapshot: object | None = None
    snapshot_taken = False
    publish_attempted = False
    stage = "create"
    primary_error: BaseException | None = None
    verification: RenderVerification | None = None
    capture: dict[str, JsonValue] | None = None
    cleanup = CleanupReport(action="none", attempted=False, succeeded=True)

    try:
        if target is None:
            token_factory = identifier_factory or (lambda: uuid.uuid4().hex[:12])
            token = _safe_token(token_factory())
            target = backend.create_isolated_page(
                f"{name_prefix} {token}",
                f"vanjaro-benchmark-{token}",
            )
            if not target.isolated:
                raise LiveBenchmarkError(
                    "isolation",
                    "backend returned a page that is not marked isolated",
                    target,
                )

        stage = "snapshot"
        snapshot = backend.snapshot_page(target.page_id)
        snapshot_taken = True

        stage = "publish"
        publish_attempted = True
        backend.publish_page(target.page_id, payload.page_payload)

        stage = "anonymous_fetch"
        anonymous_page = backend.fetch_anonymous(target.url)
        verification = verify_anonymous_render(
            anonymous_page,
            policy or AnonymousRenderPolicy(),
        )

        # Capture even a failing render so diagnostics survive after cleanup.
        stage = "capture"
        capture = dict(capture_hook(target, anonymous_page))
        if not verification.passed:
            raise AnonymousRenderError(target, verification)
    except BaseException as exc:
        if isinstance(exc, LiveBenchmarkError):
            primary_error = exc
        elif isinstance(exc, (KeyboardInterrupt, SystemExit)):
            primary_error = exc
        else:
            primary_error = LiveBenchmarkError(stage, str(exc), target)
    finally:
        if target is not None:
            cleanup = _cleanup_target(
                backend,
                target,
                created_by_harness=created_by_harness,
                snapshot=snapshot,
                snapshot_taken=snapshot_taken,
                publish_attempted=publish_attempted,
            )
    if not cleanup.succeeded and target is not None:
        raise LiveBenchmarkCleanupError(target, cleanup, primary_error) from primary_error
    if primary_error is not None:
        raise primary_error
    if target is None or verification is None or capture is None:
        raise LiveBenchmarkError("internal", "benchmark completed without a result", target)
    return LiveBenchmarkResult(
        target=target,
        verification=verification,
        capture=capture,
        cleanup=cleanup,
    )
