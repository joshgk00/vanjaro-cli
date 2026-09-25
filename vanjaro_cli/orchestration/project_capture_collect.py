"""Turn a page's resolved capture plan into real, source-aware evidence.

`collect_page_capture` is the one orchestration entry point that:

1. Verifies the live target's identity (`portal_identity.verify_project_portal`)
   before any browser work -- a misconfigured or drifted target aborts with
   zero captures and zero writes, never a partial attempt.
2. Plans the page's three required breakpoints purely
   (`project_capture_plan.plan_project_capture`) against the already-resolved
   design document and caller-supplied references. This module never guesses
   a URL or invents a Figma export; every reference it captures came from the
   planner, which came from the caller.
3. For a live reference, captures the source at its own declared viewport
   with `require_sections=False` (a design's own source page is not expected
   to already look like the built agency template) and the built output at
   the *same* viewport with `require_sections=True`, restricted to the
   verified target's own base URL.
4. For a static reference, never renders its bytes: only the built output
   goes through the browser. The source's identity was already re-checked by
   the planner.
5. Persists a versioned `capture-evidence-v2` record
   (`project_capture_v2.record_page_capture_v2`) -- a full replace of this
   page's prior record, so a failed or partial recapture can never leave a
   stale complete set behind, while every other page's record is untouched.

Every attempt becomes a structured result, never an exception: a missing
reference, an invalid reference, a capture failure, a target mismatch, and
an unmeasurable output are all reported, not raised. Screenshot filenames
under `qa/captures/` are always a hash of `page_id:breakpoint:role`, never
the raw page id, so an externally supplied id can never escape that
directory.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from vanjaro_cli.client import VanjaroClient
from vanjaro_cli.design.capture_references import LiveReference, SourceReference, StaticReference
from vanjaro_cli.design.capture_session import CapturedPage, CaptureSessionError, CaptureSessionErrorCode
from vanjaro_cli.design.fidelity_extraction import observe_expected_page
from vanjaro_cli.design.fidelity_observation import observe_built_page
from vanjaro_cli.design.models import BreakpointName, DesignDocument, Viewport
from vanjaro_cli.orchestration.portal_identity import (
    PortalIdentityError,
    VerifiedPortal,
    verify_project_portal,
)
from vanjaro_cli.orchestration.project_capture_plan import (
    BreakpointCapturePlan,
    ReferenceStatus,
    plan_project_capture,
)
from vanjaro_cli.orchestration.project_capture_v2 import (
    BreakpointCaptureAttempt,
    CaptureAttemptStatus,
    record_page_capture_v2,
)
from vanjaro_cli.project.models import ProjectManifest

__all__ = ["CAPTURE_SCREENSHOT_DIRECTORY", "CaptureSession", "collect_page_capture"]

CAPTURE_SCREENSHOT_DIRECTORY = "qa/captures"

_TARGET_MISMATCH_CODES = frozenset(
    {CaptureSessionErrorCode.TARGET_REJECTED, CaptureSessionErrorCode.MISSING_FINAL_URL}
)
_OUTPUT_NOT_MEASURABLE_CODES = frozenset(
    {CaptureSessionErrorCode.MISSING_SECTIONS, CaptureSessionErrorCode.MEASUREMENT_FAILED}
)


class CaptureSession(Protocol):
    """The one browser-capture primitive this module depends on.

    Matches `design.capture_session.PlaywrightCaptureSession.capture` --
    injected here so nothing in this module imports Playwright.
    """

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
        ...


def _screenshot_path(root: Path, page_id: str, breakpoint: BreakpointName, role: str) -> Path:
    digest = hashlib.sha256(f"{page_id}:{breakpoint.value}:{role}".encode("utf-8")).hexdigest()
    return root / CAPTURE_SCREENSHOT_DIRECTORY / f"{digest}.png"


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _stability_dict(stability: Any) -> dict[str, bool]:
    return {
        "lazy_load_triggered": bool(stability.lazy_load_triggered),
        "fonts_settled": bool(stability.fonts_settled),
        "animations_disabled": bool(stability.animations_disabled),
    }


def _safe_capture(
    capture_session: CaptureSession,
    url: str,
    *,
    viewport: Viewport,
    destination: Path,
    allowed_base_url: str | None,
    require_sections: bool,
) -> tuple[CapturedPage | None, CaptureSessionError | None]:
    try:
        captured = capture_session.capture(
            url,
            viewport=viewport,
            destination=destination,
            allowed_base_url=allowed_base_url,
            require_sections=require_sections,
        )
    except CaptureSessionError as error:
        return None, error
    return captured, None


def _classify_output_error(error: CaptureSessionError) -> CaptureAttemptStatus:
    if error.code in _TARGET_MISMATCH_CODES:
        return CaptureAttemptStatus.TARGET_MISMATCH
    if error.code in _OUTPUT_NOT_MEASURABLE_CODES:
        return CaptureAttemptStatus.OUTPUT_NOT_MEASURABLE
    return CaptureAttemptStatus.CAPTURE_FAILED


def _failed_attempt(
    breakpoint: BreakpointName, status: CaptureAttemptStatus, message: str
) -> tuple[BreakpointCaptureAttempt, dict[str, Any]]:
    return (
        BreakpointCaptureAttempt(breakpoint=breakpoint, status=status, diagnostics=(message,)),
        {"status": status.value, "diagnostics": [message]},
    )


def _declared_status_attempt(
    breakpoint: BreakpointName, status: CaptureAttemptStatus, diagnostics: tuple[str, ...]
) -> tuple[BreakpointCaptureAttempt, dict[str, Any]]:
    return (
        BreakpointCaptureAttempt(breakpoint=breakpoint, status=status, diagnostics=diagnostics),
        {"status": status.value, "diagnostics": list(diagnostics)},
    )


def _collect_breakpoint(
    root: Path,
    document: DesignDocument,
    page: Any,
    breakpoint: BreakpointName,
    bp_plan: BreakpointCapturePlan,
    built_url: str,
    *,
    capture_session: CaptureSession,
    allowed_base_url: str,
) -> tuple[BreakpointCaptureAttempt, dict[str, Any]]:
    if bp_plan.status == ReferenceStatus.NOT_DECLARED:
        return _declared_status_attempt(
            breakpoint, CaptureAttemptStatus.REFERENCE_NOT_DECLARED, bp_plan.diagnostics
        )
    if bp_plan.status == ReferenceStatus.INVALID:
        return _declared_status_attempt(
            breakpoint, CaptureAttemptStatus.REFERENCE_INVALID, bp_plan.diagnostics
        )

    reference = bp_plan.reference
    assert reference is not None
    viewport = Viewport(width=reference.viewport_width, height=reference.viewport_height)

    static_fields: dict[str, Any] = {}
    if isinstance(reference, LiveReference):
        source_capture, source_error = _safe_capture(
            capture_session,
            reference.url,
            viewport=viewport,
            destination=_screenshot_path(root, page.id, breakpoint, "source"),
            allowed_base_url=None,
            require_sections=False,
        )
        if source_error is not None:
            return _failed_attempt(breakpoint, CaptureAttemptStatus.CAPTURE_FAILED, str(source_error))
        source_kind = "live"
        source_fields: dict[str, Any] = {
            "source_path": _relative(source_capture.screenshot_path, root),
            "source_sha256": source_capture.screenshot_sha256,
            "source_stability": _stability_dict(source_capture.stability),
        }
    else:
        assert isinstance(reference, StaticReference)
        # Never render a static source: only its already-planner-validated
        # identity is recorded.
        source_kind = "static"
        source_fields = {"source_sha256": reference.sha256}
        static_fields = {
            "static_source_kind": reference.source_kind.value,
            "static_local_path": reference.local_path,
            "static_canvas_width": reference.canvas_width,
            "static_canvas_height": reference.canvas_height,
            "static_interpretation": reference.interpretation.value,
            "static_file_key": reference.file_key,
            "static_frame_node_id": reference.frame_node_id,
        }

    output_capture, output_error = _safe_capture(
        capture_session,
        built_url,
        viewport=viewport,
        destination=_screenshot_path(root, page.id, breakpoint, "output"),
        allowed_base_url=allowed_base_url,
        require_sections=True,
    )
    if output_error is not None:
        return _failed_attempt(breakpoint, _classify_output_error(output_error), str(output_error))

    expected = observe_expected_page(page, document, breakpoint, viewport)
    observed = observe_built_page(output_capture.rendered)
    if expected is None or observed is None:
        missing_side = "design" if expected is None else "build"
        return _failed_attempt(
            breakpoint,
            CaptureAttemptStatus.OUTPUT_NOT_MEASURABLE,
            f"no {missing_side} sections available to score {breakpoint.value}",
        )

    attempt = BreakpointCaptureAttempt(
        breakpoint=breakpoint,
        status=CaptureAttemptStatus.CAPTURED,
        viewport_width=viewport.width,
        viewport_height=viewport.height,
        source_kind=source_kind,
        output_path=_relative(output_capture.screenshot_path, root),
        output_sha256=output_capture.screenshot_sha256,
        output_stability=_stability_dict(output_capture.stability),
        expected=expected.model_dump(mode="json"),
        observed=observed.model_dump(mode="json"),
        **source_fields,
        **static_fields,
    )
    summary = {
        "status": "captured",
        "viewport": {"width": viewport.width, "height": viewport.height},
        "source_kind": source_kind,
    }
    return attempt, summary


def collect_page_capture(
    root: Path,
    document: DesignDocument,
    manifest: ProjectManifest,
    *,
    page_id: str,
    built_url: str,
    capture_session: CaptureSession,
    references: Sequence[SourceReference] = (),
    target_verifier: Callable[
        [ProjectManifest], tuple[VanjaroClient, VerifiedPortal]
    ] = verify_project_portal,
) -> dict[str, Any]:
    """Collect and persist one page's source-aware capture evidence.

    Returns a JSON-ready summary:
    `{"page_id", "status", "built_url", "target_base_url", "breakpoints",
    "missing_evidence", "warnings"}`. Never raises for an expected outcome --
    a target mismatch, an unresolved page, a missing/invalid reference, a
    capture failure, or an unmeasurable output all become part of the
    returned summary, with zero captures and zero evidence writes for a
    target mismatch or an unresolved page.
    """

    root = Path(root)

    try:
        _, verified = target_verifier(manifest)
    except PortalIdentityError as error:
        return {
            "page_id": page_id,
            "status": "target_mismatch",
            "error": str(error),
            "breakpoints": {},
            "missing_evidence": [],
            "warnings": [],
        }

    plan = plan_project_capture(root, document, references=references)
    page_plan = next((entry for entry in plan.pages if entry.page_id == page_id), None)
    if page_plan is None:
        return {
            "page_id": page_id,
            "status": "page_not_found",
            "breakpoints": {},
            "missing_evidence": [],
            "warnings": list(plan.diagnostics),
        }

    page = next(item for item in document.pages if item.id == page_id)

    attempts: list[BreakpointCaptureAttempt] = []
    breakpoint_summaries: dict[str, dict[str, Any]] = {}
    missing_evidence: list[str] = []

    for bp_plan in page_plan.breakpoints:
        attempt, summary = _collect_breakpoint(
            root,
            document,
            page,
            bp_plan.breakpoint,
            bp_plan,
            built_url,
            capture_session=capture_session,
            allowed_base_url=verified.base_url,
        )
        attempts.append(attempt)
        breakpoint_summaries[bp_plan.breakpoint.value] = summary
        if attempt.status != CaptureAttemptStatus.CAPTURED:
            missing_evidence.append(bp_plan.breakpoint.value)

    warnings = [diagnostic for bp_plan in page_plan.breakpoints for diagnostic in bp_plan.diagnostics]

    record_page_capture_v2(
        root,
        document,
        manifest,
        page_id=page_id,
        built_url=built_url,
        attempts=attempts,
        warnings=warnings,
    )

    if not missing_evidence:
        status = "captured"
    elif len(missing_evidence) == len(attempts):
        status = "failed"
    else:
        status = "partial"

    return {
        "page_id": page_id,
        "status": status,
        "built_url": built_url,
        "target_base_url": verified.base_url,
        "breakpoints": breakpoint_summaries,
        "missing_evidence": missing_evidence,
        "warnings": warnings,
    }
