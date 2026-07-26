"""Deterministic maintainability and remediation reports.

Reports are derived offline from Composition Plan v2. Aggregate coverage from
the plan summary remains authoritative, while entry-level counts are recomputed
so stale summaries and policy violations become explicit findings.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from vanjaro_cli.design.composition import (
    BlockType,
    CompositionPlan,
    CompositionPlanEntry,
    IssueSeverity,
    SimplificationKind,
)
from vanjaro_cli.design.style_translation import StyleDecision, TranslationLayer

__all__ = [
    "FindingCategory",
    "FindingMatchContext",
    "FindingStyleContext",
    "MaintainabilityMetrics",
    "MaintainabilityReport",
    "MaintainabilityThresholds",
    "MetricDelta",
    "PipelineStage",
    "PromotionCandidate",
    "PromotionKind",
    "ReportFinding",
    "ReportSeverity",
    "TemplateUsage",
    "build_maintainability_report",
    "render_maintainability_report",
    "serialize_maintainability_report",
]


class _ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportSeverity(str, Enum):
    """Finding severity ordered from informational to release-blocking."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FindingCategory(str, Enum):
    """Maintainability concern families used by remediation tooling."""

    COVERAGE = "coverage"
    BLOCKING = "blocking"
    MATCH = "match"
    OVERRIDE = "override"
    TEMPLATE = "template"
    CUSTOM_CODE = "custom_code"
    CSS = "css"
    MODIFIER = "modifier"
    MANUAL_MODULE = "manual_module"
    STYLE = "style"
    WARNING = "warning"
    CONTRACT = "contract"


class PipelineStage(str, Enum):
    """Pipeline owner most likely responsible for a finding."""

    SOURCE_ANALYSIS = "source_analysis"
    TEMPLATE_MATCHING = "template_matching"
    COMPOSITION_PLANNING = "composition_planning"
    STYLE_TRANSLATION = "style_translation"
    MANUAL_IMPLEMENTATION = "manual_implementation"
    QUALITY_GATE = "quality_gate"


class PromotionKind(str, Enum):
    """Reusable library improvement suggested by repeated plan evidence."""

    MODIFIER = "modifier"
    AGENCY_UTILITY = "agency_utility"
    TEMPLATE = "template"


class MaintainabilityThresholds(_ReportModel):
    """Default agency gates from REQ-QA-006."""

    minimum_native_component_coverage: float = Field(default=0.90, ge=0, le=1)
    minimum_editable_content_coverage: float = Field(default=0.95, ge=0, le=1)
    maximum_custom_code_entries: int = Field(default=0, ge=0)
    maximum_blocking_entries: int = Field(default=0, ge=0)
    maximum_manual_modules: int = Field(default=0, ge=0)
    promotion_minimum_occurrences: int = Field(default=2, ge=2)


class TemplateUsage(_ReportModel):
    """Deterministic template reuse count."""

    template_id: str
    template_name: str
    count: int = Field(ge=1)
    section_ids: tuple[str, ...]


class MaintainabilityMetrics(_ReportModel):
    """Aggregate metrics required by the maintainability gate."""

    section_count: int = Field(ge=0)
    maintainability_score: float = Field(ge=0, le=100)
    native_component_coverage: float = Field(ge=0, le=1)
    editable_content_coverage: float = Field(ge=0, le=1)
    blocking_entry_count: int = Field(ge=0)
    blocking_entry_ids: tuple[str, ...]
    custom_block_count: int = Field(ge=0)
    global_block_count: int = Field(ge=0)
    new_template_count: int = Field(ge=0)
    custom_code_entry_count: int = Field(ge=0)
    custom_code_section_ids: tuple[str, ...]
    scoped_css_section_count: int = Field(ge=0)
    scoped_css_rule_count: int = Field(ge=0)
    scoped_css_bytes: int = Field(ge=0)
    unique_css_scope_count: int = Field(ge=0)
    css_scope_collision_count: int = Field(ge=0)
    css_scope_collision_section_ids: tuple[str, ...]
    modifier_assignment_count: int = Field(ge=0)
    reusable_modifier_count: int = Field(ge=0)
    unique_modifiers: tuple[str, ...]
    manual_module_count: int = Field(ge=0)
    manual_module_section_ids: tuple[str, ...]
    manual_override_count: int = Field(ge=0)
    manual_override_section_ids: tuple[str, ...]
    override_previous_candidate_count: int = Field(ge=0)
    template_reuse_ratio: float = Field(ge=0, le=1)
    template_usage: tuple[TemplateUsage, ...]


