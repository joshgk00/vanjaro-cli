"""Durable per-page capture evidence: record, then read-only validate.

`quality_counts.compute_quality_counts` needs a `{page_id: {breakpoints}}`
mapping to score `desktop_tablet_mobile_evidence` truthfully, and
`project_fidelity.evaluate_project_fidelity` needs the same per-page evidence
to score the visual fidelity gate across a whole workspace instead of one
page. Until now nothing produced or read either: `project_quality_cmd.py`
passed `{}`, and `project_fidelity_recording.py` could only ever hold one
page's evidence in a single fixed file (`qa/fidelity-evidence.json`),
silently discarding earlier pages when a second page was captured.

This module is the one place that owns that per-page store:

- `record_page_capture_evidence` writes one JSON record per page, named by a
  hash of the page id so an arbitrary page id (including opaque hashed
  section-derived ids) can never escape the evidence directory. Recording
  never fabricates a hash or a file: every screenshot it hashes must already
  exist, written by the actual capture step.
- `resolve_workspace_capture_coverage` is the read-only, zero-network,
  zero-write validator both `project_quality_cmd.py` and
  `project_verify.py` call so the two never duplicate this parsing or
  policy. It re-derives page identity from the *current*
  `plans/resolved-design-document.json` (never trusting a page id a record
  merely claims), re-hashes every screenshot, and re-checks local build
  artifact and target-identity binding before crediting a page. A record
  that fails any check earns zero credit for that page only; independent
  valid pages still count.

Capture coverage proves correspondence to recorded *local* build artifacts
on disk at capture time — never live portal freshness. A page whose evidence
was never bound to a local build artifact, or whose target identity was never
bound to a project manifest, earns no credit: this module never invents a
binding that was never recorded, and never credits a record it cannot verify
currency for. The design-document fingerprint compared at read time is the
sha256 of the *canonical* serialization of the currently resolved document
(`serialize_design_document`), not raw file bytes — so incidental JSON
whitespace or line-ending differences on disk never register as drift, while
an actual content change always does.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from vanjaro_cli.design.fidelity_evaluation import PageObservation
from vanjaro_cli.design.models import BreakpointName, DesignDocument
from vanjaro_cli.design.quality_counts import PageIdentityMap, resolve_page_identity
from vanjaro_cli.design.serialization import (
    DesignDocumentSerializationError,
    read_design_document,
    serialize_design_document,
)
from vanjaro_cli.design.visual_gate import CANONICAL_VIEWPORTS, ViewportCapturePair
from vanjaro_cli.project.models import ProjectManifest
from vanjaro_cli.reliability.artifacts import (
    ArtifactContractError,
    atomic_write_json,
    canonical_json_sha256,
    load_strict_json,
)
from vanjaro_cli.release.paths import _contains_link_or_reparse, _resolve_repository_path

__all__ = [
    "CAPTURE_EVIDENCE_DIRECTORY",
    "DESIGN_DOCUMENT_PATH",
    "SCHEMA_VERSION",
    "PageEvidenceValidation",
    "ProjectCaptureEvidenceError",
    "WorkspaceCaptureCoverage",
    "record_page_capture_evidence",
    "resolve_workspace_capture_coverage",
]

SCHEMA_VERSION = "capture-evidence-v1"
CAPTURE_EVIDENCE_DIRECTORY = "qa/capture-evidence"
DESIGN_DOCUMENT_PATH = "plans/resolved-design-document.json"
LEGACY_EVIDENCE_PATH = "qa/fidelity-evidence.json"
_BUILD_ARTIFACT_PATHS = (
    "build/page-manifest.json",
    "build/global-page-manifest.json",
    "build/global-block-manifest.json",
)
_CANONICAL_BREAKPOINTS = frozenset({"desktop", "tablet", "mobile"})
# Kept as a literal, not imported from `project_capture_v2`, so this module
# never needs a module-level import of it: `project_capture_v2` already
# imports several helpers *from* this module, and a module-level import back
# would be a real circular import, not just an ordering inconvenience.
_SCHEMA_VERSION_V2 = "capture-evidence-v2"


class ProjectCaptureEvidenceError(ValueError):
    """Raised when a recorder is asked to bind evidence to a file that does not exist."""


def _record_filename(page_id: str) -> str:
    return hashlib.sha256(page_id.encode("utf-8")).hexdigest() + ".json"


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _build_artifact_fingerprints(root: Path) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for relative in _BUILD_ARTIFACT_PATHS:
        path = root / relative
        if path.is_file():
            fingerprints[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return fingerprints


def _target_identity_fingerprint(manifest: ProjectManifest | None) -> str | None:
    if manifest is None:
        return None
    return canonical_json_sha256(manifest.target.model_dump(mode="json"))


def record_page_capture_evidence(
    root: Path,
    document: DesignDocument,
    *,
    page_id: str,
    source_url: str,
    built_url: str,
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
    pairs: Sequence[ViewportCapturePair],
    warnings: Iterable[str] = (),
    manifest: ProjectManifest | None = None,
) -> dict[str, Any]:
    """Write this page's durable evidence record, replacing any prior one.

    A full replace, not a merge: a partial recapture (fewer breakpoints than
    before) writes exactly the breakpoints it actually captured, so a stale
    complete set from an earlier capture can never survive alongside it.

    Every capture entry's screenshots must already exist on disk — this
    never invents a hash for a file it has not read.
    """

    captures: list[dict[str, Any]] = []
    for pair in pairs:
        for role, image in (("source", pair.source), ("output", pair.output)):
            if not image.path.is_file():
                raise ProjectCaptureEvidenceError(
                    f"{pair.breakpoint.value} {role} capture does not exist: {image.path}"
                )
        captures.append(
            {
                "breakpoint": pair.breakpoint.value,
                "source_path": _relative(pair.source.path, root),
                "output_path": _relative(pair.output.path, root),
                "source_sha256": hashlib.sha256(pair.source.path.read_bytes()).hexdigest(),
                "output_sha256": hashlib.sha256(pair.output.path.read_bytes()).hexdigest(),
                "lazy_load_triggered": bool(pair.source.stability.lazy_load_triggered),
                "fonts_settled": bool(pair.source.stability.fonts_settled),
                "animations_disabled": bool(pair.source.stability.animations_disabled),
            }
        )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "page_id": page_id,
        "source_url": source_url,
        "built_url": built_url,
        "design_document_sha256": hashlib.sha256(
            serialize_design_document(document).encode("utf-8")
        ).hexdigest(),
        "build_artifact_sha256": _build_artifact_fingerprints(root),
        "target_identity_sha256": _target_identity_fingerprint(manifest),
        "expected": dict(expected),
        "observed": dict(observed),
        "captures": captures,
        "warnings": list(warnings),
    }
    destination = root / CAPTURE_EVIDENCE_DIRECTORY / _record_filename(page_id)
    atomic_write_json(destination, payload)
    return payload


@dataclass(frozen=True)
class PageEvidenceValidation:
    """The verified outcome of reading one page's evidence record."""

    page_id: str
    valid: bool
    breakpoints: frozenset[str] = frozenset()
    payload: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()


