"""Source-aware `capture-evidence-v2` per-page records: persist, then re-validate.

`project_capture_evidence.py` owns the legacy `capture-evidence-v1` store,
where every breakpoint is a live browser render at a canonical viewport. That
shape has no room for a static (image/Figma) source: it has no settlement
flags, and it may legitimately declare a viewport that is not canonical (a
1280px desktop image, a 375px Figma mobile frame). Rather than retrofit those
facts into v1's strict canonical-only records, this module adds a second,
explicitly versioned record shape in the *same* `qa/capture-evidence/`
store, read by the same `resolve_workspace_capture_coverage` both quality
counting and the fidelity gate already call.

This module intentionally does not re-implement the legacy validator or the
visual scoring engine: it reuses `project_capture_evidence`'s filename,
build-artifact, target-identity, and observation-shape helpers, and it
re-validates a static source's identity by re-planning it through the same
pure `plan_project_capture` the pre-capture planning stage already trusts --
never through a second, parallel notion of "valid".

Every capture attempt is recorded, including one that never produced a pair:
`CaptureAttemptStatus` distinguishes a declared-but-invalid reference from an
undeclared one, a capture failure, a target-mismatch abort, and an output the
build could not measure. A `status` other than `captured` never carries
capture data -- there is no half-populated attempt.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
from pathlib import Path
from typing import Any

from vanjaro_cli.design.capture_references import (
    CanvasInterpretation,
    InvalidReferenceError,
    StaticReference,
    StaticSourceKind,
)
from vanjaro_cli.design.models import BreakpointName, DesignDocument
from vanjaro_cli.design.serialization import serialize_design_document
from vanjaro_cli.design.visual_gate import CANONICAL_VIEWPORTS
from vanjaro_cli.orchestration.project_capture_evidence import (
    CAPTURE_EVIDENCE_DIRECTORY,
    _build_artifact_fingerprints,
    _record_filename,
    _target_identity_fingerprint,
    _validate_observation,
)
from vanjaro_cli.orchestration.project_capture_plan import (
    REQUIRED_BREAKPOINTS,
    ReferenceStatus,
    plan_project_capture,
)
from vanjaro_cli.project.models import ProjectManifest
from vanjaro_cli.reliability.artifacts import (
    ArtifactContractError,
    atomic_write_json,
    load_strict_json,
)
from vanjaro_cli.release.paths import _contains_link_or_reparse, _resolve_repository_path

__all__ = [
    "SCHEMA_VERSION_V2",
    "BreakpointCaptureAttempt",
    "BreakpointV2Result",
    "CaptureAttemptStatus",
    "PageCaptureV2Validation",
    "record_page_capture_v2",
    "validate_page_capture_v2",
]

SCHEMA_VERSION_V2 = "capture-evidence-v2"

_REQUIRED_BREAKPOINT_VALUES = frozenset(breakpoint.value for breakpoint in REQUIRED_BREAKPOINTS)
_LIVE = "live"
_STATIC = "static"
_SOURCE_KINDS = frozenset({_LIVE, _STATIC})
_STABILITY_FLAGS = ("lazy_load_triggered", "fonts_settled", "animations_disabled")

# A non-captured attempt must never carry capture data: a caller that skips
# a breakpoint (no reference, an invalid reference, a capture failure) has
# nothing real to report for these fields, and inventing placeholders would
# let a missing capture masquerade as one that happened.
_CAPTURE_ONLY_FIELDS = (
    "viewport_width",
    "viewport_height",
    "source_kind",
    "source_path",
    "source_sha256",
    "source_stability",
    "static_source_kind",
    "static_local_path",
    "static_canvas_width",
    "static_canvas_height",
    "static_interpretation",
    "static_file_key",
    "static_frame_node_id",
    "output_path",
    "output_sha256",
    "output_stability",
    "expected",
    "observed",
)


class CaptureAttemptStatus(str, Enum):
    """Every outcome a single breakpoint's capture attempt can reach."""

    CAPTURED = "captured"
    REFERENCE_NOT_DECLARED = "reference_not_declared"
    REFERENCE_INVALID = "reference_invalid"
    CAPTURE_FAILED = "capture_failed"
    TARGET_MISMATCH = "target_mismatch"
    OUTPUT_NOT_MEASURABLE = "output_not_measurable"


