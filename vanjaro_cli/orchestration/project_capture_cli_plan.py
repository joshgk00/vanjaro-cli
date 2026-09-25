"""Pure planning for `vanjaro project capture`: loading, references, and routes.

This module is the orchestration layer the operator-facing Click command
delegates to. It never launches a browser, never loads portal credentials,
and never contacts a portal -- the only I/O it performs is reading the
project's own local workspace files (`project.json`,
`plans/resolved-design-document.json`, `build/page-manifest.json`, and an
operator-supplied `--references` document). Read-only local static-reference
file validation is delegated entirely to
`vanjaro_cli.orchestration.project_capture_plan.plan_project_capture`; this
module never reimplements that check.

Route resolution reuses `design/capture_session.py`'s own URL-safety helpers
(`_require_within_allowed_base`) for both an explicit `--built-url` override
and a route built from the managed page manifest's server-returned `path` --
one shared implementation of "reject credentials, malformed ports, encoded
traversal, backslashes, and cross-origin/child-path escapes" rather than a
second one drifting out of sync with the capture primitive's own contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vanjaro_cli.design.capture_references import (
    CanvasInterpretation,
    InvalidReferenceError,
    LiveReference,
    SourceReference,
    StaticReference,
    StaticSourceKind,
)
from vanjaro_cli.design.capture_session import (
    CaptureSessionError,
    CaptureSessionErrorCode,
    _require_within_allowed_base,
)
from vanjaro_cli.design.models import BreakpointName, DesignDocument
from vanjaro_cli.design.quality_counts import resolve_page_identity
from vanjaro_cli.design.serialization import (
    DesignDocumentSerializationError,
    read_design_document,
)
from vanjaro_cli.orchestration.image_acquisition import (
    ImageAcquisitionError,
    resolve_workspace_file,
)
from vanjaro_cli.orchestration.project_capture_plan import (
    BreakpointCapturePlan,
    ProjectCapturePlan,
    plan_project_capture,
)
from vanjaro_cli.project.models import ProjectManifest
from vanjaro_cli.reliability.artifacts import ArtifactContractError, load_strict_json
from vanjaro_cli.reliability.diagnostics import redact_diagnostic_text

__all__ = [
    "CAPTURE_REFERENCES_SCHEMA_VERSION",
    "DESIGN_DOCUMENT_RELATIVE_PATH",
    "PAGE_MANIFEST_RELATIVE_PATH",
    "CapturePlanError",
    "CaptureReferenceDecodeError",
    "CaptureCliPlan",
    "ManagedPageRecord",
    "SelectedPageRoute",
    "build_capture_cli_plan",
    "decode_capture_references",
    "describe_page_capture_result",
    "load_managed_page_manifest",
    "load_resolved_design_document",
    "page_capture_succeeded",
    "parse_built_url_overrides",
    "render_dry_run_preview",
    "resolve_references_path",
    "summarize_capture_results",
]

CAPTURE_REFERENCES_SCHEMA_VERSION = "capture-references-v1"
DESIGN_DOCUMENT_RELATIVE_PATH = Path("plans/resolved-design-document.json")
PAGE_MANIFEST_RELATIVE_PATH = Path("build/page-manifest.json")

_LIVE_REFERENCE_KEYS = frozenset(
    {"kind", "page_id", "breakpoint", "url", "viewport_width", "viewport_height"}
)
_STATIC_REFERENCE_KEYS = frozenset(
    {
        "kind",
        "page_id",
        "breakpoint",
        "source_kind",
        "local_path",
        "sha256",
        "canvas_width",
        "canvas_height",
        "viewport_width",
        "viewport_height",
        "interpretation",
        "file_key",
        "frame_node_id",
    }
)


class CapturePlanError(ValueError):
    """A page-selection, target, or route-mapping failure blocking capture.

    Always raised before any browser or portal access -- unknown/ambiguous
    page identity, a malformed or duplicate managed page mapping, an
    unpinned target, or an unsafe built route are all diagnosed here.
    """


class CaptureReferenceDecodeError(ValueError):
    """The `--references` document does not decode into stable reference contracts."""


@dataclass(frozen=True, slots=True)
class ManagedPageRecord:
    """One `build/page-manifest.json` row: opaque design key to DNN page identity."""

    key: str
    dnn_page_id: int
    path: str | None


@dataclass(frozen=True, slots=True)
class SelectedPageRoute:
    """One chosen page's resolved, safety-checked built-output URL."""

    page_id: str
    dnn_page_id: int
    built_url: str
    built_url_source: str  # "managed_path" | "explicit_override"


