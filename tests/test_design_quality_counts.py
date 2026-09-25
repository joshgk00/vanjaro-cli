"""Rule-by-rule coverage for the composition-plan-derived quality counts."""

from __future__ import annotations

from pathlib import Path

from vanjaro_cli.design.composition import (
    BlockType,
    CompositionPlan,
    CompositionPlanEntry,
    PlanBlock,
    PlanMatch,
    PlanPolicy,
    PlanSummary,
    SemanticBinding,
)
from vanjaro_cli.design.quality_counts import (
    GENERIC_FALLBACK_TEMPLATE_IDS,
    PageIdentityMap,
    compute_quality_counts,
)
from vanjaro_cli.design.template_catalog import TemplateCatalogEntry, load_template_catalog

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_template_catalog(ROOT / "artifacts" / "block-templates")


def _template(filename: str) -> TemplateCatalogEntry:
    return next(entry for entry in CATALOG if Path(entry.relative_path).name == filename)


RICH_TEXT = _template("rich-text.json")  # native, but the designated generic fallback
LOW_NATIVE = _template("class-photo-cards-4up.json")  # native_component_ratio 0.78
HIGH_NATIVE = _template("centered-hero.json")  # native_component_ratio 1.0


def _binding(*, editable: bool = True, slot: str = "heading") -> SemanticBinding:
    return SemanticBinding(
        semantic_field="heading",
        slot=slot,
        source_element_ids=("el-1",),
        value="Welcome",
        editable=editable,
    )


def _entry(
    *,
    entry_id: str,
    source_section_id: str,
    template: TemplateCatalogEntry = RICH_TEXT,
    block_type: BlockType = BlockType.CUSTOM,
    bindings: tuple[SemanticBinding, ...] = (),
    blocking: bool = False,
    scoped_css: dict[str, str] | None = None,
    css_scope: str | None = None,
) -> CompositionPlanEntry:
    return CompositionPlanEntry(
        id=entry_id,
        source_section_id=source_section_id,
        template_id=template.template_id,
        template=template.name,
        match=PlanMatch(score=0.9, confidence="high", blocking=blocking),
        block=PlanBlock(name=f"Block {entry_id}", category=template.category, type=block_type),
        bindings=bindings,
        scoped_css=scoped_css or {},
        css_scope=css_scope,
    )


def _plan(entries: tuple[CompositionPlanEntry, ...]) -> CompositionPlan:
    return CompositionPlan(
        source_document_id="quality-doc",
        entries=entries,
        summary=PlanSummary(
            section_count=len(entries),
            blocking_count=sum(entry.match.blocking for entry in entries),
            native_component_ratio=1.0,
            editable_content_coverage=1.0,
        ),
    )


def test_editable_coverage_counts_only_all_editable_body_entries_with_bindings() -> None:
    plan = _plan(
        (
            _entry(
                entry_id="a",
                source_section_id="home.section.1",
                template=HIGH_NATIVE,
                bindings=(_binding(editable=True),),
            ),
            _entry(
                entry_id="b",
                source_section_id="home.section.2",
                template=HIGH_NATIVE,
                bindings=(_binding(editable=True, slot="heading"), _binding(editable=False, slot="subheading")),
            ),
        )
    )

    report = compute_quality_counts(plan, CATALOG, {})

    assert report.eligible_section_editable_coverage.numerator == 1
    assert report.eligible_section_editable_coverage.denominator == 2
    row_b = next(row for row in report.rows if row.entry_id == "b")
    assert row_b.is_editable is False


def test_editable_coverage_empty_denominator_records_zero_over_one_with_note() -> None:
    plan = _plan(
        (
            _entry(
                entry_id="global-1",
                source_section_id="home.header",
                template=HIGH_NATIVE,
                block_type=BlockType.GLOBAL,
                bindings=(_binding(),),
            ),
        )
    )

    report = compute_quality_counts(plan, CATALOG, {})

    assert report.eligible_section_editable_coverage.numerator == 0
    assert report.eligible_section_editable_coverage.denominator == 1
    assert any("no body entries with bindings" in warning for warning in report.warnings)