_STATUS_VALUES = frozenset(status.value for status in CaptureAttemptStatus)


@dataclass(frozen=True)
class BreakpointCaptureAttempt:
    """One breakpoint's real outcome, built by the collector, persisted as-is.

    `source_stability`/`output_stability` are plain `{flag: bool}` dicts
    rather than a `CaptureStability` model, so this module never needs a
    hard dependency on `design.visual_gate`'s pydantic types to persist one.
    """

    breakpoint: BreakpointName
    status: CaptureAttemptStatus
    viewport_width: int | None = None
    viewport_height: int | None = None
    source_kind: str | None = None
    source_path: str | None = None
    source_sha256: str | None = None
    source_stability: dict[str, bool] | None = None
    static_source_kind: str | None = None
    static_local_path: str | None = None
    static_canvas_width: int | None = None
    static_canvas_height: int | None = None
    static_interpretation: str | None = None
    static_file_key: str | None = None
    static_frame_node_id: str | None = None
    output_path: str | None = None
    output_sha256: str | None = None
    output_stability: dict[str, bool] | None = None
    expected: dict[str, Any] | None = None
    observed: dict[str, Any] | None = None
    diagnostics: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "breakpoint": self.breakpoint.value,
            "status": self.status.value,
            "viewport_width": self.viewport_width,
            "viewport_height": self.viewport_height,
            "source_kind": self.source_kind,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "source_stability": self.source_stability,
            "static_source_kind": self.static_source_kind,
            "static_local_path": self.static_local_path,
            "static_canvas_width": self.static_canvas_width,
            "static_canvas_height": self.static_canvas_height,
            "static_interpretation": self.static_interpretation,
            "static_file_key": self.static_file_key,
            "static_frame_node_id": self.static_frame_node_id,
            "output_path": self.output_path,
            "output_sha256": self.output_sha256,
            "output_stability": self.output_stability,
            "expected": self.expected,
            "observed": self.observed,
            "diagnostics": list(self.diagnostics),
        }


def record_page_capture_v2(
    root: Path,
    document: DesignDocument,
    manifest: ProjectManifest,
    *,
    page_id: str,
    built_url: str,
    attempts: Sequence[BreakpointCaptureAttempt],
    warnings: Iterable[str] = (),
) -> dict[str, Any]:
    """Write this page's `capture-evidence-v2` record, replacing any prior one.

    A full replace, not a merge, exactly like the v1 writer: a failed or
    partial recapture writes exactly the attempts it actually made, so a
    stale complete set from an earlier capture (v1 or v2) can never survive
    alongside it.
    """

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION_V2,
        "page_id": page_id,
        "built_url": built_url,
        "design_document_sha256": hashlib.sha256(
            serialize_design_document(document).encode("utf-8")
        ).hexdigest(),
        "build_artifact_sha256": _build_artifact_fingerprints(root),
        "target_identity_sha256": _target_identity_fingerprint(manifest),
        "breakpoints": [attempt.to_json() for attempt in attempts],
        "warnings": list(warnings),
    }
    destination = root / CAPTURE_EVIDENCE_DIRECTORY / _record_filename(page_id)
    atomic_write_json(destination, payload)
    return payload