@dataclass(frozen=True, slots=True)
class CaptureCliPlan:
    """The complete, read-only preview: target identity, routes, and reference plan."""

    target_base_url: str
    target_portal_id: int
    routes: tuple[SelectedPageRoute, ...]
    capture_plan: ProjectCapturePlan
    diagnostics: tuple[str, ...] = field(default_factory=tuple)


def load_resolved_design_document(root: Path) -> DesignDocument:
    """Read `plans/resolved-design-document.json`, wrapping failures as `CapturePlanError`."""

    path = root / DESIGN_DOCUMENT_RELATIVE_PATH
    try:
        return read_design_document(path)
    except DesignDocumentSerializationError as error:
        raise CapturePlanError(
            f"cannot read {DESIGN_DOCUMENT_RELATIVE_PATH.as_posix()}: {error}"
        ) from None


def resolve_references_path(root: Path, reference: Path | str) -> Path:
    """Resolve `--references` against `root`, rejecting any workspace escape.

    Relative paths are resolved against `root` -- never the process cwd --
    and containment is checked after symlink resolution, before the caller
    ever opens the file: an out-of-workspace path fails here whether it is
    absolute, a relative `..` escape, or a workspace-local symlink that
    resolves outside `root`. An absolute path that resolves inside the
    workspace is allowed. Containment is never inferred from a JSON parse
    failure or from the file simply not existing -- both of those are
    reported as separate, later failures via `resolve_workspace_file`, after
    this containment check has already passed.
    """

    try:
        absolute, _relative = resolve_workspace_file(
            root, str(reference), source_id="--references", label="references file"
        )
    except ImageAcquisitionError as error:
        raise CapturePlanError(redact_diagnostic_text(str(error))) from None
    return absolute


def load_managed_page_manifest(root: Path) -> dict[str, ManagedPageRecord]:
    """Strictly load `build/page-manifest.json`, keyed by opaque design page id.

    A malformed row (no `key`, no positive-int `page_id`) or a duplicate
    `key` is a diagnostic failure for the whole manifest, before any page is
    selected -- a partially-untrustworthy manifest can never be presumed
    trustworthy for the pages it did not go wrong on.
    """

    label = PAGE_MANIFEST_RELATIVE_PATH.as_posix()
    path = root / PAGE_MANIFEST_RELATIVE_PATH
    try:
        payload = load_strict_json(path)
    except ArtifactContractError as error:
        raise CapturePlanError(f"cannot read {label}: {error}") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("pages"), list):
        raise CapturePlanError(f"{label} has an unexpected shape")

    records: dict[str, ManagedPageRecord] = {}
    for index, raw in enumerate(payload["pages"]):
        if not isinstance(raw, dict):
            raise CapturePlanError(f"{label} pages[{index}] must be an object")
        key = raw.get("key")
        if not isinstance(key, str) or not key.strip():
            raise CapturePlanError(f"{label} pages[{index}] has no valid key")
        dnn_page_id = raw.get("page_id")
        if isinstance(dnn_page_id, bool) or not isinstance(dnn_page_id, int) or dnn_page_id <= 0:
            raise CapturePlanError(
                f"{label} page {key!r} has a malformed DNN page ID"
            )
        if key in records:
            raise CapturePlanError(
                f"{label} has more than one managed mapping for page {key!r}; ambiguous"
            )
        raw_path = raw.get("path")
        records[key] = ManagedPageRecord(
            key=key,
            dnn_page_id=dnn_page_id,
            path=raw_path if isinstance(raw_path, str) else None,
        )
    return records


def parse_built_url_overrides(specs: Sequence[str]) -> dict[str, str]:
    """Parse repeatable `PAGE_ID=URL` overrides; reject duplicates before routing."""

    overrides: dict[str, str] = {}
    for spec in specs:
        page_id, separator, url = spec.partition("=")
        page_id = page_id.strip()
        url = url.strip()
        if not separator or not page_id or not url:
            raise CapturePlanError("--built-url must be PAGE_ID=URL")
        if page_id in overrides:
            raise CapturePlanError(f"--built-url given more than once for page {page_id!r}")
        overrides[page_id] = url
    return overrides