def _reject(page_id: str | None, message: str) -> PageEvidenceValidation:
    label = page_id if page_id is not None else "?"
    return PageEvidenceValidation(
        page_id=page_id or "", valid=False, warnings=(f"page {label!r}: {message}",)
    )


def _validate_capture_entry(
    root: Path, page_id: str, entry: Any, seen: set[str]
) -> tuple[str | None, list[str]]:
    """Validate one capture entry; return its breakpoint if fully valid."""

    if not isinstance(entry, dict):
        return None, [f"page {page_id!r}: a capture entry is not an object"]
    breakpoint = entry.get("breakpoint")
    if not isinstance(breakpoint, str) or breakpoint not in _CANONICAL_BREAKPOINTS:
        return None, [f"page {page_id!r}: capture entry has an unknown breakpoint {breakpoint!r}"]
    if breakpoint in seen:
        return None, [f"page {page_id!r}: duplicate {breakpoint} capture entry; rejected"]

    issues: list[str] = []
    for flag in ("lazy_load_triggered", "fonts_settled", "animations_disabled"):
        value = entry.get(flag)
        if not isinstance(value, bool) or value is not True:
            issues.append(f"page {page_id!r}: {breakpoint} {flag} must be true, not {value!r}")

    for role, path_key, hash_key in (
        ("source", "source_path", "source_sha256"),
        ("output", "output_path", "output_sha256"),
    ):
        relative = entry.get(path_key)
        digest = entry.get(hash_key)
        if not isinstance(relative, str) or not relative or not isinstance(digest, str) or not digest:
            issues.append(f"page {page_id!r}: {breakpoint} {role} is missing a path or hash")
            continue
        resolved = _resolve_repository_path(root, relative, expected_type="file")
        if resolved is None:
            issues.append(
                f"page {page_id!r}: {breakpoint} {role} screenshot path is unsafe, a "
                f"symlink, or missing: {relative}"
            )
            continue
        try:
            observed_digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        except OSError as error:
            issues.append(f"page {page_id!r}: {breakpoint} {role} screenshot unreadable: {error}")
            continue
        if observed_digest != digest:
            issues.append(
                f"page {page_id!r}: {breakpoint} {role} screenshot changed since capture; "
                "recapture required"
            )

    if issues:
        return None, issues
    return breakpoint, []


