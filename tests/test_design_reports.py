"""Tests for offline maintainability and remediation reporting."""

from __future__ import annotations

import json

from vanjaro_cli.design.composition import (
    CompositionPlan,
    CompositionPlanEntry,
    MatchAlternative,
    OverrideAudit,
    PlanBlock,
    PlanMatch,
    PlanPolicy,
    PlanSummary,
    SemanticBinding,
    SimplificationDecision,
    SimplificationKind,
    IssueSeverity,
)
from vanjaro_cli.design.models import StyleProperty
from vanjaro_cli.design.reports import (
    FindingCategory,
    MaintainabilityThresholds,
    PipelineStage,
    PromotionKind,
    ReportSeverity,
    build_maintainability_report,
    render_maintainability_report,
    serialize_maintainability_report,
)
from vanjaro_cli.design.style_translation import StyleDecision, TranslationLayer


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


def _entry(
    index: int,
    *,
    template_id: str = "feature-cards",
    template: str = "Feature Cards",
    category: str = "Cards",
    block_type: str = "custom",
    blocking: bool = False,
    confidence: str = "high",
    modifiers: tuple[str, ...] = (),
    scoped_css: dict[str, str] | None = None,
    style_decisions: tuple[StyleDecision, ...] = (),
    simplifications: tuple[SimplificationDecision, ...] = (),
    warnings: tuple[str, ...] = (),
    override_audit: OverrideAudit | None = None,
    css_scope: str | None = None,
) -> CompositionPlanEntry:
    return CompositionPlanEntry(
        id=f"entry-{index}",
        source_section_id=f"home.section.{index}",
        template_id=template_id,
        template=template,
        match=PlanMatch(
            score=0.9 if confidence == "high" else 0.6,
            confidence=confidence,
            blocking=blocking,
            reasons=("semantic role match",),
        ),
        override_audit=override_audit,
        block=PlanBlock(
            name=f"Block {index}",
            category=category,
            type=block_type,
        ),
        bindings=(
            SemanticBinding(
                semantic_field="section_title",
                slot="heading_1",
                source_element_ids=(f"element-{index}",),
                value=f"Heading {index}",
                editable=True,
            ),
        ),
        modifiers=modifiers,
        css_scope=(css_scope or f".vj-generated .section-{index}" if scoped_css else None),
        scoped_css=scoped_css or {},
        style_decisions=style_decisions,
        simplifications=simplifications,
        warnings=warnings,
    )


def _plan(
    entries: tuple[CompositionPlanEntry, ...],
    *,
    native: float = 1.0,
    editable: float = 1.0,
    css_summary_matches: bool = True,
    css_budget: int = 12,
) -> CompositionPlan:
    rules = sum(len(entry.scoped_css) for entry in entries)
    byte_count = _css_bytes(entries)
    return CompositionPlan(
        source_document_id="design:test",
        policy=PlanPolicy(css_rule_budget=css_budget),
        entries=entries,
        summary=PlanSummary(
            section_count=len(entries),
            blocking_count=sum(entry.match.blocking for entry in entries),
            native_component_ratio=native,
            editable_content_coverage=editable,
            scoped_css_rule_count=rules if css_summary_matches else rules + 1,
            scoped_css_bytes=byte_count if css_summary_matches else byte_count + 10,
        ),
    )


def test_report_aggregates_required_maintainability_metrics() -> None:
    manual = SimplificationDecision(
        trait="interactive-map",
        classification=SimplificationKind.MANUAL_MODULE,
        severity=IssueSeverity.HIGH,
        reason="No native map module is declared.",
        source_ids=("map-1",),
    )
    style = StyleDecision(
        property=StyleProperty.BORDER_RADIUS,
        source_value="16px",
        layer=TranslationLayer.SCOPED_CSS,
        target="border-radius",
        confidence=0.8,
        reason="No declared modifier.",
    )
    entries = (
        _entry(
            1,
            template_id="custom-code",
            template="Custom Code",
            category="Custom Code",
            blocking=True,
            modifiers=("card-radius",),
            scoped_css={"border-radius": "16px"},
            style_decisions=(style,),
            simplifications=(manual,),
        ),
        _entry(
            2,
            modifiers=("card-radius",),
            scoped_css={"border-radius": "16px"},
            style_decisions=(style,),
        ),
        _entry(
            3,
            block_type="global",
            template_id="feature-cards",
            template="Feature Cards",
        ),
    )

    report = build_maintainability_report(
        _plan(entries, native=0.8, editable=0.9)
    )

    metrics = report.metrics
    assert metrics.section_count == 3
    assert metrics.native_component_coverage == 0.8
    assert metrics.editable_content_coverage == 0.9
    assert metrics.blocking_entry_ids == ("home.section.1",)
    assert metrics.custom_block_count == 2
    assert metrics.global_block_count == 1
    assert metrics.custom_code_section_ids == ("home.section.1",)
    assert metrics.scoped_css_section_count == 2
    assert metrics.scoped_css_rule_count == 2
    assert metrics.scoped_css_bytes == _css_bytes(entries)
    assert metrics.unique_css_scope_count == 2
    assert metrics.css_scope_collision_count == 0
    assert metrics.modifier_assignment_count == 2
    assert metrics.reusable_modifier_count == 1
    assert metrics.unique_modifiers == ("card-radius",)
    assert metrics.manual_module_section_ids == ("home.section.1",)
    assert metrics.manual_override_count == 0
    assert metrics.template_reuse_ratio == 2 / 3
    assert [(item.template_id, item.count) for item in metrics.template_usage] == [
        ("custom-code", 1),
        ("feature-cards", 2),
    ]
    assert report.passes_gate is False
    assert metrics.maintainability_score < 100


