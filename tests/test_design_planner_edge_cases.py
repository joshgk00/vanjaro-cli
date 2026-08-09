"""Adversarial edge-contract audit for DT-201 through DT-204 and DT-213.

Known specification gaps are marked strict xfail so they remain visible without
making the broader integration suite unusable.  Remove each mark with the
corresponding production fix.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from vanjaro_cli.cli import cli
from vanjaro_cli.design.composition import (
    CompositionPlan,
    CompositionPlanEntry,
    IssueSeverity,
    PlanBlock,
    PlanMatch,
    PlanPolicy,
    PlanSummary,
    SimplificationDecision,
    SimplificationKind,
    serialize_composition_plan,
)
from vanjaro_cli.design.models import (
    Alignment,
    AssetKind,
    AssetRecord,
    AssetRole,
    ContentElement,
    ContentKind,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    Interaction,
    InteractionKind,
    LayoutKind,
    LayoutObservation,
    MediaPosition,
    NavigationVisibility,
    Page,
    RepeatGroup,
    RepeatGroupItem,
    RepeatGroupKind,
    Section,
    SourceKind,
    StyleSet,
)
from vanjaro_cli.design.planner import (
    PlanningError,
    bind_section,
    emit_library_plan,
    plan_design_document,
    validate_composition_plan,
)
from vanjaro_cli.design.serialization import write_design_document
from vanjaro_cli.design.template_catalog import TemplateCatalogEntry, load_template_catalog


ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_template_catalog(ROOT / "artifacts" / "block-templates")
REPEAT_ENTRIES = tuple(entry for entry in CATALOG if entry.capabilities.repeat_group is not None)


def _entry(filename: str) -> TemplateCatalogEntry:
    return next(entry for entry in CATALOG if Path(entry.relative_path).name == filename)


def _kind_for_catalog(value: str) -> RepeatGroupKind:
    return {
        "article": RepeatGroupKind.BLOG_POST,
        "card": RepeatGroupKind.CARD,
        "gallery_item": RepeatGroupKind.GALLERY_ITEM,
        "pricing_plan": RepeatGroupKind.PRICING_PLAN,
        "person": RepeatGroupKind.TEAM_MEMBER,
        "testimonial": RepeatGroupKind.TESTIMONIAL,
        "faq_item": RepeatGroupKind.FAQ_ITEM,
        "logo": RepeatGroupKind.OTHER,
        "marquee_item": RepeatGroupKind.OTHER,
        "stat": RepeatGroupKind.STAT,
        "feature": RepeatGroupKind.OTHER,
        "navigation_column": RepeatGroupKind.NAVIGATION_ITEM,
        "navigation_item": RepeatGroupKind.NAVIGATION_ITEM,
    }[value]


def _content_kind(field: str) -> ContentKind:
    leaf = field.rsplit(".", 1)[-1]
    return {
        "title": ContentKind.HEADING,
        "question": ContentKind.HEADING,
        "body": ContentKind.TEXT,
        "answer": ContentKind.TEXT,
        "quote": ContentKind.QUOTE,
        "author": ContentKind.TEXT,
        "media": ContentKind.IMAGE,
        "background_media": ContentKind.IMAGE,
        "icon": ContentKind.IMAGE,
        "action": ContentKind.BUTTON,
        "features": ContentKind.LIST_ITEM,
        "links": ContentKind.LIST_ITEM,
        "value": ContentKind.STAT,
        "price": ContentKind.STAT,
        "label": ContentKind.TEXT,
        "role": ContentKind.TEXT,
        "meta": ContentKind.TEXT,
        "tag": ContentKind.TEXT,
        "contact_items": ContentKind.LIST_ITEM,
    }.get(leaf, ContentKind.TEXT)


def _element(identifier: str, field: str, order: int, *, value: str | None = None) -> ContentElement:
    kind = _content_kind(field)
    leaf = field.rsplit(".", 1)[-1]
    if value is None:
        value = f"/{identifier}.jpg" if kind == ContentKind.IMAGE else f"{leaf} {identifier}"
    attributes = {"alt": f"Alt {identifier}"} if kind == ContentKind.IMAGE else {}
    if kind == ContentKind.BUTTON:
        attributes["href"] = f"/{identifier}"
    return ContentElement(
        id=identifier, kind=kind, role=leaf, value=value,
        attributes=attributes, order=order, provenance=[], confidence=1,
    )


def _catalog_section(entry: TemplateCatalogEntry, *, item_count: int = 2) -> Section:
    content: list[ContentElement] = []
    items: list[RepeatGroupItem] = []
    order = 0
    fields = entry.capabilities.fields

    # Footer brand fields are genuinely section-level; column fields are group
    # fields despite using a `column.` prefix instead of `item.`.
    for semantic_field in fields:
        if semantic_field.startswith("item.") or semantic_field.startswith("column."):
            continue
        order += 1
        content.append(_element(f"section-{order}", semantic_field, order))

    for item_index in range(1, item_count + 1):
        item_fields: dict[str, str | list[str]] = {}
        repeat_fields = [
            field for field in fields
            if field.startswith("item.") or field.startswith("column.")
        ]
        for semantic_field in repeat_fields:
            leaf = semantic_field.rsplit(".", 1)[-1]
            values = []
            value_count = 2 if leaf in {"features", "links"} else 1
            for value_index in range(1, value_count + 1):
                order += 1
                element = _element(
                    f"item-{item_index}-{leaf}-{value_index}", semantic_field, order,
                )
                content.append(element)
                values.append(element.id)
            item_fields[leaf] = values if value_count > 1 else values[0]
        items.append(RepeatGroupItem(id=f"item-{item_index}", fields=item_fields))

    repeat = entry.capabilities.repeat_group
    assert repeat is not None
    return Section(
        id=f"audit.{Path(entry.relative_path).stem}", order=0,
        semantic_role=entry.capabilities.roles[0], role_confidence=1,
        candidate_roles=[],
        layout=LayoutObservation(
            kind=LayoutKind.GRID, contained=True,
            columns=repeat.default, media_position=MediaPosition.TOP,
            alignment=Alignment.LEFT,
        ),
        content=content,
        groups=[RepeatGroup(
            id="repeat-group", kind=_kind_for_catalog(repeat.kind), items=items,
        )],
        style=StyleSet(), responsive=[], decorative_layers=[], interactions=[],
        provenance=[],
    )


def _document(section: Section, *, assets: list[AssetRecord] | None = None) -> DesignDocument:
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.FIGMA, identifier="audit-fixture",
            captured_at=datetime(2026, 7, 16, tzinfo=UTC), adapter_version="1.0",
        ),
        tokens=DesignTokens(), assets=assets or [],
        pages=[Page(
            id="page", source_reference="fixture", title="Audit", slug="audit",
            sections=[section], breakpoints=[],
            navigation_visibility=NavigationVisibility.UNKNOWN, provenance=[],
        )],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1, unsupported_traits=[]),
    )


_family_parameters = []
for _catalog_entry in REPEAT_ENTRIES:
    _filename = Path(_catalog_entry.relative_path).name
    _family_parameters.append(pytest.param(_catalog_entry, id=_filename))


@pytest.mark.parametrize("entry", _family_parameters)
def test_every_catalog_repeat_family_binds_all_required_fields_item_by_item(entry):
    maximum = entry.capabilities.repeat_group.maximum
    section = _catalog_section(entry, item_count=min(2, maximum or 2))
    bindings = bind_section(section, entry)
    required = {
        field for field, requirement in entry.capabilities.fields.items()
        if requirement == "required"
    }
    repeat_fields = {
        field for field in required
        if field.startswith("item.") or field.startswith("column.")
    }
    for item in section.groups[0].items:
        bound = {
            binding.semantic_field for binding in bindings
            if binding.item_id == item.id
        }
        assert repeat_fields <= bound, (entry.name, item.id, repeat_fields - bound)
    section_required = required - repeat_fields
    assert section_required <= {
        binding.semantic_field for binding in bindings if binding.item_id is None
    }


def test_list_valued_repeat_field_binds_each_value_without_losing_item_owner():
    entry = _entry("pricing-cards-3up.json")
    section = _catalog_section(entry, item_count=2)
    bindings = bind_section(section, entry)
    features = [binding for binding in bindings if binding.semantic_field == "item.features"]
    assert [(binding.item_id, binding.value) for binding in features] == [
        ("item-1", "features item-1-features-1"),
        ("item-1", "features item-1-features-2"),
        ("item-2", "features item-2-features-1"),
        ("item-2", "features item-2-features-2"),
    ]
    assert len({binding.slot for binding in features}) == 4
    assert [binding.slot for binding in features] == [
        "list-item_1", "list-item_2", "list-item_4", "list-item_5",
    ]


def test_repeat_field_value_overflow_fails_instead_of_shifting_into_next_owner():
    entry = _entry("pricing-cards-3up.json")
    section = _catalog_section(entry, item_count=2)
    first = section.groups[0].items[0]
    feature_ids = list(first.fields["features"])
    extra = _element("item-1-features-3", "item.features", 100)
    fourth = _element("item-1-features-4", "item.features", 101)
    section = section.model_copy(update={
        "content": [*section.content, extra, fourth],
        "groups": [section.groups[0].model_copy(update={
            "items": [
                first.model_copy(update={
                    "fields": {**first.fields, "features": [*feature_ids, extra.id, fourth.id]}
                }),
                section.groups[0].items[1],
            ]
        })],
    })

    with pytest.raises(PlanningError, match=r"item-1.*item\.features.*4 values.*3 physical"):
        bind_section(section, entry)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        (
            "footer-3col.json",
            {"column.title": "heading_2", "column.links": "list-item_1"},
        ),
        (
            "footer-4col.json",
            {"column.title": "heading_2", "column.links": "list-item_1"},
        ),
    ],
)
def test_footer_repeat_fields_cannot_take_fixed_contact_slots(filename, expected):
    entry = _entry(filename)
    section = _catalog_section(entry, item_count=1)

    bindings = bind_section(section, entry)
    first = {
        field: next(
            binding.slot
            for binding in bindings
            if binding.item_id == "item-1" and binding.semantic_field == field
        )
        for field in expected
    }

    assert {field: first[field] for field in expected} == expected
    assert next(
        binding.slot
        for binding in bindings
        if binding.semantic_field == "contact_title"
    ) == ("heading_3" if filename == "footer-3col.json" else "heading_4")


@pytest.mark.parametrize(
    ("filename", "item_count", "maximum"),
    [("footer-3col.json", 2, 1), ("footer-4col.json", 3, 2)],
)
def test_fixed_footer_capacity_rejects_contact_column_renumbering(
    filename, item_count, maximum
):
    entry = _entry(filename)

    with pytest.raises(PlanningError, match=rf"{item_count}.*maximum.*{maximum}"):
        bind_section(_catalog_section(entry, item_count=item_count), entry)


@pytest.mark.parametrize(
    ("filename", "expected_slots"),
    [
        (
            "class-photo-cards-4up.json",
            {
                    "item.media": "image_1_src", "item.title": "heading_3",
                "item.tag": "text_1", "item.body": "text_2", "item.action": "button_1",
            },
        ),
        (
            "blog-post-cards-3up.json",
            {
                "item.media": "image_1_src", "item.tag": "text_1",
                "item.title": "heading_2", "item.body": "text_2", "item.action": "button_1",
            },
        ),
        (
            "blog-post-cards-4up.json",
            {
                "item.media": "image_1_src", "item.tag": "text_2",
                "item.title": "heading_2", "item.body": "text_3", "item.meta": "text_4",
            },
        ),
    ],
)
def test_mixed_slot_repeat_fields_bind_to_their_physical_slots(filename, expected_slots):
    entry = _entry(filename)
    bindings = bind_section(_catalog_section(entry, item_count=1), entry)
    first_item = {
        binding.semantic_field: binding.slot
        for binding in bindings
        if binding.item_id == "item-1" and not binding.semantic_field.endswith((".alt", ".href"))
    }

    assert first_item == expected_slots


def test_missing_optional_field_reserves_its_slot_and_preserves_later_item_alignment():
    entry = _entry("feature-cards-3up.json")
    section = _catalog_section(entry, item_count=3)
    second = section.groups[0].items[1]
    second_fields = dict(second.fields)
    removed_body = second_fields.pop("body")
    section = section.model_copy(update={
        "content": [element for element in section.content if element.id != removed_body],
        "groups": [section.groups[0].model_copy(update={
            "items": [section.groups[0].items[0], second.model_copy(update={"fields": second_fields}), section.groups[0].items[2]],
        })],
    })
    bindings = bind_section(section, entry)
    third_body = next(
        binding for binding in bindings
        if binding.item_id == "item-3" and binding.semantic_field == "item.body"
    )
    assert third_body.slot == "text_3"
    assert not any(
        binding.item_id == "item-2" and binding.semantic_field == "item.body"
        for binding in bindings
    )


def test_placeholder_optional_field_cannot_shift_the_next_item_owner():
    entry = _entry("feature-cards-3up.json")
    section = _catalog_section(entry, item_count=3)
    second_body = section.groups[0].items[1].fields["body"]
    section = section.model_copy(update={
        "content": [
            element.model_copy(update={"value": "Placeholder text"})
            if element.id == second_body else element
            for element in section.content
        ]
    })

    bindings = bind_section(section, entry)

    third_body = next(
        binding for binding in bindings
        if binding.item_id == "item-3" and binding.semantic_field == "item.body"
    )
    assert third_body.slot == "text_3"
    assert not any(
        binding.item_id == "item-2" and binding.semantic_field == "item.body"
        for binding in bindings
    )


def test_required_media_with_no_asset_or_source_fails_with_item_context():
    entry = _entry("gallery-3up.json")
    section = _catalog_section(entry, item_count=1)
    item = section.groups[0].items[0]
    media_id = item.fields["media"]
    section = section.model_copy(update={
        "content": [
            element.model_copy(update={"value": None, "attributes": {}})
            if element.id == media_id else element
            for element in section.content
        ]
    })
    with pytest.raises(PlanningError, match=r"item-1.*item\.media"):
        bind_section(section, entry)


def test_cta_background_media_binds_to_section_background_slot():
    entry = _entry("cta-banner.json")
    section = Section(
        id="audit.cta-background", order=0,
        semantic_role="cta_banner", role_confidence=1, candidate_roles=[],
        layout=LayoutObservation(
            kind=LayoutKind.STACK, contained=True, columns=1,
            media_position=MediaPosition.BACKGROUND, alignment=Alignment.CENTER,
        ),
        content=[
            _element("cta-title", "title", 0, value="Join the program"),
            _element("cta-action", "action", 1, value="Register now"),
            _element("cta-background", "background_media", 2, value="/images/cta.jpg"),
        ],
        groups=[], style=StyleSet(), responsive=[], decorative_layers=[],
        interactions=[], provenance=[],
    )

    bindings = bind_section(section, entry)

    background = next(binding for binding in bindings if binding.semantic_field == "background_media")
    assert background.slot == "background_image"
    assert background.value == "/images/cta.jpg"


def test_required_media_with_explicit_unresolved_asset_fails():
    entry = _entry("gallery-3up.json")
    section = _catalog_section(entry, item_count=1)
    media_id = section.groups[0].items[0].fields["media"]
    asset = AssetRecord(
        id="missing-asset", kind=AssetKind.IMAGE, role=AssetRole.EDITORIAL,
        missing_reason="signed URL expired",
    )
    section = section.model_copy(update={
        "content": [
            element.model_copy(update={"value": None, "asset_id": asset.id})
            if element.id == media_id else element
            for element in section.content
        ]
    })
    with pytest.raises(PlanningError, match=r"item-1.*item\.media"):
        bind_section(section, entry, assets={asset.id: asset})


def test_unmigrated_remote_media_becomes_visible_blocker_and_never_reaches_library_plan():
    entry = _entry("gallery-3up.json")
    section = _catalog_section(entry, item_count=1)
    media_id = section.groups[0].items[0].fields["media"]
    section = section.model_copy(update={
        "content": [
            element.model_copy(update={"value": "https://source.invalid/original.jpg"})
            if element.id == media_id else element
            for element in section.content
        ]
    })

    plan = plan_design_document(
        _document(section), catalog=CATALOG,
        template_overrides={section.id: entry.template_id},
    )

    assert plan.entries[0].match.blocking is True
    assert any("item.media" in warning for warning in plan.entries[0].warnings)
    assert emit_library_plan(plan) == []


def test_expandable_template_deterministically_expands_within_declared_maximum():
    entry = _entry("feature-cards-3up.json")
    assert entry.capabilities.repeat_group.expandable is True
    section = _catalog_section(entry, item_count=4)
    first = bind_section(section, entry)
    second = bind_section(section, entry)
    assert first == second
    assert {binding.item_id for binding in first if binding.semantic_field == "item.title"} == {
        "item-1", "item-2", "item-3", "item-4",
    }


def test_expanded_plan_dry_runs_through_existing_build_library(runner, tmp_path):
    entry = _entry("feature-cards-3up.json")
    section = _catalog_section(entry, item_count=4)
    plan = plan_design_document(
        _document(section), catalog=CATALOG,
        template_overrides={section.id: entry.template_id},
    )
    library_path = tmp_path / "library-plan.json"
    library_path.write_text(json.dumps(emit_library_plan(plan)), encoding="utf-8")

    assert not validate_composition_plan(plan, catalog=CATALOG)

    result = runner.invoke(
        cli,
        ["blocks", "build-library", "--plan", str(library_path), "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["summary"]["total"] == 1


def test_repeat_overflow_is_rejected_with_declared_capacity_context():
    entry = _entry("feature-cards-3up.json")
    maximum = entry.capabilities.repeat_group.maximum
    assert maximum == 12
    with pytest.raises(PlanningError, match=r"13.*maximum.*12"):
        bind_section(_catalog_section(entry, item_count=13), entry)


def test_optional_slots_are_cleared_and_no_template_placeholder_leaks_to_library_plan():
    entry = _entry("feature-cards-3up.json")
    section = _catalog_section(entry, item_count=2)
    plan = plan_design_document(
        _document(section), catalog=CATALOG,
        template_overrides={section.id: entry.template_id},
    )
    serialized = json.dumps(emit_library_plan(plan), sort_keys=True).lower()
    assert "feature three" not in serialized
    assert "lorem ipsum" not in serialized
    assert "placehold.co" not in serialized
    # Two cards in a three-up. Pack 1.6.0 put the section title in heading_1,
    # so the unused card's title is the fourth heading slot.
    assert emit_library_plan(plan)[0]["overrides"]["heading_4"] == ""


def test_manual_template_override_has_author_reason_and_prior_candidate_audit():
    section = _catalog_section(_entry("feature-cards-3up.json"), item_count=2)
    override = _entry("feature-cards-4up.json")
    plan = plan_design_document(
        _document(section), catalog=CATALOG,
        template_overrides={section.id: override.template_id},
    )
    payload = plan.entries[0].model_dump(mode="json")
    assert payload["override_audit"]["author"]
    assert payload["override_audit"]["reason"]
    assert payload["override_audit"]["previous_candidates"]


def test_high_severity_manual_module_blocks_even_when_simplification_is_allowed():
    entry = _entry("feature-cards-3up.json")
    section = _catalog_section(entry, item_count=2).model_copy(update={
        "interactions": [Interaction(
            id="source-form", kind=InteractionKind.FORM,
            target_element_ids=[], native_representation_known=False,
            provenance=[], confidence=1,
        )]
    })
    plan = plan_design_document(
        _document(section), catalog=CATALOG,
        policy=PlanPolicy(allow_simplification=True),
        template_overrides={section.id: entry.template_id},
    )
    planned = plan.entries[0]
    assert planned.match.blocking is True
    assert any(
        decision.severity == IssueSeverity.HIGH
        and decision.classification == SimplificationKind.MANUAL_MODULE
        and decision.blocks_approval
        for decision in planned.simplifications
    )
    assert plan.summary.blocking_count == 1


def test_plan_contract_rejects_unblocked_high_severity_omission():
    with pytest.raises(ValidationError, match="must block"):
        CompositionPlanEntry(
            id="entry", source_section_id="section", template_id="template",
            template="Template", match=PlanMatch(score=1, confidence="high", blocking=False),
            block=PlanBlock(name="Block", category="Audit"),
            simplifications=(SimplificationDecision(
                trait="interaction:form", classification=SimplificationKind.OMIT,
                severity=IssueSeverity.HIGH, reason="unsupported",
            ),),
        )


def _over_budget_plan() -> CompositionPlan:
    entry = _entry("rich-text.json")
    rules = {f"--audit-rule-{index}": str(index) for index in range(13)}
    plan_entry = CompositionPlanEntry(
        id="entry", source_section_id="section", template_id=entry.template_id,
        template=entry.name, match=PlanMatch(score=1, confidence="high"),
        block=PlanBlock(name="Audit Rich Text", category=entry.category),
        css_scope=".audit-project .design-section-audit", scoped_css=rules,
    )
    return CompositionPlan(
        source_document_id="audit", policy=PlanPolicy(css_rule_budget=12),
        entries=(plan_entry,),
        summary=PlanSummary(
            section_count=1, blocking_count=0, native_component_ratio=1,
            editable_content_coverage=1, scoped_css_rule_count=13,
            scoped_css_bytes=len(json.dumps(rules)),
        ),
    )


def test_css_budget_is_reported_by_library_aware_validator():
    issues = validate_composition_plan(_over_budget_plan(), catalog=CATALOG)
    assert any("rule count 13 exceeds budget 12" in issue for issue in issues)


def test_blocks_plan_validate_returns_structured_css_budget_failure(runner, tmp_path):
    plan_path = tmp_path / "over-budget-plan.json"
    plan_path.write_text(serialize_composition_plan(_over_budget_plan()), encoding="utf-8")
    result = runner.invoke(cli, ["blocks", "plan-validate", str(plan_path), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["category"] == "plan_validation_failed"
    assert "rule count 13 exceeds budget 12" in payload["error"]["message"]


def test_blocks_plan_override_persists_audit_fields(runner, tmp_path):
    section = _catalog_section(_entry("feature-cards-3up.json"), item_count=2)
    override = _entry("feature-cards-4up.json")
    design_path = tmp_path / "design.json"
    plan_path = tmp_path / "plan.json"
    write_design_document(design_path, _document(section))
    result = runner.invoke(cli, [
        "blocks", "plan", "--design", str(design_path), "--output", str(plan_path),
        "--template-override", f"{section.id}={override.template_id}", "--json",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    assert payload["entries"][0]["template_id"] == override.template_id
    assert payload["entries"][0]["override_audit"]["author"] == "cli-user"
    assert payload["entries"][0]["override_audit"]["reason"]
    assert payload["entries"][0]["override_audit"]["previous_candidates"]