@dataclass(frozen=True)
class BreakpointV2Result:
    """One breakpoint's re-validated outcome, ready for the fidelity consumer.

    `valid` is independent per breakpoint: a page with two valid comparisons
    and one rejected one still exposes the two good comparisons. `is_canonical`
    is an independent fact from `valid` -- a valid 1280px desktop comparison is
    `valid=True, is_canonical=False`, and only a breakpoint that is both counts
    toward the strict three-canonical-viewport release policy.
    """

    breakpoint: str
    status: str
    valid: bool
    is_canonical: bool = False
    viewport_width: int | None = None
    viewport_height: int | None = None
    source_kind: str | None = None
    source_path: str | None = None
    source_sha256: str | None = None
    source_stability: dict[str, bool] | None = None
    static_source_kind: str | None = None
    static_local_path: str | None = None
    output_path: str | None = None
    output_stability: dict[str, bool] | None = None
    expected: dict[str, Any] | None = None
    observed: dict[str, Any] | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class PageCaptureV2Validation:
    """The verified outcome of reading one page's `capture-evidence-v2` record."""

    page_id: str
    record_valid: bool
    breakpoints: dict[str, BreakpointV2Result] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def canonical_breakpoints(self) -> frozenset[str]:
        """Breakpoints valid *and* at exactly the canonical viewport.

        This is the only set fed to `quality_counts.compute_quality_counts`:
        a real but noncanonical comparison (375px mobile, 1280px desktop)
        must never be mistaken for canonical release evidence.
        """

        return frozenset(
            name
            for name, result in self.breakpoints.items()
            if result.valid and result.is_canonical
        )

    def has_valid_comparison(self) -> bool:
        return any(result.valid for result in self.breakpoints.values())


def _reject_record(page_id: str | None, message: str) -> PageCaptureV2Validation:
    label = page_id if page_id is not None else "?"
    return PageCaptureV2Validation(
        page_id=page_id or "", record_valid=False, warnings=(f"page {label!r}: {message}",)
    )


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_canonical_viewport(breakpoint_value: str, width: Any, height: Any) -> bool:
    try:
        breakpoint = BreakpointName(breakpoint_value)
    except ValueError:
        return False
    canonical = CANONICAL_VIEWPORTS.get(breakpoint)
    return canonical is not None and canonical.width == width and canonical.height == height


def _check_file_hash(
    root: Path, page_id: str, breakpoint_value: str, role: str, relative: Any, digest: Any
) -> list[str]:
    if not isinstance(relative, str) or not relative or not isinstance(digest, str) or not digest:
        return [f"page {page_id!r}: {breakpoint_value} {role} is missing a path or hash"]
    resolved = _resolve_repository_path(root, relative, expected_type="file")
    if resolved is None:
        return [
            f"page {page_id!r}: {breakpoint_value} {role} file is unsafe, a symlink, or "
            f"missing: {relative}"
        ]
    try:
        observed_digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError as error:
        return [f"page {page_id!r}: {breakpoint_value} {role} file unreadable: {error}"]
    if observed_digest != digest:
        return [
            f"page {page_id!r}: {breakpoint_value} {role} file changed since capture; "
            "recapture required"
        ]
    return []


def _check_stability(page_id: str, breakpoint_value: str, role: str, raw: Any) -> list[str]:
    if not isinstance(raw, dict):
        return [f"page {page_id!r}: {breakpoint_value} {role} is missing settlement evidence"]
    issues: list[str] = []
    for flag in _STABILITY_FLAGS:
        value = raw.get(flag)
        if not isinstance(value, bool) or value is not True:
            issues.append(
                f"page {page_id!r}: {breakpoint_value} {role} {flag} must be true, not {value!r}"
            )
    return issues


