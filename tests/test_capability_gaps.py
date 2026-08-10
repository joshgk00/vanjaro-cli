"""The capability gap report has to rank work, not just list warnings.

Every gap found so far was found by a person reading one site's loss list by
eye. These tests pin the three things that make the report worth reading
instead: it attributes a loss to a template, it refuses to rank losses that are
not capability gaps, and it does not send anyone to fix what the library has
already fixed.
"""

from __future__ import annotations

import pytest

from vanjaro_cli.design.capability_gaps import (
    MatchedCase,
    PlannedProject,
    build_capability_gap_report,
)
from vanjaro_cli.design.matcher import (
    ConfidenceLevel,
    MaintainabilitySignals,
    MatchSubscores,
    TemplateMatchCandidate,
    TemplateMatchResult,
)
from vanjaro_cli.design.composition import (
    CompositionPlan,
    CompositionPlanEntry,
    PlanBlock,
    PlanMatch,
    PlanSummary,
)
from vanjaro_cli.design.template_catalog import load_template_catalog


def _entry(
    section: str,
    template_id: str,
    warnings: tuple[str, ...],
    *,
    form_fields: tuple[dict, ...] = (),
) -> CompositionPlanEntry:
    return CompositionPlanEntry(
        id=f"entry-{section}",
        source_section_id=section,
        template_id=template_id,
        template=template_id.split("/")[-1],
        match=PlanMatch(score=0.8, confidence="high"),
        block=PlanBlock(name=f"block-{section}", category="Cards"),
        warnings=warnings,
        form_fields=form_fields,
    )


def _project(project_id: str, *entries: CompositionPlanEntry) -> PlannedProject:
    return PlannedProject(
        project_id=project_id,
        plan=CompositionPlan(
            source_document_id=f"design:{project_id}",
            entries=entries,
            summary=PlanSummary(
                section_count=len(entries),
                blocking_count=0,
                native_component_ratio=1.0,
                editable_content_coverage=1.0,
            ),
        ),
    )


def _uneditable(field: str) -> str:
    return f"source field '{field}' is not editable by template"


def test_a_gap_is_attributed_to_the_template_that_dropped_the_content() -> None:
    """A section id alone cannot be worked from — it says where content was lost
    but not what to widen."""

    report = build_capability_gap_report(
        [_project("site", _entry("s.1", "Cards/feature-cards-4up", (_uneditable("body"),)))]
    )

    assert [(gap.template_id, gap.field, gap.kind) for gap in report.gaps] == [
        ("Cards/feature-cards-4up", "body", "no_field")
    ]
    assert report.gaps[0].sections == ("s.1",)
    assert report.gaps[0].projects == ("site",)


def test_the_worst_gap_ranks_first_across_sites() -> None:
    """Ranked by sections lost, because that is what widening recovers — and
    across sites, so a gap costing three sections on a site nobody is looking at
    outranks one costing a section on the site in hand."""

    report = build_capability_gap_report(
        [
            _project(
                "far",
                _entry("f.1", "Cards/feature-cards-4up", (_uneditable("body"),)),
                _entry("f.2", "Cards/feature-cards-4up", (_uneditable("body"),)),
            ),
            _project("near", _entry("n.1", "Content/video-feature", (_uneditable("primary_action"),))),
        ]
    )

    assert [gap.field for gap in report.gaps] == ["body", "primary_action"]
    assert report.gaps[0].dropped_field_count == 2
    assert report.gaps[0].projects == ("far",)


def test_one_overflow_reported_twice_counts_as_one_section() -> None:
    """The matcher says it while choosing and the planner says it again while
    binding. Counting warnings would rank a capacity gap above a missing field
    purely for being mentioned more often."""

    report = build_capability_gap_report(
        [
            _project(
                "site",
                _entry(
                    "s.2",
                    "Content/split-media-reverse",
                    (
                        "body needs 3 slots, template owns 1",
                        "s.2: field 'body' has 3 values but owns 1 physical slots",
                    ),
                ),
            )
        ]
    )

    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.kind == "insufficient_capacity"
    assert gap.dropped_field_count == 1
    assert (gap.demanded_slots, gap.owned_slots) == (3, 1)


def test_capacity_records_the_largest_demand_any_section_made() -> None:
    """Widening to the largest demand closes every section the gap covers;
    widening to the smallest closes one and leaves the report unchanged."""

    report = build_capability_gap_report(
        [
            _project(
                "site",
                _entry("s.1", "Content/split-media", ("body needs 2 slots, template owns 1",)),
                _entry("s.2", "Content/split-media", ("body needs 5 slots, template owns 1",)),
            )
        ]
    )

    assert report.gaps[0].demanded_slots == 5


