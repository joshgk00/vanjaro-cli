"""Release contract for agency pack 1.13.0: the additive Heroes/trust-badge-hero template (RT-21).

1.13.0 adds one template and changes nothing else. Every published byte below
1.13.0 stays frozen, every pre-existing template keeps its exact contract hashes,
and a project pinned to 1.12.0 may upgrade without any template change being
treated as reviewed, because none occurred.
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
)
from vanjaro_cli.utils.semver import compare_semver


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_PACKS = PROJECT_ROOT / "artifacts" / "agency-packs"
FAMILY = REPOSITORY_PACKS / "clicks-and-mortars"
BADGE_HERO = "Heroes/trust-badge-hero"
FEATURE_CARDS_3UP = "Cards/feature-cards-3up"


def _resolve(version: str):
    return AgencyPackRegistry(REPOSITORY_PACKS).resolve("clicks-and-mortars", version)


def _by_id(pack) -> dict:
    return {item.template_id: item for item in pack.templates.templates}


def test_the_repository_is_at_or_past_1_13_0_and_its_snapshot_is_current() -> None:
    assert compare_semver(_PACK_VERSION, "1.13.0") >= 0
    assert compare_semver(_TEMPLATE_VERSION, "1.13.0") >= 0
    assert (FAMILY / "packs" / "1.13.0.json").is_file()
    assert (FAMILY / "templates" / "1.13.0.json").is_file()
    assert check_repository_pack_artifacts() == ()


def test_everything_published_before_1_13_0_is_frozen() -> None:
    for relative, expected_digest in _HISTORICAL_DIGESTS.items():
        digest = hashlib.sha256((FAMILY / relative).read_bytes()).hexdigest()
        assert digest == expected_digest, f"historical payload drifted: {relative}"
    assert {"templates/1.12.0.json", "packs/1.12.0.json"} <= set(_HISTORICAL_DIGESTS)


def test_1_13_0_adds_exactly_one_template_and_changes_nothing_else() -> None:
    previous = _resolve("1.12.0")
    current = _resolve("1.13.0")
    previous_by_id = _by_id(previous)
    current_by_id = _by_id(current)

    assert set(current_by_id) - set(previous_by_id) == {BADGE_HERO}
    assert set(previous_by_id) <= set(current_by_id)
    assert [
        identifier for identifier in previous_by_id if previous_by_id[identifier] != current_by_id[identifier]
    ] == []
    assert previous.modifiers == current.modifiers
    assert previous.templates.capability_schema_version == current.templates.capability_schema_version


def test_upgrade_from_1_12_0_is_compatible_and_reports_only_the_addition() -> None:
    report = plan_agency_pack_upgrade(
        _resolve("1.12.0"),
        _resolve("1.13.0"),
        AgencyPackUsage(
            templates=(FEATURE_CARDS_3UP, "Heroes/split-hero"),
            source_fingerprint="a" * 64,
        ),
    )

    assert report.status == "compatible"
    assert report.issues == ()
    assert report.changes.templates_added == (BADGE_HERO,)
    assert report.changes.templates_removed == ()
    assert report.changes.templates_changed == ()
    assert report.changes.modifiers_changed == ()


def test_the_1_12_0_rule_approves_no_template_change() -> None:
    rule = next(item for item in _resolve("1.13.0").manifest.upgrade_rules if item.from_version == "1.12.0")

    assert rule.compatible_template_changes == ()
    assert rule.compatible_modifier_changes == ()
    assert rule.compatible_capability_schema_change is False


def test_upgrade_from_1_11_0_still_approves_only_the_feature_cards_change() -> None:
    report = plan_agency_pack_upgrade(
        _resolve("1.11.0"),
        _resolve("1.13.0"),
        AgencyPackUsage(
            templates=(FEATURE_CARDS_3UP,),
            source_fingerprint="b" * 64,
        ),
    )

    assert report.status == "compatible"
    assert report.changes.templates_changed == (FEATURE_CARDS_3UP,)
    assert report.changes.templates_added == (BADGE_HERO,)


def _copy_templates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    templates = tmp_path / "block-templates"
    shutil.copytree(PROJECT_ROOT / "artifacts" / "block-templates", templates)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates))
    return templates / "Heroes" / "trust-badge-hero.json"


def test_unreviewed_executable_drift_in_badge_hero_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _copy_templates(tmp_path, monkeypatch)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["template"]["components"][0]["components"][0]["components"][0]["components"][1][
        "content"
    ] = "Unreviewed eyebrow edit"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="executable template drifted for Heroes/trust-badge-hero"):
        render_repository_pack_artifacts(registry_root=tmp_path / "packs")


def test_badge_hero_capability_drift_at_the_published_version_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _copy_templates(tmp_path, monkeypatch)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["capabilities"]["fields"]["eyebrow"] = "required"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="release content drifted"):
        render_repository_pack_artifacts(registry_root=tmp_path / "packs")