class FindingMatchContext(_ReportModel):
    """Selected-match evidence attached to a section finding."""

    template_id: str
    template_name: str
    score: float = Field(ge=0, le=1)
    confidence: Literal["high", "medium", "low"]
    blocking: bool


class FindingStyleContext(_ReportModel):
    """Style translation evidence attached to a finding."""

    property: str
    layer: str
    target: str
    source_value: str
    confidence: float = Field(ge=0, le=1)
    breakpoint: str | None = None


class ReportFinding(_ReportModel):
    """Actionable finding mapped to its source and pipeline owner."""

    id: str
    severity: ReportSeverity
    category: FindingCategory
    message: str
    recommendation: str
    pipeline_stage: PipelineStage
    section_id: str | None = None
    entry_id: str | None = None
    match: FindingMatchContext | None = None
    style_decision: FindingStyleContext | None = None
    source_ids: tuple[str, ...] = ()
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class PromotionCandidate(_ReportModel):
    """Repeated remediation evidence worth promoting into the shared library."""

    id: str
    kind: PromotionKind
    key: str
    occurrences: int = Field(ge=2)
    section_ids: tuple[str, ...]
    reason: str
    recommendation: str


class MetricDelta(_ReportModel):
    """Current-versus-prior metric change."""

    metric: str
    previous: float
    current: float
    delta: float
    direction: Literal["higher_is_better", "lower_is_better"]
    improved: bool


class MaintainabilityReport(_ReportModel):
    """Public deterministic maintainability report artifact."""

    schema_version: Literal["1.0"] = "1.0"
    source_document_id: str
    thresholds: MaintainabilityThresholds
    passes_gate: bool
    metrics: MaintainabilityMetrics
    findings: tuple[ReportFinding, ...]
    promotion_candidates: tuple[PromotionCandidate, ...]
    deltas: tuple[MetricDelta, ...] = ()


_SEVERITY_ORDER = {
    ReportSeverity.HIGH: 0,
    ReportSeverity.MEDIUM: 1,
    ReportSeverity.LOW: 2,
    ReportSeverity.INFO: 3,
}


def _match_context(entry: CompositionPlanEntry) -> FindingMatchContext:
    return FindingMatchContext(
        template_id=entry.template_id,
        template_name=entry.template,
        score=entry.match.score,
        confidence=entry.match.confidence,
        blocking=entry.match.blocking,
    )


def _style_context(decision: StyleDecision) -> FindingStyleContext:
    return FindingStyleContext(
        property=decision.property.value,
        layer=decision.layer.value,
        target=decision.target,
        source_value=decision.source_value,
        confidence=decision.confidence,
        breakpoint=decision.breakpoint.value if decision.breakpoint else None,
    )


def _finding(
    identifier: str,
    severity: ReportSeverity,
    category: FindingCategory,
    message: str,
    recommendation: str,
    stage: PipelineStage,
    *,
    entry: CompositionPlanEntry | None = None,
    style_decision: StyleDecision | None = None,
    source_ids: tuple[str, ...] = (),
    metadata: dict[str, JsonValue] | None = None,
) -> ReportFinding:
    return ReportFinding(
        id=identifier,
        severity=severity,
        category=category,
        message=message,
        recommendation=recommendation,
        pipeline_stage=stage,
        section_id=entry.source_section_id if entry else None,
        entry_id=entry.id if entry else None,
        match=_match_context(entry) if entry else None,
        style_decision=_style_context(style_decision) if style_decision else None,
        source_ids=source_ids,
        metadata=metadata or {},
    )