def test_a_form_field_is_held_back_when_the_form_travels_as_a_placeholder() -> None:
    """A form is never rebuilt from a template, so ranking this would send the
    next iteration to give a template a field it must not have."""

    report = build_capability_gap_report(
        [
            _project(
                "site",
                _entry(
                    "s.4",
                    "CTAs/cta-split",
                    (_uneditable("form_field"),),
                    form_fields=({"name": "email", "type": "email"},),
                ),
            )
        ]
    )

    assert report.gaps == ()
    assert len(report.held_back) == 1
    assert "placeholder" in report.held_back[0].reason


def test_a_form_field_nobody_inventoried_is_still_a_gap() -> None:
    """Held back on the evidence that the form was handled, not on the field's
    name — otherwise a form the pipeline silently dropped would read as handled."""

    report = build_capability_gap_report(
        [_project("site", _entry("s.4", "CTAs/cta-split", (_uneditable("form_field"),)))]
    )

    assert [gap.field for gap in report.gaps] == ["form_field"]
    assert report.held_back == ()


def test_a_picture_the_extractor_called_decoration_is_not_a_gap() -> None:
    """A mascot floated beside a video was deliberately kept out of the media
    the template holds, because counting it made the section overflow. Ranking
    it would ask for a field that undoes that decision."""

    report = build_capability_gap_report(
        [_project("site", _entry("s.10", "Content/video-feature", (_uneditable("decorative_media"),)))]
    )

    assert report.gaps == ()
    assert report.held_back[0].reason == (
        "the extractor classified this picture as decoration, not content"
    )


def test_real_content_dropped_by_the_same_template_still_ranks() -> None:
    """The rule holds back one field, not the template that carried it."""

    report = build_capability_gap_report(
        [
            _project(
                "site",
                _entry(
                    "s.10",
                    "Content/video-feature",
                    (_uneditable("decorative_media"), _uneditable("primary_action")),
                ),
            )
        ]
    )

    assert [gap.field for gap in report.gaps] == ["primary_action"]
    assert len(report.held_back) == 1


def test_an_asset_that_resolved_to_nothing_is_not_a_template_gap() -> None:
    """The template owned the slot. Widening it would change nothing, and the
    real defect — the picture never arrived — would keep its cover."""

    warning = "image s.2.background-media.1 was not bound: its asset resolved to no usable source"
    report = build_capability_gap_report(
        [_project("site", _entry("s.2", "Heroes/centered-hero", (warning,)))]
    )

    assert report.gaps == ()
    assert report.held_back[0].reason.startswith("the template owns the slot")


def test_an_unsupported_interaction_is_not_a_missing_field() -> None:
    report = build_capability_gap_report(
        [_project("site", _entry("s.4", "CTAs/cta-split", ("required interaction 'form' is unsupported",)))]
    )

    assert report.gaps == ()
    assert "behaviour" in report.held_back[0].reason


def test_a_template_wanting_content_the_source_lacks_is_not_a_gap() -> None:
    """The mirror image of a gap: nothing was dropped, so there is nothing to
    widen and ranking it would be work that recovers no content."""

    report = build_capability_gap_report(
        [
            _project(
                "site",
                _entry(
                    "s.1",
                    "Cards/gallery-3up",
                    ("required template field 'section_body' has no source content",),
                ),
            )
        ]
    )

    assert report.gaps == ()
    assert report.held_back == ()


def test_a_static_only_field_is_a_gap_of_its_own_kind() -> None:
    """The field is declared, so a check that only asks whether the name exists
    would call this fixed while the content still cannot reach the build."""

    warning = (
        "source field 'body' maps only to a static template slot, "
        "so its content cannot reach the build"
    )
    report = build_capability_gap_report([_project("site", _entry("s.1", "Cards/gallery-3up", (warning,)))])

    assert [(gap.field, gap.kind) for gap in report.gaps] == [("body", "static_only")]


def _match(section: str, template_id: str, missing: tuple[str, ...]) -> TemplateMatchResult:
    candidate = TemplateMatchCandidate(
        template_id=template_id,
        template_name=template_id.split("/")[-1],
        score=0.8,
        confidence=ConfidenceLevel.HIGH,
        subscores=MatchSubscores(
            semantic_role=1.0,
            fields=0.8,
            repeat_group=1.0,
            layout=1.0,
            responsive=1.0,
            style=1.0,
            interaction=1.0,
            maintainability=1.0,
        ),
        missing_requirements=missing,
        reasons=(),
        maintainability=MaintainabilitySignals(
            native_component_ratio=1.0,
            editable_content_coverage=0.8,
            required_modifier_count=0,
            estimated_css_bytes=0,
            estimated_css_selectors=0,
            uses_custom_code=False,
            global_block_reuse=False,
            template_reuse_count=1,
        ),
    )
    return TemplateMatchResult(
        section_id=section,
        candidates=(candidate,),
        selected_candidate=candidate,
        blocking=False,
    )


