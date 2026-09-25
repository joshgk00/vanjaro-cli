"""Deterministic three-breakpoint visual quality gate.

This module does not capture screenshots or calculate perceptual similarity by
itself.  It validates caller-supplied screenshot pairs and scores, or invokes
injected capture/score hooks.  Keeping browser and vision dependencies behind
hooks makes the gate fully offline-testable and reusable by CLI, benchmark, or
portal harness callers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from enum import Enum
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vanjaro_cli.design.models import BreakpointName, Viewport

__all__ = [
    "CANONICAL_VIEWPORTS",
    "CaptureHook",
    "CaptureImage",
    "CaptureStability",
    "GateFailure",
    "GateLevel",
    "ScoreHook",
    "SectionAggregateScore",
    "SectionVisualScore",
    "StaticCaptureSource",
    "SystemicVisualFinding",
    "VisualFindingSeverity",
    "VisualGateInputError",
    "VisualGatePolicy",
    "VisualGateResult",
    "ViewportCapturePair",
    "ViewportVisualScore",
    "evaluate_visual_gate",
    "resolve_visual_captures",
    "run_visual_quality_gate",
    "serialize_visual_gate_result",
]


class _GateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GateLevel(str, Enum):
    DRAFT = "draft"
    SHIP = "ship"


class VisualFindingSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


CANONICAL_VIEWPORTS: dict[BreakpointName, Viewport] = {
    BreakpointName.DESKTOP: Viewport(width=1440, height=900),
    BreakpointName.TABLET: Viewport(width=768, height=1024),
    BreakpointName.MOBILE: Viewport(width=390, height=844),
}
_BREAKPOINT_ORDER = {
    BreakpointName.DESKTOP: 0,
    BreakpointName.TABLET: 1,
    BreakpointName.MOBILE: 2,
}


class VisualGateInputError(ValueError):
    """Raised when captures or scores are incomplete, unstable, or mismatched."""

    def __init__(self, issues: Iterable[str]):
        self.issues = tuple(issues)
        super().__init__("Visual gate input is invalid:\n- " + "\n- ".join(self.issues))


class CaptureStability(_GateModel):
    """Evidence that a screenshot was stable before image capture."""

    lazy_load_triggered: bool
    fonts_settled: bool
    animations_disabled: bool

    @property
    def settled(self) -> bool:
        return self.lazy_load_triggered and self.fonts_settled and self.animations_disabled


class CaptureImage(_GateModel):
    """One source or migrated-output screenshot and its settle evidence."""

    path: Path
    stability: CaptureStability


class StaticCaptureSource(_GateModel):
    """A static (image/Figma) capture source, never a browser render.

    Only a caller that has already re-validated this source's identity,
    containment, and hash against the current design (the capture planner in
    `orchestration.project_capture_plan`) may construct one -- `validated`
    has no other value, so it can never be defaulted into existence the way
    a fabricated `CaptureStability` could. A static source has no settlement
    evidence, and none is invented here: it is simply absent from this type.
    """

    source_kind: Literal["image", "figma"]
    path: Path
    sha256: str = Field(min_length=64, max_length=64)
    validated: Literal[True] = True


class ViewportCapturePair(_GateModel):
    """Source/output screenshots captured at one canonical breakpoint."""

    breakpoint: BreakpointName
    viewport: Viewport
    source: CaptureImage | StaticCaptureSource
    output: CaptureImage
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class SectionVisualScore(_GateModel):
    section_id: str = Field(min_length=1)
    score: float = Field(ge=0, le=100)


class ViewportVisualScore(_GateModel):
    """Per-section and page score returned by a caller's scoring engine."""

    breakpoint: BreakpointName
    overall_score: float = Field(ge=0, le=100)
    sections: tuple[SectionVisualScore, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_sections(self) -> "ViewportVisualScore":
        identifiers = [section.section_id.casefold() for section in self.sections]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("section IDs must be unique within a viewport score")
        return self


class SystemicVisualFinding(_GateModel):
    id: str = Field(min_length=1)
    severity: VisualFindingSeverity
    issue: str = Field(min_length=1)
    pipeline_stage: str | None = None


class VisualGatePolicy(_GateModel):
    """Thresholds from REQ-QA-004, configurable for explicit policy changes."""

    draft_overall_minimum: float = Field(default=75, ge=0, le=100)
    draft_section_minimum: float = Field(default=60, ge=0, le=100)
    ship_overall_minimum: float = Field(default=85, ge=0, le=100)
    ship_section_minimum: float = Field(default=75, ge=0, le=100)
    ship_mobile_minimum: float = Field(default=75, ge=0, le=100)
    ship_blocks_high_systemic: bool = True


class GateFailure(_GateModel):
    code: Literal[
        "overall_score_below_threshold",
        "section_score_below_threshold",
        "mobile_score_below_threshold",
        "high_systemic_finding",
    ]
    message: str = Field(min_length=1)
    observed: float | str
    required: float | str
    breakpoint: BreakpointName | None = None
    section_id: str | None = None
    finding_id: str | None = None


class SectionAggregateScore(_GateModel):
    section_id: str = Field(min_length=1)
    score: float = Field(ge=0, le=100)
    viewport_scores: dict[BreakpointName, float]


class VisualGateResult(_GateModel):
    schema_version: Literal["1.0"] = "1.0"
    level: GateLevel
    passed: bool
    overall_score: float = Field(ge=0, le=100)
    viewport_scores: tuple[ViewportVisualScore, ...]
    section_scores: tuple[SectionAggregateScore, ...]
    findings: tuple[SystemicVisualFinding, ...]
    failures: tuple[GateFailure, ...]
    policy: VisualGatePolicy

    @model_validator(mode="after")
    def result_consistency(self) -> "VisualGateResult":
        if self.passed == bool(self.failures):
            raise ValueError("passed must be true exactly when failures is empty")
        return self


CaptureHook = Callable[[BreakpointName, Viewport], ViewportCapturePair]
ScoreHook = Callable[[ViewportCapturePair], ViewportVisualScore]


def _validate_complete_breakpoints(values: Iterable[BreakpointName], label: str) -> None:
    values_list = list(values)
    duplicates = sorted(
        {item.value for item in values_list if values_list.count(item) > 1}
    )
    present = set(values_list)
    missing = [item.value for item in CANONICAL_VIEWPORTS if item not in present]
    unexpected = sorted(item.value for item in present if item not in CANONICAL_VIEWPORTS)
    issues = []
    if duplicates:
        issues.append(f"{label} contains duplicate breakpoints: {', '.join(duplicates)}")
    if missing:
        issues.append(f"{label} is missing required breakpoints: {', '.join(missing)}")
    if unexpected:
        issues.append(f"{label} contains unsupported breakpoints: {', '.join(unexpected)}")
    if issues:
        raise VisualGateInputError(issues)


def _validate_capture_image(
    breakpoint: BreakpointName, label: str, image: CaptureImage, *, require_files: bool
) -> list[str]:
    issues: list[str] = []
    if require_files and not image.path.is_file():
        issues.append(f"{breakpoint.value} {label} image does not exist: {image.path}")
    if not image.stability.lazy_load_triggered:
        issues.append(f"{breakpoint.value} {label} capture did not trigger lazy loading")
    if not image.stability.fonts_settled:
        issues.append(f"{breakpoint.value} {label} capture did not settle fonts")
    if not image.stability.animations_disabled:
        issues.append(f"{breakpoint.value} {label} capture did not disable animations")
    return issues


def _validate_capture(capture: ViewportCapturePair, *, require_files: bool) -> list[str]:
    issues: list[str] = []
    expected = CANONICAL_VIEWPORTS[capture.breakpoint]
    if capture.viewport != expected:
        issues.append(
            f"{capture.breakpoint.value} viewport must be "
            f"{expected.width}x{expected.height}, got "
            f"{capture.viewport.width}x{capture.viewport.height}"
        )
    if isinstance(capture.source, StaticCaptureSource):
        # A validated static source carries no settlement evidence to check
        # -- it was never rendered -- only that its identified file exists.
        if require_files and not capture.source.path.is_file():
            issues.append(
                f"{capture.breakpoint.value} source image does not exist: {capture.source.path}"
            )
    else:
        issues.extend(
            _validate_capture_image(
                capture.breakpoint, "source", capture.source, require_files=require_files
            )
        )
    issues.extend(
        _validate_capture_image(
            capture.breakpoint, "output", capture.output, require_files=require_files
        )
    )
    return issues


def resolve_visual_captures(
    *,
    captures: Iterable[ViewportCapturePair] | None = None,
    capture_hook: CaptureHook | None = None,
    require_files: bool = True,
) -> tuple[ViewportCapturePair, ...]:
    """Resolve and validate a complete, settled three-breakpoint capture set."""

    if captures is not None and capture_hook is not None:
        raise VisualGateInputError(("pass captures or capture_hook, not both",))
    if captures is None and capture_hook is None:
        raise VisualGateInputError(("captures or capture_hook is required",))
    if capture_hook is not None:
        resolved = [
            capture_hook(breakpoint, CANONICAL_VIEWPORTS[breakpoint])
            for breakpoint in sorted(CANONICAL_VIEWPORTS, key=_BREAKPOINT_ORDER.get)
        ]
    else:
        resolved = list(captures or ())
    _validate_complete_breakpoints(
        (capture.breakpoint for capture in resolved), "capture set"
    )
    issues = [issue for capture in resolved for issue in _validate_capture(capture, require_files=require_files)]
    if issues:
        raise VisualGateInputError(issues)
    return tuple(sorted(resolved, key=lambda item: _BREAKPOINT_ORDER[item.breakpoint]))


def _resolve_scores(
    captures: tuple[ViewportCapturePair, ...],
    *,
    scores: Iterable[ViewportVisualScore] | None,
    score_hook: ScoreHook | None,
) -> tuple[ViewportVisualScore, ...]:
    if scores is not None and score_hook is not None:
        raise VisualGateInputError(("pass scores or score_hook, not both",))
    if scores is None and score_hook is None:
        raise VisualGateInputError(("scores or score_hook is required",))
    resolved = [score_hook(capture) for capture in captures] if score_hook else list(scores or ())
    _validate_complete_breakpoints((score.breakpoint for score in resolved), "score set")
    capture_breakpoints = {capture.breakpoint for capture in captures}
    score_breakpoints = {score.breakpoint for score in resolved}
    if capture_breakpoints != score_breakpoints:
        raise VisualGateInputError(("score breakpoints do not match capture breakpoints",))
    return tuple(sorted(resolved, key=lambda item: _BREAKPOINT_ORDER[item.breakpoint]))


def _mean(values: Iterable[float]) -> float:
    collected = list(values)
    return round(sum(collected) / len(collected), 2)


def _aggregate_sections(
    scores: tuple[ViewportVisualScore, ...],
) -> tuple[SectionAggregateScore, ...]:
    by_section: dict[str, dict[BreakpointName, float]] = {}
    canonical_ids: dict[str, str] = {}
    for viewport_score in scores:
        for section in viewport_score.sections:
            key = section.section_id.casefold()
            canonical_ids.setdefault(key, section.section_id)
            by_section.setdefault(key, {})[viewport_score.breakpoint] = section.score
    return tuple(
        SectionAggregateScore(
            section_id=canonical_ids[key],
            score=_mean(by_section[key].values()),
            viewport_scores={
                breakpoint: by_section[key][breakpoint]
                for breakpoint in sorted(by_section[key], key=_BREAKPOINT_ORDER.get)
            },
        )
        for key in sorted(by_section)
    )


def evaluate_visual_gate(
    captures: Iterable[ViewportCapturePair],
    scores: Iterable[ViewportVisualScore],
    *,
    level: GateLevel = GateLevel.DRAFT,
    findings: Iterable[SystemicVisualFinding] = (),
    policy: VisualGatePolicy | None = None,
    require_files: bool = True,
) -> VisualGateResult:
    """Validate inputs and apply draft or ship thresholds deterministically."""

    resolved_captures = resolve_visual_captures(
        captures=captures, require_files=require_files
    )
    resolved_scores = _resolve_scores(
        resolved_captures, scores=scores, score_hook=None
    )
    resolved_policy = policy or VisualGatePolicy()
    resolved_findings = tuple(sorted(findings, key=lambda item: item.id.casefold()))
    overall = _mean(score.overall_score for score in resolved_scores)
    section_minimum = (
        resolved_policy.draft_section_minimum
        if level == GateLevel.DRAFT
        else resolved_policy.ship_section_minimum
    )
    overall_minimum = (
        resolved_policy.draft_overall_minimum
        if level == GateLevel.DRAFT
        else resolved_policy.ship_overall_minimum
    )
    failures: list[GateFailure] = []
    if overall < overall_minimum:
        failures.append(GateFailure(
            code="overall_score_below_threshold",
            message=f"Overall score {overall:.2f} is below the {level.value} minimum {overall_minimum:.2f}.",
            observed=overall, required=overall_minimum,
        ))
    for viewport_score in resolved_scores:
        for section in sorted(viewport_score.sections, key=lambda item: item.section_id.casefold()):
            if section.score < section_minimum:
                failures.append(GateFailure(
                    code="section_score_below_threshold",
                    message=(
                        f"Section {section.section_id!r} scores {section.score:.2f} at "
                        f"{viewport_score.breakpoint.value}, below {section_minimum:.2f}."
                    ),
                    observed=section.score, required=section_minimum,
                    breakpoint=viewport_score.breakpoint, section_id=section.section_id,
                ))
    if level == GateLevel.SHIP:
        mobile = next(
            score for score in resolved_scores
            if score.breakpoint == BreakpointName.MOBILE
        )
        if mobile.overall_score < resolved_policy.ship_mobile_minimum:
            failures.append(GateFailure(
                code="mobile_score_below_threshold",
                message=(
                    f"Mobile overall score {mobile.overall_score:.2f} is below the ship "
                    f"minimum {resolved_policy.ship_mobile_minimum:.2f}."
                ),
                observed=mobile.overall_score,
                required=resolved_policy.ship_mobile_minimum,
                breakpoint=BreakpointName.MOBILE,
            ))
        if resolved_policy.ship_blocks_high_systemic:
            for finding in resolved_findings:
                if finding.severity == VisualFindingSeverity.HIGH:
                    failures.append(GateFailure(
                        code="high_systemic_finding",
                        message=f"High-severity systemic finding {finding.id!r} blocks shipment: {finding.issue}",
                        observed=finding.severity.value,
                        required="no high systemic finding",
                        finding_id=finding.id,
                    ))
    return VisualGateResult(
        level=level, passed=not failures, overall_score=overall,
        viewport_scores=resolved_scores,
        section_scores=_aggregate_sections(resolved_scores),
        findings=resolved_findings, failures=tuple(failures),
        policy=resolved_policy,
    )


def run_visual_quality_gate(
    *,
    captures: Iterable[ViewportCapturePair] | None = None,
    capture_hook: CaptureHook | None = None,
    scores: Iterable[ViewportVisualScore] | None = None,
    score_hook: ScoreHook | None = None,
    level: GateLevel = GateLevel.DRAFT,
    findings: Iterable[SystemicVisualFinding] = (),
    policy: VisualGatePolicy | None = None,
    require_files: bool = True,
) -> VisualGateResult:
    """Resolve capture/score hooks and evaluate the requested quality gate."""

    resolved_captures = resolve_visual_captures(
        captures=captures, capture_hook=capture_hook,
        require_files=require_files,
    )
    resolved_scores = _resolve_scores(
        resolved_captures, scores=scores, score_hook=score_hook
    )
    return evaluate_visual_gate(
        resolved_captures, resolved_scores, level=level,
        findings=findings, policy=policy, require_files=require_files,
    )


def serialize_visual_gate_result(
    result: VisualGateResult, *, indent: int = 2,
) -> str:
    """Serialize a gate result with stable ordering and a trailing newline."""

    return json.dumps(
        result.model_dump(mode="json", exclude_none=True),
        indent=indent, sort_keys=True, ensure_ascii=False,
    ) + "\n"
