"""Score a project's recorded capture evidence against the visual fidelity gate.

Reads the per-page capture evidence a workspace has recorded, scores it with
the pure metrics, and applies the draft gate thresholds. Launch enforces the
result, because rendered evidence only exists after hidden publication.

Absent evidence is a blocker, not a pass. A build nobody looked at is not a
build that looked right, and the release measures require desktop, tablet, and
mobile evidence for every release candidate. Reporting "not scored" as valid
would let an unmeasured build go live.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vanjaro_cli.design.fidelity import UnavailableScoreError, to_viewport_visual_score
from vanjaro_cli.design.fidelity_evaluation import (
    PageObservation,
    score_breakpoint_fidelity,
    score_hook_from_observations,
    score_section_fidelity,
)
from vanjaro_cli.design.models import BreakpointName, Viewport
from vanjaro_cli.design.visual_gate import (
    CANONICAL_VIEWPORTS,
    CaptureImage,
    CaptureStability,
    GateLevel,
    StaticCaptureSource,
    ViewportCapturePair,
    VisualGateInputError,
    evaluate_visual_gate,
    serialize_visual_gate_result,
)
from vanjaro_cli.orchestration.project_capture_evidence import (
    CAPTURE_EVIDENCE_DIRECTORY,
    resolve_workspace_capture_coverage,
)
from vanjaro_cli.orchestration.project_capture_plan import REQUIRED_BREAKPOINTS
from vanjaro_cli.orchestration.project_capture_v2 import BreakpointV2Result, PageCaptureV2Validation
from vanjaro_cli.project.models import ProjectManifest

__all__ = [
    "FIDELITY_EVIDENCE_PATH",
    "ProjectFidelityError",
    "evaluate_project_fidelity",
]

FIDELITY_EVIDENCE_PATH = "qa/fidelity-evidence.json"


class ProjectFidelityError(ValueError):
    """Raised when recorded fidelity evidence is malformed."""


def _breakpoint(value: str, label: str) -> BreakpointName:
    try:
        return BreakpointName(value)
    except ValueError as error:
        raise ProjectFidelityError(
            f"{label} references unknown breakpoint {value!r}"
        ) from error


def _observations(
    payload: dict[str, Any], key: str
) -> dict[BreakpointName, PageObservation]:
    raw = payload.get(key)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ProjectFidelityError(f"{key} observations must be an object")
    result: dict[BreakpointName, PageObservation] = {}
    for name, value in raw.items():
        breakpoint = _breakpoint(name, f"{key} observations")
        try:
            result[breakpoint] = PageObservation.model_validate(value)
        except ValueError as error:
            raise ProjectFidelityError(
                f"{key} observations for {name} are invalid: {error}"
            ) from error
    return result


def _captures(payload: dict[str, Any], root: Path) -> tuple[ViewportCapturePair, ...]:
    raw = payload.get("captures")
    if not isinstance(raw, list) or not raw:
        return ()
    pairs: list[ViewportCapturePair] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ProjectFidelityError("each capture entry must be an object")
        breakpoint = _breakpoint(str(entry.get("breakpoint")), "captures")
        viewport = CANONICAL_VIEWPORTS.get(breakpoint)
        if viewport is None:
            raise ProjectFidelityError(
                f"capture for {breakpoint.value} is not a canonical gate viewport"
            )
        stability = CaptureStability(
            lazy_load_triggered=bool(entry.get("lazy_load_triggered")),
            fonts_settled=bool(entry.get("fonts_settled")),
            animations_disabled=bool(entry.get("animations_disabled")),
        )
        source = entry.get("source_path")
        output = entry.get("output_path")
        if not isinstance(source, str) or not isinstance(output, str):
            raise ProjectFidelityError(
                f"capture for {breakpoint.value} must name source and output paths"
            )
        pairs.append(
            ViewportCapturePair(
                breakpoint=breakpoint,
                viewport=viewport,
                source=CaptureImage(path=root / source, stability=stability),
                output=CaptureImage(path=root / output, stability=stability),
            )
        )
    return tuple(pairs)


def _not_scored(reason: str) -> tuple[dict[str, Any], list[str]]:
    return (
        {"status": "not_scored", "reason": reason},
        [f"visual fidelity was not scored: {reason}"],
    )


def evaluate_project_fidelity(
    root: Path, manifest: ProjectManifest | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Score recorded fidelity evidence and return its report and blockers.

    Returns a `(report, blockers)` pair. Blockers are non-empty whenever the
    build was not scored or failed the draft thresholds.

    When per-page evidence exists under `qa/capture-evidence/` (written by
    `record_project_fidelity_evidence`), every current design page is scored
    independently and a missing or stale page is a blocker on its own — this
    workspace-wide report is never satisfied by just the last page captured.
    Otherwise this falls back to the legacy single-file
    `qa/fidelity-evidence.json` reader, whose "scored" status reflects only
    that one page's evidence, not authenticated workspace-wide coverage.
    """

    evidence_dir = root / CAPTURE_EVIDENCE_DIRECTORY
    if evidence_dir.is_dir() and any(evidence_dir.glob("*.json")):
        return _evaluate_workspace_fidelity(root, manifest)
    return _evaluate_legacy_fidelity(root)


