"""M4 contracts for immutable agency packs and deterministic upgrade reports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest
from pydantic import ValidationError

from vanjaro_cli.agency_library import (
    AgencyPackCompatibilityError,
    AgencyPackRegistry,
    AgencyPackRegistryError,
    AgencyPackUsage,
    PackPayloadReference,
    plan_agency_pack_upgrade,
    read_project_pack_usage,
)
from vanjaro_cli.cli import cli
from vanjaro_cli.design.models import SourceKind
from vanjaro_cli.project import (
    ProjectSource,
    create_manifest,
    initialize_workspace,
)
from vanjaro_cli.utils.semver import compare_semver, validate_semver
from vanjaro_cli.agency_library.generation import (
    check_repository_pack_artifacts,
    render_repository_pack_artifacts,
    write_repository_pack_artifacts,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_PACKS = PROJECT_ROOT / "artifacts" / "agency-packs"


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_bytes(value)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _contract(identifier: str, seed: str) -> dict[str, str]:
    return {
        "template_id": identifier,
        "template_sha256": hashlib.sha256(f"template:{seed}".encode()).hexdigest(),
        "capability_sha256": hashlib.sha256(f"capability:{seed}".encode()).hexdigest(),
    }


def _modifier(identifier: str, seed: str | None = None) -> dict[str, str]:
    return {
        "modifier_id": identifier,
        "contract_sha256": hashlib.sha256(
            f"modifier:{seed or identifier}".encode()
        ).hexdigest(),
    }


def _publish_pack(
    registry: Path,
    *,
    version: str,
    templates: list[dict[str, str]],
    modifiers: list[dict[str, str]],
    template_version: str | None = None,
    modifier_version: str | None = None,
    capability_schema_version: str = "1.0",
    rules: list[dict] | None = None,
) -> None:
    family = registry / "clicks-and-mortars"
    template_version = template_version or version
    modifier_version = modifier_version or version
    template_path = family / "templates" / f"{template_version}.json"
    modifier_path = family / "modifiers" / f"{modifier_version}.json"
    template_value = {
        "schema_version": "1.0",
        "version": template_version,
        "capability_schema_version": capability_schema_version,
        "templates": templates,
    }
    modifier_value = {
        "schema_version": "1.0",
        "version": modifier_version,
        "modifiers": modifiers,
    }
    template_hash = (
        hashlib.sha256(template_path.read_bytes()).hexdigest()
        if template_path.exists()
        else _write_json(template_path, template_value)
    )
    modifier_hash = (
        hashlib.sha256(modifier_path.read_bytes()).hexdigest()
        if modifier_path.exists()
        else _write_json(modifier_path, modifier_value)
    )
    _write_json(
        family / "packs" / f"{version}.json",
        {
            "schema_version": "1.0",
            "name": "clicks-and-mortars",
            "version": version,
            "templates": {
                "version": template_version,
                "path": f"templates/{template_version}.json",
                "sha256": template_hash,
            },
            "modifiers": {
                "version": modifier_version,
                "path": f"modifiers/{modifier_version}.json",
                "sha256": modifier_hash,
            },
            "upgrade_rules": rules or [],
        },
    )


def _base_registry(tmp_path: Path) -> tuple[Path, AgencyPackRegistry]:
    root = tmp_path / "packs"
    _publish_pack(
        root,
        version="1.0.0",
        templates=[_contract("Cards/feature", "v1")],
        modifiers=[_modifier("card-radius")],
    )
    return root, AgencyPackRegistry(root)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _project(root: Path, project_id: str) -> Path:
    manifest = create_manifest(
        name=project_id,
        project_id=project_id,
        target_profile=project_id,
        sources=[
            ProjectSource(
                id="source-1",
                kind=SourceKind.LIVE_HTML,
                reference="sources/source.html",
            )
        ],
        agency_pack_name="clicks-and-mortars",
        agency_pack_version="1.0.0",
    )
    initialize_workspace(root, manifest)
    (root / "sources" / "source.html").write_text("<main></main>", encoding="utf-8")
    _write_json(
        root / "plans" / "composition-plan.json",
        {
            "entries": [
                {
                    "template_id": "Cards/feature",
                    "modifiers": ["card-radius"],
                }
            ]
        },
    )
    return root


def test_semver_contract_rejects_ambiguous_versions_and_compares_prereleases() -> None:
    assert validate_semver("1.2.3-beta.2+build.7") == "1.2.3-beta.2+build.7"
    assert compare_semver("1.2.3-beta.2", "1.2.3") == -1
    assert compare_semver("1.10.0", "1.2.9") == 1
    for invalid in ("1", "1.0", "01.0.0", "v1.0.0", "1.0.0-"):
        with pytest.raises(ValueError):
            validate_semver(invalid)


def test_repository_pack_snapshot_is_current_and_resolves_all_templates() -> None:
    assert check_repository_pack_artifacts() == ()
    registry = AgencyPackRegistry(REPOSITORY_PACKS)
    initial = registry.resolve("clicks-and-mortars", "1.0.0")
    patch = registry.resolve("clicks-and-mortars", "1.0.1")
    physical = registry.resolve("clicks-and-mortars", "1.1.0")

    assert len(initial.templates.templates) == 29
    assert initial.templates == patch.templates
    assert initial.modifiers == patch.modifiers
    assert patch.manifest.upgrade_rules[0].from_version == "1.0.0"
    assert len(physical.templates.templates) == 29
    assert physical.templates.version == "1.1.0"
    assert physical.templates.capability_schema_version == "1.1"
    assert physical.modifiers.version == "1.0.0"
    assert {rule.from_version for rule in physical.manifest.upgrade_rules} == {
        "1.0.0", "1.0.1",
    }


def test_pack_generator_never_rewrites_digest_locked_history(tmp_path: Path) -> None:
    registry = tmp_path / "agency-packs"
    shutil.copytree(REPOSITORY_PACKS, registry)
    family = registry / "clicks-and-mortars"
    historical = {
        path.relative_to(family).as_posix(): path.read_bytes()
        for version_dir in ("templates", "modifiers", "packs")
        for path in (family / version_dir).glob("1.0*.json")
    }

    rendered = render_repository_pack_artifacts(registry_root=registry)
    written = write_repository_pack_artifacts(registry_root=registry)

    assert set(written) == set(rendered)
    assert all(path.name not in {"1.0.0.json", "1.0.1.json"} for path in written)
    assert historical == {
        relative: (family / relative).read_bytes()
        for relative in historical
    }
    victim = family / "packs" / "1.0.0.json"
    victim.write_bytes(victim.read_bytes() + b" ")
    assert any(
        "immutable agency-pack artifact digest drifted" in issue
        for issue in check_repository_pack_artifacts(registry_root=registry)
    )

    current = family / "packs" / "1.3.0.json"
    tampered = current.read_bytes() + b" "
    current.write_bytes(tampered)
    with pytest.raises(ValueError, match="refusing to rewrite published"):
        write_repository_pack_artifacts(registry_root=registry)
    assert current.read_bytes() == tampered


def test_pack_generator_rejects_unaudited_executable_template_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    templates = tmp_path / "block-templates"
    shutil.copytree(PROJECT_ROOT / "artifacts" / "block-templates", templates)
    target = templates / "Heroes" / "centered-hero.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["template"]["components"][0]["components"][0]["components"][0][
        "components"
    ][0]["content"] = "Unaudited executable change"
    target.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates))

    with pytest.raises(ValueError, match="executable template drifted"):
        render_repository_pack_artifacts(registry_root=tmp_path / "packs")


def test_pack_generator_rejects_same_version_capability_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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


@pytest.mark.parametrize("from_version", ["1.0.0", "1.0.1"])
def test_repository_physical_contract_upgrade_is_explicitly_reviewed(
    from_version: str,
) -> None:
    registry = AgencyPackRegistry(REPOSITORY_PACKS)
    current = registry.resolve("clicks-and-mortars", from_version)
    target = registry.resolve("clicks-and-mortars", "1.1.0")
    used = current.templates.templates[0].template_id

    report = plan_agency_pack_upgrade(
        current,
        target,
        AgencyPackUsage(
            templates=(used,),
            source_fingerprint="a" * 64,
        ),
    )

    assert report.status == "compatible"
    assert {issue.code for issue in report.issues} == {
        "capability_schema_change_reviewed",
        "used_template_changed_reviewed",
    }


def test_pack_payload_paths_reject_escape_and_absolute_locations() -> None:
    for invalid in (
        "../templates.json",
        "/templates.json",
        "C:\\templates.json",
        "templates.json?token=secret",
    ):
        with pytest.raises(ValidationError):
            PackPayloadReference(version="1.0.0", path=invalid, sha256="a" * 64)


def test_registry_verifies_identity_versions_and_immutable_payload_digest(
    tmp_path: Path,
) -> None:
    root, registry = _base_registry(tmp_path)

    resolved = registry.resolve("clicks-and-mortars", "1.0.0")

    assert resolved.templates.templates[0].template_id == "Cards/feature"
    assert len(resolved.digest) == 64
    payload = root / "clicks-and-mortars" / "templates" / "1.0.0.json"
    payload.write_bytes(payload.read_bytes() + b" ")
    with pytest.raises(AgencyPackRegistryError) as caught:
        registry.resolve("clicks-and-mortars", "1.0.0")
    assert caught.value.code == "agency_pack_payload_digest_mismatch"


def test_additive_upgrade_is_compatible_with_explicit_rule(tmp_path: Path) -> None:
    root, registry = _base_registry(tmp_path)
    _publish_pack(
        root,
        version="1.1.0",
        templates=[
            _contract("Cards/feature", "v1"),
            _contract("Cards/gallery", "v1"),
        ],
        modifiers=[_modifier("card-radius"), _modifier("band-color")],
        rules=[{"from_version": "1.0.0"}],
    )

    report = plan_agency_pack_upgrade(
        registry.resolve("clicks-and-mortars", "1.0.0"),
        registry.resolve("clicks-and-mortars", "1.1.0"),
        AgencyPackUsage(
            templates=("Cards/feature",),
            modifiers=("card-radius",),
            source_fingerprint="a" * 64,
        ),
    )

    assert report.status == "compatible"
    assert report.changes.templates_added == ("Cards/gallery",)
    assert report.changes.modifiers_added == ("band-color",)
    assert report.issues == ()
    assert report == plan_agency_pack_upgrade(
        registry.resolve("clicks-and-mortars", "1.0.0"),
        registry.resolve("clicks-and-mortars", "1.1.0"),
        report.usage,
    )


@pytest.mark.parametrize(
    ("target_templates", "target_modifiers", "rule", "expected_status", "expected_code"),
    [
        (
            [_contract("Cards/feature", "changed")],
            [_modifier("card-radius")],
            {"from_version": "1.0.0"},
            "blocked",
            "used_template_changed_unreviewed",
        ),
        (
            [_contract("Cards/feature", "changed")],
            [_modifier("card-radius")],
            {
                "from_version": "1.0.0",
                "compatible_template_changes": ["Cards/feature"],
            },
            "compatible",
            "used_template_changed_reviewed",
        ),
        (
            [_contract("Cards/replacement", "v1")],
            [_modifier("card-radius")],
            {
                "from_version": "1.0.0",
                "template_replacements": {
                    "Cards/feature": "Cards/replacement"
                },
            },
            "remediation_required",
            "used_template_replacement_required",
        ),
        (
            [_contract("Cards/feature", "v1")],
            [],
            {"from_version": "1.0.0"},
            "blocked",
            "used_modifier_removed",
        ),
    ],
)
def test_used_contract_changes_have_stable_compatibility_outcomes(
    tmp_path: Path,
    target_templates: list[dict[str, str]],
    target_modifiers: list[dict[str, str]],
    rule: dict,
    expected_status: str,
    expected_code: str,
) -> None:
    root, registry = _base_registry(tmp_path)
    _publish_pack(
        root,
        version="2.0.0",
        templates=target_templates,
        modifiers=target_modifiers,
        rules=[rule],
    )

    report = plan_agency_pack_upgrade(
        registry.resolve("clicks-and-mortars", "1.0.0"),
        registry.resolve("clicks-and-mortars", "2.0.0"),
        AgencyPackUsage(
            templates=("Cards/feature",),
            modifiers=("card-radius",),
            source_fingerprint="a" * 64,
        ),
    )

    assert report.status == expected_status
    assert expected_code in {issue.code for issue in report.issues}


def test_missing_rule_and_capability_schema_change_are_blockers(tmp_path: Path) -> None:
    root, registry = _base_registry(tmp_path)
    _publish_pack(
        root,
        version="2.0.0",
        templates=[_contract("Cards/feature", "v1")],
        modifiers=[_modifier("card-radius")],
        capability_schema_version="2.0",
    )

    report = plan_agency_pack_upgrade(
        registry.resolve("clicks-and-mortars", "1.0.0"),
        registry.resolve("clicks-and-mortars", "2.0.0"),
        AgencyPackUsage(source_fingerprint="a" * 64),
    )

    assert report.status == "blocked"
    assert {item.code for item in report.issues} == {
        "capability_schema_changed",
        "upgrade_rule_missing",
    }


def test_capability_schema_change_requires_explicit_rule_review(tmp_path: Path) -> None:
    root, registry = _base_registry(tmp_path)
    _publish_pack(
        root,
        version="1.1.0",
        templates=[_contract("Cards/feature", "v1")],
        modifiers=[_modifier("card-radius")],
        capability_schema_version="1.1",
        rules=[{
            "from_version": "1.0.0",
            "compatible_capability_schema_change": True,
        }],
    )

    report = plan_agency_pack_upgrade(
        registry.resolve("clicks-and-mortars", "1.0.0"),
        registry.resolve("clicks-and-mortars", "1.1.0"),
        AgencyPackUsage(source_fingerprint="a" * 64),
    )

    assert report.status == "compatible"
    assert [issue.code for issue in report.issues] == [
        "capability_schema_change_reviewed"
    ]


def test_two_projects_share_pack_and_get_project_bound_zero_write_dry_run_reports(
    runner,
    tmp_path: Path,
) -> None:
    registry_root, _ = _base_registry(tmp_path)
    _publish_pack(
        registry_root,
        version="1.0.1",
        templates=[_contract("Cards/feature", "v1")],
        modifiers=[_modifier("card-radius")],
        template_version="1.0.0",
        modifier_version="1.0.0",
        rules=[{"from_version": "1.0.0", "notes": ["Governance metadata patch."]}],
    )
    first = _project(tmp_path / "client-one", "client-one")
    second = _project(tmp_path / "client-two", "client-two")
    before_first = _snapshot(first)
    before_second = _snapshot(second)

    def invoke(root: Path):
        return runner.invoke(
            cli,
            [
                "project",
                "pack",
                "upgrade",
                str(root),
                "--to-version",
                "1.0.1",
                "--packs-dir",
                str(registry_root),
                "--dry-run",
                "--json",
            ],
        )

    first_result = invoke(first)
    second_result = invoke(second)

    assert first_result.exit_code == second_result.exit_code == 0
    first_payload = json.loads(first_result.output)
    second_payload = json.loads(second_result.output)
    assert first_payload["report"]["fingerprint"] != second_payload["report"]["fingerprint"]
    assert first_payload["report"]["changes"] == second_payload["report"]["changes"]
    assert first_payload["report"]["issues"] == second_payload["report"]["issues"]
    assert first_payload["report"]["status"] == "compatible"
    assert _snapshot(first) == before_first
    assert _snapshot(second) == before_second


def test_cli_requires_explicit_mode_and_rejects_unknown_target_without_writes(runner, tmp_path: Path) -> None:
    registry_root, _ = _base_registry(tmp_path)
    root = _project(tmp_path / "client", "client")
    before = _snapshot(root)

    apply_result = runner.invoke(
        cli,
        [
            "project",
            "pack",
            "upgrade",
            str(root),
            "--to-version",
            "1.1.0",
            "--packs-dir",
            str(registry_root),
            "--json",
        ],
    )
    unknown = runner.invoke(
        cli,
        [
            "project",
            "pack",
            "upgrade",
            str(root),
            "--to-version",
            "1.1.0",
            "--packs-dir",
            str(registry_root),
            "--dry-run",
            "--json",
        ],
    )

    assert json.loads(apply_result.output)["error"]["category"] == "agency_pack_mode_required"
    assert json.loads(unknown.output)["error"]["category"] == "agency_pack_not_found"
    assert _snapshot(root) == before


def test_upgrade_direction_and_pack_name_fail_closed(tmp_path: Path) -> None:
    root, registry = _base_registry(tmp_path)
    current = registry.resolve("clicks-and-mortars", "1.0.0")
    with pytest.raises(AgencyPackCompatibilityError) as caught:
        plan_agency_pack_upgrade(current, current, AgencyPackUsage())
    assert caught.value.code == "agency_pack_upgrade_direction_invalid"


def test_missing_or_malformed_project_usage_cannot_report_compatible(tmp_path: Path) -> None:
    root, registry = _base_registry(tmp_path)
    _publish_pack(
        root,
        version="1.1.0",
        templates=[_contract("Cards/feature", "v1")],
        modifiers=[_modifier("card-radius")],
        rules=[{"from_version": "1.0.0"}],
    )
    current = registry.resolve("clicks-and-mortars", "1.0.0")
    target = registry.resolve("clicks-and-mortars", "1.1.0")

    missing = plan_agency_pack_upgrade(current, target, AgencyPackUsage())

    assert missing.status == "blocked"
    assert {issue.code for issue in missing.issues} == {"project_usage_unavailable"}

    plan = tmp_path / "malformed-plan.json"
    _write_json(plan, {"entries": [{"template_id": None, "modifiers": []}]})
    with pytest.raises(AgencyPackCompatibilityError) as caught:
        read_project_pack_usage(plan)
    assert caught.value.code == "agency_pack_usage_invalid"