def _rebuild_static_reference(
    page_id: str, breakpoint_value: str, entry: Mapping[str, Any]
) -> tuple[StaticReference | None, list[str]]:
    try:
        reference = StaticReference(
            page_id=page_id,
            breakpoint=BreakpointName(breakpoint_value),
            source_kind=StaticSourceKind(entry.get("static_source_kind")),
            local_path=entry.get("static_local_path"),
            sha256=entry.get("source_sha256"),
            canvas_width=entry.get("static_canvas_width"),
            canvas_height=entry.get("static_canvas_height"),
            viewport_width=entry.get("viewport_width"),
            viewport_height=entry.get("viewport_height"),
            interpretation=CanvasInterpretation(entry.get("static_interpretation")),
            file_key=entry.get("static_file_key"),
            frame_node_id=entry.get("static_frame_node_id"),
        )
    except (InvalidReferenceError, ValueError) as error:
        return None, [f"page {page_id!r}: {breakpoint_value} static identity is invalid: {error}"]
    return reference, []


def _replan_static_reference(
    root: Path, document: DesignDocument, reference: StaticReference
) -> list[str]:
    """Re-verify a static reference's identity, containment, and hash.

    Reuses the same pure `plan_project_capture` the pre-capture planning
    stage trusts, rather than a second notion of "valid" carried only by
    this module.
    """

    plan = plan_project_capture(root, document, references=(reference,))
    for page_plan in plan.pages:
        if page_plan.page_id != reference.page_id:
            continue
        for breakpoint_plan in page_plan.breakpoints:
            if breakpoint_plan.breakpoint != reference.breakpoint:
                continue
            if breakpoint_plan.status == ReferenceStatus.VALID:
                return []
            detail = "; ".join(breakpoint_plan.diagnostics) or breakpoint_plan.status.value
            return [
                f"page {reference.page_id!r}: {reference.breakpoint.value} static reference "
                f"failed re-planning against the current design: {detail}"
            ]
    return [
        f"page {reference.page_id!r}: {reference.breakpoint.value} could not be re-planned; "
        "page not found in the current design document"
    ]