def test_a_benchmark_case_reports_gaps_without_a_plan() -> None:
    """The corpus never builds a composition plan, so for thirty-odd iterations
    the ranked queue covered the projects someone had open and none of the five
    cases the pipeline is measured against."""

    report = build_capability_gap_report(
        [
            MatchedCase(
                case_id="html-dnn-services",
                matches=(_match("s.3", "Content/stats-band-3up", (_uneditable("section_title"),)),),
            )
        ]
    )

    assert [(gap.template_id, gap.field) for gap in report.gaps] == [
        ("Content/stats-band-3up", "section_title")
    ]
    assert report.gaps[0].projects == ("html-dnn-services",)
    assert report.section_count == 1


def test_a_case_and_a_project_losing_the_same_field_are_one_gap() -> None:
    """Ranking is by sections lost wherever they are, or a gap that costs one
    section in each of two places would rank below one costing two in either."""

    report = build_capability_gap_report(
        [
            _project("site", _entry("s.1", "Content/stats-band-3up", (_uneditable("section_title"),))),
            MatchedCase(
                case_id="case",
                matches=(_match("s.3", "Content/stats-band-3up", (_uneditable("section_title"),)),),
            ),
        ]
    )

    assert len(report.gaps) == 1
    assert report.gaps[0].dropped_field_count == 2
    assert report.gaps[0].projects == ("case", "site")


def test_a_loss_on_a_wrongly_matched_section_is_a_routing_defect() -> None:
    """The corpus says which templates are acceptable. Widening the one that
    won anyway would bind the content and bury the reason it was reached."""

    report = build_capability_gap_report(
        [
            MatchedCase(
                case_id="case",
                matches=(_match("s.0", "Heroes/centered-hero", (_uneditable("hero_media"),)),),
                expected_templates=(("split-hero", "split-media-reverse"),),
            )
        ]
    )

    assert report.gaps == ()
    assert "routing defect" in report.held_back[0].reason


def test_a_loss_on_an_acceptable_template_still_ranks() -> None:
    """The guard must not swallow the corpus's real gaps: `stats-band-3up` is
    the template its sections are supposed to match, and it has no heading."""

    report = build_capability_gap_report(
        [
            MatchedCase(
                case_id="case",
                matches=(_match("s.3", "Content/stats-band-3up", (_uneditable("section_title"),)),),
                expected_templates=(("stats-band-3up", "icon-feature-list"),),
            )
        ]
    )

    assert [gap.field for gap in report.gaps] == ["section_title"]
    assert report.held_back == ()


def test_a_project_has_no_answer_key_so_nothing_is_held_back_for_routing() -> None:
    """Only the corpus knows which template a section should match. A project
    plan must not be second-guessed by an empty expectation."""

    report = build_capability_gap_report(
        [_project("site", _entry("s.1", "Heroes/centered-hero", (_uneditable("hero_media"),)))]
    )

    assert [gap.field for gap in report.gaps] == ["hero_media"]


def test_a_per_item_field_on_a_template_that_repeats_nothing_is_not_a_gap() -> None:
    """`cta-banner` repeats nothing, so there is no item for `item.event_type`
    to belong to and declaring one would give the template nowhere to put a
    second value. The section carries a list, which is a bigger question."""

    catalog = {entry.template_id: entry.capabilities for entry in load_template_catalog()}
    report = build_capability_gap_report(
        [_project("site", _entry("s.4", "CTAs/cta-banner", (_uneditable("item.event_type"),)))],
        catalog=catalog,
    )

    assert report.gaps == ()
    assert "repeats nothing" in report.held_back[0].reason


def test_a_per_item_field_on_a_template_that_does_repeat_still_ranks() -> None:
    """`logo-bar` repeats logos and holds only their pictures, so a logo's name
    is a field it could have and does not."""

    catalog = {entry.template_id: entry.capabilities for entry in load_template_catalog()}
    report = build_capability_gap_report(
        [_project("site", _entry("s.1", "Content/logo-bar", (_uneditable("item.label"),)))],
        catalog=catalog,
    )

    assert [(gap.template_id, gap.field) for gap in report.gaps] == [
        ("Content/logo-bar", "item.label")
    ]
    assert report.held_back == ()


