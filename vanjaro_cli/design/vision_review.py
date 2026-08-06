"""Advisory vision review over fidelity captures (VF-101, measurement Layer 2).

Findings diagnose; they never score. The primary fidelity number comes from the
deterministic metrics and must not depend on a language model, so nothing here
returns a score and no scoring module imports this one. What a reviewer adds is
the answer geometry cannot give: *why* a section looks wrong, and which pipeline
stage and file most likely caused it.

Provider output is untrusted. A model can name a section that does not exist, a
category that is not in the vocabulary, or a stage that was never run. Every one
of those is dropped with a warning rather than repaired, because a finding
pointing at the wrong section sends the work queue somewhere real work is not.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from vanjaro_cli.design.models import BreakpointName
from vanjaro_cli.design.reports import (
    FindingCategory,
    PipelineStage,
    ReportFinding,
    ReportSeverity,
)
from vanjaro_cli.design.fidelity_capture import CaptureOutcome


__all__ = [
    "VisionProvider",
    "VisionReviewOutcome",
    "VisionReviewRequest",
    "review_captures",
]


_BREAKPOINT_ORDER = {
    BreakpointName.DESKTOP: 0,
    BreakpointName.TABLET: 1,
    BreakpointName.MOBILE: 2,
}


class _VisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VisionReviewRequest(_VisionModel):
    """One breakpoint's captured pair plus the sections it may refer to."""

    page_id: str = Field(min_length=1)
    breakpoint: BreakpointName
    source_image: Path
    output_image: Path
    section_ids: tuple[str, ...]


class VisionProvider(Protocol):
    """Reviews one captured pair and returns raw, unvalidated findings."""

    def review(self, request: VisionReviewRequest) -> Sequence[Mapping[str, object]]:
        ...


class VisionReviewOutcome(_VisionModel):
    """Advisory findings and every reason a finding was dropped or missing.

    Deliberately carries no score, and no field any gate reads.
    """

    findings: tuple[ReportFinding, ...] = ()
    warnings: tuple[str, ...] = ()


def _enum_member(enum_type, raw: object):
    if isinstance(raw, enum_type):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return enum_type(raw.strip().casefold())
    except ValueError:
        return None


def _text(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    return value or None


def _finding_from_provider(
    raw: Mapping[str, object],
    request: VisionReviewRequest,
    index: int,
    warnings: list[str],
) -> ReportFinding | None:
    label = f"{request.page_id}/{request.breakpoint.value} finding {index + 1}"

    section_id = _text(raw.get("section_id"))
    if section_id is None or section_id not in request.section_ids:
        warnings.append(
            f"{label} named an unknown section {section_id!r}; the finding was dropped"
        )
        return None

    severity = _enum_member(ReportSeverity, raw.get("severity"))
    category = _enum_member(FindingCategory, raw.get("category"))
    stage = _enum_member(PipelineStage, raw.get("pipeline_stage"))
    missing = [
        name
        for name, value in (
            ("severity", severity),
            ("category", category),
            ("pipeline_stage", stage),
        )
        if value is None
    ]
    if missing:
        warnings.append(
            f"{label} used an unrecognized {', '.join(missing)}; the finding was dropped"
        )
        return None

    message = _text(raw.get("message"))
    recommendation = _text(raw.get("recommendation"))
    if message is None or recommendation is None:
        warnings.append(
            f"{label} carried no message or recommendation; the finding was dropped"
        )
        return None

    return ReportFinding(
        id=f"vision-{request.page_id}-{request.breakpoint.value}-{index + 1}",
        severity=severity,
        category=category,
        message=message,
        recommendation=recommendation,
        pipeline_stage=stage,
        section_id=section_id,
        breakpoint=request.breakpoint,
        source_file=_text(raw.get("source_file")),
    )


def review_captures(
    outcome: CaptureOutcome,
    provider: VisionProvider,
    *,
    page_id: str,
    section_ids: Sequence[str],
) -> VisionReviewOutcome:
    """Review every captured breakpoint and return advisory findings only.

    A provider failure at one breakpoint costs that breakpoint's findings and
    nothing else. It never raises, because a diagnostic layer that can fail the
    run would make an advisory signal load-bearing.
    """

    known_sections = tuple(dict.fromkeys(section_ids))
    findings: list[ReportFinding] = []
    warnings: list[str] = []

    for pair in sorted(
        outcome.pairs, key=lambda item: _BREAKPOINT_ORDER.get(item.breakpoint, 99)
    ):
        request = VisionReviewRequest(
            page_id=page_id,
            breakpoint=pair.breakpoint,
            source_image=Path(pair.source.path),
            output_image=Path(pair.output.path),
            section_ids=known_sections,
        )
        try:
            raw_findings = provider.review(request)
        except Exception as exc:  # noqa: BLE001 - any provider failure is advisory
            warnings.append(
                f"vision review failed at {pair.breakpoint.value}: {exc}; "
                "no findings were recorded for that breakpoint"
            )
            continue
        if not isinstance(raw_findings, Sequence) or isinstance(raw_findings, (str, bytes)):
            warnings.append(
                f"vision review at {pair.breakpoint.value} returned no finding list; "
                "no findings were recorded for that breakpoint"
            )
            continue
        for index, raw in enumerate(raw_findings):
            if not isinstance(raw, Mapping):
                warnings.append(
                    f"{page_id}/{pair.breakpoint.value} finding {index + 1} was not an "
                    "object; the finding was dropped"
                )
                continue
            finding = _finding_from_provider(raw, request, index, warnings)
            if finding is not None:
                findings.append(finding)

    for breakpoint in outcome.failed_breakpoints:
        warnings.append(
            f"no capture at {breakpoint.value}, so it was not reviewed"
        )

    return VisionReviewOutcome(findings=tuple(findings), warnings=tuple(warnings))