def _looks_like_custom_code(entry: CompositionPlanEntry) -> bool:
    values = (
        entry.template_id,
        entry.template,
        entry.block.name,
        entry.block.category,
    )
    normalized = " ".join(values).casefold().replace("_", "-")
    return "custom-code" in normalized or "raw-code" in normalized


def _css_bytes(entries: tuple[CompositionPlanEntry, ...]) -> int:
    return sum(
        len(
            json.dumps(
                entry.scoped_css,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        for entry in entries
    )


def _score(
    *,
    native_coverage: float,
    editable_coverage: float,
    custom_code_count: int,
    blocking_count: int,
    manual_module_count: int,
    css_rule_count: int,
    css_budget: int,
    section_count: int,
    thresholds: MaintainabilityThresholds,
) -> float:
    native = (
        1.0
        if thresholds.minimum_native_component_coverage == 0
        else min(1.0, native_coverage / thresholds.minimum_native_component_coverage)
    )
    editable = (
        1.0
        if thresholds.minimum_editable_content_coverage == 0
        else min(1.0, editable_coverage / thresholds.minimum_editable_content_coverage)
    )
    custom_code = 1.0 if custom_code_count <= thresholds.maximum_custom_code_entries else 0.0
    blocking = 1.0 if blocking_count <= thresholds.maximum_blocking_entries else 0.0
    manual = 1.0 if manual_module_count <= thresholds.maximum_manual_modules else 0.0
    total_css_budget = css_budget * section_count
    css = 1.0 if css_rule_count == 0 else (
        min(1.0, total_css_budget / css_rule_count) if total_css_budget else 0.0
    )
    return round(
        native * 35
        + editable * 35
        + custom_code * 10
        + blocking * 10
        + css * 5
        + manual * 5,
        2,
    )


def _promotion_candidates(
    plan: CompositionPlan,
    thresholds: MaintainabilityThresholds,
) -> tuple[PromotionCandidate, ...]:
    modifier_sections: dict[str, set[str]] = defaultdict(set)
    css_sections: dict[tuple[str, str], set[str]] = defaultdict(set)
    trait_sections: dict[str, set[str]] = defaultdict(set)

    for entry in plan.entries:
        for modifier in entry.modifiers:
            modifier_sections[modifier].add(entry.source_section_id)
        for property_name, value in entry.scoped_css.items():
            css_sections[(property_name, value)].add(entry.source_section_id)
        for simplification in entry.simplifications:
            if simplification.classification in {
                SimplificationKind.NEW_TEMPLATE,
                SimplificationKind.MANUAL_MODULE,
                SimplificationKind.MODIFIER,
            }:
                trait_sections[simplification.trait].add(entry.source_section_id)

    minimum = thresholds.promotion_minimum_occurrences
    candidates: list[PromotionCandidate] = []
    for modifier, sections in modifier_sections.items():
        if len(sections) < minimum:
            continue
        ordered_sections = tuple(sorted(sections))
        candidates.append(
            PromotionCandidate(
                id=f"modifier:{modifier}",
                kind=PromotionKind.MODIFIER,
                key=modifier,
                occurrences=len(sections),
                section_ids=ordered_sections,
                reason=f"Modifier {modifier!r} is used across {len(sections)} sections.",
                recommendation="Keep the modifier documented and covered by a shared visual regression fixture.",
            )
        )
    for (property_name, value), sections in css_sections.items():
        if len(sections) < minimum:
            continue
        ordered_sections = tuple(sorted(sections))
        key = f"{property_name}:{value}"
        candidates.append(
            PromotionCandidate(
                id=f"agency-utility:{property_name}:{value}",
                kind=PromotionKind.AGENCY_UTILITY,
                key=key,
                occurrences=len(sections),
                section_ids=ordered_sections,
                reason=f"The same scoped CSS declaration appears in {len(sections)} sections.",
                recommendation="Promote the declaration to a reviewed agency utility or template modifier.",
            )
        )
    for trait, sections in trait_sections.items():
        if len(sections) < minimum:
            continue
        ordered_sections = tuple(sorted(sections))
        candidates.append(
            PromotionCandidate(
                id=f"template:{trait}",
                kind=PromotionKind.TEMPLATE,
                key=trait,
                occurrences=len(sections),
                section_ids=ordered_sections,
                reason=f"The unresolved trait appears in {len(sections)} sections.",
                recommendation="Review the repeated trait for a shared template capability or modifier.",
            )
        )
    return tuple(sorted(candidates, key=lambda item: (item.kind.value, item.key, item.id)))


def _metric_deltas(
    current: MaintainabilityMetrics,
    prior: MaintainabilityReport | None,
) -> tuple[MetricDelta, ...]:
    if prior is None:
        return ()
    tracked = (
        ("maintainability_score", "higher_is_better"),
        ("native_component_coverage", "higher_is_better"),
        ("editable_content_coverage", "higher_is_better"),
        ("blocking_entry_count", "lower_is_better"),
        ("custom_code_entry_count", "lower_is_better"),
        ("scoped_css_rule_count", "lower_is_better"),
        ("scoped_css_bytes", "lower_is_better"),
        ("css_scope_collision_count", "lower_is_better"),
        ("manual_module_count", "lower_is_better"),
    )
    deltas: list[MetricDelta] = []
    for metric, direction in tracked:
        previous = float(getattr(prior.metrics, metric))
        value = float(getattr(current, metric))
        delta = round(value - previous, 4)
        improved = delta > 0 if direction == "higher_is_better" else delta < 0
        deltas.append(
            MetricDelta(
                metric=metric,
                previous=previous,
                current=value,
                delta=delta,
                direction=direction,
                improved=improved,
            )
        )
    return tuple(deltas)


def _entry_findings(plan: CompositionPlan) -> list[ReportFinding]:
    findings: list[ReportFinding] = []
    for entry in plan.entries:
        if entry.match.blocking:
            findings.append(
                _finding(
                    f"{entry.id}:blocking",
                    ReportSeverity.MEDIUM,
                    FindingCategory.BLOCKING,
                    "The section has a blocking template or simplification decision.",
                    "Resolve the blocking match, add a supported template, or explicitly approve a documented simplification.",
                    PipelineStage.COMPOSITION_PLANNING,
                    entry=entry,
                )
            )
        elif entry.match.confidence == "low":
            findings.append(
                _finding(
                    f"{entry.id}:low-match",
                    ReportSeverity.MEDIUM,
                    FindingCategory.MATCH,
                    f"Selected template confidence is low ({entry.match.score:.2f}).",
                    "Review the top alternatives or add template capability metadata before publishing.",
                    PipelineStage.TEMPLATE_MATCHING,
                    entry=entry,
                )
            )

        if entry.override_audit is not None:
            audit = entry.override_audit
            findings.append(
                _finding(
                    f"{entry.id}:override-audit",
                    ReportSeverity.INFO,
                    FindingCategory.OVERRIDE,
                    f"Template selection was manually overridden by {audit.author}.",
                    "Retain the audit when regenerating the plan and review whether the override should become reusable matching policy.",
                    PipelineStage.TEMPLATE_MATCHING,
                    entry=entry,
                    metadata={
                        "author": audit.author,
                        "reason": audit.reason,
                        "previous_candidates": [
                            candidate.model_dump(mode="json")
                            for candidate in audit.previous_candidates
                        ],
                    },
                )
            )

        if _looks_like_custom_code(entry):
            findings.append(
                _finding(
                    f"{entry.id}:custom-code",
                    ReportSeverity.MEDIUM,
                    FindingCategory.CUSTOM_CODE,
                    "The selected entry appears to require Custom Code.",
                    "Replace it with a native template or document the approved gap requiring Custom Code.",
                    PipelineStage.TEMPLATE_MATCHING,
                    entry=entry,
                )
            )

        if len(entry.scoped_css) > plan.policy.css_rule_budget:
            findings.append(
                _finding(
                    f"{entry.id}:css-budget",
                    ReportSeverity.MEDIUM,
                    FindingCategory.CSS,
                    (
                        f"Scoped CSS uses {len(entry.scoped_css)} rules, exceeding "
                        f"the per-section budget of {plan.policy.css_rule_budget}."
                    ),
                    "Promote repeated rules to theme controls, utilities, or template modifiers.",
                    PipelineStage.STYLE_TRANSLATION,
                    entry=entry,
                    metadata={"rules": len(entry.scoped_css)},
                )
            )

        for decision_index, decision in enumerate(entry.style_decisions):
            if decision.layer not in {TranslationLayer.SCOPED_CSS, TranslationLayer.MANUAL}:
                continue
            severity = (
                ReportSeverity.MEDIUM
                if decision.layer == TranslationLayer.MANUAL
                else ReportSeverity.LOW
            )
            findings.append(
                _finding(
                    f"{entry.id}:style:{decision_index + 1}",
                    severity,
                    FindingCategory.STYLE,
                    f"{decision.property.value} uses {decision.layer.value} translation.",
                    (
                        "Resolve the property with a reviewed theme, utility, or modifier mapping."
                        if decision.layer == TranslationLayer.MANUAL
                        else "Review repeated scoped declarations for promotion to a reusable utility."
                    ),
                    PipelineStage.STYLE_TRANSLATION,
                    entry=entry,
                    style_decision=decision,
                )
            )

        for simplification_index, simplification in enumerate(entry.simplifications):
            severity = {
                IssueSeverity.LOW: ReportSeverity.LOW,
                IssueSeverity.MEDIUM: ReportSeverity.MEDIUM,
                IssueSeverity.HIGH: ReportSeverity.HIGH,
            }[simplification.severity]
            if simplification.classification == SimplificationKind.MANUAL_MODULE:
                category = FindingCategory.MANUAL_MODULE
                stage = PipelineStage.MANUAL_IMPLEMENTATION
                recommendation = "Implement the module manually, then document a repeatable agency pattern."
            elif simplification.classification == SimplificationKind.NEW_TEMPLATE:
                category = FindingCategory.TEMPLATE
                stage = PipelineStage.COMPOSITION_PLANNING
                recommendation = "Author and validate a reusable template capability before publishing."
            elif simplification.classification == SimplificationKind.MODIFIER:
                category = FindingCategory.MODIFIER
                stage = PipelineStage.STYLE_TRANSLATION
                recommendation = "Promote the treatment to a documented, tested template modifier."
            else:
                category = FindingCategory.TEMPLATE
                stage = PipelineStage.COMPOSITION_PLANNING
                recommendation = "Review and explicitly approve the visual simplification."
            findings.append(
                _finding(
                    f"{entry.id}:simplification:{simplification_index + 1}",
                    severity,
                    category,
                    f"{simplification.trait}: {simplification.reason}",
                    recommendation,
                    stage,
                    entry=entry,
                    source_ids=simplification.source_ids,
                    metadata={"classification": simplification.classification.value},
                )
            )

        for warning_index, warning in enumerate(entry.warnings):
            findings.append(
                _finding(
                    f"{entry.id}:warning:{warning_index + 1}",
                    ReportSeverity.LOW,
                    FindingCategory.WARNING,
                    warning,
                    "Review the planner warning and either resolve it or record an explicit acceptance.",
                    PipelineStage.COMPOSITION_PLANNING,
                    entry=entry,
                )
            )
    return findings


def build_maintainability_report(
    plan: CompositionPlan | dict[str, JsonValue],
    *,
    prior_report: MaintainabilityReport | dict[str, JsonValue] | None = None,
    thresholds: MaintainabilityThresholds | None = None,
) -> MaintainabilityReport:
    """Aggregate a Composition Plan into a deterministic remediation report."""

    validated_plan = plan if isinstance(plan, CompositionPlan) else CompositionPlan.model_validate(plan)
    validated_prior = (
        prior_report
        if isinstance(prior_report, MaintainabilityReport)
        else MaintainabilityReport.model_validate(prior_report)
        if prior_report is not None
        else None
    )
    policy = thresholds or MaintainabilityThresholds()
    entries = validated_plan.entries
    blocking_ids = tuple(
        sorted(entry.source_section_id for entry in entries if entry.match.blocking)
    )
    custom_code_ids = tuple(
        sorted(entry.source_section_id for entry in entries if _looks_like_custom_code(entry))
    )
    manual_module_ids = tuple(
        sorted(
            {
                entry.source_section_id
                for entry in entries
                if any(
                    item.classification == SimplificationKind.MANUAL_MODULE
                    for item in entry.simplifications
                )
            }
        )
    )
    new_template_count = sum(
        item.classification == SimplificationKind.NEW_TEMPLATE
        for entry in entries
        for item in entry.simplifications
    )
    modifier_counts = Counter(modifier for entry in entries for modifier in entry.modifiers)
    scope_sections: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        if entry.css_scope and entry.scoped_css:
            scope_sections[entry.css_scope].add(entry.source_section_id)
    colliding_scopes = {
        scope: sections for scope, sections in scope_sections.items() if len(sections) > 1
    }
    collision_section_ids = tuple(
        sorted({section_id for sections in colliding_scopes.values() for section_id in sections})
    )
    override_entries = tuple(entry for entry in entries if entry.override_audit is not None)
    template_sections: dict[tuple[str, str], list[str]] = defaultdict(list)
    for entry in entries:
        template_sections[(entry.template_id, entry.template)].append(entry.source_section_id)
    template_usage = tuple(
        TemplateUsage(
            template_id=template_id,
            template_name=template_name,
            count=len(section_ids),
            section_ids=tuple(sorted(section_ids)),
        )
        for (template_id, template_name), section_ids in sorted(template_sections.items())
    )
    reused_sections = sum(item.count for item in template_usage if item.count > 1)
    css_rules = sum(len(entry.scoped_css) for entry in entries)
    css_bytes = _css_bytes(entries)
    score = _score(
        native_coverage=validated_plan.summary.native_component_ratio,
        editable_coverage=validated_plan.summary.editable_content_coverage,
        custom_code_count=len(custom_code_ids),
        blocking_count=len(blocking_ids),
        manual_module_count=len(manual_module_ids),
        css_rule_count=css_rules,
        css_budget=validated_plan.policy.css_rule_budget,
        section_count=len(entries),
        thresholds=policy,
    )
    metrics = MaintainabilityMetrics(
        section_count=len(entries),
        maintainability_score=score,
        native_component_coverage=validated_plan.summary.native_component_ratio,
        editable_content_coverage=validated_plan.summary.editable_content_coverage,
        blocking_entry_count=len(blocking_ids),
        blocking_entry_ids=blocking_ids,
        custom_block_count=sum(entry.block.type == BlockType.CUSTOM for entry in entries),
        global_block_count=sum(entry.block.type == BlockType.GLOBAL for entry in entries),
        new_template_count=new_template_count,
        custom_code_entry_count=len(custom_code_ids),
        custom_code_section_ids=custom_code_ids,
        scoped_css_section_count=sum(bool(entry.scoped_css) for entry in entries),
        scoped_css_rule_count=css_rules,
        scoped_css_bytes=css_bytes,
        unique_css_scope_count=len(scope_sections),
        css_scope_collision_count=len(colliding_scopes),
        css_scope_collision_section_ids=collision_section_ids,
        modifier_assignment_count=sum(modifier_counts.values()),
        reusable_modifier_count=len(modifier_counts),
        unique_modifiers=tuple(sorted(modifier_counts)),
        manual_module_count=len(manual_module_ids),
        manual_module_section_ids=manual_module_ids,
        manual_override_count=len(override_entries),
        manual_override_section_ids=tuple(
            sorted(entry.source_section_id for entry in override_entries)
        ),
        override_previous_candidate_count=sum(
            len(entry.override_audit.previous_candidates)
            for entry in override_entries
            if entry.override_audit is not None
        ),
        template_reuse_ratio=(reused_sections / len(entries) if entries else 0.0),
        template_usage=template_usage,
    )

    findings = _entry_findings(validated_plan)
    if metrics.native_component_coverage < policy.minimum_native_component_coverage:
        findings.append(
            _finding(
                "gate:native-coverage",
                ReportSeverity.HIGH,
                FindingCategory.COVERAGE,
                (
                    f"Native component coverage is {metrics.native_component_coverage:.1%}; "
                    f"the gate requires {policy.minimum_native_component_coverage:.1%}."
                ),
                "Replace custom/raw implementations with supported Vanjaro components or templates.",
                PipelineStage.QUALITY_GATE,
            )
        )
    if metrics.editable_content_coverage < policy.minimum_editable_content_coverage:
        findings.append(
            _finding(
                "gate:editable-coverage",
                ReportSeverity.HIGH,
                FindingCategory.COVERAGE,
                (
                    f"Editable content coverage is {metrics.editable_content_coverage:.1%}; "
                    f"the gate requires {policy.minimum_editable_content_coverage:.1%}."
                ),
                "Expose visitor-facing text and editorial media through semantic template bindings.",
                PipelineStage.QUALITY_GATE,
            )
        )
    if metrics.custom_code_entry_count > policy.maximum_custom_code_entries:
        findings.append(
            _finding(
                "gate:custom-code",
                ReportSeverity.HIGH,
                FindingCategory.CUSTOM_CODE,
                f"Custom Code is used by {metrics.custom_code_entry_count} section(s).",
                "Remove Custom Code or record the approved gap that requires it.",
                PipelineStage.QUALITY_GATE,
                metadata={"section_ids": list(metrics.custom_code_section_ids)},
            )
        )
    if metrics.blocking_entry_count > policy.maximum_blocking_entries:
        findings.append(
            _finding(
                "gate:blocking-entries",
                ReportSeverity.HIGH,
                FindingCategory.BLOCKING,
                f"The plan contains {metrics.blocking_entry_count} blocking section(s).",
                "Resolve blocking matches or explicitly revise the approval threshold.",
                PipelineStage.QUALITY_GATE,
                metadata={"section_ids": list(metrics.blocking_entry_ids)},
            )
        )
    if metrics.manual_module_count > policy.maximum_manual_modules:
        findings.append(
            _finding(
                "gate:manual-modules",
                ReportSeverity.HIGH,
                FindingCategory.MANUAL_MODULE,
                f"Manual modules are required by {metrics.manual_module_count} section(s).",
                "Replace manual modules with supported components or approve and document the maintenance owner.",
                PipelineStage.QUALITY_GATE,
                metadata={"section_ids": list(metrics.manual_module_section_ids)},
            )
        )
    for scope, section_ids in sorted(colliding_scopes.items()):
        findings.append(
            _finding(
                f"contract:css-scope:{scope}",
                ReportSeverity.HIGH,
                FindingCategory.CSS,
                f"CSS scope {scope!r} is shared by {len(section_ids)} sections.",
                "Regenerate unique client-and-section scopes before emitting scoped CSS.",
                PipelineStage.STYLE_TRANSLATION,
                source_ids=tuple(sorted(section_ids)),
                metadata={"css_scope": scope},
            )
        )
    if validated_plan.summary.scoped_css_rule_count != css_rules or validated_plan.summary.scoped_css_bytes != css_bytes:
        findings.append(
            _finding(
                "contract:css-summary",
                ReportSeverity.MEDIUM,
                FindingCategory.CONTRACT,
                "Composition Plan CSS summary does not match recomputed entry totals.",
                "Regenerate the Composition Plan before using its summary for approval.",
                PipelineStage.COMPOSITION_PLANNING,
                metadata={
                    "summary_rules": validated_plan.summary.scoped_css_rule_count,
                    "computed_rules": css_rules,
                    "summary_bytes": validated_plan.summary.scoped_css_bytes,
                    "computed_bytes": css_bytes,
                },
            )
        )

    ordered_findings = tuple(
        sorted(
            findings,
            key=lambda item: (
                _SEVERITY_ORDER[item.severity],
                item.section_id or "",
                item.id,
            ),
        )
    )
    promotions = _promotion_candidates(validated_plan, policy)
    blocking_gate = any(finding.severity == ReportSeverity.HIGH for finding in ordered_findings)
    report_without_deltas = MaintainabilityReport(
        source_document_id=validated_plan.source_document_id,
        thresholds=policy,
        passes_gate=not blocking_gate,
        metrics=metrics,
        findings=ordered_findings,
        promotion_candidates=promotions,
    )
    return report_without_deltas.model_copy(
        update={"deltas": _metric_deltas(metrics, validated_prior)}
    )


def serialize_maintainability_report(
    report: MaintainabilityReport,
    *,
    indent: int = 2,
) -> str:
    """Serialize a report with sorted keys and a trailing newline."""

    return json.dumps(
        report.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        indent=indent,
        sort_keys=True,
    ) + "\n"


def render_maintainability_report(report: MaintainabilityReport) -> str:
    """Render a stable concise human-readable remediation report."""

    metrics = report.metrics
    lines = [
        "Maintainability Report",
        f"Source: {report.source_document_id}",
        f"Gate: {'PASS' if report.passes_gate else 'FAIL'}",
        f"Score: {metrics.maintainability_score:.2f}/100",
        f"Native component coverage: {metrics.native_component_coverage:.1%}",
        f"Editable content coverage: {metrics.editable_content_coverage:.1%}",
        (
            "Blocks: "
            f"{metrics.custom_block_count} custom, {metrics.global_block_count} global, "
            f"{metrics.blocking_entry_count} blocking"
        ),
        (
            "Custom work: "
            f"{metrics.custom_code_entry_count} Custom Code, "
            f"{metrics.new_template_count} new templates, "
            f"{metrics.manual_module_count} manual modules"
        ),
        (
            "Scoped CSS: "
            f"{metrics.scoped_css_rule_count} rules, {metrics.scoped_css_bytes} bytes, "
            f"{metrics.scoped_css_section_count} sections, "
            f"{metrics.unique_css_scope_count} unique scopes, "
            f"{metrics.css_scope_collision_count} collisions"
        ),
        (
            "Modifiers: "
            f"{metrics.modifier_assignment_count} assignments, "
            f"{metrics.reusable_modifier_count} unique"
        ),
        (
            "Manual overrides: "
            f"{metrics.manual_override_count} audited, "
            f"{metrics.override_previous_candidate_count} prior candidates retained"
        ),
        "",
        f"Findings ({len(report.findings)}):",
    ]
    if report.findings:
        for finding in report.findings:
            location = f" [{finding.section_id}]" if finding.section_id else ""
            lines.append(
                f"- {finding.severity.value.upper()} {finding.category.value}{location}: "
                f"{finding.message}"
            )
            lines.append(f"  Action: {finding.recommendation}")
            lines.append(f"  Stage: {finding.pipeline_stage.value}")
    else:
        lines.append("- None")

    lines.extend(["", f"Promotion candidates ({len(report.promotion_candidates)}):"])
    if report.promotion_candidates:
        for candidate in report.promotion_candidates:
            lines.append(
                f"- {candidate.kind.value} {candidate.key}: "
                f"{candidate.occurrences} sections"
            )
            lines.append(f"  Action: {candidate.recommendation}")
    else:
        lines.append("- None")

    if report.deltas:
        lines.extend(["", "Changes from prior run:"])
        for delta in report.deltas:
            marker = "+" if delta.delta > 0 else ""
            outcome = "improved" if delta.improved else "regressed" if delta.delta else "unchanged"
            lines.append(
                f"- {delta.metric}: {delta.previous:g} -> {delta.current:g} "
                f"({marker}{delta.delta:g}, {outcome})"
            )
    return "\n".join(lines) + "\n"
