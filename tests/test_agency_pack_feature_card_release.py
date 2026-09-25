"""Release contract for agency pack 1.12.0: the reviewed feature-cards-3up fix.

Covers the narrow, reviewed structural change to Cards/feature-cards-3up
(section heading moved into its own grid/row/column with head-style-2) that
motivated publishing agency pack 1.12.0 from 1.11.0. Every published byte
below 1.12.0 must stay frozen; only the feature-cards-3up template hash may
move, and only a project pinned to 1.11.0 may treat that change as reviewed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from vanjaro_cli.agency_library import (
    AgencyPackRegistry,
    AgencyPackUsage,
    plan_agency_pack_upgrade,
)
from vanjaro_cli.agency_library.generation import (
    _HISTORICAL_DIGESTS,
    _PACK_VERSION,
    _TEMPLATE_VERSION,
    check_repository_pack_artifacts,
    render_repository_pack_artifacts,
    write_repository_pack_artifacts,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_PACKS = PROJECT_ROOT / "artifacts" / "agency-packs"
FAMILY = REPOSITORY_PACKS / "clicks-and-mortars"
FEATURE_CARDS_3UP = "Cards/feature-cards-3up"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_this_release_is_1_12_0_and_repository_snapshot_is_current() -> None:
    assert _PACK_VERSION == "1.12.0"
    assert _TEMPLATE_VERSION == "1.12.0"
    assert check_repository_pack_artifacts() == ()


def test_every_prior_published_byte_and_digest_is_frozen() -> None:
    # Every payload pinned in the historical digest map (1.0.0 through the
    # now-frozen 1.11.0) must still be byte-identical on disk.
    for relative, expected_digest in _HISTORICAL_DIGESTS.items():
        path = FAMILY / relative
        assert path.is_file(), f"missing historical payload: {relative}"
        assert _sha256(path) == expected_digest, f"historical payload drifted: {relative}"
    assert "templates/1.11.0.json" in _HISTORICAL_DIGESTS
    assert "packs/1.11.0.json" in _HISTORICAL_DIGESTS


def test_check_and_write_are_deterministic_and_idempotent(tmp_path: Path) -> None:
    registry = tmp_path / "agency-packs"
    shutil.copytree(REPOSITORY_PACKS, registry)

    first_drift = check_repository_pack_artifacts(registry_root=registry)
    second_drift = check_repository_pack_artifacts(registry_root=registry)
    assert first_drift == () == second_drift

    before_snapshot = {
        path: path.read_bytes() for path in (registry / "clicks-and-mortars").rglob("*.json")
    }
    written_first = write_repository_pack_artifacts(registry_root=registry)
    written_second = write_repository_pack_artifacts(registry_root=registry)
    assert written_first == written_second
    after_snapshot = {
        path: path.read_bytes() for path in (registry / "clicks-and-mortars").rglob("*.json")
    }
    assert before_snapshot == after_snapshot


def test_exactly_one_template_hash_changed_between_1_11_0_and_1_12_0() -> None:
    registry = AgencyPackRegistry(REPOSITORY_PACKS)
    previous = registry.resolve("clicks-and-mortars", "1.11.0")
    current = registry.resolve("clicks-and-mortars", "1.12.0")

    previous_by_id = {item.template_id: item for item in previous.templates.templates}
    current_by_id = {item.template_id: item for item in current.templates.templates}

    assert set(previous_by_id) == set(current_by_id)

    changed = [
        identifier
        for identifier in previous_by_id
        if previous_by_id[identifier] != current_by_id[identifier]
    ]
    assert changed == [FEATURE_CARDS_3UP]

    # The reviewed change is structural only: the capability contract for
    # feature-cards-3up must be untouched, and no modifier payload moved.
    assert (
        previous_by_id[FEATURE_CARDS_3UP].capability_sha256
        == current_by_id[FEATURE_CARDS_3UP].capability_sha256
    )
    assert (
        previous_by_id[FEATURE_CARDS_3UP].template_sha256
        != current_by_id[FEATURE_CARDS_3UP].template_sha256
    )
    assert previous.modifiers == current.modifiers
    assert previous.manifest.modifiers == current.manifest.modifiers


def test_upgrade_report_from_1_11_0_is_compatible_only_via_reviewed_feature_cards_change() -> None:
    registry = AgencyPackRegistry(REPOSITORY_PACKS)
    current = registry.resolve("clicks-and-mortars", "1.11.0")
    target = registry.resolve("clicks-and-mortars", "1.12.0")

    report = plan_agency_pack_upgrade(
        current,
        target,
        AgencyPackUsage(
            templates=(FEATURE_CARDS_3UP, "Content/rich-text"),
            source_fingerprint="a" * 64,
        ),
    )

    assert report.status == "compatible"
    assert report.changes.templates_changed == (FEATURE_CARDS_3UP,)
    assert report.changes.templates_added == ()
    assert report.changes.templates_removed == ()
    assert report.changes.modifiers_changed == ()
    assert report.changes.capability_schema_changed is False
    assert {issue.code for issue in report.issues} == {"used_template_changed_reviewed"}
    (issue,) = [item for item in report.issues if item.code == "used_template_changed_reviewed"]
    assert issue.subject == FEATURE_CARDS_3UP

    rule = next(
        item for item in target.manifest.upgrade_rules if item.from_version == "1.11.0"
    )
    assert rule.compatible_template_changes == (FEATURE_CARDS_3UP,)
    assert rule.compatible_modifier_changes == ()
    assert rule.compatible_capability_schema_change is False


def test_upgrade_from_1_11_0_still_blocks_unreviewed_template_drift() -> None:
    # A hypothetical project pinned to 1.11.0 but relying on a template that
    # is *not* the reviewed feature-cards-3up change must not be silently
    # waved through by the narrow rule.
    registry = AgencyPackRegistry(REPOSITORY_PACKS)
    current = registry.resolve("clicks-and-mortars", "1.11.0")
    target = registry.resolve("clicks-and-mortars", "1.12.0")
    rule = next(
        item for item in target.manifest.upgrade_rules if item.from_version == "1.11.0"
    )
    assert "Content/rich-text" not in rule.compatible_template_changes
    assert len(rule.compatible_template_changes) == 1


def test_same_version_republish_with_drift_is_rejected(tmp_path: Path) -> None:
    registry = tmp_path / "agency-packs"
    shutil.copytree(REPOSITORY_PACKS, registry)
    current_pack = registry / "clicks-and-mortars" / "packs" / f"{_PACK_VERSION}.json"
    tampered = current_pack.read_bytes() + b" "
    current_pack.write_bytes(tampered)

    with pytest.raises(ValueError, match="refusing to rewrite published"):
        write_repository_pack_artifacts(registry_root=registry)
    assert current_pack.read_bytes() == tampered
    assert any(
        "immutable agency-pack artifact digest drifted" not in issue
        and "generated agency-pack artifact is stale" in issue
        for issue in check_repository_pack_artifacts(registry_root=registry)
    )


def test_unreviewed_executable_drift_on_another_template_is_still_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    templates = tmp_path / "block-templates"
    shutil.copytree(PROJECT_ROOT / "artifacts" / "block-templates", templates)
    target = templates / "Heroes" / "centered-hero.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["template"]["components"][0]["components"][0]["components"][0][
        "components"
    ][0]["content"] = "Unreviewed drift unrelated to the feature-cards-3up fix"
    target.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates))

    with pytest.raises(ValueError, match="executable template drifted"):
        render_repository_pack_artifacts(registry_root=tmp_path / "packs")


def test_feature_cards_3up_capability_drift_at_current_version_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    templates = tmp_path / "block-templates"
    shutil.copytree(PROJECT_ROOT / "artifacts" / "block-templates", templates)
    target = templates / "Cards" / "feature-cards-3up.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["capabilities"]["fields"]["item.body"] = "required"
    target.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates))

    with pytest.raises(ValueError, match="release content drifted"):
        render_repository_pack_artifacts(registry_root=tmp_path / "packs")
