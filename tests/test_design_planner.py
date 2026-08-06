"""Composition Plan v2 and semantic binding tests."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from vanjaro_cli.design.composition import (
    CompositionPlan,
    CompositionPlanEntry,
    PlanBlock,
    PlanMatch,
    PlanSummary,
    SemanticBinding,
    deserialize_composition_plan,
    render_composition_plan_schema,
    serialize_composition_plan,
)
from vanjaro_cli.design.models import (
    Alignment,
    AssetKind,
    AssetRecord,
    ContentElement,
    ContentKind,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
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
    StyleObservation,
    StyleProperty,
    StyleSet,
)
from vanjaro_cli.design.planner import (
    PlanningError,
    bind_section,
    emit_library_plan,
    plan_design_document,
)
from vanjaro_cli.design.template_catalog import load_template_catalog


ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_template_catalog(ROOT / "artifacts" / "block-templates")


def _entry(filename: str):
    return next(entry for entry in CATALOG if Path(entry.relative_path).name == filename)


def _element(
    index: int, kind: ContentKind, role: str, value: str, *, prefix: str = "element"
) -> ContentElement:
    return ContentElement(
        id=f"{prefix}-{index}",
        kind=kind,
        role=role,
        value=value,
        order=index,
        provenance=[],
        confidence=1.0,
    )


def _feature_section(
    *,
    missing_second_title: bool = False,
    section_id: str = "home.services",
    element_prefix: str = "element",
    group_id: str = "cards",
    item_prefix: str = "card",
) -> Section:
    content = [
        _element(1, ContentKind.HEADING, "section_title", "Our Services", prefix=element_prefix)
    ]
    items = []
    next_index = 2
    for item_index in range(2):
        fields: dict[str, str] = {}
        if not (missing_second_title and item_index == 1):
            title = _element(
                next_index, ContentKind.HEADING, "card_title", f"Service {item_index + 1}",
                prefix=element_prefix,
            )
            content.append(title)
            fields["title"] = title.id
            next_index += 1
        body = _element(
            next_index, ContentKind.TEXT, "card_body", f"Body {item_index + 1}",
            prefix=element_prefix,
        )
        content.append(body)
        fields["body"] = body.id
        next_index += 1
        action = ContentElement(
            id=f"{element_prefix}-{next_index}",
            kind=ContentKind.BUTTON,
            role="card_action",
            value=f"Learn {item_index + 1}",
            attributes={"href": f"/service-{item_index + 1}"},
            order=next_index,
            provenance=[],
            confidence=1.0,
        )
        content.append(action)
        fields["action"] = action.id
        next_index += 1
        items.append(RepeatGroupItem(id=f"{item_prefix}-{item_index + 1}", fields=fields))
    return Section(
        id=section_id,
        order=0,
        semantic_role="feature_cards",
        role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(
            kind=LayoutKind.GRID,
            contained=True,
            columns=3,
            media_position=MediaPosition.TOP,
            alignment=Alignment.LEFT,
        ),
        content=content,
        groups=[RepeatGroup(id=group_id, kind=RepeatGroupKind.CARD, items=items)],
        style=StyleSet(),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )


def _document(section: Section) -> DesignDocument:
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.LIVE_HTML,
            identifier="https://source.test",
            captured_at=datetime(2026, 7, 16, tzinfo=UTC),
            adapter_version="1.0",
        ),
        tokens=DesignTokens(),
        assets=[],
        pages=[
            Page(
                id="home",
                source_reference="https://source.test",
                title="Home",
                slug="",
                sections=[section],
                breakpoints=[],
                navigation_visibility=NavigationVisibility.VISIBLE,
                provenance=[],
            )
        ],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1.0, unsupported_traits=[]),
    )


def test_repeat_items_bind_from_declared_relationships_not_matching_suffixes() -> None:
    bindings = bind_section(_feature_section(), _entry("feature-cards-3up.json"))
    by_source_and_field = {
        (binding.source_element_ids[0], binding.semantic_field): binding for binding in bindings
    }

    first_title = by_source_and_field[("element-2", "item.title")]
    second_title = by_source_and_field[("element-5", "item.title")]
    assert first_title.item_id == "card-1"
    assert second_title.item_id == "card-2"


def test_section_semantic_fields_prefer_distinct_matching_elements() -> None:
    section = Section(
        id="video",
        order=0,
        semantic_role="video_feature",
        role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.STACK, contained=True),
        content=[
            _element(1, ContentKind.HEADING, "eyebrow", "Our Media"),
            _element(2, ContentKind.HEADING, "section_title", "See what students can do"),
            _element(3, ContentKind.IMAGE, "media", "assets/video-poster.jpg"),
        ],
        groups=[],
        style=StyleSet(),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )

    bindings = bind_section(section, _entry("video-feature.json"))

    by_field = {binding.semantic_field: binding.value for binding in bindings}
    assert by_field["eyebrow"] == "Our Media"
    assert by_field["title"] == "See what students can do"


def test_section_title_role_beats_preceding_generic_heading_for_title() -> None:
    section = Section(
        id="cta",
        order=0,
        semantic_role="call_to_action",
        role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.SPLIT, contained=True),
        content=[
            _element(1, ContentKind.HEADING, "subtitle", "Give your child the gift of music"),
            _element(2, ContentKind.HEADING, "section_title", "Join our music studio"),
            _element(3, ContentKind.TEXT, "body", "Programs come to your community."),
            _element(4, ContentKind.IMAGE, "section_media", "assets/mobile-studio.png"),
        ],
        groups=[],
        style=StyleSet(),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )

    bindings = bind_section(section, _entry("cta-split.json"))

    by_field = {binding.semantic_field: binding.value for binding in bindings}
    assert by_field["title"] == "Join our music studio"
    assert by_field["subtitle"] == "Give your child the gift of music"


def test_button_content_and_href_use_distinct_slots_without_stealing_next_button() -> None:
    bindings = bind_section(_feature_section(), _entry("feature-cards-3up.json"))
    actions = [binding for binding in bindings if binding.semantic_field.startswith("item.action")]

    assert [(item.item_id, item.slot, item.value) for item in actions] == [
        ("card-1", "button_1", "Learn 1"),
        ("card-1", "button_1_href", "/service-1"),
        ("card-2", "button_2", "Learn 2"),
        ("card-2", "button_2_href", "/service-2"),
    ]


def test_missing_required_repeat_field_fails_with_item_context() -> None:
    with pytest.raises(PlanningError, match=r"home\.services/card-2.*item\.title"):
        bind_section(_feature_section(missing_second_title=True), _entry("feature-cards-3up.json"))


def test_document_planning_preserves_binding_blocker_and_continues_supported_sections() -> None:
    blocked = _feature_section(missing_second_title=True)
    supported = _feature_section(
        section_id="home.more-services",
        element_prefix="more-element",
        group_id="more-cards",
        item_prefix="more-card",
    ).model_copy(update={"order": 1})
    document = _document(blocked)
    document = document.model_copy(
        update={
            "pages": [
                document.pages[0].model_copy(update={"sections": [blocked, supported]})
            ]
        }
    )
    document = DesignDocument.model_validate(document.model_dump(mode="json"))

    plan = plan_design_document(document, catalog=CATALOG)
    library = emit_library_plan(plan)

    assert plan.summary.section_count == 2
    assert plan.summary.blocking_count == 1
    assert plan.entries[0].match.blocking is True
    assert plan.entries[0].simplifications[0].classification.value == "new_template"
    assert any("card-2" in warning for warning in plan.entries[0].warnings)
    assert [item["name"] for item in library] == ["Home Feature Cards 2"]


def test_plan_is_deterministic_and_emits_current_library_format_without_sample_copy() -> None:
    document = _document(_feature_section())

    first = plan_design_document(document, catalog=CATALOG)
    second = plan_design_document(document, catalog=reversed(CATALOG))
    library = emit_library_plan(first)

    assert first == second
    assert first.entries[0].template == "Feature Cards (3-up)"
    assert first.entries[0].block.name == "Home Feature Cards"
    assert library[0]["overrides"]["heading_1"] == "Service 1"
    assert library[0]["overrides"]["heading_3"] == ""
    assert len(library[0]["template_digest"]) == 64
    assert "Feature Three" not in str(library)
    assert deserialize_composition_plan(serialize_composition_plan(first)) == first


def test_plan_records_explainable_style_decisions_and_css_budget_metrics() -> None:
    section = _feature_section().model_copy(
        update={
            "style": StyleSet(
                observations=[
                    StyleObservation(property=StyleProperty.FONT_SIZE, value="19px")
                ]
            )
        }
    )

    plan = plan_design_document(_document(section), catalog=CATALOG)
    entry = plan.entries[0]

    assert entry.style_decisions[0].source_value == "19px"
    assert entry.style_decisions[0].layer.value == "scoped_css"
    assert entry.style_decisions[0].confidence > 0
    assert entry.css_scope == ".https-source-test .design-section-home-services"
    assert entry.scoped_css == {"font-size": "19px"}
    assert plan.summary.scoped_css_rule_count == 1
    assert plan.summary.scoped_css_bytes > 0


def test_placeholder_source_value_is_never_emitted() -> None:
    plan = CompositionPlan(
        source_document_id="design-test",
        entries=(
            CompositionPlanEntry(
                id="section.plan",
                source_section_id="section",
                template_id="template",
                template="Template",
                match=PlanMatch(score=1, confidence="high"),
                block=PlanBlock(name="Unique", category="Test"),
                bindings=(
                    SemanticBinding(
                        semantic_field="media",
                        slot="image_1_src",
                        source_element_ids=("image",),
                        value="https://placehold.co/800x600",
                    ),
                ),
            ),
        ),
        summary=PlanSummary(
            section_count=1,
            blocking_count=0,
            native_component_ratio=1,
            editable_content_coverage=1,
        ),
    )

    with pytest.raises(PlanningError, match="placeholder value rejected"):
        emit_library_plan(plan)


def test_plan_contract_rejects_duplicate_block_names() -> None:
    entry = CompositionPlanEntry(
        id="one.plan",
        source_section_id="one",
        template_id="template",
        template="Template",
        match=PlanMatch(score=1, confidence="high"),
        block=PlanBlock(name="Duplicate", category="Test"),
    )
    with pytest.raises(ValidationError, match="block names must be unique"):
        CompositionPlan(
            source_document_id="design-test",
            entries=(
                entry,
                entry.model_copy(
                    update={"id": "two.plan", "source_section_id": "two"}
                ),
            ),
            summary=PlanSummary(
                section_count=2,
                blocking_count=0,
                native_component_ratio=1,
                editable_content_coverage=1,
            ),
        )


def test_committed_composition_schema_matches_model() -> None:
    committed = json.loads(
        (ROOT / "schemas" / "composition-plan-v2.schema.json").read_text(encoding="utf-8")
    )
    generated = json.loads(render_composition_plan_schema())

    assert committed == generated


def _gallery_section_with_image(asset_id: str) -> Section:
    image = ContentElement(
        id="element-9",
        kind=ContentKind.IMAGE,
        role="card_media",
        value=None,
        asset_id=asset_id,
        group_id="gallery",
        order=1,
        provenance=[],
        confidence=1.0,
    )
    return Section(
        id="home.gallery",
        order=1,
        semantic_role="gallery",
        role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.GRID, contained=True, columns=3),
        content=[image],
        groups=[
            RepeatGroup(
                id="gallery",
                kind=RepeatGroupKind.GALLERY_ITEM,
                items=[RepeatGroupItem(id="shot-1", fields={"media": image.id})],
            )
        ],
        style=StyleSet(),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )


def _unresolvable_asset(asset_id: str) -> AssetRecord:
    """An asset the crawl recorded but never resolved to a usable file."""

    return AssetRecord(
        id=asset_id,
        kind=AssetKind.IMAGE,
        role="editorial",
        source_url="https://source.test/missing.jpg",
        local_path=None,
    )


def test_an_unresolvable_image_records_why_alongside_the_existing_error() -> None:
    """`gallery-3up` requires `item.media`, so the loss already raises. What it
    never said was *why*: "missing or has no slot" reads like a library gap when
    the real cause is an asset that resolved to nothing. The two need different
    fixes."""

    dropped: list[str] = []
    with pytest.raises(PlanningError) as raised:
        bind_section(
            _gallery_section_with_image("asset-1"),
            _entry("gallery-3up.json"),
            assets={"asset-1": _unresolvable_asset("asset-1")},
            dropped=dropped,
        )

    assert any("item.media" in issue for issue in raised.value.issues)
    assert len(dropped) == 1
    assert "element-9" in dropped[0]
    assert "no usable source" in dropped[0]


def test_a_resolvable_image_binds_and_reports_nothing() -> None:
    resolved = AssetRecord(
        id="asset-1",
        kind=AssetKind.IMAGE,
        role="editorial",
        source_url="https://source.test/photo.jpg",
        local_path="assets/photo.jpg",
    )
    dropped: list[str] = []

    bindings = bind_section(
        _gallery_section_with_image("asset-1"),
        _entry("gallery-3up.json"),
        assets={"asset-1": resolved},
        dropped=dropped,
    )

    assert [b for b in bindings if b.semantic_field == "item.media"]
    assert dropped == []


def test_the_sink_is_optional_and_never_changes_binding() -> None:
    section = _gallery_section_with_image("asset-1")
    assets = {"asset-1": _unresolvable_asset("asset-1")}

    with pytest.raises(PlanningError) as with_sink:
        bind_section(section, _entry("gallery-3up.json"), assets=assets, dropped=[])
    with pytest.raises(PlanningError) as without:
        bind_section(section, _entry("gallery-3up.json"), assets=assets)

    assert with_sink.value.issues == without.value.issues
