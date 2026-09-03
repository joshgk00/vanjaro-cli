"""Transactional, offline agency-pack apply acceptance tests."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import pytest

from vanjaro_cli.agency_library.generation import _PACK_VERSION
from vanjaro_cli.agency_library import (
    AgencyPackApplyError,
    AgencyPackRegistry,
    apply_agency_pack_upgrade,
    plan_agency_pack_upgrade,
    read_project_pack_usage,
    rollback_agency_pack_upgrade,
)
from vanjaro_cli.project import (
    ApprovalGate,
    ApprovalRecord,
    ApprovalStatus,
    load_manifest,
    migrate_project_manifest,
    write_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKS = PROJECT_ROOT / "artifacts" / "agency-packs"
KTS_PROJECT = PROJECT_ROOT / "artifacts" / "e2e" / "agency-project-kts-2026-07-16"
IMAGE_PROJECT = PROJECT_ROOT / "artifacts" / "e2e" / "agency-image-provider-dryrun"
MUTABLE = (
    "project.json",
    "plans/composition-plan.json",
    "plans/library-plan.json",
    "plans/global-block-plan.json",
    "plans/resolved-design-document.json",
    "plans/validation.json",
    "plans/planning-request.json",
)


def _copy_project(source: Path, destination: Path) -> Path:
    assert source.is_dir(), f"missing representative project: {source}"
    shutil.copytree(source, destination)
    migrate_project_manifest(destination, apply=True)
    return destination


def _mutable_snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        relative: (root / relative).read_bytes() if (root / relative).is_file() else None
        for relative in MUTABLE
    }


def _report(root: Path):
    registry = AgencyPackRegistry(PACKS)
    manifest = load_manifest(root)
    return registry, plan_agency_pack_upgrade(
        registry.resolve(manifest.agency_pack.name, manifest.agency_pack.version),
        registry.resolve(manifest.agency_pack.name, _PACK_VERSION),
        read_project_pack_usage(
            root / "plans" / "composition-plan.json",
            replan_inputs=(
                root / "project.json",
                root / "analysis" / "design-document.json",
                root / "analysis" / "design-overlays.json",
                root / "plans" / "library-plan.json",
                root / "plans" / "planning-request.json",
            ),
        ),
    )


def test_reviewed_apply_replans_real_project_and_invalidates_every_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _copy_project(KTS_PROJECT, tmp_path / "kts-client")
    manifest = load_manifest(root)
    now = datetime.now(timezone.utc)
    for gate in (ApprovalGate.PLAN, ApprovalGate.PORTAL_MUTATION, ApprovalGate.PUBLISH):
        manifest.approvals.append(
            ApprovalRecord(
                id=f"upgrade-test-{gate.value.replace('_', '-')}",
                gate=gate,
                status=ApprovalStatus.APPROVED,
                fingerprint="a" * 64,
                requested_by="qa",
                requested_at=now,
                resolved_at=now,
                resolved_by="qa",
            )
        )
    write_manifest(root, manifest)
    registry, report = _report(root)
    assert report.status == "compatible"

    def forbid_network(*args, **kwargs):  # pragma: no cover - only called on regression
        raise AssertionError("pack apply must not perform network or portal calls")

    monkeypatch.setattr("requests.sessions.Session.request", forbid_network)
    result = apply_agency_pack_upgrade(
        root,
        registry=registry,
        to_version=_PACK_VERSION,
        accepted_fingerprint=report.fingerprint,
        reviewed_by="agency-reviewer",
    )

    updated = load_manifest(root)
    assert result["state"] == "committed"
    assert updated.agency_pack.version == _PACK_VERSION
    assert updated.agency_pack.digest == result["pack_digest"]
    assert updated.stages["plan"].status.value == "completed"
    assert all(
        item.status == ApprovalStatus.SUPERSEDED
        for item in updated.approvals
        if item.id.startswith("upgrade-test-")
    )
    assert (root / str(result["transaction_artifact"])).is_file()
    transaction = json.loads((root / str(result["transaction_artifact"])).read_text())
    assert transaction["state"] == "committed"
    assert transaction["after_plan_fingerprint"] != transaction["before_plan_fingerprint"]
    assert json.loads((root / "plans" / "planning-request.json").read_text())[
        "target_pack"
    ]["digest"] == result["pack_digest"]


def test_stale_acceptance_and_blocked_project_are_zero_write(tmp_path: Path) -> None:
    compatible = _copy_project(KTS_PROJECT, tmp_path / "compatible")
    registry, accepted_report = _report(compatible)
    before = _mutable_snapshot(compatible)
    with pytest.raises(AgencyPackApplyError) as stale:
        apply_agency_pack_upgrade(
            compatible,
            registry=registry,
            to_version=_PACK_VERSION,
            accepted_fingerprint="0" * 64,
            reviewed_by="reviewer",
        )
    assert stale.value.code == "agency_pack_report_stale"
    assert _mutable_snapshot(compatible) == before
    assert not (compatible / ".agency-pack-upgrade.lock").exists()

    design_path = compatible / "analysis" / "design-document.json"
    design_path.write_bytes(design_path.read_bytes() + b"\n")
    changed_before = _mutable_snapshot(compatible)
    with pytest.raises(AgencyPackApplyError) as changed:
        apply_agency_pack_upgrade(
            compatible,
            registry=registry,
            to_version=_PACK_VERSION,
            accepted_fingerprint=accepted_report.fingerprint,
            reviewed_by="reviewer",
        )
    assert changed.value.code == "agency_pack_report_stale"
    assert _mutable_snapshot(compatible) == changed_before

    blocked = _copy_project(IMAGE_PROJECT, tmp_path / "blocked")
    blocked_registry, blocked_report = _report(blocked)
    assert blocked_report.status == "blocked"
    blocked_before = _mutable_snapshot(blocked)
    with pytest.raises(AgencyPackApplyError) as rejected:
        apply_agency_pack_upgrade(
            blocked,
            registry=blocked_registry,
            to_version=_PACK_VERSION,
            accepted_fingerprint=blocked_report.fingerprint,
            reviewed_by="reviewer",
        )
    assert rejected.value.code == "agency_pack_migration_not_automated"
    assert _mutable_snapshot(blocked) == blocked_before


def test_planning_failure_restores_every_mutable_file_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _copy_project(KTS_PROJECT, tmp_path / "rollback-client")
    registry, report = _report(root)
    before = _mutable_snapshot(root)

    def fail_planning(*args, **kwargs):
        raise RuntimeError("injected planning failure")

    monkeypatch.setattr(
        "vanjaro_cli.agency_library.project_upgrade.run_project_planning",
        fail_planning,
    )
    with pytest.raises(AgencyPackApplyError) as failure:
        apply_agency_pack_upgrade(
            root,
            registry=registry,
            to_version=_PACK_VERSION,
            accepted_fingerprint=report.fingerprint,
            reviewed_by="failure-test",
        )
    assert failure.value.code == "agency_pack_apply_failed"
    assert _mutable_snapshot(root) == before
    journals = list((root / "history" / "pack-upgrades").glob("*/transaction.json"))
    assert len(journals) == 1
    journal = json.loads(journals[0].read_text())
    assert journal["state"] == "rolled_back"
    assert "injected planning failure" in journal["failure"]
    assert not (root / ".agency-pack-upgrade.lock").exists()

    journal["state"] = "applying"
    journals[0].write_text(json.dumps(journal, indent=2, sort_keys=True) + "\n")
    (root / "project.json").write_bytes(b"interrupted partial write")
    (root / ".agency-pack-upgrade.lock").write_text("pid=999999\n")
    recovery = rollback_agency_pack_upgrade(
        root,
        transaction_id=journals[0].parent.name,
        rolled_back_by="recovery-operator",
    )
    assert recovery["state"] == "rolled_back"
    assert _mutable_snapshot(root) == before
    with pytest.raises(AgencyPackApplyError) as replay:
        rollback_agency_pack_upgrade(
            root,
            transaction_id=journals[0].parent.name,
            rolled_back_by="replay-attempt",
        )
    assert replay.value.code == "agency_pack_transaction_not_recoverable"
    assert _mutable_snapshot(root) == before