def test_unknown_template_counts_as_not_native_and_warns() -> None:
    plan = _plan(
        (
            _entry(
                entry_id="a",
                source_section_id="home.section.1",
                template=HIGH_NATIVE,
                bindings=(_binding(),),
            ),
        )
    )
    # Simulate a plan matched against a catalog that no longer has this template.
    mutated = plan.model_copy(
        update={
            "entries": (
                plan.entries[0].model_copy(update={"template_id": "Missing/gone"}),
            )
        }
    )

    report = compute_quality_counts(mutated, CATALOG, {})

    assert report.native_agency_component_ratio.numerator == 0
    assert report.native_agency_component_ratio.denominator == 1
    assert any("Missing/gone" in warning for warning in report.warnings)
    assert report.rows[0].is_native is False


def test_scoped_css_within_the_plan_budget_keeps_a_template_native() -> None:
    plan = _plan(
        (
            _entry(
                entry_id="a",
                source_section_id="home.section.1",
                template=HIGH_NATIVE,
                bindings=(_binding(),),
                scoped_css={".audit-section .title": "color: red;"},
                css_scope=".audit-project .design-section-audit",
            ),
        )
    )

    report = compute_quality_counts(plan, CATALOG, {})

    assert report.native_agency_component_ratio.numerator == 1
    assert report.native_agency_component_ratio.denominator == 1


def test_scoped_css_over_the_plan_budget_makes_a_template_non_native() -> None:
    over_budget = {
        f".audit-section .rule-{index}": "color: red;"
        for index in range(PlanPolicy().css_rule_budget + 1)
    }
    plan = _plan(
        (
            _entry(
                entry_id="a",
                source_section_id="home.section.1",
                template=HIGH_NATIVE,
                bindings=(_binding(),),
                scoped_css=over_budget,
                css_scope=".audit-project .design-section-audit",
            ),
        )
    )

    report = compute_quality_counts(plan, CATALOG, {})

    assert report.native_agency_component_ratio.numerator == 0
    assert report.native_agency_component_ratio.denominator == 1


def test_low_native_ratio_template_is_not_native() -> None:
    plan = _plan(
        (
            _entry(
                entry_id="a",
                source_section_id="home.section.1",
                template=LOW_NATIVE,
                bindings=(_binding(),),
            ),
        )
    )

    report = compute_quality_counts(plan, CATALOG, {})

    assert report.native_agency_component_ratio.numerator == 0


def test_rich_text_and_blocking_match_both_count_as_generic_fallback() -> None:
    plan = _plan(
        (
            _entry(
                entry_id="a",
                source_section_id="home.section.1",
                template=RICH_TEXT,
                bindings=(_binding(),),
            ),
            _entry(
                entry_id="b",
                source_section_id="home.section.2",
                template=HIGH_NATIVE,
                bindings=(_binding(),),
                blocking=True,
            ),
            _entry(
                entry_id="c",
                source_section_id="home.section.3",
                template=HIGH_NATIVE,
                bindings=(_binding(),),
            ),
        )
    )

    report = compute_quality_counts(plan, CATALOG, {})

    assert report.body_without_generic_fallback.numerator == 1
    assert report.body_without_generic_fallback.denominator == 3
    assert RICH_TEXT.template_id in GENERIC_FALLBACK_TEMPLATE_IDS
    row_a = next(row for row in report.rows if row.entry_id == "a")
    row_b = next(row for row in report.rows if row.entry_id == "b")
    row_c = next(row for row in report.rows if row.entry_id == "c")
    assert row_a.is_generic_fallback is True
    assert row_b.is_generic_fallback is True
    assert row_c.is_generic_fallback is False


def test_capture_evidence_with_two_of_three_breakpoints_does_not_count() -> None:
    plan = _plan(
        (
            _entry(
                entry_id="a",
                source_section_id="home.section.1",
                template=HIGH_NATIVE,
                bindings=(_binding(),),
            ),
            _entry(
                entry_id="b",
                source_section_id="about.section.1",
                template=HIGH_NATIVE,
                bindings=(_binding(),),
            ),
        )
    )
    page_identity = PageIdentityMap(
        page_ids=("home", "about"),
        section_page_ids={"home.section.1": "home", "about.section.1": "about"},
    )

    report = compute_quality_counts(
        plan,
        CATALOG,
        {
            "home": {"desktop", "tablet"},
            "about": {"desktop", "tablet", "mobile"},
        },
        page_identity=page_identity,
    )

    assert report.desktop_tablet_mobile_evidence.numerator == 1
    assert report.desktop_tablet_mobile_evidence.denominator == 2