def test_findings_map_section_match_style_decision_and_pipeline_stage() -> None:
    manual_style = StyleDecision(
        property=StyleProperty.TRANSFORM,
        source_value="rotate(8deg)",
        layer=TranslationLayer.MANUAL,
        target="manual_review",
        confidence=0.4,
        reason="Unsupported transform.",
    )
    new_template = SimplificationDecision(
        trait="complex-timeline",
        classification=SimplificationKind.NEW_TEMPLATE,
        severity=IssueSeverity.HIGH,
        reason="No template supports alternating milestones.",
        source_ids=("timeline-1",),
    )
    entry = _entry(
        1,
        blocking=True,
        confidence="low",
        style_decisions=(manual_style,),
        simplifications=(new_template,),
        warnings=("One optional image was unresolved.",),
    )

    report = build_maintainability_report(_plan((entry,)))

    section_findings = [finding for finding in report.findings if finding.section_id]
    assert section_findings
    assert all(finding.section_id == "home.section.1" for finding in section_findings)
    assert all(finding.match is not None for finding in section_findings)
    style_finding = next(
        finding for finding in report.findings if finding.style_decision is not None
    )
    assert style_finding.style_decision.property == "transform"
    assert style_finding.style_decision.layer == "manual"
    assert style_finding.pipeline_stage == PipelineStage.STYLE_TRANSLATION
    template_finding = next(
        finding
        for finding in report.findings
        if finding.category == FindingCategory.TEMPLATE
    )
    assert template_finding.source_ids == ("timeline-1",)
    assert template_finding.pipeline_stage == PipelineStage.COMPOSITION_PLANNING
    assert any(
        finding.category == FindingCategory.WARNING
        for finding in report.findings
    )


def test_report_detects_css_budget_and_summary_contract_drift() -> None:
    entry = _entry(
        1,
        scoped_css={"a": "1", "b": "2", "c": "3"},
    )

    report = build_maintainability_report(
        _plan((entry,), css_summary_matches=False, css_budget=2)
    )

    assert any(finding.id == "entry-1:css-budget" for finding in report.findings)
    contract = next(
        finding for finding in report.findings if finding.id == "contract:css-summary"
    )
    assert contract.severity == ReportSeverity.MEDIUM
    assert contract.pipeline_stage == PipelineStage.COMPOSITION_PLANNING
    assert contract.metadata["computed_rules"] == 3


def test_report_audits_manual_override_and_detects_scope_collisions() -> None:
    audit = OverrideAudit(
        author="Agency reviewer",
        reason="The alternate has the required editorial workflow.",
        previous_candidates=(
            MatchAlternative(
                template_id="feature-cards",
                template_name="Feature Cards",
                score=0.91,
                confidence="high",
            ),
            MatchAlternative(
                template_id="icon-list",
                template_name="Icon List",
                score=0.84,
                confidence="medium",
            ),
        ),
    )
    entries = (
        _entry(
            1,
            scoped_css={"border-radius": "16px"},
            css_scope=".client-site .shared-section",
            override_audit=audit,
        ),
        _entry(
            2,
            scoped_css={"padding": "24px"},
            css_scope=".client-site .shared-section",
        ),
    )

    report = build_maintainability_report(_plan(entries))

    assert report.metrics.manual_override_count == 1
    assert report.metrics.manual_override_section_ids == ("home.section.1",)
    assert report.metrics.override_previous_candidate_count == 2
    assert report.metrics.unique_css_scope_count == 1
    assert report.metrics.css_scope_collision_count == 1
    assert report.metrics.css_scope_collision_section_ids == (
        "home.section.1",
        "home.section.2",
    )
    override = next(item for item in report.findings if item.category == FindingCategory.OVERRIDE)
    assert override.match is not None
    assert override.metadata["author"] == "Agency reviewer"
    assert len(override.metadata["previous_candidates"]) == 2
    collision = next(item for item in report.findings if item.id.startswith("contract:css-scope:"))
    assert collision.severity == ReportSeverity.HIGH
    assert collision.pipeline_stage == PipelineStage.STYLE_TRANSLATION
    assert collision.source_ids == ("home.section.1", "home.section.2")
    assert report.passes_gate is False


