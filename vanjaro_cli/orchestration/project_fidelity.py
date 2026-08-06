"""Run the deterministic visual fidelity gate during project verification.

Reads the fidelity evidence a project workspace has recorded, scores it with
the pure metrics, and applies the draft gate thresholds. The result becomes
part of `draft-verification.json`, which is already a fingerprinted stage
artifact, so a change in score invalidates any downstream publish approval
without extra machinery.

Absent evidence is a blocker, not a pass. A build nobody looked at is not a
build that looked right, and the release measures require desktop, tablet, and
mobile evidence for every release candidate. Reporting "not scored" as valid
would let an unmeasured build publish.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vanjaro_cli.design.fidelity import UnavailableScoreError
from vanjaro_cli.design.fidelity_evaluation import (
    PageObservation,
    score_hook_from_observations,
    score_section_fidelity,
)
from vanjaro_cli.design.models import BreakpointName
from vanjaro_cli.design.visual_gate import (
    CANONICAL_VIEWPORTS,
    CaptureImage,
    CaptureStability,
    GateLevel,
    ViewportCapturePair,
    VisualGateInputError,
    evaluate_visual_gate,
    serialize_visual_gate_result,
)

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


def evaluate_project_fidelity(root: Path) -> tuple[dict[str, Any], list[str]]:
    """Score recorded fidelity evidence and return its report and blockers.

    Returns a `(report, blockers)` pair. Blockers are non-empty whenever the
    build was not scored or failed the draft thresholds.
    """

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

    blockers = [
        f"visual fidelity gate failed: {failure['message']}"
        for failure in report.get("failures", [])
    ]
    return report, blockers


def _dimension_coverage(
    expected: dict[BreakpointName, Any],
    observed: dict[BreakpointName, Any],
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
            coverage[breakpoint.value] = round(
                sum(entry.dimension_coverage for entry in scores) / len(scores), 4
            )
    return coverage