def _decode_breakpoint(raw: Mapping[str, Any], index: int) -> BreakpointName:
    value = raw.get("breakpoint")
    try:
        return BreakpointName(value)
    except ValueError:
        raise CaptureReferenceDecodeError(
            f"references[{index}] has an unknown breakpoint {value!r}"
        ) from None


def _decode_live_reference(raw: Mapping[str, Any], index: int) -> LiveReference:
    unknown = set(raw) - _LIVE_REFERENCE_KEYS
    if unknown:
        raise CaptureReferenceDecodeError(
            f"references[{index}] has unknown fields: {sorted(unknown)}"
        )
    breakpoint_name = _decode_breakpoint(raw, index)
    try:
        return LiveReference(
            page_id=raw.get("page_id"),
            breakpoint=breakpoint_name,
            url=raw.get("url"),
            viewport_width=raw.get("viewport_width"),
            viewport_height=raw.get("viewport_height"),
        )
    except InvalidReferenceError as error:
        raise CaptureReferenceDecodeError(f"references[{index}] is invalid: {error}") from None


def _decode_static_reference(raw: Mapping[str, Any], index: int) -> StaticReference:
    unknown = set(raw) - _STATIC_REFERENCE_KEYS
    if unknown:
        raise CaptureReferenceDecodeError(
            f"references[{index}] has unknown fields: {sorted(unknown)}"
        )
    breakpoint_name = _decode_breakpoint(raw, index)
    source_kind_raw = raw.get("source_kind")
    try:
        source_kind = StaticSourceKind(source_kind_raw)
    except ValueError:
        raise CaptureReferenceDecodeError(
            f"references[{index}] has an unknown source_kind {source_kind_raw!r}"
        ) from None
    interpretation_raw = raw.get("interpretation")
    try:
        interpretation = CanvasInterpretation(interpretation_raw)
    except ValueError:
        raise CaptureReferenceDecodeError(
            f"references[{index}] has an unknown interpretation {interpretation_raw!r}"
        ) from None
    try:
        return StaticReference(
            page_id=raw.get("page_id"),
            breakpoint=breakpoint_name,
            source_kind=source_kind,
            local_path=raw.get("local_path"),
            sha256=raw.get("sha256"),
            canvas_width=raw.get("canvas_width"),
            canvas_height=raw.get("canvas_height"),
            viewport_width=raw.get("viewport_width"),
            viewport_height=raw.get("viewport_height"),
            interpretation=interpretation,
            file_key=raw.get("file_key"),
            frame_node_id=raw.get("frame_node_id"),
        )
    except InvalidReferenceError as error:
        raise CaptureReferenceDecodeError(f"references[{index}] is invalid: {error}") from None


def decode_capture_references(payload: object) -> tuple[SourceReference, ...]:
    """Strictly decode a `capture-references-v1` document into stable reference contracts.

    Every field decodes exactly into `LiveReference`/`StaticReference`
    construction -- an unknown top-level field, an unknown per-reference
    field, an unrecognized `kind`/`breakpoint`/`source_kind`/`interpretation`
    string, or a reference missing required ownership (a Figma export
    without `file_key`/`frame_node_id`) all fail decoding rather than
    silently dropping or defaulting a field. File existence, hash currency,
    and Figma ownership are never checked here -- that is
    `plan_project_capture`'s job, reused unchanged.
    """

    if not isinstance(payload, dict):
        raise CaptureReferenceDecodeError("references document must be a JSON object")
    if payload.get("schema_version") != CAPTURE_REFERENCES_SCHEMA_VERSION:
        raise CaptureReferenceDecodeError(
            "unsupported references schema_version "
            f"{payload.get('schema_version')!r}; expected "
            f"{CAPTURE_REFERENCES_SCHEMA_VERSION!r}"
        )
    unknown_top_level = set(payload) - {"schema_version", "references"}
    if unknown_top_level:
        raise CaptureReferenceDecodeError(
            f"references document has unknown top-level fields: {sorted(unknown_top_level)}"
        )
    raw_references = payload.get("references")
    if not isinstance(raw_references, list):
        raise CaptureReferenceDecodeError(
            "references document must contain a 'references' list"
        )

    decoded: list[SourceReference] = []
    for index, raw in enumerate(raw_references):
        if not isinstance(raw, dict):
            raise CaptureReferenceDecodeError(f"references[{index}] must be a JSON object")
        kind = raw.get("kind")
        if kind == "live":
            decoded.append(_decode_live_reference(raw, index))
        elif kind == "static":
            decoded.append(_decode_static_reference(raw, index))
        else:
            raise CaptureReferenceDecodeError(f"references[{index}] has an unknown kind {kind!r}")
    return tuple(decoded)


