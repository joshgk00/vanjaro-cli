"""W1 contracts for the versioned, typed executable agency-pack style payload.

Covers what ``artifacts/test_agency_style_pack_independent.py`` (the root's
immutable baseline) does not: legacy/opt-in schema parity at the model layer,
exact generated declaration semantics, payload-level safety/domain rejection,
class-name collision, deterministic ordering-independent hashing, context
immutability, and the explicit unsupported-style-upgrade guard.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.test_agency_pack_governance import _base_registry, _contract, _modifier, _write_json
from vanjaro_cli.agency_library import (
    AgencyPackCompatibilityError,
    AgencyPackManifest,
    AgencyPackRegistry,
    AgencyPackRegistryError,
    AgencyPackUsage,
    AgencyStylePayload,
    AgencyStyleUtility,
    PackPayloadReference,
    plan_agency_pack_upgrade,
    resolve_style_context,
)


def _style_utility(**overrides: object) -> dict:
    payload = {"property": "order", "source_value": "2", "class_name": "cm-order-2"}
    payload.update(overrides)
    return payload


def _publish_style_pack(
    root: Path,
    *,
    pack_version: str = "1.0.0",
    style_version: str = "1.0.0",
    utilities: list[dict] | None = None,
) -> tuple[Path, Path]:
    """Publish a 1.1 pack with a styles payload; returns (manifest_path, style_path)."""

    family = root / "clicks-and-mortars"
    manifest_path = family / "packs" / f"{pack_version}.json"
    if not manifest_path.exists():
        _write_json(
            family / "templates" / f"{pack_version}.json",
            {
                "schema_version": "1.0",
                "version": pack_version,
                "capability_schema_version": "1.0",
                "templates": [_contract("Cards/feature", "v1")],
            },
        )
        _write_json(
            family / "modifiers" / f"{pack_version}.json",
            {
                "schema_version": "1.0",
                "version": pack_version,
                "modifiers": [_modifier("card-radius")],
            },
        )
    style_path = family / "styles" / f"{style_version}.json"
    style_payload = {
        "schema_version": "1.0",
        "version": style_version,
        "utilities": utilities if utilities is not None else [_style_utility()],
    }
    style_digest = _write_json(style_path, style_payload)
    template_hash = hashlib.sha256(
        (family / "templates" / f"{pack_version}.json").read_bytes()
    ).hexdigest()
    modifier_hash = hashlib.sha256(
        (family / "modifiers" / f"{pack_version}.json").read_bytes()
    ).hexdigest()
    _write_json(
        manifest_path,
        {
            "schema_version": "1.1",
            "name": "clicks-and-mortars",
            "version": pack_version,
            "templates": {
                "version": pack_version,
                "path": f"templates/{pack_version}.json",
                "sha256": template_hash,
            },
            "modifiers": {
                "version": pack_version,
                "path": f"modifiers/{pack_version}.json",
                "sha256": modifier_hash,
            },
            "styles": {
                "version": style_version,
                "path": f"styles/{style_version}.json",
                "sha256": style_digest,
            },
            "upgrade_rules": [],
        },
    )
    return manifest_path, style_path


# --- schema parity: legacy 1.0 vs opt-in 1.1 --------------------------------


def test_schema_1_0_rejects_a_nonempty_styles_reference() -> None:
    reference = PackPayloadReference(version="1.0.0", path="templates/1.0.0.json", sha256="a" * 64)
    with pytest.raises(ValidationError, match="1.0"):
        AgencyPackManifest(
            schema_version="1.0",
            name="clicks-and-mortars",
            version="1.0.0",
            templates=reference,
            modifiers=reference,
            styles=reference,
        )


def test_schema_1_1_accepts_and_serializes_a_styles_reference() -> None:
    reference = PackPayloadReference(version="1.0.0", path="templates/1.0.0.json", sha256="a" * 64)
    style_reference = PackPayloadReference(version="1.0.0", path="styles/1.0.0.json", sha256="b" * 64)
    manifest = AgencyPackManifest(
        schema_version="1.1",
        name="clicks-and-mortars",
        version="1.0.0",
        templates=reference,
        modifiers=reference,
        styles=style_reference,
    )
    dumped = manifest.model_dump(mode="json")
    assert dumped["styles"] == style_reference.model_dump(mode="json")
    assert json.loads(manifest.model_dump_json())["styles"] == style_reference.model_dump(mode="json")


def test_schema_1_0_without_styles_omits_the_field_from_every_serialization(tmp_path: Path) -> None:
    root, registry = _base_registry(tmp_path)
    resolved = registry.resolve("clicks-and-mortars", "1.0.0")
    assert "styles" not in resolved.manifest.model_dump(mode="json")
    assert "styles" not in json.loads(resolved.manifest.model_dump_json())
    assert resolved.styles is None


# --- opt-in style resolution: exact generated semantics ---------------------


def test_style_resolution_generates_exact_declarations_and_stylesheet(tmp_path: Path) -> None:
    utilities = [
        {"property": "order", "source_value": "2", "class_name": "cm-order-2"},
        {
            "property": "text_align",
            "source_value": "center",
            "class_name": "cm-text-center",
            "important": True,
        },
    ]
    root = tmp_path / "packs"
    _publish_style_pack(root, utilities=utilities)
    resolved = AgencyPackRegistry(root).resolve("clicks-and-mortars", "1.0.0")

    context = resolve_style_context(resolved)

    assert context.agency_utilities == {
        "order:2": "cm-order-2",
        "text_align:center": "cm-text-center",
    }
    assert ".cm-order-2 { order: 2; }" in context.stylesheet
    assert ".cm-text-center { text-align: center !important; }" in context.stylesheet
    assert context.stylesheet_sha256 == hashlib.sha256(context.stylesheet.encode()).hexdigest()
    assert context.target_verified is False
    assert context.pack_name == resolved.manifest.name
    assert context.pack_version == resolved.manifest.version
    assert context.pack_digest == resolved.digest
    assert context.style_version == resolved.manifest.styles.version
    assert context.style_digest == resolved.manifest.styles.sha256


def test_no_style_legacy_pack_resolves_to_an_empty_context(tmp_path: Path) -> None:
    root, registry = _base_registry(tmp_path)
    resolved = registry.resolve("clicks-and-mortars", "1.0.0")

    context = resolve_style_context(resolved)

    assert context.agency_utilities == {}
    assert context.stylesheet == ""
    assert context.stylesheet_sha256 == hashlib.sha256(b"").hexdigest()
    assert context.target_verified is False
    assert context.style_version is None
    assert context.style_digest is None


def test_payload_may_explicitly_declare_no_utilities(tmp_path: Path) -> None:
    root = tmp_path / "packs"
    _publish_style_pack(root, utilities=[])
    resolved = AgencyPackRegistry(root).resolve("clicks-and-mortars", "1.0.0")

    context = resolve_style_context(resolved)

    assert context.agency_utilities == {}
    assert context.stylesheet == ""


# --- digest tamper / version mismatch / traversal ---------------------------


def test_style_payload_digest_tamper_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "packs"
    _, style_path = _publish_style_pack(root)
    style_path.write_bytes(style_path.read_bytes() + b" ")

    with pytest.raises(AgencyPackRegistryError) as caught:
        AgencyPackRegistry(root).resolve("clicks-and-mortars", "1.0.0")
    assert caught.value.code == "agency_pack_payload_digest_mismatch"


def test_style_payload_version_mismatch_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "packs"
    manifest_path, style_path = _publish_style_pack(root)
    payload = json.loads(style_path.read_text(encoding="utf-8"))
    payload["version"] = "9.9.9"
    digest = _write_json(style_path, payload)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["styles"]["sha256"] = digest
    _write_json(manifest_path, manifest)

    with pytest.raises(AgencyPackRegistryError) as caught:
        AgencyPackRegistry(root).resolve("clicks-and-mortars", "1.0.0")
    assert caught.value.code == "agency_pack_payload_version_mismatch"


def test_style_reference_path_rejects_traversal_and_absolute_locations() -> None:
    for invalid in ("../styles.json", "/styles.json", "C:\\styles.json", "styles.json?x=1"):
        with pytest.raises(ValidationError):
            PackPayloadReference(version="1.0.0", path=invalid, sha256="a" * 64)


@pytest.mark.skipif(os.name == "nt", reason="symlink escape uses a POSIX symlink")
def test_style_payload_symlink_escaping_the_pack_family_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "packs"
    manifest_path, style_path = _publish_style_pack(root)
    outside = tmp_path / "outside-styles.json"
    outside.write_text(style_path.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        style_path.unlink()
        style_path.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not permitted in this environment")

    with pytest.raises(AgencyPackRegistryError) as caught:
        AgencyPackRegistry(root).resolve("clicks-and-mortars", "1.0.0")
    # A symlink still resolves to real bytes inside the family in this
    # layout, so the registry's normal digest/identity checks -- not a
    # separate symlink-specific code path -- are what catch a mismatch. What
    # matters here is that escape via a symlink is never silently trusted.
    assert caught.value.code in {
        "agency_pack_payload_missing",
        "agency_pack_payload_digest_mismatch",
        "agency_pack_payload_outside_registry",
    }


# --- source property/value validation ---------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_value": ""},
        {"source_value": "   "},
        {"source_value": "2; background:url(evil)"},
        {"source_value": "</style><script>alert(1)</script>", "property": "font_family"},
        {"source_value": "javascript:alert(1)", "property": "background_image"},
        {"source_value": "url(javascript:alert(1))", "property": "background_image"},
        {"source_value": "@import url(evil.css)", "property": "font_family"},
        {"source_value": "red/*x*/", "property": "text_color"},
        {"source_value": "1.5"},
        {"class_name": "Cm-Order"},
        {"class_name": "1cm-order"},
        {"class_name": ".cm-order, .evil{color:red}"},
    ],
)
def test_hostile_or_malformed_utilities_are_rejected(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        AgencyStyleUtility(**_style_utility(**overrides))


def test_unknown_property_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AgencyStyleUtility(**_style_utility(property="not-a-real-property"))


def test_non_executable_keyword_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AgencyStyleUtility(**_style_utility(property="display", source_value="banana"))


def test_valid_keyword_value_from_the_canonical_utility_table_is_accepted() -> None:
    utility = AgencyStyleUtility(property="display", source_value="Flex", class_name="cm-d-flex")
    assert utility.source_value == "Flex"


# --- class-name / definition collision --------------------------------------


def test_duplicate_class_name_with_conflicting_definitions_is_rejected() -> None:
    with pytest.raises(ValidationError, match="class name"):
        AgencyStylePayload(
            version="1.0.0",
            utilities=[
                _style_utility(class_name="cm-shared"),
                _style_utility(source_value="3", class_name="cm-shared"),
            ],
        )


def test_duplicate_normalized_property_value_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="property/value"):
        AgencyStylePayload(
            version="1.0.0",
            utilities=[
                _style_utility(class_name="cm-order-2-a"),
                _style_utility(class_name="cm-order-2-b"),
            ],
        )


# --- deterministic hashing, independent of input ordering -------------------


def test_stylesheet_hash_is_independent_of_utility_declaration_order(tmp_path: Path) -> None:
    forward = [
        {"property": "order", "source_value": "2", "class_name": "cm-order-2"},
        {"property": "display", "source_value": "flex", "class_name": "cm-d-flex"},
    ]
    backward = list(reversed(forward))

    root_a = tmp_path / "packs-a"
    _publish_style_pack(root_a, utilities=forward)
    root_b = tmp_path / "packs-b"
    _publish_style_pack(root_b, utilities=backward)

    context_a = resolve_style_context(AgencyPackRegistry(root_a).resolve("clicks-and-mortars", "1.0.0"))
    context_b = resolve_style_context(AgencyPackRegistry(root_b).resolve("clicks-and-mortars", "1.0.0"))

    assert context_a.stylesheet == context_b.stylesheet
    assert context_a.stylesheet_sha256 == context_b.stylesheet_sha256
    assert context_a.agency_utilities == context_b.agency_utilities


# --- immutable context, no client leakage -----------------------------------


def test_context_is_frozen_and_utilities_mapping_cannot_leak_back_into_state(tmp_path: Path) -> None:
    root = tmp_path / "packs"
    _publish_style_pack(root)
    resolved = AgencyPackRegistry(root).resolve("clicks-and-mortars", "1.0.0")

    context = resolve_style_context(resolved)
    mapping = context.agency_utilities
    mapping["order:2"] = "tampered"
    mapping["order:99"] = "injected"

    assert context.agency_utilities == {"order:2": "cm-order-2"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.stylesheet = "tampered"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.agency_utility_items = ()  # type: ignore[misc]

    assert resolve_style_context(resolved) == context


def test_context_never_carries_class_names_outside_the_generated_stylesheet(tmp_path: Path) -> None:
    root = tmp_path / "packs"
    _publish_style_pack(
        root,
        utilities=[{"property": "order", "source_value": "2", "class_name": "cm-order-2"}],
    )
    resolved = AgencyPackRegistry(root).resolve("clicks-and-mortars", "1.0.0")

    context = resolve_style_context(resolved)

    assert set(context.agency_utilities.values()) == {"cm-order-2"}
    assert context.stylesheet.count(".cm-order-2") == 1


# --- explicit unsupported style-upgrade guard --------------------------------


def test_upgrade_planner_blocks_when_the_current_pack_has_executable_styles(tmp_path: Path) -> None:
    root = tmp_path / "packs"
    _publish_style_pack(root, pack_version="1.0.0")
    _publish_style_pack(root, pack_version="1.1.0", style_version="1.1.0")
    registry = AgencyPackRegistry(root)

    with pytest.raises(AgencyPackCompatibilityError) as caught:
        plan_agency_pack_upgrade(
            registry.resolve("clicks-and-mortars", "1.0.0"),
            registry.resolve("clicks-and-mortars", "1.1.0"),
            AgencyPackUsage(source_fingerprint="a" * 64),
        )
    assert caught.value.code == "agency_pack_style_upgrade_unsupported"


def test_upgrade_planner_blocks_when_only_the_target_pack_has_executable_styles(tmp_path: Path) -> None:
    root, registry = _base_registry(tmp_path)
    _publish_style_pack(root, pack_version="1.1.0", style_version="1.1.0")

    with pytest.raises(AgencyPackCompatibilityError) as caught:
        plan_agency_pack_upgrade(
            registry.resolve("clicks-and-mortars", "1.0.0"),
            registry.resolve("clicks-and-mortars", "1.1.0"),
            AgencyPackUsage(source_fingerprint="a" * 64),
        )
    assert caught.value.code == "agency_pack_style_upgrade_unsupported"


def test_style_upgrade_guard_fires_before_any_upgrade_rule_or_usage_check(tmp_path: Path) -> None:
    """The style guard must fail closed even with no upgrade rule/usage at all."""

    root = tmp_path / "packs"
    _publish_style_pack(root, pack_version="1.0.0")
    _publish_style_pack(root, pack_version="1.1.0", style_version="1.1.0")
    registry = AgencyPackRegistry(root)

    with pytest.raises(AgencyPackCompatibilityError) as caught:
        plan_agency_pack_upgrade(
            registry.resolve("clicks-and-mortars", "1.0.0"),
            registry.resolve("clicks-and-mortars", "1.1.0"),
            AgencyPackUsage(),
        )
    assert caught.value.code == "agency_pack_style_upgrade_unsupported"