def test_no_capture_evidence_supplied_records_zero_numerator() -> None:
    plan = _plan(
        (
            _entry(
                entry_id="a",
                source_section_id="home.section.1",
                template=HIGH_NATIVE,
                bindings=(_binding(),),
            ),
        )
    )
    page_identity = PageIdentityMap(
        page_ids=("home",), section_page_ids={"home.section.1": "home"}
    )

    report = compute_quality_counts(plan, CATALOG, {}, page_identity=page_identity)

    assert report.desktop_tablet_mobile_evidence.numerator == 0
    assert report.desktop_tablet_mobile_evidence.denominator == 1


def test_missing_page_identity_earns_zero_capture_credit_even_with_matching_evidence() -> None:
    # Regression for the punctuation-heuristic bug: without an authoritative
    # page_identity, a capture_evidence mapping keyed by what *looks* like a
    # page id (because it happens to be the text before the first ".") must
    # never be credited.
    plan = _plan(
        (
            _entry(
                entry_id="a",
                source_section_id="home.section.1",
                template=HIGH_NATIVE,
                bindings=(_binding(),),
            ),
        )
    )

    report = compute_quality_counts(
        plan, CATALOG, {"home": {"desktop", "tablet", "mobile"}}
    )

    assert report.desktop_tablet_mobile_evidence.numerator == 0
    assert report.desktop_tablet_mobile_evidence.denominator == 1
    assert any(
        "punctuation" in warning for warning in report.warnings
    )


def test_page_identity_with_no_pages_earns_zero_capture_credit() -> None:
    plan = _plan(
        (
            _entry(
                entry_id="a",
                source_section_id="home.section.1",
                template=HIGH_NATIVE,
                bindings=(_binding(),),
            ),
        )
    )
    empty_identity = PageIdentityMap(page_ids=(), section_page_ids={})

    report = compute_quality_counts(
        plan,
        CATALOG,
        {"home": {"desktop", "tablet", "mobile"}},
        page_identity=empty_identity,
    )

    assert report.desktop_tablet_mobile_evidence.numerator == 0
    assert report.desktop_tablet_mobile_evidence.denominator == 1
    assert any(
        "no authoritative pages" in warning for warning in report.warnings
    )


def test_ambiguous_section_page_mapping_warns_but_real_pages_still_earn_credit() -> None:
    # A section mapped to a page id that is not in the identity's own
    # page_ids list is ambiguous/unresolvable membership, not a real page.
    plan = _plan(
        (
            _entry(
                entry_id="a",
                source_section_id="home.section.1",
                template=HIGH_NATIVE,
                bindings=(_binding(),),
            ),
        )
    )
    dangling_identity = PageIdentityMap(
        page_ids=("home",), section_page_ids={"home.section.1": "ghost-page"}
    )

    report = compute_quality_counts(
        plan,
        CATALOG,
        {"home": {"desktop", "tablet", "mobile"}, "ghost-page": {"desktop", "tablet", "mobile"}},
        page_identity=dangling_identity,
    )

    # "ghost-page" is not a real page (absent from page_ids), so it can never
    # be credited no matter what capture_evidence claims about it; "home" is
    # a real page and earns credit independently of which entries map to it.
    assert report.desktop_tablet_mobile_evidence.numerator == 1
    assert report.desktop_tablet_mobile_evidence.denominator == 1
    assert any("no page mapping" in warning for warning in report.warnings)


def test_duplicate_page_ids_are_deduplicated_for_the_denominator() -> None:
    plan = _plan(
        (
            _entry(
                entry_id="a",
                source_section_id="home.section.1",
                template=HIGH_NATIVE,
                bindings=(_binding(),),
            ),
        )
    )
    dup_identity = PageIdentityMap(
        page_ids=("home", "home"), section_page_ids={"home.section.1": "home"}
    )

    report = compute_quality_counts(
        plan,
        CATALOG,
        {"home": {"desktop", "tablet", "mobile"}},
        page_identity=dup_identity,
    )

    assert report.desktop_tablet_mobile_evidence.numerator == 1
    assert report.desktop_tablet_mobile_evidence.denominator == 1


def test_report_is_deterministic_across_repeated_calls() -> None:
    plan = _plan(
        (
            _entry(
                entry_id="b",
                source_section_id="home.section.2",
                template=HIGH_NATIVE,
                bindings=(_binding(),),
            ),
            _entry(
                entry_id="a",
                source_section_id="home.section.1",
                template=HIGH_NATIVE,
                bindings=(_binding(),),
            ),
        )
    )

    first = compute_quality_counts(plan, CATALOG, {})
    second = compute_quality_counts(plan, CATALOG, {})

    assert first == second
    assert [row.entry_id for row in first.rows] == ["a", "b"]