def _validate_breakpoint_entry(
    root: Path,
    page_id: str,
    breakpoint_value: str,
    entry: Mapping[str, Any],
    *,
    document: DesignDocument,
    valid_section_ids: frozenset[str],
) -> tuple[BreakpointV2Result, list[str]]:
    status_value = entry.get("status")
    if not isinstance(status_value, str) or status_value not in _STATUS_VALUES:
        return (
            BreakpointV2Result(breakpoint=breakpoint_value, status="capture_failed", valid=False),
            [f"page {page_id!r}: {breakpoint_value} has an unknown status {status_value!r}"],
        )

    raw_diagnostics = entry.get("diagnostics")
    diagnostics = (
        tuple(str(item) for item in raw_diagnostics) if isinstance(raw_diagnostics, list) else ()
    )

    if status_value != CaptureAttemptStatus.CAPTURED.value:
        stray = [key for key in _CAPTURE_ONLY_FIELDS if entry.get(key) is not None]
        if stray:
            return (
                BreakpointV2Result(
                    breakpoint=breakpoint_value, status=status_value, valid=False,
                    diagnostics=diagnostics,
                ),
                [
                    f"page {page_id!r}: {breakpoint_value} status {status_value!r} must not "
                    f"carry capture data: {stray}"
                ],
            )
        return (
            BreakpointV2Result(
                breakpoint=breakpoint_value, status=status_value, valid=False,
                diagnostics=diagnostics,
            ),
            [],
        )

    issues: list[str] = []
    viewport_width = entry.get("viewport_width")
    viewport_height = entry.get("viewport_height")
    if not _is_positive_int(viewport_width) or not _is_positive_int(viewport_height):
        return (
            BreakpointV2Result(
                breakpoint=breakpoint_value, status=status_value, valid=False,
                diagnostics=diagnostics,
            ),
            [f"page {page_id!r}: {breakpoint_value} captured status requires a positive integer viewport"],
        )

    source_kind = entry.get("source_kind")
    if source_kind not in _SOURCE_KINDS:
        issues.append(f"page {page_id!r}: {breakpoint_value} has an unknown source_kind {source_kind!r}")
    elif source_kind == _LIVE:
        static_keys = (
            "static_source_kind", "static_local_path", "static_canvas_width",
            "static_canvas_height", "static_interpretation", "static_file_key",
            "static_frame_node_id",
        )
        stray_static = [key for key in static_keys if entry.get(key) is not None]
        if stray_static:
            issues.append(
                f"page {page_id!r}: {breakpoint_value} live capture must not carry static "
                f"identity fields: {stray_static}"
            )
        issues.extend(
            _check_file_hash(
                root, page_id, breakpoint_value, "source",
                entry.get("source_path"), entry.get("source_sha256"),
            )
        )
        issues.extend(_check_stability(page_id, breakpoint_value, "source", entry.get("source_stability")))
    else:  # static
        if entry.get("source_stability") is not None:
            issues.append(
                f"page {page_id!r}: {breakpoint_value} static capture must never carry "
                "source settlement flags"
            )
        reference, reference_issues = _rebuild_static_reference(page_id, breakpoint_value, entry)
        issues.extend(reference_issues)
        if reference is not None:
            issues.extend(_replan_static_reference(root, document, reference))

    issues.extend(
        _check_file_hash(
            root, page_id, breakpoint_value, "output",
            entry.get("output_path"), entry.get("output_sha256"),
        )
    )
    issues.extend(_check_stability(page_id, breakpoint_value, "output", entry.get("output_stability")))

    required_width = float(viewport_width) if _is_positive_int(viewport_width) else None
    _, expected_issues = _validate_observation(
        page_id, breakpoint_value, "expected", entry.get("expected"), valid_section_ids,
        expected_viewport_width=required_width,
    )
    _, observed_issues = _validate_observation(
        page_id, breakpoint_value, "observed", entry.get("observed"), valid_section_ids,
        expected_viewport_width=required_width,
    )
    issues.extend(expected_issues)
    issues.extend(observed_issues)

    is_canonical = _is_canonical_viewport(breakpoint_value, viewport_width, viewport_height)

    if issues:
        return (
            BreakpointV2Result(
                breakpoint=breakpoint_value, status=status_value, valid=False,
                is_canonical=is_canonical, viewport_width=viewport_width,
                viewport_height=viewport_height, source_kind=source_kind,
                diagnostics=diagnostics,
            ),
            issues,
        )

    return (
        BreakpointV2Result(
            breakpoint=breakpoint_value, status=status_value, valid=True,
            is_canonical=is_canonical, viewport_width=viewport_width, viewport_height=viewport_height,
            source_kind=source_kind,
            source_path=entry.get("source_path"),
            source_sha256=entry.get("source_sha256"),
            source_stability=entry.get("source_stability"),
            static_source_kind=entry.get("static_source_kind"),
            static_local_path=entry.get("static_local_path"),
            output_path=entry.get("output_path"),
            output_stability=entry.get("output_stability"),
            expected=entry.get("expected"),
            observed=entry.get("observed"),
            diagnostics=diagnostics,
        ),
        [],
    )