def _validate_observation(
    page_id: str,
    breakpoint: str,
    role: str,
    raw: Any,
    valid_section_ids: frozenset[str],
    *,
    expected_viewport_width: float | None = None,
) -> tuple[PageObservation | None, list[str]]:
    """Validate one expected/observed entry against the real `PageObservation` model.

    A bare nonempty dict is not evidence: this rejects empty sections,
    duplicate or unowned section ids, and a wrong viewport width, the same
    way `project_fidelity.py`'s scoring path does, so the two never disagree
    about what counts as a real observation.

    `expected_viewport_width` lets a source-aware (v2) caller require the
    validated source reference's own declared width instead of the
    canonical breakpoint width; every v1 caller omits it and keeps the
    original canonical-only check.
    """

    if not isinstance(raw, dict) or not raw:
        return None, [f"page {page_id!r}: {breakpoint} has no {role} observation"]
    try:
        observation = PageObservation.model_validate(raw)
    except ValidationError as error:
        return None, [f"page {page_id!r}: {breakpoint} {role} observation is invalid: {error}"]

    canonical_width = (
        expected_viewport_width
        if expected_viewport_width is not None
        else float(CANONICAL_VIEWPORTS[BreakpointName(breakpoint)].width)
    )
    if observation.viewport_width != canonical_width:
        return None, [
            f"page {page_id!r}: {breakpoint} {role} observation viewport_width "
            f"{observation.viewport_width!r} does not match the canonical "
            f"{canonical_width!r} for {breakpoint}"
        ]

    section_ids = {section.section_id for section in observation.sections}
    unowned = sorted(section_ids - valid_section_ids)
    if unowned:
        return None, [
            f"page {page_id!r}: {breakpoint} {role} observation references sections "
            f"not owned by this page in the current design document: {unowned}"
        ]

    return observation, []