def _evaluate_legacy_fidelity(root: Path) -> tuple[dict[str, Any], list[str]]:
    evidence_path = root / FIDELITY_EVIDENCE_PATH
    if not evidence_path.exists():
        return _not_scored(
            f"no evidence recorded at {FIDELITY_EVIDENCE_PATH}"
        )

    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectFidelityError(
            f"{FIDELITY_EVIDENCE_PATH} could not be read: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise ProjectFidelityError(f"{FIDELITY_EVIDENCE_PATH} must contain an object")

    report, blockers = _score_payload(payload, root)
    report["legacy"] = True
    return report, blockers


def _evaluate_workspace_fidelity(
    root: Path, manifest: ProjectManifest | None
) -> tuple[dict[str, Any], list[str]]:
    coverage = resolve_workspace_capture_coverage(root, manifest)
    if not coverage.page_identity.page_ids:
        report, blockers = _not_scored(
            "; ".join(coverage.warnings) or "no current design pages could be resolved"
        )
        report["legacy"] = False
        return report, blockers

    pages: dict[str, Any] = {}
    blockers: list[str] = []
    scored_count = 0
    usable_count = 0
    for page_id in coverage.page_identity.page_ids:
        payload = coverage.valid_records.get(page_id)
        if payload is not None:
            try:
                page_report, page_blockers = _score_payload(payload, root)
            except ProjectFidelityError as error:
                # A record that reaches here has already passed
                # `_validate_record`'s checks, so this should not happen; if
                # it ever does, one page's malformed evidence must degrade to
                # a diagnosable zero-credit page, not crash the whole
                # workspace-wide report.
                page_report, page_blockers = _not_scored(str(error))
        else:
            v2 = coverage.v2_records.get(page_id)
            if v2 is not None:
                try:
                    page_report, page_blockers = _score_v2_page(v2, root)
                except (ProjectFidelityError, ValueError) as error:
                    page_report, page_blockers = _not_scored(str(error))
            else:
                reasons = [
                    warning
                    for warning in coverage.warnings
                    if warning.startswith(f"page {page_id!r}")
                ]
                reason = "; ".join(reasons) if reasons else "no current capture evidence recorded"
                page_report, page_blockers = _not_scored(reason)
        pages[page_id] = page_report
        if page_report["status"] == "scored":
            scored_count += 1
        if page_report["status"] in ("scored", "partially_scored"):
            usable_count += 1
        blockers.extend(f"page {page_id}: {message}" for message in page_blockers)

    if scored_count == len(pages):
        status = "scored"
    elif usable_count:
        status = "partially_scored"
    else:
        status = "not_scored"

    report = {
        "status": status,
        "legacy": False,
        "passed": status == "scored" and not blockers,
        "page_count": len(pages),
        "scored_page_count": scored_count,
        "pages": pages,
    }
    return report, blockers


def _score_payload(payload: dict[str, Any], root: Path) -> tuple[dict[str, Any], list[str]]:
    """Score one page's `expected`/`observed`/`captures` payload.

    Shared by the legacy single-page reader and the multi-page workspace
    reader so both reuse exactly the same scoring and capture validation.
    """

    expected = _observations(payload, "expected")
    observed = _observations(payload, "observed")
    if not expected or not observed:
        return _not_scored("evidence contains no design or build observations")

    captures = _captures(payload, root)
    if not captures:
        return _not_scored("evidence records no settled captures")

    try:
        result = evaluate_visual_gate(
            captures,
            scores=[score_hook_from_observations(expected, observed)(pair) for pair in captures],
            level=GateLevel.DRAFT,
        )
    except (VisualGateInputError, UnavailableScoreError, ValueError) as error:
        return _not_scored(str(error))

    report = json.loads(serialize_visual_gate_result(result))
    report["status"] = "scored"
    report["dimension_coverage"] = _dimension_coverage(expected, observed)
    report["evidence_coverage"] = _dimension_coverage(
        expected, observed, signal_level=True
    )

    blockers = [
        f"visual fidelity gate failed: {failure['message']}"
        for failure in report.get("failures", [])
    ]
    return report, blockers


def _rebuild_gate_source(result: BreakpointV2Result, root: Path) -> CaptureImage | StaticCaptureSource:
    """Rebuild one breakpoint's gate-ready source from its validated v2 result.

    Never fabricates settlement evidence: a live source's stability comes
    from what was actually recorded, and a static source carries none at
    all -- it is a `StaticCaptureSource`, which has no stability field to
    invent one into.
    """

    if result.source_kind == "static":
        return StaticCaptureSource(
            source_kind=result.static_source_kind,  # type: ignore[arg-type]
            path=root / (result.static_local_path or ""),
            sha256=result.source_sha256 or "",
        )
    stability = result.source_stability or {}
    return CaptureImage(
        path=root / (result.source_path or ""),
        stability=CaptureStability(
            lazy_load_triggered=bool(stability.get("lazy_load_triggered")),
            fonts_settled=bool(stability.get("fonts_settled")),
            animations_disabled=bool(stability.get("animations_disabled")),
        ),
    )


def _v2_release_completeness(v2: PageCaptureV2Validation) -> tuple[dict[str, Any], list[str]]:
    availability = {
        name: {
            "status": result.status,
            "valid": result.valid,
            "is_canonical": result.is_canonical,
            "viewport_width": result.viewport_width,
            "viewport_height": result.viewport_height,
            "source_kind": result.source_kind,
        }
        for name, result in v2.breakpoints.items()
    }
    missing_or_noncanonical = [
        breakpoint.value
        for breakpoint in REQUIRED_BREAKPOINTS
        if not (
            v2.breakpoints.get(breakpoint.value) is not None
            and v2.breakpoints[breakpoint.value].valid
            and v2.breakpoints[breakpoint.value].is_canonical
        )
    ]
    release_completeness = {
        "canonical_complete": not missing_or_noncanonical,
        "missing_or_noncanonical_breakpoints": missing_or_noncanonical,
        "viewport_availability": availability,
    }
    blockers = [
        f"{name}: release requires a canonical capture (status="
        f"{v2.breakpoints[name].status if name in v2.breakpoints else 'reference_not_declared'})"
        for name in missing_or_noncanonical
    ]
    return release_completeness, blockers


def _score_v2_page(v2: PageCaptureV2Validation, root: Path) -> tuple[dict[str, Any], list[str]]:
    """Score one page's `capture-evidence-v2` record.

    Every breakpoint the shared reader marked `valid` is scored with the
    same section metrics the legacy path uses, at its own actual viewport --
    canonical or not. When all three required breakpoints are both valid and
    canonical, this runs through the complete existing gate (thresholds and
    all), exactly like a legacy three-canonical page. Otherwise it scores
    only the available valid comparisons directly and reports release
    completeness separately: a missing or noncanonical breakpoint is always
    a release blocker, never papered over as a passing gate.
    """

    release_completeness, completeness_blockers = _v2_release_completeness(v2)
    canonical_complete = release_completeness["canonical_complete"]

    valid_breakpoints = {name: result for name, result in v2.breakpoints.items() if result.valid}
    if not valid_breakpoints:
        report, reason_blockers = _not_scored("no valid source-paired comparisons recorded")
        report["legacy"] = False
        report["schema_version"] = "capture-evidence-v2"
        report["release_completeness"] = release_completeness
        return report, reason_blockers + completeness_blockers

    expected: dict[BreakpointName, PageObservation] = {}
    observed: dict[BreakpointName, PageObservation] = {}
    for name, result in valid_breakpoints.items():
        breakpoint = BreakpointName(name)
        expected[breakpoint] = PageObservation.model_validate(result.expected)
        observed[breakpoint] = PageObservation.model_validate(result.observed)

    if canonical_complete:
        captures = []
        for breakpoint in REQUIRED_BREAKPOINTS:
            result = v2.breakpoints[breakpoint.value]
            viewport = Viewport(width=result.viewport_width, height=result.viewport_height)
            output_stability = result.output_stability or {}
            captures.append(
                ViewportCapturePair(
                    breakpoint=breakpoint,
                    viewport=viewport,
                    source=_rebuild_gate_source(result, root),
                    output=CaptureImage(
                        path=root / (result.output_path or ""),
                        stability=CaptureStability(
                            lazy_load_triggered=bool(output_stability.get("lazy_load_triggered")),
                            fonts_settled=bool(output_stability.get("fonts_settled")),
                            animations_disabled=bool(output_stability.get("animations_disabled")),
                        ),
                    ),
                )
            )
        try:
            gate_result = evaluate_visual_gate(
                captures,
                scores=[
                    score_hook_from_observations(expected, observed)(pair) for pair in captures
                ],
                level=GateLevel.DRAFT,
            )
        except (VisualGateInputError, UnavailableScoreError, ValueError) as error:
            report, _ = _not_scored(str(error))
            report["legacy"] = False
        else:
            report = json.loads(serialize_visual_gate_result(gate_result))
            report["status"] = "scored"
            report["legacy"] = False
    else:
        viewport_scores = [
            to_viewport_visual_score(
                score_breakpoint_fidelity(expected[breakpoint], observed[breakpoint], breakpoint=breakpoint)
            )
            for breakpoint in sorted(expected, key=lambda item: item.value)
        ]
        overall = (
            round(sum(score.overall_score for score in viewport_scores) / len(viewport_scores), 2)
            if viewport_scores
            else 0.0
        )
        report = {
            "status": "partially_scored",
            "legacy": False,
            "passed": False,
            "overall_score": overall,
            "viewport_scores": [score.model_dump(mode="json") for score in viewport_scores],
        }

    report["schema_version"] = "capture-evidence-v2"
    report["dimension_coverage"] = _dimension_coverage(expected, observed)
    report["evidence_coverage"] = _dimension_coverage(expected, observed, signal_level=True)
    report["release_completeness"] = release_completeness

    gate_blockers = [
        f"visual fidelity gate failed: {failure['message']}" for failure in report.get("failures", [])
    ]
    return report, gate_blockers + completeness_blockers


def _dimension_coverage(
    expected: dict[BreakpointName, Any],
    observed: dict[BreakpointName, Any],
    *,
    signal_level: bool = False,
) -> dict[str, float]:
    """Report how much of the regime each breakpoint's score was built from.

    A viewport score is a weighted mean over the dimensions that could be
    measured, renormalized so absent evidence never reads as a poor build. That
    is right for scoring and misleading for comparing: on this corpus the design
    side supplies geometry and spacing only at desktop, so tablet and mobile
    score higher on two dimensions than desktop does on four. Without this
    number, "mobile 83" reads as confidence when it means "we measured less".

    It matters most at mobile, which has its own floor on the ship gate.
    """

    coverage: dict[str, float] = {}
    for breakpoint, expected_page in expected.items():
        observed_page = observed.get(breakpoint)
        if observed_page is None:
            continue
        observed_by_id = {
            section.section_id: section for section in observed_page.sections
        }
        scores = [
            score_section_fidelity(
                section,
                observed_by_id.get(section.section_id),
                breakpoint=breakpoint,
                expected_viewport_width=expected_page.viewport_width,
                observed_viewport_width=observed_page.viewport_width,
                section_count=len(expected_page.sections),
            )
            for section in expected_page.sections
        ]
        if scores:
            values = [
                entry.evidence_coverage if signal_level else entry.dimension_coverage
                for entry in scores
            ]
            coverage[breakpoint.value] = round(sum(values) / len(values), 4)
    return coverage
