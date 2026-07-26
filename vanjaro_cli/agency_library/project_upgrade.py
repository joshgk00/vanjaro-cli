"""Reviewed, local-only agency-pack upgrades for project workspaces."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterator, Mapping, Sequence

from vanjaro_cli.agency_library.compatibility import (
    plan_agency_pack_upgrade,
    read_project_pack_usage,
)
from vanjaro_cli.agency_library.registry import AgencyPackRegistry, ResolvedAgencyPack
from vanjaro_cli.design.template_catalog import (
    TemplateCatalogEntry,
    load_template_catalog,
    load_template_data,
)
from vanjaro_cli.orchestration.project_planning import run_project_planning
from vanjaro_cli.project import (
    AuditEvent,
    DecisionRecord,
    ProjectStage,
    StageEngine,
    StageInputs,
    StageStatus,
    invalidate_stage_state,
    load_manifest,
    write_manifest,
)


_LOCK_NAME = ".agency-pack-upgrade.lock"
_PLAN_FILES = (
    "plans/composition-plan.json",
    "plans/library-plan.json",
    "plans/global-block-plan.json",
    "plans/resolved-design-document.json",
    "plans/validation.json",
    "plans/planning-request.json",
)
# Restore the manifest last so it never advertises planning artifacts that are
# only partially recovered.
_MUTABLE_FILES = (*_PLAN_FILES, "project.json")


class AgencyPackApplyError(ValueError):
    """Stable, operator-facing failure from a reviewed pack transaction."""

    def __init__(self, code: str, message: str, *, recommended_action: str) -> None:
        self.code = code
        self.recommended_action = recommended_action
        super().__init__(message)

    def as_dict(self) -> dict[str, str]:
        return {
            "category": self.code,
            "message": str(self),
            "recommended_action": self.recommended_action,
        }


def apply_agency_pack_upgrade(
    root: Path,
    *,
    registry: AgencyPackRegistry,
    to_version: str,
    accepted_fingerprint: str,
    reviewed_by: str,
) -> dict[str, object]:
    """Apply a compatible pack upgrade as an offline compensating transaction."""

    root = root.expanduser().resolve()
    actor = reviewed_by.strip()
    if not actor:
        raise AgencyPackApplyError(
            "agency_pack_reviewer_required",
            "a non-empty reviewer identity is required",
            recommended_action="Pass --by with the person who reviewed the dry-run report.",
        )
    if not _is_sha256(accepted_fingerprint):
        raise AgencyPackApplyError(
            "agency_pack_acceptance_invalid",
            "the accepted report fingerprint must be a lowercase SHA-256 value",
            recommended_action="Copy the exact fingerprint from the latest dry-run report.",
        )

    with _workspace_lock(root):
        manifest = load_manifest(root)
        if any(record.status == StageStatus.RUNNING for record in manifest.stages.values()):
            raise AgencyPackApplyError(
                "agency_pack_project_busy",
                "the project has a running stage",
                recommended_action="Finish or recover the running stage before upgrading its pack.",
            )
        current = registry.resolve(manifest.agency_pack.name, manifest.agency_pack.version)
        locked_digest = getattr(manifest.agency_pack, "digest", None)
        if locked_digest is not None and locked_digest != current.digest:
            raise AgencyPackApplyError(
                "agency_pack_current_digest_mismatch",
                "the current project pack digest no longer matches the registry",
                recommended_action="Restore the immutable current pack before attempting an upgrade.",
            )
        target = registry.resolve(manifest.agency_pack.name, to_version)
        usage = read_project_pack_usage(
            root / "plans/composition-plan.json",
            replan_inputs=_replan_inputs(root),
        )
        report = plan_agency_pack_upgrade(current, target, usage)
        if report.fingerprint != accepted_fingerprint:
            raise AgencyPackApplyError(
                "agency_pack_report_stale",
                "the accepted report fingerprint does not match the current project and registry",
                recommended_action="Run the dry-run again and review the newly generated report.",
            )
        if report.status != "compatible":
            raise AgencyPackApplyError(
                "agency_pack_migration_not_automated",
                f"only compatible reports can be applied; this report is {report.status}",
                recommended_action="Resolve every remediation or blocker and produce a compatible report.",
            )
        if set(usage.sections_by_template) != set(usage.templates):
            raise AgencyPackApplyError(
                "agency_pack_section_evidence_missing",
                "the current plan does not identify every affected source section",
                recommended_action="Regenerate the project plan before applying the upgrade.",
            )
        _attest_current_plan_provenance(root, current)
        catalog = _attest_catalog(target)
        if current.modifiers != target.modifiers:
            raise AgencyPackApplyError(
                "agency_pack_modifier_migration_not_automated",
                "the target changes modifier contracts, which are not yet executable by this workflow",
                recommended_action="Publish a target with unchanged modifiers or migrate modifiers manually under review.",
            )
        planning_request = _recover_planning_request(root, target, catalog, actor)

        transaction_id = _next_transaction_id(root, current, target, report.fingerprint)
        transaction_dir = root / "history" / "pack-upgrades" / transaction_id
        snapshot = _create_snapshot(root, transaction_dir)
        journal_path = transaction_dir / "transaction.json"
        journal: dict[str, object] = {
            "schema_version": "1.0",
            "transaction_id": transaction_id,
            "state": "prepared",
            "reviewed_by": actor,
            "project_id": manifest.project.id,
            "report_fingerprint": report.fingerprint,
            "from_pack": _pack_lock(current),
            "to_pack": _pack_lock(target),
            "snapshot": snapshot,
            "created_at": _utc_now().isoformat(),
        }
        accepted_report_path = transaction_dir / "accepted-report.json"
        _atomic_json(accepted_report_path, report.as_dict())
        journal["accepted_report_sha256"] = hashlib.sha256(
            accepted_report_path.read_bytes()
        ).hexdigest()
        _atomic_json(journal_path, journal)
        before_plan = usage.source_fingerprint
        invalidated: tuple[str, ...] = ()
        superseded: tuple[str, ...] = ()
        try:
            journal["state"] = "applying"
            _atomic_json(journal_path, journal)
            now = _utc_now()
            working = manifest.model_copy(deep=True)
            working.agency_pack = working.agency_pack.model_copy(
                update={"version": target.manifest.version, "digest": target.digest}
            )
            active_approvals = {
                item.id
                for item in working.approvals
                if item.status.value in {"pending", "approved"}
            }
            invalidated = invalidate_stage_state(
                working,
                ProjectStage.PLAN,
                now=now,
                resolved_by=actor,
                approval_note=f"Superseded by agency-pack transaction {transaction_id}.",
            )
            superseded = tuple(
                item.id
                for item in working.approvals
                if item.id in active_approvals and item.status.value == "superseded"
            )
            working.audit.append(
                AuditEvent(
                    id=_unique_id(working.audit, f"{transaction_id}-started"),
                    occurred_at=now,
                    kind="agency_pack_upgrade_started",
                    message=(
                        f"Started reviewed agency-pack upgrade {current.manifest.version} "
                        f"to {target.manifest.version}."
                    ),
                    stage=ProjectStage.PLAN,
                    fingerprint=report.fingerprint,
                    artifacts=[f"history/pack-upgrades/{transaction_id}/transaction.json"],
                )
            )
            working.project = working.project.model_copy(update={"updated_at": now})
            write_manifest(root, working)

            plan_files = [Path("analysis/design-document.json")]
            if (root / "analysis" / "design-overlays.json").is_file():
                plan_files.append(Path("analysis/design-overlays.json"))
            policy = planning_request["policy"]
            overrides = planning_request["template_overrides"]
            execution = StageEngine(root, allow_pack_upgrade_lock=True).execute(
                ProjectStage.PLAN,
                StageInputs(
                    data={
                        **planning_request,
                        "template_catalog_fingerprint": _catalog_fingerprint(catalog),
                    },
                    files=tuple(plan_files),
                ),
                lambda context: run_project_planning(
                    context,
                    minimum_confidence=float(policy["minimum_confidence"]),
                    allow_simplification=bool(policy["allow_simplification"]),
                    css_rule_budget=int(policy["css_rule_budget"]),
                    template_overrides=overrides,
                    override_author=str(planning_request["override_author"]),
                    override_reason=str(planning_request["override_reason"]),
                    catalog=catalog,
                    planning_request=planning_request,
                ),
            )
            validation = _read_json(root / "plans" / "validation.json")
            if validation.get("valid") is not True:
                raise AgencyPackApplyError(
                    "agency_pack_replan_invalid",
                    "the target-pack replan produced approval-blocking validation issues",
                    recommended_action="Inspect the rolled-back transaction evidence and revise the design mapping.",
                )
            final_target = registry.resolve(manifest.agency_pack.name, to_version)
            if final_target.digest != target.digest:
                raise AgencyPackApplyError(
                    "agency_pack_target_digest_changed",
                    "the target pack changed while the transaction was running",
                    recommended_action="Restore immutable registry content and retry from a new dry-run.",
                )
            after_usage = read_project_pack_usage(
                root / "plans/composition-plan.json",
                replan_inputs=_replan_inputs(root),
            )
            _require_usage_in_pack(after_usage.templates, after_usage.modifiers, target)
            committed = load_manifest(root)
            finished = _utc_now()
            committed.decisions.append(
                DecisionRecord(
                    id=_unique_id(committed.decisions, f"{transaction_id}-decision"),
                    topic="agency_pack_upgrade",
                    selection=f"{target.manifest.name}@{target.manifest.version}",
                    rationale=f"Accepted compatibility report {report.fingerprint}.",
                    decided_by=actor,
                    decided_at=finished,
                    stage=ProjectStage.PLAN,
                    metadata={
                        "from_digest": current.digest,
                        "to_digest": target.digest,
                        "transaction_id": transaction_id,
                    },
                )
            )
            committed.audit.append(
                AuditEvent(
                    id=_unique_id(committed.audit, f"{transaction_id}-committed"),
                    occurred_at=finished,
                    kind="agency_pack_upgraded",
                    message=(
                        f"Committed agency-pack upgrade to {target.manifest.version}; "
                        "the new plan requires fresh approval."
                    ),
                    stage=ProjectStage.PLAN,
                    fingerprint=execution.output_fingerprint,
                    artifacts=[f"history/pack-upgrades/{transaction_id}/transaction.json"],
                )
            )
            committed.project = committed.project.model_copy(update={"updated_at": finished})
            write_manifest(root, committed)
            journal.update(
                {
                    "state": "committed",
                    "committed_at": finished.isoformat(),
                    "before_plan_fingerprint": before_plan,
                    "after_plan_fingerprint": after_usage.source_fingerprint,
                    "plan_output_fingerprint": execution.output_fingerprint,
                    "invalidated_stages": list(invalidated),
                    "superseded_approvals": list(superseded),
                }
            )
            _atomic_json(journal_path, journal)
            return {
                "transaction_id": transaction_id,
                "state": "committed",
                "from_version": current.manifest.version,
                "to_version": target.manifest.version,
                "pack_digest": target.digest,
                "report_fingerprint": report.fingerprint,
                "before_plan_fingerprint": before_plan,
                "after_plan_fingerprint": after_usage.source_fingerprint,
                "plan_output_fingerprint": execution.output_fingerprint,
                "invalidated_stages": list(invalidated),
                "superseded_approvals": list(superseded),
                "transaction_artifact": f"history/pack-upgrades/{transaction_id}/transaction.json",
            }
        except Exception as exc:
            _restore_snapshot(root, transaction_dir / "snapshot", snapshot)
            journal.update(
                {
                    "state": "rolled_back",
                    "rolled_back_at": _utc_now().isoformat(),
                    "failure": str(exc) or exc.__class__.__name__,
                }
            )
            _atomic_json(journal_path, journal)
            if isinstance(exc, AgencyPackApplyError):
                raise
            raise AgencyPackApplyError(
                "agency_pack_apply_failed",
                f"the pack transaction failed and project files were restored: {exc}",
                recommended_action=f"Inspect history/pack-upgrades/{transaction_id}/transaction.json.",
            ) from exc


def rollback_agency_pack_upgrade(
    root: Path, *, transaction_id: str, rolled_back_by: str
) -> dict[str, object]:
    """Recover a prepared/applying local transaction from its verified snapshot."""

    root = root.expanduser().resolve()
    actor = rolled_back_by.strip()
    if not actor:
        raise AgencyPackApplyError(
            "agency_pack_reviewer_required",
            "a non-empty recovery operator identity is required",
            recommended_action="Pass --by with the person authorizing recovery.",
        )
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", transaction_id):
        raise AgencyPackApplyError(
            "agency_pack_transaction_invalid",
            "the transaction ID is invalid",
            recommended_action="Copy the exact directory name from history/pack-upgrades.",
        )
    transaction_dir = _safe_path(root, f"history/pack-upgrades/{transaction_id}")
    journal_path = transaction_dir / "transaction.json"
    journal = _read_json(journal_path)
    if journal.get("transaction_id") != transaction_id:
        raise AgencyPackApplyError(
            "agency_pack_transaction_invalid",
            "the transaction journal identity does not match its directory",
            recommended_action="Do not recover from untrusted or moved transaction evidence.",
        )
    # Explicit recovery may clear only a lock whose recorded process is no longer alive.
    _clear_interrupted_lock(root / _LOCK_NAME)
    with _workspace_lock(root):
        journal = _read_json(journal_path)
        if journal.get("transaction_id") != transaction_id:
            raise AgencyPackApplyError(
                "agency_pack_transaction_invalid",
                "the transaction journal changed while recovery was acquiring the lock",
                recommended_action="Stop and inspect the transaction evidence.",
            )
        if journal.get("state") not in {"prepared", "applying"}:
            raise AgencyPackApplyError(
                "agency_pack_transaction_not_recoverable",
                f"transaction state {journal.get('state')!r} is terminal or invalid",
                recommended_action="Recover only a prepared or applying interrupted transaction.",
            )
        records = journal.get("snapshot")
        if not isinstance(records, list):
            raise AgencyPackApplyError(
                "agency_pack_snapshot_invalid",
                "the transaction journal has no valid snapshot inventory",
                recommended_action="Stop and restore the workspace from an external backup.",
            )
        try:
            current_project_id = load_manifest(root).project.id
        except Exception:
            current_project_id = None
        if current_project_id is not None and current_project_id != journal.get("project_id"):
            raise AgencyPackApplyError(
                "agency_pack_workspace_identity_mismatch",
                "the transaction belongs to a different project workspace",
                recommended_action="Select the original project transaction before recovery.",
            )
        _restore_snapshot(root, transaction_dir / "snapshot", records)
        journal.update(
            {
                "state": "rolled_back",
                "rolled_back_at": _utc_now().isoformat(),
                "rolled_back_by": actor,
                "failure": journal.get("failure", "explicit interruption recovery"),
            }
        )
        _atomic_json(journal_path, journal)
    return {
        "transaction_id": transaction_id,
        "state": "rolled_back",
        "rolled_back_by": actor,
        "transaction_artifact": f"history/pack-upgrades/{transaction_id}/transaction.json",
    }


def _attest_catalog(target: ResolvedAgencyPack) -> tuple[TemplateCatalogEntry, ...]:
    catalog = tuple(load_template_catalog())
    contracts = {item.template_id: item for item in target.templates.templates}
    entries = {item.template_id: item for item in catalog}
    if set(entries) != set(contracts):
        raise AgencyPackApplyError(
            "agency_pack_catalog_identity_mismatch",
            "the executable template catalog does not exactly match the target pack",
            recommended_action="Install the exact target template catalog and retry.",
        )
    for identifier, entry in entries.items():
        contract = contracts[identifier]
        template_sha = _canonical_sha256(load_template_data(entry))
        capability_sha = _canonical_sha256(entry.capabilities.model_dump(mode="json"))
        if template_sha != contract.template_sha256 or capability_sha != contract.capability_sha256:
            raise AgencyPackApplyError(
                "agency_pack_catalog_digest_mismatch",
                f"executable template {identifier!r} does not match the target pack",
                recommended_action="Restore the published target catalog before applying the upgrade.",
            )
    return catalog


def _attest_current_plan_provenance(
    root: Path, current: ResolvedAgencyPack
) -> None:
    composition = _read_json(root / "plans" / "composition-plan.json")
    try:
        library = json.loads((root / "plans" / "library-plan.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgencyPackApplyError(
            "agency_pack_plan_provenance_invalid",
            f"cannot read the current executable library plan: {exc}",
            recommended_action="Regenerate the project plan with its locked current pack.",
        ) from exc
    entries = composition.get("entries")
    if not isinstance(entries, list) or not isinstance(library, list):
        raise AgencyPackApplyError(
            "agency_pack_plan_provenance_invalid",
            "composition and library plans must contain governed entry lists",
            recommended_action="Regenerate the project plan with its locked current pack.",
        )
    contracts = {item.template_id: item for item in current.templates.templates}
    expected: dict[str, tuple[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise AgencyPackApplyError(
                "agency_pack_plan_provenance_invalid",
                "composition entries must be objects",
                recommended_action="Regenerate the project plan with its locked current pack.",
            )
        match = entry.get("match")
        if isinstance(match, dict) and match.get("blocking") is True:
            continue
        key, template_id, template_name = (
            entry.get("source_section_id"),
            entry.get("template_id"),
            entry.get("template"),
        )
        if not all(isinstance(value, str) and value for value in (key, template_id, template_name)):
            raise AgencyPackApplyError(
                "agency_pack_plan_provenance_invalid",
                "composition entries lack executable template provenance",
                recommended_action="Regenerate the project plan with its locked current pack.",
            )
        expected[key] = (template_id, template_name)
    observed: set[str] = set()
    for item in library:
        if not isinstance(item, dict):
            raise AgencyPackApplyError(
                "agency_pack_plan_provenance_invalid",
                "library-plan entries must be objects",
                recommended_action="Regenerate the project plan with its locked current pack.",
            )
        key, digest = item.get("key"), item.get("template_digest")
        if not isinstance(key, str) or key in observed or key not in expected:
            raise AgencyPackApplyError(
                "agency_pack_plan_provenance_invalid",
                "library-plan section identities do not match the composition plan",
                recommended_action="Regenerate the project plan with its locked current pack.",
            )
        template_id, template_name = expected[key]
        contract = contracts.get(template_id)
        if (
            contract is None
            or item.get("template") != template_name
            or digest != contract.template_sha256
        ):
            raise AgencyPackApplyError(
                "agency_pack_plan_provenance_mismatch",
                f"library-plan template for section {key!r} is not locked to the current pack",
                recommended_action="Restore the current executable catalog and regenerate the plan.",
            )
        observed.add(key)
    if observed != set(expected):
        raise AgencyPackApplyError(
            "agency_pack_plan_provenance_invalid",
            "library plan is missing executable composition sections",
            recommended_action="Regenerate the project plan with its locked current pack.",
        )


def _recover_planning_request(
    root: Path,
    target: ResolvedAgencyPack,
    catalog: Sequence[TemplateCatalogEntry],
    actor: str,
) -> dict[str, Any]:
    payload = _read_json(root / "plans" / "composition-plan.json")
    policy = payload.get("policy")
    entries = payload.get("entries")
    if not isinstance(policy, dict) or not isinstance(entries, list):
        raise AgencyPackApplyError(
            "agency_pack_planning_request_unavailable",
            "the existing plan cannot be reproduced safely",
            recommended_action="Run project plan again before reviewing the pack upgrade.",
        )
    overrides: dict[str, str] = {}
    audit_pairs: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("override_audit"):
            continue
        audit = entry["override_audit"]
        if not isinstance(audit, dict):
            raise AgencyPackApplyError(
                "agency_pack_planning_request_ambiguous",
                "legacy override audit data is ambiguous",
                recommended_action="Rerun project plan with explicit override metadata.",
            )
        section_id, template_id = entry.get("source_section_id"), entry.get("template_id")
        author, reason = audit.get("author"), audit.get("reason")
        if not all(isinstance(value, str) and value.strip() for value in (section_id, template_id, author, reason)):
            raise AgencyPackApplyError(
                "agency_pack_planning_request_ambiguous",
                "legacy override audit data is incomplete",
                recommended_action="Rerun project plan with explicit override metadata.",
            )
        overrides[section_id] = template_id
        audit_pairs.add((author, reason))
    if len(audit_pairs) > 1:
        raise AgencyPackApplyError(
            "agency_pack_planning_request_ambiguous",
            "the existing plan contains overrides with different authors or reasons",
            recommended_action="Rerun project plan with one explicit override review context.",
        )
    minimum_confidence = policy.get("minimum_confidence", 0.65)
    allow_simplification = policy.get("allow_simplification", False)
    css_rule_budget = policy.get("css_rule_budget", 12)
    if (
        isinstance(minimum_confidence, bool)
        or not isinstance(minimum_confidence, (int, float))
        or not 0 <= float(minimum_confidence) <= 1
        or not isinstance(allow_simplification, bool)
        or isinstance(css_rule_budget, bool)
        or not isinstance(css_rule_budget, int)
        or css_rule_budget < 0
    ):
        raise AgencyPackApplyError(
            "agency_pack_planning_request_invalid",
            "the persisted planning policy has invalid value types or ranges",
            recommended_action="Rerun project plan with explicit valid policy options.",
        )
    override_author, override_reason = next(iter(audit_pairs), (actor, "agency-pack replan"))
    return {
        "schema_version": "1.0",
        "policy": {
            "minimum_confidence": float(minimum_confidence),
            "allow_simplification": allow_simplification,
            "css_rule_budget": css_rule_budget,
        },
        "template_overrides": dict(sorted(overrides.items(), key=lambda item: item[0].casefold())),
        "override_author": override_author,
        "override_reason": override_reason,
        "target_pack": _pack_lock(target),
        "template_library_version": target.templates.version,
        "template_catalog_fingerprint": _catalog_fingerprint(catalog),
    }


def _create_snapshot(root: Path, transaction_dir: Path) -> list[dict[str, object]]:
    if transaction_dir.exists():
        raise AgencyPackApplyError(
            "agency_pack_transaction_exists",
            f"transaction directory already exists: {transaction_dir.name}",
            recommended_action="Inspect the existing transaction before retrying.",
        )
    snapshot_root = transaction_dir / "snapshot"
    snapshot_root.mkdir(parents=True)
    records: list[dict[str, object]] = []
    for relative in _MUTABLE_FILES:
        source = _safe_path(root, relative)
        record: dict[str, object] = {"path": relative, "existed": source.is_file()}
        if source.is_file():
            raw = source.read_bytes()
            destination = _safe_path(snapshot_root, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            record["sha256"] = hashlib.sha256(raw).hexdigest()
        records.append(record)
    return records


def _restore_snapshot(
    root: Path, snapshot_root: Path, records: list[dict[str, object]]
) -> None:
    if not snapshot_root.is_dir():
        raise AgencyPackApplyError(
            "agency_pack_snapshot_missing",
            "the transaction snapshot is missing",
            recommended_action="Stop and restore the workspace from an external backup.",
        )
    if len(records) != len(_MUTABLE_FILES):
        raise AgencyPackApplyError(
            "agency_pack_snapshot_invalid",
            "the snapshot inventory is incomplete",
            recommended_action="Stop and restore the workspace from an external backup.",
        )
    prepared: list[tuple[Path, bool, bytes | None]] = []
    observed: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise AgencyPackApplyError(
                "agency_pack_snapshot_invalid",
                "snapshot records must be objects",
                recommended_action="Stop and restore the workspace from an external backup.",
            )
        relative = record.get("path")
        existed = record.get("existed")
        if (
            not isinstance(relative, str)
            or relative not in _MUTABLE_FILES
            or relative in observed
            or not isinstance(existed, bool)
        ):
            raise AgencyPackApplyError(
                "agency_pack_snapshot_invalid",
                "snapshot paths and existence flags must match the governed inventory",
                recommended_action="Stop and restore the workspace from an external backup.",
            )
        observed.add(relative)
        target = _safe_path(root, relative)
        raw: bytes | None = None
        if existed:
            expected = record.get("sha256")
            if not isinstance(expected, str) or not _is_sha256(expected):
                raise AgencyPackApplyError(
                    "agency_pack_snapshot_invalid",
                    f"snapshot record has no valid digest for {relative}",
                    recommended_action="Stop and restore the workspace from an external backup.",
                )
            raw = _safe_path(snapshot_root, relative).read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise AgencyPackApplyError(
                    "agency_pack_snapshot_tampered",
                    f"snapshot hash mismatch for {relative}",
                    recommended_action="Stop and restore the workspace from an external backup.",
                )
        elif "sha256" in record:
            raise AgencyPackApplyError(
                "agency_pack_snapshot_invalid",
                f"nonexistent snapshot record unexpectedly has a digest for {relative}",
                recommended_action="Stop and restore the workspace from an external backup.",
            )
        prepared.append((target, existed, raw))
    if observed != set(_MUTABLE_FILES):
        raise AgencyPackApplyError(
            "agency_pack_snapshot_invalid",
            "the snapshot inventory does not match the governed mutable files",
            recommended_action="Stop and restore the workspace from an external backup.",
        )
    for target, existed, raw in prepared:
        if existed:
            assert raw is not None
            _atomic_bytes(target, raw)
        else:
            target.unlink(missing_ok=True)


@contextmanager
def _workspace_lock(root: Path) -> Iterator[None]:
    path = root / _LOCK_NAME
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise AgencyPackApplyError(
            "agency_pack_upgrade_locked",
            "another pack transaction or interrupted transaction owns the workspace lock",
            recommended_action=f"Inspect and recover {path.name} before retrying.",
        ) from exc
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.close(descriptor)
        yield
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        path.unlink(missing_ok=True)


def _next_transaction_id(
    root: Path,
    current: ResolvedAgencyPack,
    target: ResolvedAgencyPack,
    fingerprint: str,
) -> str:
    base = f"{current.manifest.version}-to-{target.manifest.version}-{fingerprint[:12]}"
    parent = root / "history" / "pack-upgrades"
    attempt = 1
    while (parent / f"{base}-attempt-{attempt:04d}").exists():
        attempt += 1
    return f"{base}-attempt-{attempt:04d}"


def _clear_interrupted_lock(path: Path) -> None:
    if not path.exists():
        return
    try:
        content = path.read_text(encoding="ascii").strip()
        pid = int(content.removeprefix("pid="))
    except (OSError, ValueError) as exc:
        raise AgencyPackApplyError(
            "agency_pack_upgrade_lock_invalid",
            "the interrupted transaction lock has invalid ownership data",
            recommended_action="Confirm no upgrade process is running before repairing the lock manually.",
        ) from exc
    if _process_is_alive(pid):
        raise AgencyPackApplyError(
            "agency_pack_upgrade_locked",
            f"upgrade process {pid} is still active",
            recommended_action="Wait for the active process to finish before recovery.",
        )
    path.unlink()


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        # Access denied also means the process exists but cannot be inspected.
        return ctypes.windll.kernel32.GetLastError() == 5
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _require_usage_in_pack(
    templates: Sequence[str], modifiers: Sequence[str], target: ResolvedAgencyPack
) -> None:
    allowed_templates = {item.template_id for item in target.templates.templates}
    allowed_modifiers = {item.modifier_id for item in target.modifiers.modifiers}
    missing = sorted(set(templates) - allowed_templates, key=str.casefold)
    missing_modifiers = sorted(set(modifiers) - allowed_modifiers, key=str.casefold)
    if missing or missing_modifiers:
        raise AgencyPackApplyError(
            "agency_pack_replan_outside_target",
            f"replan used contracts outside the target pack: templates={missing}, modifiers={missing_modifiers}",
            recommended_action="Repair the target catalog and planner policy before retrying.",
        )


def _pack_lock(pack: ResolvedAgencyPack) -> dict[str, str]:
    return {
        "name": pack.manifest.name,
        "version": pack.manifest.version,
        "digest": pack.digest,
    }


def _catalog_fingerprint(catalog: Sequence[TemplateCatalogEntry]) -> str:
    return _canonical_sha256(
        [
            {"template_id": entry.template_id, "data": load_template_data(entry)}
            for entry in catalog
        ]
    )


def _replan_inputs(root: Path) -> tuple[Path, ...]:
    return (
        root / "project.json",
        root / "analysis" / "design-document.json",
        root / "analysis" / "design-overlays.json",
        root / "plans" / "library-plan.json",
        root / "plans" / "planning-request.json",
    )


def _unique_id(records: Sequence[object], preferred: str) -> str:
    existing = {str(getattr(item, "id")) for item in records}
    candidate = preferred.lower().replace("_", "-")
    suffix = 1
    while candidate in existing:
        suffix += 1
        candidate = f"{preferred}-{suffix}"
    return candidate


def _safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise AgencyPackApplyError(
            "agency_pack_artifact_path_unsafe",
            f"transaction artifact escapes the workspace: {relative}",
            recommended_action="Remove the unsafe transaction and restore from a trusted backup.",
        ) from exc
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgencyPackApplyError(
            "agency_pack_artifact_invalid",
            f"cannot read required artifact {path}: {exc}",
            recommended_action="Regenerate the project plan before upgrading.",
        ) from exc
    if not isinstance(value, dict):
        raise AgencyPackApplyError(
            "agency_pack_artifact_invalid",
            f"required artifact is not an object: {path}",
            recommended_action="Regenerate the project plan before upgrading.",
        )
    return value


def _atomic_json(path: Path, value: object) -> None:
    _atomic_bytes(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def _atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "AgencyPackApplyError",
    "apply_agency_pack_upgrade",
    "rollback_agency_pack_upgrade",
]