def test_a_section_level_field_on_a_non_repeating_template_still_ranks() -> None:
    """The rule is about per-item fields. A section-level field on the same
    template is an ordinary gap and must not be swept up with them."""

    catalog = {entry.template_id: entry.capabilities for entry in load_template_catalog()}
    report = build_capability_gap_report(
        [_project("site", _entry("s.4", "CTAs/cta-banner", (_uneditable("eyebrow"),)))],
        catalog=catalog,
    )

    assert [gap.field for gap in report.gaps] == ["eyebrow"]


def test_without_a_catalog_the_repeat_group_cannot_be_checked() -> None:
    """The report still works with no library to consult; it just cannot make
    this judgement, and it says nothing rather than guessing."""

    report = build_capability_gap_report(
        [_project("site", _entry("s.4", "CTAs/cta-banner", (_uneditable("item.event_type"),)))]
    )

    assert [gap.field for gap in report.gaps] == ["item.event_type"]


def test_a_gap_the_library_has_since_closed_is_not_ranked() -> None:
    """Pack 1.6.0 gave `feature-cards-3up` a section title. A plan written
    before it still reports the loss, and some plans cannot be refreshed to find
    out — re-analysing a project invalidates approvals granted against it."""

    catalog = {entry.template_id: entry.capabilities for entry in load_template_catalog()}
    report = build_capability_gap_report(
        [_project("older", _entry("s.3", "Cards/feature-cards-3up", (_uneditable("section_title"),)))],
        catalog=catalog,
    )

    assert report.gaps == ()
    assert len(report.stale) == 1
    assert report.stale[0].reason == "the template now declares the field as editable"


def test_a_gap_the_library_still_has_stays_ranked() -> None:
    """The guard above must not swallow live work: `pricing-cards-3up` has no
    section title, and the report has to keep saying so."""

    catalog = {entry.template_id: entry.capabilities for entry in load_template_catalog()}
    report = build_capability_gap_report(
        [_project("site", _entry("s.4", "Cards/pricing-cards-3up", (_uneditable("section_title"),)))],
        catalog=catalog,
    )

    assert [(gap.template_id, gap.field) for gap in report.gaps] == [
        ("Cards/pricing-cards-3up", "section_title")
    ]
    assert report.stale == ()


def test_a_capacity_gap_the_library_has_widened_enough_is_not_ranked() -> None:
    catalog = {entry.template_id: entry.capabilities for entry in load_template_catalog()}
    report = build_capability_gap_report(
        [_project("older", _entry("s.1", "Content/bio-about", ("body needs 3 slots, template owns 1",)))],
        catalog=catalog,
    )

    assert report.gaps == ()
    assert report.stale[0].reason == "the template now owns 3 slots for the field"


def test_a_template_that_has_left_the_library_is_not_work() -> None:
    report = build_capability_gap_report(
        [_project("older", _entry("s.1", "Cards/retired-template", (_uneditable("body"),)))],
        catalog={},
    )

    assert report.gaps == ()
    assert report.stale[0].reason == "the template is no longer in the library"


def test_the_same_evidence_produces_the_same_order() -> None:
    """A queue that reshuffles between runs cannot be worked from."""

    projects = [
        _project(
            "site",
            _entry("s.1", "Cards/gallery-6up", (_uneditable("body"),)),
            _entry("s.2", "Cards/blog-post-cards-3up", (_uneditable("body"),)),
            _entry("s.3", "Content/logo-bar", (_uneditable("section_body"),)),
        )
    ]

    first = build_capability_gap_report(projects)
    second = build_capability_gap_report(projects)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert [gap.template_id for gap in first.gaps] == [
        "Cards/blog-post-cards-3up",
        "Cards/gallery-6up",
        "Content/logo-bar",
    ]


@pytest.mark.parametrize("kind", ["no_field", "insufficient_capacity"])
def test_the_report_counts_sections_not_warnings(kind: str) -> None:
    warning = (
        _uneditable("body") if kind == "no_field" else "body needs 2 slots, template owns 1"
    )
    report = build_capability_gap_report(
        [
            _project(
                "site",
                _entry("s.1", "Cards/feature-cards-4up", (warning,)),
                _entry("s.2", "Cards/feature-cards-4up", (warning,)),
            )
        ]
    )

    assert report.dropped_field_count == 2
    assert report.gaps[0].sections == ("s.1", "s.2")