def validate_page_capture_v2(
    root: Path,
    record_path: Path,
    *,
    document: DesignDocument,
    current_page_ids: frozenset[str],
    page_section_ids: Mapping[str, frozenset[str]],
    document_sha256: str,
    build_artifact_sha256: Mapping[str, str],
    manifest: ProjectManifest | None,
) -> PageCaptureV2Validation:
    """Read and re-validate one page's `capture-evidence-v2` record.

    Read-only, zero-network: re-derives page/section ownership, design/build/
    target currency, static identity, and observation shape from current
    state rather than trusting anything the record merely claims. Unlike the
    v1 reader, a rejected breakpoint does not taint the whole page -- each
    breakpoint's validity is independent, so a page can expose one real
    comparison even when another breakpoint's evidence was tampered with or
    never declared.
    """

    label = record_path.name
    if _contains_link_or_reparse(record_path):
        return _reject_record(None, f"capture evidence record {label} is a symlink or reparse point")
    try:
        resolved_record = record_path.resolve()
        resolved_record.relative_to(root.resolve())
    except (OSError, ValueError):
        return _reject_record(None, f"capture evidence record {label} escapes the workspace")

    try:
        payload = load_strict_json(record_path)
    except ArtifactContractError as error:
        return _reject_record(None, f"capture evidence record {label} is malformed: {error}")
    if not isinstance(payload, dict):
        return _reject_record(None, f"capture evidence record {label} must contain a JSON object")

    page_id = payload.get("page_id")
    if not isinstance(page_id, str) or not page_id:
        return _reject_record(None, f"capture evidence record {label} has no valid page_id")
    if record_path.name != _record_filename(page_id):
        return _reject_record(page_id, f"record filename {label} does not match its page_id; rejected")
    if payload.get("schema_version") != SCHEMA_VERSION_V2:
        return _reject_record(
            page_id, f"unsupported capture evidence schema {payload.get('schema_version')!r}"
        )
    if page_id not in current_page_ids:
        return _reject_record(page_id, "not a page in the current resolved design document; rejected")
    if payload.get("design_document_sha256") != document_sha256:
        return _reject_record(page_id, "captured design document is stale; recapture required")

    recorded_build = payload.get("build_artifact_sha256")
    if not isinstance(recorded_build, dict) or not recorded_build:
        return _reject_record(
            page_id,
            "no local build artifact binding was recorded; recapture after a local build exists",
        )
    if not build_artifact_sha256:
        return _reject_record(
            page_id,
            "no current local build artifacts exist to verify against; build the workspace "
            "before this evidence can be trusted",
        )
    if dict(recorded_build) != dict(build_artifact_sha256):
        return _reject_record(page_id, "local build artifacts changed since capture; recapture required")

    recorded_target = payload.get("target_identity_sha256")
    if not isinstance(recorded_target, str) or not recorded_target:
        return _reject_record(
            page_id, "no target identity was recorded; recapture with a project manifest present"
        )
    if manifest is None:
        return _reject_record(
            page_id, "no current project manifest was supplied; target identity cannot be verified"
        )
    if recorded_target != _target_identity_fingerprint(manifest):
        return _reject_record(page_id, "recorded target identity no longer matches project.json")

    built_url = payload.get("built_url")
    if not isinstance(built_url, str) or not built_url:
        return _reject_record(page_id, "record has no built_url")

    breakpoints_raw = payload.get("breakpoints")
    if not isinstance(breakpoints_raw, list) or not breakpoints_raw:
        return _reject_record(page_id, "record has no breakpoints")

    seen: set[str] = set()
    entries: dict[str, Mapping[str, Any]] = {}
    for entry in breakpoints_raw:
        if not isinstance(entry, dict):
            return _reject_record(page_id, "a breakpoint entry is not an object")
        value = entry.get("breakpoint")
        if not isinstance(value, str) or value not in _REQUIRED_BREAKPOINT_VALUES:
            return _reject_record(page_id, f"breakpoint entry has an unknown breakpoint {value!r}")
        if value in seen:
            return _reject_record(page_id, f"duplicate {value} breakpoint entry; rejected")
        seen.add(value)
        entries[value] = entry
    if seen != _REQUIRED_BREAKPOINT_VALUES:
        missing = sorted(_REQUIRED_BREAKPOINT_VALUES - seen)
        return _reject_record(page_id, f"record is missing required breakpoints {missing}")

    valid_section_ids = page_section_ids.get(page_id, frozenset())
    warnings: list[str] = []
    results: dict[str, BreakpointV2Result] = {}
    for breakpoint_value, entry in entries.items():
        result, issues = _validate_breakpoint_entry(
            root, page_id, breakpoint_value, entry,
            document=document, valid_section_ids=valid_section_ids,
        )
        results[breakpoint_value] = result
        warnings.extend(issues)

    return PageCaptureV2Validation(
        page_id=page_id, record_valid=True, breakpoints=results, warnings=tuple(warnings)
    )
