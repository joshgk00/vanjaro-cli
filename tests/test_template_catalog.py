"""Focused tests for the versioned block-template capability catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from vanjaro_cli.design.template_catalog import (
    CapabilityManifest,
    TemplateCatalogError,
    check_generated_artifacts,
    load_template_catalog,
    load_template_data,
    render_capability_schema,
    render_catalog_markdown,
    write_generated_artifacts,
)
from vanjaro_cli.design.physical_contract import primary_slots
from vanjaro_cli.orchestration.project_planning import template_catalog_fingerprint
from vanjaro_cli.utils.block_compose import find_template


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PROJECT_ROOT / "artifacts" / "block-templates"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "template-capabilities-v1.1.schema.json"
CATALOG_DOC_PATH = PROJECT_ROOT / "docs" / "template-capability-catalog.md"

# Audited semantic ownership contract. Each declaration maps to a distinct
# editable slot (or to the section background slot for ``background_media``).
# In particular, item-only templates must not advertise a section title, and
# section actions must not be advertised as per-item actions.
EXPECTED_FIELDS_BY_TEMPLATE = {
    "Cards/blog-post-cards-3up.json": {
        "section_title", "item.media", "item.tag", "item.title", "item.body", "item.action"
    },
    "Cards/blog-post-cards-4up.json": {
        "section_title", "section_body", "item.media", "item.tag", "item.title", "item.body",
        "item.meta", "action"
    },
    "Cards/class-photo-cards-4up.json": {
        "section_title", "subtitle", "item.title", "item.body", "item.media", "item.tag", "item.action"
    },
    "Cards/feature-cards-3up.json": {
        "section_title", "item.title", "item.body", "item.action", "item.media"
    },
    "Cards/feature-cards-4up.json": {
        "section_title", "item.title", "item.body", "item.media"
    },
    "Cards/gallery-3up.json": {
        "section_title", "section_body", "item.title", "item.meta", "item.media"
    },
    "Cards/gallery-6up.json": {
        "section_title", "section_body", "item.title", "item.meta", "item.media"
    },
    "Cards/pricing-cards-3up.json": {"item.title", "item.price", "item.features", "item.action"},
    "Cards/team-member-grid-4up.json": {
        "section_title", "section_body", "item.title", "item.role", "item.body", "item.media"
    },
    "Cards/testimonial-cards-3up.json": {"section_title", "item.quote", "item.author"},
    "Content/bio-about.json": {"title", "eyebrow", "body", "media"},
    "Content/contact-section.json": {
        "section_title", "section_body", "contact_items", "action_title", "action_body", "action"
    },
    "Content/faq-accordion.json": {"section_title", "item.question", "item.answer"},
    "Content/logo-bar.json": {"section_title", "item.media"},
    "Content/ribbon-marquee.json": {"item.body"},
    "Content/rich-text.json": {"title", "body"},
    "Content/split-media-reverse.json": {"title", "subtitle", "body", "action", "media"},
    "Content/split-media.json": {"media", "title", "subtitle", "body", "action"},
    "Content/stats-band-3up.json": {"item.value", "item.label"},
    "Content/stats-grid-4up.json": {"section_title", "item.value", "item.label"},
    "Content/video-feature.json": {"eyebrow", "title", "body", "media", "action"},
    "CTAs/cta-banner.json": {"title", "subtitle", "body", "action", "background_media"},
    "CTAs/cta-split.json": {"title", "subtitle", "body", "media", "action"},
    "Heroes/centered-hero.json": {"title", "body", "action", "background_media"},
    "Heroes/photo-band.json": {"background_media"},
    "Heroes/split-hero.json": {"title", "body", "action", "media"},
    "Lists/icon-feature-list.json": {"item.title", "item.body", "item.media"},
    "Navigation/footer-3col.json": {
        "brand.title", "brand.body", "column.title", "column.links", "contact_title", "contact_items"
    },
    "Navigation/footer-4col.json": {
        "brand.title", "brand.body", "column.title", "column.links", "contact_title", "contact_items"
    },
    "Navigation/navbar-brand-links.json": {
        "brand", "item.navigation_item"
    },
    "Navigation/navbar-brand-links-cta.json": {
        "brand", "item.navigation_item", "action"
    },
}


def _capabilities() -> dict:
    return {
        "schema_version": "1.0",
        "roles": ["feature_cards"],
        "layout": {
            "kind": "grid",
            "columns": [3],
            "media_positions": ["top", "none"],
            "alignment": ["left", "center"],
        },
        "repeat_group": {
            "kind": "card",
            "minimum": 2,
            "default": 3,
            "maximum": 12,
            "expandable": True,
        },
        "fields": {"item.title": "required", "item.body": "optional"},
        "responsive": {
            "desktop_columns": 3,
            "tablet_columns": 2,
            "mobile_columns": 1,
            "stacking_order": "source",
        },
        "interactions": ["link"],
        "native_component_ratio": 1.0,
        "supported_modifiers": ["card-radius"],
    }


def _write_template(root: Path, relative_path: str, name: str, capabilities: dict | None = None) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "name": name,
        "category": "Cards",
        "description": "A test template",
        "capabilities": capabilities if capabilities is not None else _capabilities(),
        "template": {"type": "section", "components": []},
        "styles": [],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_all_tracked_templates_have_valid_unique_capabilities() -> None:
    catalog = load_template_catalog(TEMPLATES_DIR)

    assert len(catalog) == 31
    assert len({entry.name.casefold() for entry in catalog}) == len(catalog)
    assert all(entry.capabilities.fields for entry in catalog)
    assert all(entry.capabilities.schema_version == "1.1" for entry in catalog)
    assert all(
        set(entry.capabilities.physical_fields) == set(entry.capabilities.fields)
        for entry in catalog
    )
    assert all(entry.capabilities.responsive.mobile_columns >= 1 for entry in catalog)
    assert all(0 <= entry.capabilities.native_component_ratio <= 1 for entry in catalog)


def test_catalog_order_and_template_ids_are_deterministic() -> None:
    first = load_template_catalog(TEMPLATES_DIR)
    second = load_template_catalog(TEMPLATES_DIR)

    assert [entry.template_id for entry in first] == [entry.template_id for entry in second]
    assert [entry.relative_path.casefold() for entry in first] == sorted(
        entry.relative_path.casefold() for entry in first
    )
    assert all(not entry.template_id.endswith(".json") for entry in first)


def test_declared_fields_match_audited_semantic_slot_ownership() -> None:
    catalog = load_template_catalog(TEMPLATES_DIR)

    assert {entry.relative_path for entry in catalog} == set(EXPECTED_FIELDS_BY_TEMPLATE)
    for entry in catalog:
        assert set(entry.capabilities.fields) == EXPECTED_FIELDS_BY_TEMPLATE[entry.relative_path], (
            f"{entry.relative_path} capability fields drifted from its audited editable slots"
        )


def test_physical_contracts_own_every_primary_visitor_slot_exactly_once() -> None:
    for entry in load_template_catalog(TEMPLATES_DIR):
        data = load_template_data(entry)
        expected = {
            slot["key"]
            for slot in primary_slots(data["template"])
            if slot["key"] != "background_image"
            or "background_media" in entry.capabilities.fields
        }
        owners = [
            slot
            for contract in entry.capabilities.physical_fields.values()
            for slot in contract.slots
        ]

        assert set(owners) == expected, entry.relative_path
        assert len(owners) == len(set(owners)), entry.relative_path


def test_physical_contract_rejects_missing_duplicate_and_wrong_cardinality(
    tmp_path: Path,
) -> None:
    source = TEMPLATES_DIR / "Cards" / "pricing-cards-3up.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    physical = payload["capabilities"]["physical_fields"]
    physical["item.price"]["slots"][0] = physical["item.title"]["slots"][0]
    physical["item.features"]["slots"].pop()
    _write_template(
        tmp_path,
        "Cards/adversarial.json",
        "Adversarial",
        payload["capabilities"],
    )
    target = tmp_path / "Cards" / "adversarial.json"
    target_data = json.loads(target.read_text(encoding="utf-8"))
    target_data["template"] = payload["template"]
    target.write_text(json.dumps(target_data), encoding="utf-8")

    with pytest.raises(TemplateCatalogError) as caught:
        load_template_catalog(tmp_path)

    message = str(caught.value)
    assert "owned by both" in message
    assert "expected 9" in message
    assert "have no semantic owner" in message


def test_mixed_slot_templates_declare_fields_in_physical_component_order() -> None:
    catalog = {entry.relative_path: entry for entry in load_template_catalog(TEMPLATES_DIR)}

    expected = {
        "Cards/class-photo-cards-4up.json": (
            "section_title", "subtitle", "item.media", "item.title", "item.tag", "item.body", "item.action",
        ),
        "Cards/blog-post-cards-3up.json": (
            "section_title", "item.media", "item.tag", "item.title", "item.body", "item.action",
        ),
        "Cards/blog-post-cards-4up.json": (
            "section_title", "section_body", "item.media", "item.tag", "item.title",
            "item.body", "item.meta", "action",
        ),
        "Content/split-media.json": (
            "media", "title", "subtitle", "body", "action",
        ),
        "Content/split-media-reverse.json": (
            "title", "subtitle", "body", "action", "media",
        ),
        "CTAs/cta-banner.json": (
            "title", "subtitle", "body", "action", "background_media",
        ),
        "CTAs/cta-split.json": (
            "title", "subtitle", "body", "media", "action",
        ),
    }
    for relative_path, field_order in expected.items():
        assert tuple(catalog[relative_path].capabilities.fields) == field_order

    assert catalog["Content/video-feature.json"].capabilities.fields["action"] == "optional"


def test_generated_schema_and_documentation_cannot_silently_drift() -> None:
    catalog = load_template_catalog(TEMPLATES_DIR)

    assert SCHEMA_PATH.read_text(encoding="utf-8") == render_capability_schema()
    assert CATALOG_DOC_PATH.read_text(encoding="utf-8") == render_catalog_markdown(catalog)
    assert check_generated_artifacts(templates_dir=TEMPLATES_DIR) == ()


def test_generate_and_check_custom_artifact_paths(tmp_path: Path) -> None:
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, "Cards/example.json", "Example")
    schema_path = tmp_path / "schema.json"
    documentation_path = tmp_path / "catalog.md"

    written = write_generated_artifacts(
        templates_dir=templates_dir,
        schema_path=schema_path,
        documentation_path=documentation_path,
    )

    assert written == (schema_path, documentation_path)
    assert check_generated_artifacts(
        templates_dir=templates_dir,
        schema_path=schema_path,
        documentation_path=documentation_path,
    ) == ()
    documentation_path.write_text("stale\n", encoding="utf-8")
    assert check_generated_artifacts(
        templates_dir=templates_dir,
        schema_path=schema_path,
        documentation_path=documentation_path,
    ) == (f"generated artifact is stale: {documentation_path}",)


def test_project_template_catalog_fingerprint_changes_with_executable_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    templates_dir = tmp_path / "templates"
    template_path = _write_template(templates_dir, "Cards/example.json", "Example")
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))
    before = template_catalog_fingerprint()

    template = json.loads(template_path.read_text(encoding="utf-8"))
    template["template"]["components"].append(
        {"type": "text", "content": "Changed approved content"}
    )
    template_path.write_text(json.dumps(template), encoding="utf-8")

    assert template_catalog_fingerprint() != before


def test_duplicate_template_names_fail_case_insensitively(tmp_path: Path) -> None:
    _write_template(tmp_path, "Cards/first.json", "Feature Cards")
    _write_template(tmp_path, "Cards/second.json", "feature cards")

    with pytest.raises(TemplateCatalogError) as exc_info:
        load_template_catalog(tmp_path)

    message = str(exc_info.value)
    assert "duplicate template name" in message
    assert "Cards/first.json" in message
    assert "Cards/second.json" in message


def test_missing_and_invalid_capabilities_report_all_files(tmp_path: Path) -> None:
    missing = _write_template(tmp_path, "Cards/missing.json", "Missing")
    missing_data = json.loads(missing.read_text(encoding="utf-8"))
    del missing_data["capabilities"]
    missing.write_text(json.dumps(missing_data), encoding="utf-8")
    invalid = _capabilities()
    invalid["native_component_ratio"] = 1.5
    _write_template(tmp_path, "Cards/invalid.json", "Invalid", invalid)

    with pytest.raises(TemplateCatalogError) as exc_info:
        load_template_catalog(tmp_path)

    assert len(exc_info.value.issues) == 2
    assert "Cards/missing.json: capabilities is required" in exc_info.value.issues
    assert any("Cards/invalid.json" in issue and "native_component_ratio" in issue for issue in exc_info.value.issues)


def test_manifest_enforces_repeat_range_and_unique_capability_names() -> None:
    invalid_range = _capabilities()
    invalid_range["repeat_group"]["minimum"] = 4
    duplicate_roles = _capabilities()
    duplicate_roles["roles"] = ["feature_cards", "feature_cards"]

    with pytest.raises(ValidationError, match="default must be greater"):
        CapabilityManifest.model_validate(invalid_range)
    with pytest.raises(ValidationError, match="roles must not contain duplicates"):
        CapabilityManifest.model_validate(duplicate_roles)


def test_existing_template_resolution_remains_compatible() -> None:
    legacy_loaded = find_template("Centered Hero", templates_dir=TEMPLATES_DIR)
    entry = next(entry for entry in load_template_catalog(TEMPLATES_DIR) if entry.name == "Centered Hero")

    assert legacy_loaded["template"]["type"] == "section"
    assert legacy_loaded["styles"] == []
    assert load_template_data(entry) == legacy_loaded
