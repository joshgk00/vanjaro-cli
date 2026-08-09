"""Unit tests for deterministic capability-based template matching."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from vanjaro_cli.design.matcher import (
    ConfidenceLevel,
    ConfidencePolicy,
    MatchContext,
    ScoringWeights,
    apply_match_override,
    match_section,
    score_template,
)
from vanjaro_cli.design.models import (
    Alignment,
    BreakpointName,
    ContentElement,
    ContentKind,
    EvidenceStatus,
    Interaction,
    InteractionKind,
    LayoutKind,
    LayoutObservation,
    MediaPosition,
    RepeatGroup,
    RepeatGroupItem,
    RepeatGroupKind,
    ResponsiveObservation,
    Section,
    StyleObservation,
    StyleProperty,
    StyleSet,
    Viewport,
)
from vanjaro_cli.design.template_catalog import TemplateCatalogEntry, load_template_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_template_catalog(PROJECT_ROOT / "artifacts" / "block-templates")


def _entry(filename: str) -> TemplateCatalogEntry:
    return next(entry for entry in CATALOG if Path(entry.relative_path).name == filename)


def _element(index: int, role: str, group_id: str | None = None) -> ContentElement:
    if "media" in role or "image" in role:
        kind = ContentKind.IMAGE
    elif "title" in role:
        kind = ContentKind.HEADING
    elif "action" in role:
        kind = ContentKind.BUTTON
    elif "quote" in role:
        kind = ContentKind.QUOTE
    else:
        kind = ContentKind.TEXT
    return ContentElement(
        id=f"element-{index}",
        kind=kind,
        role=role,
        value=f"{role} value",
        group_id=group_id,
        order=index,
        provenance=[],
        confidence=1.0,
    )


def _section(
    *,
    section_id: str = "section-1",
    role: str = "feature_cards",
    layout_kind: LayoutKind = LayoutKind.GRID,
    columns: int | None = 3,
    media_position: MediaPosition | None = MediaPosition.TOP,
    alignment: Alignment | None = Alignment.LEFT,
    section_roles: tuple[str, ...] = ("section_title",),
    item_fields: tuple[str, ...] = ("title", "body", "media"),
    item_count: int = 3,
    group_kind: RepeatGroupKind = RepeatGroupKind.CARD,
    responsive_columns: tuple[tuple[BreakpointName, int], ...] = (
        (BreakpointName.TABLET, 2),
        (BreakpointName.MOBILE, 1),
    ),
    style: StyleSet | None = None,
    interactions: tuple[InteractionKind, ...] = (),
) -> Section:
    content = [_element(index, content_role) for index, content_role in enumerate(section_roles, 1)]
    groups: list[RepeatGroup] = []
    if item_fields and item_count:
        items: list[RepeatGroupItem] = []
        next_index = len(content) + 1
        for item_index in range(item_count):
            fields: dict[str, str] = {}
            for field_name in item_fields:
                element = _element(next_index, f"card_{field_name}", "group-1")
                content.append(element)
                fields[field_name] = element.id
                next_index += 1
            items.append(RepeatGroupItem(id=f"item-{item_index + 1}", fields=fields))
        groups.append(RepeatGroup(id="group-1", kind=group_kind, items=items))
    responsive = [
        ResponsiveObservation(
            breakpoint=breakpoint,
            viewport=Viewport(width=768 if breakpoint == BreakpointName.TABLET else 390, height=800),
            status=EvidenceStatus.OBSERVED,
            layout_changes={"columns": responsive_count},
        )
        for breakpoint, responsive_count in responsive_columns
    ]
    interaction_models = [
        Interaction(
            id=f"interaction-{index}",
            kind=kind,
            native_representation_known=True,
            provenance=[],
            confidence=1.0,
        )
        for index, kind in enumerate(interactions, 1)
    ]
    return Section(
        id=section_id,
        order=1,
        semantic_role=role,
        role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(
            kind=layout_kind,
            contained=True,
            columns=columns,
            media_position=media_position,
            alignment=alignment,
        ),
        content=content,
        groups=groups,
        style=style or StyleSet(),
        responsive=responsive,
        decorative_layers=[],
        interactions=interaction_models,
        provenance=[],
    )


def _split_hero() -> Section:
    return _section(
        role="hero",
        layout_kind=LayoutKind.SPLIT,
        columns=2,
        media_position=MediaPosition.RIGHT,
        section_roles=("section_title", "body", "primary_action", "hero_media"),
        item_fields=(),
        item_count=0,
        responsive_columns=((BreakpointName.MOBILE, 1),),
    )


def test_matcher_is_deterministic_and_returns_top_three_with_explanations() -> None:
    section = _section()

    first = match_section(section, CATALOG)
    second = match_section(section, reversed(CATALOG))

    assert first == second
    assert len(first.candidates) == 3
    assert Path(first.selected_candidate.template_id).name == "feature-cards-3up"
    assert first.candidates[0].score >= first.candidates[1].score >= first.candidates[2].score
    assert len(first.candidates[0].reasons) == 8
    assert first.candidates[0].subscores.semantic_role == 1.0


def test_each_scoring_dimension_distinguishes_supported_and_unsupported_templates() -> None:
    feature = _section()
    exact = score_template(feature, _entry("feature-cards-3up.json"))
    unrelated = score_template(feature, _entry("rich-text.json"))
    responsive_match = score_template(feature, _entry("feature-cards-4up.json"))
    responsive_mismatch = score_template(feature, _entry("feature-cards-3up.json"))
    styled = _section(
        style=StyleSet(
            observations=[
                StyleObservation(property=StyleProperty.BOX_SHADOW, value="0 1px 4px #0003")
            ]
        )
    )
    style_match = score_template(styled, _entry("feature-cards-3up.json"))
    style_mismatch = score_template(styled, _entry("rich-text.json"))

    assert exact.subscores.semantic_role > unrelated.subscores.semantic_role
    assert exact.subscores.fields > unrelated.subscores.fields
    assert exact.subscores.repeat_group > unrelated.subscores.repeat_group
    assert exact.subscores.layout > unrelated.subscores.layout
    assert responsive_match.subscores.responsive > responsive_mismatch.subscores.responsive
    assert style_match.subscores.style > style_mismatch.subscores.style


def test_interaction_subscore_recognizes_native_video_support() -> None:
    section = _section(
        role="video_feature",
        layout_kind=LayoutKind.STACK,
        columns=1,
        media_position=MediaPosition.BOTTOM,
        section_roles=("section_title", "body", "hero_media", "primary_action"),
        item_fields=(),
        item_count=0,
        responsive_columns=(),
        interactions=(InteractionKind.VIDEO_EMBED,),
    )

    supported = score_template(section, _entry("video-feature.json"))
    unsupported = score_template(section, _entry("rich-text.json"))

    assert supported.subscores.interaction == 1.0
    assert unsupported.subscores.interaction == 0.0
    assert any("required interaction" in issue for issue in unsupported.missing_requirements)


def test_confidence_thresholds_and_weight_contract_are_explicit() -> None:
    policy = ConfidencePolicy()

    assert policy.classify(0.85) == ConfidenceLevel.HIGH
    assert policy.classify(0.849999) == ConfidenceLevel.MEDIUM
    assert policy.classify(0.65) == ConfidenceLevel.MEDIUM
    assert policy.classify(0.649999) == ConfidenceLevel.LOW
    with pytest.raises(ValidationError, match="sum to 1.0"):
        ScoringWeights(semantic_role=0.30)


def test_missing_required_field_caps_otherwise_high_confidence() -> None:
    section = _section(
        role="call_to_action",
        layout_kind=LayoutKind.STACK,
        columns=1,
        media_position=MediaPosition.NONE,
        alignment=Alignment.CENTER,
        section_roles=("section_title", "body", "primary_action", "legal_disclaimer"),
        item_fields=(),
        item_count=0,
        responsive_columns=(),
    )

    candidate = score_template(section, _entry("cta-banner.json"))

    assert candidate.score >= 0.85
    assert candidate.confidence == ConfidenceLevel.MEDIUM
    assert "required field coverage is incomplete" in candidate.confidence_cap_reasons
    assert any("legal_disclaimer" in issue for issue in candidate.missing_requirements)


def test_missing_required_interaction_caps_otherwise_high_confidence() -> None:
    section = _section(
        role="hero",
        layout_kind=LayoutKind.STACK,
        columns=1,
        media_position=MediaPosition.NONE,
        alignment=Alignment.CENTER,
        section_roles=("section_title", "body", "primary_action"),
        item_fields=(),
        item_count=0,
        responsive_columns=(),
        interactions=(InteractionKind.ACCORDION,),
    )

    candidate = score_template(section, _entry("centered-hero.json"))

    assert candidate.score >= 0.85
    assert candidate.confidence == ConfidenceLevel.MEDIUM
    assert "a required interaction is unsupported" in candidate.confidence_cap_reasons


def test_maintainability_blocks_custom_code_auto_selection_when_native_is_medium() -> None:
    native = _entry("centered-hero.json")
    custom_base = _entry("split-hero.json")
    custom = custom_base.model_copy(
        update={
            "template_id": "Custom/custom-code",
            "name": "Custom Code",
            "category": "Custom Code",
            "capabilities": custom_base.capabilities.model_copy(update={"native_component_ratio": 0.0}),
        }
    )
    section = _split_hero()

    result = match_section(
        section,
        (custom, native),
        context=MatchContext(custom_code_template_ids=frozenset({custom.template_id})),
    )

    assert result.candidates[0].template_id == custom.template_id
    assert not result.candidates[0].auto_selectable
    assert result.selected_candidate.template_id == native.template_id
    assert result.selected_candidate.score >= 0.65
    assert result.selected_candidate.maintainability.native_component_ratio == 1.0


def test_maintainability_accounts_for_css_editability_and_reuse() -> None:
    entry = _entry("feature-cards-3up.json")
    section = _section()
    baseline = score_template(section, entry)
    reused = score_template(
        section,
        entry,
        context=MatchContext(
            global_block_template_ids=frozenset({entry.template_id}),
            template_reuse_counts={entry.template_id: 3},
        ),
    )
    css_heavy = score_template(
        section,
        entry,
        context=MatchContext(
            generated_css_bytes_by_template={entry.template_id: 2000},
            generated_css_selectors_by_template={entry.template_id: 10},
        ),
    )

    assert reused.subscores.maintainability > baseline.subscores.maintainability
    assert css_heavy.subscores.maintainability < baseline.subscores.maintainability
    # This item-only template deliberately has no section-title slot. The
    # coverage rose from 0.5 when the template gained an editable media slot
    # (VF-214): more of the observed content now has somewhere real to go.
    assert reused.maintainability.editable_content_coverage == 0.75
    assert any("section_title" in issue for issue in reused.missing_requirements)
    assert reused.maintainability.global_block_reuse


def test_override_records_author_reason_selected_template_and_prior_candidates() -> None:
    section = _split_hero()
    result = match_section(section, CATALOG)
    alternative = score_template(section, _entry("split-media.json"))
    timestamp = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)

    overridden = apply_match_override(
        result,
        alternative,
        author="josh@example.com",
        reason="Agency standard for editorial split sections",
        created_at=timestamp,
    )

    assert overridden.selected_candidate.template_id == alternative.template_id
    assert overridden.override is not None
    assert overridden.override.section_id == section.id
    assert overridden.override.selected_template_id == alternative.template_id
    assert overridden.override.author == "josh@example.com"
    assert overridden.override.reason.startswith("Agency standard")
    assert overridden.override.created_at == timestamp
    assert [item.template_id for item in overridden.override.prior_candidates] == [
        item.template_id for item in result.candidates
    ]
    assert not overridden.blocking


def test_override_requires_auditable_author_reason_and_aware_time() -> None:
    result = match_section(_split_hero(), CATALOG)

    with pytest.raises(ValueError, match="author"):
        apply_match_override(result, result.candidates[0], author=" ", reason="because")
    with pytest.raises(ValueError, match="reason"):
        apply_match_override(result, result.candidates[0], author="Josh", reason=" ")
    with pytest.raises(ValueError, match="timezone-aware"):
        apply_match_override(
            result,
            result.candidates[0],
            author="Josh",
            reason="because",
            created_at=datetime(2026, 7, 16),
        )


def _explanations(section: Section, filename: str) -> tuple[str, ...]:
    return match_section(section, [_entry(filename)]).candidates[0].missing_requirements


def _static_only_capabilities():
    """A real manifest with its media slot moved from editable to static.

    Derived rather than constructed: the three templates that had this shape
    were given a real media slot, so the catalog no longer contains an example,
    but the reporting still has to work.
    """

    capabilities = _entry("gallery-3up.json").capabilities
    fields = {k: v for k, v in capabilities.fields.items() if k != "item.media"}
    return capabilities.model_copy(
        update={
            "fields": fields,
            "static_fields": tuple(capabilities.static_fields) + ("item.media",),
        }
    )


def test_a_field_matching_only_a_static_slot_is_reported() -> None:
    """The quietest content loss in the pipeline: a field aliasing to a slot the
    template declares static counts as represented, so it is never reported
    unsupported, and binding then skips it because only editable fields bind.
    Three designed images left the pilot build that way with no warning."""

    from vanjaro_cli.design.matcher import _field_score

    section = _section(item_fields=("title", "body", "media"))

    _score, _coverage, missing = _field_score(section, _static_only_capabilities())

    assert any(
        "item.media" in message and "static template slot" in message
        for message in missing
    )


def test_a_field_with_no_slot_at_all_is_still_reported_separately() -> None:
    """The two failures need different fixes, so they must read differently."""

    from vanjaro_cli.design.matcher import _field_score

    section = _section(item_fields=("title", "body", "media"))

    _score, _coverage, missing = _field_score(section, _static_only_capabilities())
    static_only = [m for m in missing if "static template slot" in m]

    assert static_only
    assert not any(m in static_only for m in missing if "is not editable" in m)


def test_a_field_bound_to_an_editable_slot_is_not_reported() -> None:
    section = _section(item_fields=("title", "body", "media"))

    explanations = _explanations(section, "feature-cards-3up.json")

    assert not any("item.title" in message for message in explanations)
    assert not any("item.body" in message for message in explanations)


def test_reporting_a_static_only_field_does_not_change_any_score() -> None:
    """Editable coverage already excluded these; only the report was missing."""

    section = _section(item_fields=("title", "body", "media"))
    candidate = match_section(section, [_entry("feature-cards-3up.json")]).candidates[0]

    assert candidate.subscores.fields < 1.0
    assert 0.0 <= candidate.score <= 1.0


def _flat_section(*roles: str) -> Section:
    return _section(
        role="call_to_action",
        section_roles=roles,
        item_fields=(),
        item_count=0,
        layout_kind=LayoutKind.STACK,
        columns=1,
        media_position=None,
    )


def test_a_template_that_cannot_hold_the_content_scores_lower() -> None:
    """Field presence was the whole of the field score, so a template owning one
    action slot scored as well as one owning four against ten actions — and the
    plan then failed at binding, after the choice was already made."""

    entry = _entry("cta-split.json")
    fits = score_template(_flat_section("section_title", "primary_action"), entry)
    overflows = score_template(
        _flat_section("section_title", *["primary_action"] * 10), entry
    )

    assert overflows.score < fits.score


def test_the_overflow_is_reported_with_the_count_it_needs() -> None:
    entry = _entry("cta-split.json")

    candidate = score_template(_flat_section("section_title", *["primary_action"] * 10), entry)

    assert any(
        "needs 10 slots, template owns 1" in requirement
        for requirement in candidate.missing_requirements
    )


def test_content_that_fits_is_not_penalised() -> None:
    entry = _entry("cta-split.json")

    candidate = score_template(_flat_section("section_title", "primary_action"), entry)

    assert not any("slots" in requirement for requirement in candidate.missing_requirements)


def test_a_template_whose_required_field_cannot_be_filled_is_not_chosen() -> None:
    """A contact form matched a CTA banner requiring an action it does not have,
    while the contact template beside it needed none. Choosing an unbuildable
    template only to block afterwards discards one that would have worked."""

    section = _section(
        role="contact",
        section_roles=("section_title", "section_media"),
        item_fields=(),
        item_count=0,
        layout_kind=LayoutKind.STACK,
        columns=1,
        media_position=None,
    )

    result = match_section(section, CATALOG)
    selected = result.selected_candidate

    assert not [
        requirement
        for requirement in selected.missing_requirements
        if requirement.startswith("required template field ")
    ], f"selected {selected.template_id} cannot be filled: {selected.missing_requirements}"


def test_an_unfillable_template_still_wins_when_nothing_can_be_filled() -> None:
    """The rule prefers a buildable template; it does not invent one."""

    section = _section(
        role="contact",
        section_roles=(),
        item_fields=(),
        item_count=0,
        layout_kind=LayoutKind.STACK,
        columns=1,
        media_position=None,
    )

    result = match_section(section, CATALOG)

    assert result.selected_candidate.template_id