def _resolve_route_from_managed_path(
    base_url: str, raw_path: str | None, page_id: str
) -> str:
    if not raw_path or not raw_path.strip():
        raise CapturePlanError(
            f"page {page_id!r} has no managed route path; supply --built-url {page_id}=URL"
        )
    candidate = raw_path.strip()
    if candidate.startswith("http://") or candidate.startswith("https://"):
        built_url = candidate
    elif candidate.startswith("/"):
        built_url = base_url.rstrip("/") + candidate
    else:
        raise CapturePlanError(
            f"page {page_id!r} managed route path is ambiguous (not root-relative or "
            f"absolute); supply --built-url {page_id}=URL"
        )
    try:
        _require_within_allowed_base(
            built_url, base_url, code=CaptureSessionErrorCode.TARGET_REJECTED
        )
    except CaptureSessionError as error:
        raise CapturePlanError(
            f"page {page_id!r} managed route is outside the target base: {error}"
        ) from None
    return built_url


def _validate_explicit_built_url(url: str, base_url: str, page_id: str) -> str:
    try:
        _require_within_allowed_base(url, base_url, code=CaptureSessionErrorCode.TARGET_REJECTED)
    except CaptureSessionError as error:
        raise CapturePlanError(f"--built-url for page {page_id!r} is invalid: {error}") from None
    return url


def build_capture_cli_plan(
    root: Path,
    manifest: ProjectManifest,
    document: DesignDocument,
    *,
    requested_page_ids: Sequence[str] = (),
    built_url_overrides: Mapping[str, str] | None = None,
    references: Sequence[SourceReference] = (),
) -> CaptureCliPlan:
    """Resolve page selection, managed routes, and the reference plan -- purely and locally.

    Never contacts a portal or loads credentials: `manifest.target` supplies
    the pinned expected base URL and portal ID directly from the already-
    loaded project manifest, and `build/page-manifest.json` supplies the
    managed DNN page identity and server-returned path.
    """

    if manifest.target.expected_base_url is None or manifest.target.expected_portal_id is None:
        raise CapturePlanError(
            "project target must pin expected_base_url and expected_portal_id before capture"
        )
    target_base_url = manifest.target.expected_base_url
    target_portal_id = manifest.target.expected_portal_id
    built_url_overrides = built_url_overrides or {}

    identity = resolve_page_identity(document)
    known_page_ids = frozenset(identity.page_ids)

    if requested_page_ids:
        selected_ids: list[str] = []
        for page_id in requested_page_ids:
            if page_id not in known_page_ids:
                raise CapturePlanError(
                    f"unknown page id {page_id!r}; not present in the resolved design document"
                )
            if page_id not in selected_ids:
                selected_ids.append(page_id)
    else:
        selected_ids = list(identity.page_ids)

    if not selected_ids:
        raise CapturePlanError("no design pages are available to capture")

    unknown_overrides = sorted(set(built_url_overrides) - set(selected_ids))
    if unknown_overrides:
        raise CapturePlanError(
            f"--built-url given for page(s) not selected for capture: {unknown_overrides}"
        )

    managed_by_key = load_managed_page_manifest(root)

    routes: list[SelectedPageRoute] = []
    for page_id in selected_ids:
        record = managed_by_key.get(page_id)
        if record is None:
            raise CapturePlanError(
                f"page {page_id!r} has no managed page mapping in "
                f"{PAGE_MANIFEST_RELATIVE_PATH.as_posix()}; build or publish it first"
            )
        override = built_url_overrides.get(page_id)
        if override is not None:
            built_url = _validate_explicit_built_url(override, target_base_url, page_id)
            source = "explicit_override"
        else:
            built_url = _resolve_route_from_managed_path(target_base_url, record.path, page_id)
            source = "managed_path"
        routes.append(
            SelectedPageRoute(
                page_id=page_id,
                dnn_page_id=record.dnn_page_id,
                built_url=built_url,
                built_url_source=source,
            )
        )

    capture_plan = plan_project_capture(root, document, references=references)

    return CaptureCliPlan(
        target_base_url=target_base_url,
        target_portal_id=target_portal_id,
        routes=tuple(routes),
        capture_plan=capture_plan,
    )


