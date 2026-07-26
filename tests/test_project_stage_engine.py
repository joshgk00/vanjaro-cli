"""State-machine tests for resumable agency project stages and approvals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from vanjaro_cli.design.models import SourceKind
from vanjaro_cli.project import (
    ApprovalGate,
    ApprovalRecord,
    ApprovalStatus,
    ProjectApprovalError,
    ProjectSource,
    ProjectStage,
    ProjectStageError,
    StageApprovalError,
    StageDependencyError,
    StageEngine,
    StageInputs,
    StageOperationError,
    StageResult,
    StageStatus,
    create_manifest,
    initialize_workspace,
    invalidate_stage_state,
    load_manifest,
    request_approval,
    resolve_approval,
    write_manifest,
)


NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


class SequenceClock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    manifest = create_manifest(
        name="Stage Engine",
        target_profile="stage-engine",
        sources=[
            ProjectSource(
                id="live-html-1",
                kind=SourceKind.LIVE_HTML,
                reference="https://agency.example/",
            )
        ],
        agency_pack_name="agency",
        agency_pack_version="1.0.0",
        clock=lambda: NOW,
    )
    initialize_workspace(root, manifest)
    return root


def _write_operation(relative: str, content: str, calls: list[int] | None = None):
    def operation(context):
        if calls is not None:
            calls.append(context.attempt)
        path = context.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return StageResult(artifacts=(relative,), message=f"Wrote {relative}.")

    return operation


def _complete_analysis_and_plan(root: Path, clock: SequenceClock) -> None:
    engine = StageEngine(root, clock=clock)
    engine.execute(
        ProjectStage.ANALYZE,
        StageInputs(data={"mode": "offline"}),
        _write_operation("analysis/design-document.json", "analysis"),
    )
    engine.execute(
        ProjectStage.PLAN,
        StageInputs(files=(Path("analysis/design-document.json"),)),
        _write_operation("plans/composition-plan.json", "plan"),
    )


def test_dependency_gate_blocks_out_of_order_stage_without_mutation(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    before = (root / "project.json").read_bytes()

    with pytest.raises(StageDependencyError, match="requires completed stage.*analyze"):
        StageEngine(root).execute(
            ProjectStage.PLAN,
            StageInputs(),
            lambda context: pytest.fail("operation must not run"),
        )

    assert (root / "project.json").read_bytes() == before


def test_pack_upgrade_lock_blocks_concurrent_stage_before_any_write(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    before = (root / "project.json").read_bytes()
    (root / ".agency-pack-upgrade.lock").write_text("pid=1\n", encoding="ascii")

    with pytest.raises(ProjectStageError, match="locked by an agency-pack upgrade"):
        StageEngine(root).execute(
            ProjectStage.ANALYZE,
            StageInputs(),
            lambda context: pytest.fail("operation must not run"),
        )

    assert (root / "project.json").read_bytes() == before


def test_dry_run_never_calls_operation_or_changes_manifest(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    before = (root / "project.json").read_bytes()
    calls: list[int] = []

    execution = StageEngine(root).execute(
        ProjectStage.ANALYZE,
        StageInputs(data={"source": "cached"}),
        _write_operation("analysis/design-document.json", "analysis", calls),
        dry_run=True,
    )

    assert execution.status == "dry_run"
    assert execution.action == "execute"
    assert calls == []
    assert not (root / "analysis" / "design-document.json").exists()
    assert (root / "project.json").read_bytes() == before


def test_completed_stage_resumes_only_when_inputs_and_outputs_match(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    calls: list[int] = []
    engine = StageEngine(root, clock=SequenceClock())
    inputs = StageInputs(data={"source": "cached"})

    first = engine.execute(
        ProjectStage.ANALYZE,
        inputs,
        _write_operation("analysis/design-document.json", "first", calls),
    )
    second = engine.execute(
        ProjectStage.ANALYZE,
        inputs,
        _write_operation("analysis/design-document.json", "should-not-run", calls),
    )

    assert first.status == "completed"
    assert second.status == "resumed"
    assert calls == [1]

    (root / "analysis" / "design-document.json").write_text("tampered", encoding="utf-8")
    third = engine.execute(
        ProjectStage.ANALYZE,
        inputs,
        _write_operation("analysis/design-document.json", "repaired", calls),
    )
    assert third.status == "completed"
    assert third.attempt == 2
    assert calls == [1, 2]


def test_changed_input_reruns_and_invalidates_downstream_and_approval(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    clock = SequenceClock()
    _complete_analysis_and_plan(root, clock)
    approval = request_approval(
        root,
        gate=ApprovalGate.PORTAL_MUTATION,
        requested_by="operator",
        clock=clock,
    )
    resolve_approval(
        root,
        approval.id,
        approved=True,
        resolved_by="operator",
        clock=clock,
    )
    StageEngine(root, clock=clock).execute(
        ProjectStage.THEME,
        StageInputs(),
        _write_operation("build/theme-result.json", "theme"),
    )

    StageEngine(root, clock=clock).execute(
        ProjectStage.ANALYZE,
        StageInputs(data={"mode": "fresh"}),
        _write_operation("analysis/design-document.json", "fresh-analysis"),
    )
    manifest = load_manifest(root)

    assert manifest.stages[ProjectStage.ANALYZE].status == StageStatus.COMPLETED
    assert manifest.stages[ProjectStage.PLAN].status == StageStatus.PENDING
    assert manifest.stages[ProjectStage.THEME].status == StageStatus.PENDING
    assert manifest.approvals[0].status == ApprovalStatus.SUPERSEDED


def test_plan_invalidation_supersedes_every_plan_dependent_gate(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    clock = SequenceClock()
    _complete_analysis_and_plan(root, clock)
    manifest = load_manifest(root)
    manifest.approvals = [
        ApprovalRecord(
            id=f"{gate.value}-approval",
            gate=gate,
            status=ApprovalStatus.APPROVED,
            fingerprint=chr(ord("a") + index) * 64,
            requested_by="operator",
            requested_at=NOW,
            resolved_at=NOW,
            resolved_by="operator",
        )
        for index, gate in enumerate(ApprovalGate)
    ]

    invalidated = invalidate_stage_state(
        manifest,
        ProjectStage.PLAN,
        now=NOW + timedelta(minutes=1),
        resolved_by="pack-upgrade",
        approval_note="Agency pack changed.",
    )

    assert ProjectStage.PLAN.value in invalidated
    assert {approval.gate for approval in manifest.approvals} == set(ApprovalGate)
    assert all(
        approval.status == ApprovalStatus.SUPERSEDED
        for approval in manifest.approvals
    )
    assert all(
        approval.resolved_by == "pack-upgrade"
        for approval in manifest.approvals
    )


def test_portal_mutation_requires_exact_approved_plan_fingerprint(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    clock = SequenceClock()
    _complete_analysis_and_plan(root, clock)
    before = (root / "project.json").read_bytes()
    calls: list[int] = []

    with pytest.raises(StageApprovalError, match="approved portal_mutation fingerprint"):
        StageEngine(root, clock=clock).execute(
            ProjectStage.THEME,
            StageInputs(),
            _write_operation("build/theme-result.json", "theme", calls),
        )
    assert calls == []
    assert (root / "project.json").read_bytes() == before

    request = request_approval(
        root,
        gate=ApprovalGate.PORTAL_MUTATION,
        requested_by="operator",
        clock=clock,
    )
    resolve_approval(
        root,
        request.id,
        approved=True,
        resolved_by="operator",
        clock=clock,
    )
    execution = StageEngine(root, clock=clock).execute(
        ProjectStage.THEME,
        StageInputs(),
        _write_operation("build/theme-result.json", "theme", calls),
    )
    assert execution.status == "completed"
    assert execution.approval_fingerprint == request.fingerprint
    assert calls == [1]


def test_operation_failure_is_persisted_and_retry_increments_attempt(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    clock = SequenceClock()

    def fail(context):
        raise RuntimeError("source unavailable")

    with pytest.raises(StageOperationError, match="source unavailable"):
        StageEngine(root, clock=clock).execute(
            ProjectStage.ANALYZE,
            StageInputs(),
            fail,
        )
    failed = load_manifest(root).stages[ProjectStage.ANALYZE]
    assert failed.status == StageStatus.FAILED
    assert failed.attempt == 1
    assert failed.message == "source unavailable"

    execution = StageEngine(root, clock=clock).execute(
        ProjectStage.ANALYZE,
        StageInputs(),
        _write_operation("analysis/design-document.json", "recovered"),
    )
    assert execution.status == "completed"
    assert execution.attempt == 2


def test_interrupted_running_stage_restarts_without_claiming_completion(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    manifest = load_manifest(root)
    manifest.stages[ProjectStage.ANALYZE] = manifest.stages[ProjectStage.ANALYZE].model_copy(
        update={
            "status": StageStatus.RUNNING,
            "attempt": 1,
            "input_fingerprint": "a" * 64,
            "started_at": NOW,
        }
    )
    write_manifest(root, manifest)

    execution = StageEngine(root, clock=SequenceClock()).execute(
        ProjectStage.ANALYZE,
        StageInputs(),
        _write_operation("analysis/design-document.json", "restarted"),
    )
    assert execution.status == "completed"
    assert execution.attempt == 2


def test_missing_declared_artifact_fails_stage(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    with pytest.raises(StageOperationError, match="missing artifact"):
        StageEngine(root, clock=SequenceClock()).execute(
            ProjectStage.ANALYZE,
            StageInputs(),
            lambda context: StageResult(artifacts=("analysis/missing.json",)),
        )
    assert load_manifest(root).stages[ProjectStage.ANALYZE].status == StageStatus.FAILED


def test_approval_requests_are_idempotent_and_reject_noncurrent_fingerprints(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    clock = SequenceClock()
    _complete_analysis_and_plan(root, clock)

    first = request_approval(
        root,
        gate=ApprovalGate.PORTAL_MUTATION,
        requested_by="operator",
        clock=clock,
    )
    duplicate = request_approval(
        root,
        gate=ApprovalGate.PORTAL_MUTATION,
        requested_by="operator",
        clock=clock,
    )
    assert duplicate.id == first.id

    with pytest.raises(ProjectApprovalError, match="not the current plan output"):
        request_approval(
            root,
            gate=ApprovalGate.PORTAL_MUTATION,
            requested_by="operator",
            fingerprint="f" * 64,
            clock=clock,
        )
    manifest = load_manifest(root)
    assert manifest.approvals == [first]


def test_approval_cannot_be_requested_before_owner_stage(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    with pytest.raises(ProjectApprovalError, match="before plan completes"):
        request_approval(
            root,
            gate=ApprovalGate.PORTAL_MUTATION,
            requested_by="operator",
        )