def _validate_record(
    root: Path,
    record_path: Path,
    *,
    current_page_ids: frozenset[str],
    page_section_ids: Mapping[str, frozenset[str]],
    document_sha256: str,
    build_artifact_sha256: Mapping[str, str],
    manifest: ProjectManifest | None,
) -> PageEvidenceValidation:
    label = record_path.name
    if _contains_link_or_reparse(record_path):
        return _reject(None, f"capture evidence record {label} is a symlink or reparse point")
    try:
        resolved_record = record_path.resolve()
        resolved_record.relative_to(root.resolve())
    except (OSError, ValueError):
        return _reject(None, f"capture evidence record {label} escapes the workspace")

    try:
        payload = load_strict_json(record_path)
    except ArtifactContractError as error:
        return _reject(None, f"capture evidence record {label} is malformed: {error}")
    if not isinstance(payload, dict):
        return _reject(None, f"capture evidence record {label} must contain a JSON object")

    page_id = payload.get("page_id")
    if not isinstance(page_id, str) or not page_id:
        return _reject(None, f"capture evidence record {label} has no valid page_id")
    if record_path.name != _record_filename(page_id):
        return _reject(page_id, f"record filename {label} does not match its page_id; rejected")
    if payload.get("schema_version") != SCHEMA_VERSION:
        return _reject(page_id, f"unsupported capture evidence schema {payload.get('schema_version')!r}")
    if page_id not in current_page_ids:
        return _reject(page_id, "not a page in the current resolved design document; rejected")
    if payload.get("design_document_sha256") != document_sha256:
        return _reject(page_id, "captured design document is stale; recapture required")

    warnings: list[str] = []
    recorded_build = payload.get("build_artifact_sha256")
    if not isinstance(recorded_build, dict) or not recorded_build:
        return _reject(
            page_id,
            "no local build artifact binding was recorded; recapture after a "
            "local build exists",
        )
    if not build_artifact_sha256:
        return _reject(
            page_id,
            "no current local build artifacts exist to verify against; build "
            "the workspace before this evidence can be trusted",
        )
    if dict(recorded_build) != dict(build_artifact_sha256):
        return _reject(page_id, "local build artifacts changed since capture; recapture required")

    recorded_target = payload.get("target_identity_sha256")
    if not isinstance(recorded_target, str) or not recorded_target:
        return _reject(
            page_id,
            "no target identity was recorded; recapture with a project manifest present",
        )
    if manifest is None:
        return _reject(
            page_id,
            "no current project manifest was supplied; target identity cannot be verified",
        )
    if recorded_target != _target_identity_fingerprint(manifest):
        return _reject(page_id, "recorded target identity no longer matches project.json")

    captures = payload.get("captures")
    expected = payload.get("expected")
    observed = payload.get("observed")
    if not isinstance(captures, list) or not captures:
        return _reject(page_id, "no captures recorded")
    if not isinstance(expected, dict) or not isinstance(observed, dict):
        return _reject(page_id, "expected/observed observations are missing or malformed")

    valid_section_ids = page_section_ids.get(page_id, frozenset())
    seen: set[str] = set()
    verified: set[str] = set()
    for entry in captures:
        breakpoint, issues = _validate_capture_entry(root, page_id, entry, seen)
        if issues:
            warnings.extend(issues)
            continue
        assert breakpoint is not None
        seen.add(breakpoint)
        _, expected_issues = _validate_observation(
            page_id, breakpoint, "expected", expected.get(breakpoint), valid_section_ids
        )
        _, observed_issues = _validate_observation(
            page_id, breakpoint, "observed", observed.get(breakpoint), valid_section_ids
        )
        if expected_issues or observed_issues:
            warnings.extend(expected_issues)
            warnings.extend(observed_issues)
            continue
        verified.add(breakpoint)

    if len(seen) != len(captures):
        # A rejected entry (duplicate, tampered, unpaired) taints the whole
        # page: partial trust would let a tampered breakpoint hide behind
        # two good ones.
        return PageEvidenceValidation(
            page_id=page_id, valid=False, warnings=tuple(warnings)
        )
    if not _CANONICAL_BREAKPOINTS <= verified:
        missing = sorted(_CANONICAL_BREAKPOINTS - verified)
        warnings.append(f"page {page_id!r}: incomplete breakpoint coverage, missing {missing}")
        return PageEvidenceValidation(
            page_id=page_id, valid=False, warnings=tuple(warnings)
        )

    return PageEvidenceValidation(
        page_id=page_id,
        valid=True,
        breakpoints=frozenset(verified),
        payload=payload,
        warnings=tuple(warnings),
    )


def _peek_schema_version(record_path: Path) -> str | None:
    """Cheap, side-effect-free read of just a record's `schema_version`.

    Used only to choose which validator reads a record next; the chosen
    validator re-reads and fully re-checks the file itself, so a malformed
    or unreadable file here just falls through to the v1 validator, which
    already reports it as malformed.
    """

    try:
        payload = load_strict_json(record_path)
    except ArtifactContractError:
        return None
    if isinstance(payload, dict):
        version = payload.get("schema_version")
        if isinstance(version, str):
            return version
    return None


@dataclass(frozen=True)
class WorkspaceCaptureCoverage:
    """The single read-only view both quality counting and the fidelity gate use."""

    page_identity: PageIdentityMap
    capture_evidence: dict[str, frozenset[str]] = field(default_factory=dict)
    valid_records: dict[str, dict[str, Any]] = field(default_factory=dict)
    v2_records: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