def _reference_preview(reference: SourceReference | None) -> dict[str, Any] | None:
    if isinstance(reference, LiveReference):
        return {"kind": "live", "url": redact_diagnostic_text(reference.url)}
    if isinstance(reference, StaticReference):
        return {
            "kind": "static",
            "source_kind": reference.source_kind.value,
            "local_path": reference.local_path,
            "sha256": reference.sha256,
            "file_key": reference.file_key,
            "frame_node_id": reference.frame_node_id,
        }
    return None


def _breakpoint_preview(entry: BreakpointCapturePlan) -> dict[str, Any]:
    return {
        "breakpoint": entry.breakpoint.value,
        "status": entry.status.value,
        "reference": _reference_preview(entry.reference),
        "viewport": (
            {"width": entry.declared_viewport[0], "height": entry.declared_viewport[1]}
            if entry.declared_viewport is not None
            else None
        ),
        "is_canonical_viewport": entry.is_canonical_viewport,
        "diagnostics": list(entry.diagnostics),
    }


def render_dry_run_preview(manifest: ProjectManifest, plan: CaptureCliPlan) -> dict[str, Any]:
    """Build the local-only JSON preview: no network, browser, or credential access."""

    breakpoint_plans_by_page = {
        page_plan.page_id: page_plan for page_plan in plan.capture_plan.pages
    }
    pages_payload = []
    for route in plan.routes:
        page_plan = breakpoint_plans_by_page.get(route.page_id)
        pages_payload.append(
            {
                "page_id": route.page_id,
                "dnn_page_id": route.dnn_page_id,
                "built_url": redact_diagnostic_text(route.built_url),
                "built_url_source": route.built_url_source,
                "breakpoints": [
                    _breakpoint_preview(entry) for entry in (page_plan.breakpoints if page_plan else ())
                ],
            }
        )
    return {
        "status": "ok",
        "project_id": manifest.project.id,
        "dry_run": True,
        "target": {
            "base_url": redact_diagnostic_text(plan.target_base_url),
            "portal_id": plan.target_portal_id,
        },
        "pages": pages_payload,
        "diagnostics": list(plan.capture_plan.diagnostics),
    }


_PAGE_CAPTURE_SUCCESS_STATUSES = frozenset({"captured", "ok"})


def page_capture_succeeded(result: object) -> bool:
    """Narrow success check bound to the real collector's explicit contract.

    `project_capture_collect.collect_page_capture` reports one of
    ``"captured"`` (every breakpoint captured), ``"partial"`` or
    ``"failed"`` (some/all breakpoints missing), or ``"target_mismatch"`` /
    ``"page_not_found"`` (a preflight failure before any capture). Only
    ``"captured"`` is a real, complete success -- a partial or failed page
    is never upgraded to success just because some other page fully
    succeeded, and this function never claims a fidelity pass, only that
    capture completed. ``"ok"`` is also accepted as an explicitly supported
    legacy status for existing test doubles. Anything else -- an unknown
    status, a missing key, a non-mapping, or an exception raised by the
    collector (already turned into ``{"status": "error", ...}`` by the
    caller) -- is a failed page.
    """

    return (
        isinstance(result, Mapping) and result.get("status") in _PAGE_CAPTURE_SUCCESS_STATUSES
    )


def describe_page_capture_result(result: object) -> str:
    """The collector's own status word for human-readable output.

    Never collapses the real contract's distinct outcomes into a generic
    "FAILED" -- ``captured``, ``partial``, ``failed``, ``target_mismatch``,
    and ``page_not_found`` are all shown as reported. A result that is not a
    mapping with a string ``status`` (a malformed collector return) is
    reported as ``"malformed"`` rather than guessed at.
    """

    if isinstance(result, Mapping):
        status = result.get("status")
        if isinstance(status, str) and status:
            return status
    return "malformed"


def summarize_capture_results(page_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pure aggregation: an honest count, never a fidelity claim."""

    total = len(page_results)
    succeeded = sum(
        1 for entry in page_results if page_capture_succeeded(entry.get("result"))
    )
    return {
        "status": "ok" if total > 0 and succeeded == total else "error",
        "captured": succeeded,
        "total": total,
    }