def test_blocking_and_manual_module_thresholds_are_enforced() -> None:
    manual = SimplificationDecision(
        trait="interactive-map",
        classification=SimplificationKind.MANUAL_MODULE,
        severity=IssueSeverity.LOW,
        reason="A specialized editor is required.",
    )
    plan = _plan((_entry(1, blocking=True, simplifications=(manual,)),))

    report = build_maintainability_report(plan)

    assert {finding.id for finding in report.findings} >= {
        "gate:blocking-entries",
        "gate:manual-modules",
    }
    relaxed = build_maintainability_report(
        plan,
        thresholds=MaintainabilityThresholds(
            maximum_blocking_entries=1,
            maximum_manual_modules=1,
        ),
    )
    assert relaxed.passes_gate is True
    assert not any(finding.id.startswith("gate:") for finding in relaxed.findings)


def test_report_proposes_modifier_utility_and_template_promotions() -> None:
    repeated_trait = SimplificationDecision(
        trait="angled-ribbon",
        classification=SimplificationKind.MODIFIER,
        severity=IssueSeverity.MEDIUM,
        reason="Template lacks the decorative treatment.",
    )
    entries = (
        _entry(
            1,
            modifiers=("band-color",),
            scoped_css={"clip-path": "polygon(...)"},
            simplifications=(repeated_trait,),
        ),
        _entry(
            2,
            modifiers=("band-color",),
            scoped_css={"clip-path": "polygon(...)"},
            simplifications=(repeated_trait,),
        ),
    )

    report = build_maintainability_report(_plan(entries))

    by_kind = {candidate.kind: candidate for candidate in report.promotion_candidates}
    assert by_kind[PromotionKind.MODIFIER].key == "band-color"
    assert by_kind[PromotionKind.AGENCY_UTILITY].key == "clip-path:polygon(...)"
    assert by_kind[PromotionKind.TEMPLATE].key == "angled-ribbon"
    assert all(candidate.occurrences == 2 for candidate in by_kind.values())
    assert all(
        candidate.section_ids == ("home.section.1", "home.section.2")
        for candidate in by_kind.values()
    )


def test_report_calculates_prior_run_deltas_with_improvement_direction() -> None:
    prior_entry = _entry(
        1,
        template_id="custom-code",
        template="Custom Code",
        category="Custom Code",
        blocking=False,
        scoped_css={"color": "#123", "padding": "20px"},
    )
    prior = build_maintainability_report(
        _plan((prior_entry,), native=0.7, editable=0.8)
    )
    current = build_maintainability_report(
        _plan((_entry(1),), native=0.95, editable=0.98),
        prior_report=prior.model_dump(mode="json"),
    )

    deltas = {delta.metric: delta for delta in current.deltas}
    assert deltas["native_component_coverage"].delta == 0.25
    assert deltas["native_component_coverage"].improved is True
    assert deltas["custom_code_entry_count"].delta == -1
    assert deltas["custom_code_entry_count"].improved is True
    assert deltas["scoped_css_rule_count"].delta == -2
    assert deltas["scoped_css_rule_count"].direction == "lower_is_better"
    assert deltas["maintainability_score"].delta > 0


def test_report_accepts_plan_dict_and_serializers_are_deterministic() -> None:
    plan = _plan((_entry(1, block_type="global"),))

    report = build_maintainability_report(plan.model_dump(mode="json"))
    first_json = serialize_maintainability_report(report)
    second_json = serialize_maintainability_report(report)
    first_human = render_maintainability_report(report)
    second_human = render_maintainability_report(report)

    assert first_json == second_json
    assert first_json.endswith("\n")
    assert json.loads(first_json)["passes_gate"] is True
    assert first_human == second_human
    assert first_human.endswith("\n")
    assert "Gate: PASS" in first_human
    assert "Native component coverage: 100.0%" in first_human
    assert "Findings (0):\n- None" in first_human


def test_threshold_override_controls_coverage_gate() -> None:
    plan = _plan((_entry(1),), native=0.85, editable=0.9)

    default_report = build_maintainability_report(plan)
    relaxed_report = build_maintainability_report(
        plan,
        thresholds=MaintainabilityThresholds(
            minimum_native_component_coverage=0.8,
            minimum_editable_content_coverage=0.85,
        ),
    )

    assert default_report.passes_gate is False
    assert relaxed_report.passes_gate is True
    assert {
        finding.id for finding in default_report.findings
    } >= {"gate:native-coverage", "gate:editable-coverage"}
    assert not any(
        finding.category == FindingCategory.COVERAGE
        for finding in relaxed_report.findings
    )

    disabled_coverage_gate = build_maintainability_report(
        _plan((_entry(1),), native=0, editable=0),
        thresholds=MaintainabilityThresholds(
            minimum_native_component_coverage=0,
            minimum_editable_content_coverage=0,
        ),
    )
    assert disabled_coverage_gate.metrics.maintainability_score == 100
    assert disabled_coverage_gate.passes_gate is True