def resolve_workspace_capture_coverage(
    root: Path, manifest: ProjectManifest | None = None
) -> WorkspaceCaptureCoverage:
    """Read and validate every page's evidence record. Never writes, never calls out.

    Both `project_quality_cmd.py` and `project_verify.py` call this so page
    identity and capture validation are parsed and policed in exactly one
    place.
    """

    warnings: list[str] = []
    document_path = root / DESIGN_DOCUMENT_PATH
    if not document_path.is_file():
        warnings.append(
            f"no resolved design document at {DESIGN_DOCUMENT_PATH}; capture "
            "coverage cannot be attributed to real pages"
        )
        return WorkspaceCaptureCoverage(
            page_identity=PageIdentityMap(page_ids=(), section_page_ids={}),
            warnings=tuple(warnings),
        )
    try:
        document = read_design_document(document_path)
    except DesignDocumentSerializationError as error:
        warnings.append(f"cannot read {DESIGN_DOCUMENT_PATH}: {error}")
        return WorkspaceCaptureCoverage(
            page_identity=PageIdentityMap(page_ids=(), section_page_ids={}),
            warnings=tuple(warnings),
        )

    # Hash the canonical re-serialization of the *parsed* document, not the
    # raw file bytes: this must be the same fingerprint function the
    # recorder used, so incidental JSON whitespace or line-ending
    # differences on disk are never mistaken for design drift.
    document_sha256 = hashlib.sha256(
        serialize_design_document(document).encode("utf-8")
    ).hexdigest()
    page_identity = resolve_page_identity(document)
    current_page_ids = frozenset(page_identity.page_ids)
    page_section_ids = {
        page.id: frozenset(section.id for section in page.sections)
        for page in document.pages
    }
    build_artifact_sha256 = _build_artifact_fingerprints(root)

    evidence_dir = root / CAPTURE_EVIDENCE_DIRECTORY
    capture_evidence: dict[str, frozenset[str]] = {}
    valid_records: dict[str, dict[str, Any]] = {}
    v2_records: dict[str, Any] = {}
    if not evidence_dir.is_dir():
        warnings.append(
            f"no per-page capture evidence directory at {CAPTURE_EVIDENCE_DIRECTORY}; "
            "workspace capture coverage is 0 for every page"
        )
    else:
        for record_path in sorted(evidence_dir.glob("*.json")):
            if _peek_schema_version(record_path) == _SCHEMA_VERSION_V2:
                # Deferred import: `project_capture_v2` imports several
                # helpers from this module at its own module level, so this
                # module must never import it back at module level too.
                from vanjaro_cli.orchestration.project_capture_v2 import (
                    validate_page_capture_v2,
                )

                v2_result = validate_page_capture_v2(
                    root,
                    record_path,
                    document=document,
                    current_page_ids=current_page_ids,
                    page_section_ids=page_section_ids,
                    document_sha256=document_sha256,
                    build_artifact_sha256=build_artifact_sha256,
                    manifest=manifest,
                )
                warnings.extend(v2_result.warnings)
                if v2_result.record_valid:
                    v2_records[v2_result.page_id] = v2_result
                    canonical = v2_result.canonical_breakpoints()
                    if canonical:
                        capture_evidence[v2_result.page_id] = canonical
                continue

            result = _validate_record(
                root,
                record_path,
                current_page_ids=current_page_ids,
                page_section_ids=page_section_ids,
                document_sha256=document_sha256,
                build_artifact_sha256=build_artifact_sha256,
                manifest=manifest,
            )
            warnings.extend(result.warnings)
            if result.valid and result.payload is not None:
                capture_evidence[result.page_id] = result.breakpoints
                valid_records[result.page_id] = result.payload

    if not capture_evidence and (root / LEGACY_EVIDENCE_PATH).is_file():
        warnings.append(
            f"{LEGACY_EVIDENCE_PATH} exists but is a legacy single-page record; it is "
            "not used for authenticated workspace-wide capture coverage"
        )

    return WorkspaceCaptureCoverage(
        page_identity=page_identity,
        capture_evidence=capture_evidence,
        valid_records=valid_records,
        v2_records=v2_records,
        warnings=tuple(warnings),
    )
