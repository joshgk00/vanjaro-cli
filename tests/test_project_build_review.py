"""Acceptance coverage for fingerprint-bound one-stage project builds."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from vanjaro_cli.cli import cli
from vanjaro_cli.commands import project_build_cmd
from vanjaro_cli.orchestration import project_build_review
from vanjaro_cli.orchestration.project_build_review import PreparedBuildReview
from vanjaro_cli.project.build_receipt import finalize_build_receipt
from vanjaro_cli.project.models import ApprovalGate, ProjectStage
from vanjaro_cli.project import (
    ProjectSource,
    StageEngine,
    StageInputs,
    StageResult,
    create_manifest,
    initialize_workspace,
    load_manifest,
    request_approval,
    resolve_approval,
    write_manifest,
)
from vanjaro_cli.design.models import SourceKind
from vanjaro_cli.project.stage_engine import StageExecution


def _execution(*, action: str = "execute", status: str = "dry_run") -> StageExecution:
    return StageExecution(
        stage=ProjectStage.ASSETS,
        action=action,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        input_fingerprint="1" * 64,
        output_fingerprint=None,
        attempt=1,
        artifacts=(),
        approval_gate=ApprovalGate.PORTAL_MUTATION,
        approval_fingerprint="2" * 64,
    )


def _receipt(operator: str = "Agency Operator") -> dict:
    return finalize_build_receipt(
        {
            "schema_version": "agency-build-review-v1",
            "contract_version": "1.0",
            "project_id": "example",
            "target": {
                "profile": "example",
                "expected_base_url": "http://example.test",
                "expected_portal_id": 7,
            },
            "stage": "assets",
            "stage_contract_version": "1.1",
            "action": "execute",
            "attempt": 1,
            "requested": {
                "theme_mode": "preserve",
                "through": "verify",
                "page_mode": "isolated",
                "operator": operator,
            },
            "manifest_fingerprint": "3" * 64,
            "dependencies": [
                {
                    "stage": "theme",
                    "status": "completed",
                    "output_fingerprint": "4" * 64,
                }
            ],
            "inputs": {
                "data": {"folder": "Images/agency/example/"},
                "files": [
                    {"path": "plans/library-plan.json", "sha256": "5" * 64}
                ],
            },
            "input_fingerprint": "1" * 64,
            "approval": {
                "id": "approval-1",
                "gate": "portal_mutation",
                "status": "approved",
                "fingerprint": "2" * 64,
            },
            "observed_portal": {
                "profile": "example",
                "base_url": "http://example.test",
                "portal_id": 7,
                "health_status": "ok",
                "dnn_version": "9",
                "vanjaro_version": "1",
                "user_name": "host",
            },
            "preview": {
                "schema_version": "agency-build-stage-plan-v1",
                "stage": "assets",
                "upstream_probes": [],
                "portal_actions": [],
                "local_writes": ["build/asset-manifest.json"],
                "details": {},
            },
        }
    )


def _workspace_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _write_stage_artifact(relative: str, content: str):
    def operation(context):
        path = context.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return StageResult(artifacts=(relative,), message=f"Wrote {relative}.")

    return operation


def _review_workspace(tmp_path: Path) -> Path:
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    root = tmp_path / "project"
    manifest = create_manifest(
        name="Receipt Review",
        target_profile="receipt-review",
        sources=[
            ProjectSource(
                id="live-html-1",
                kind=SourceKind.LIVE_HTML,
                reference="https://source.example/",
            )
        ],
        agency_pack_name="agency",
        agency_pack_version="1.0.0",
        clock=lambda: now,
    )
    manifest.target = manifest.target.model_copy(
        update={
            "expected_base_url": "http://portal.test",
            "expected_portal_id": 7,
        }
    )
    initialize_workspace(root, manifest)
    engine = StageEngine(root)
    engine.execute(
        ProjectStage.ANALYZE,
        StageInputs(data={"mode": "offline"}),
        _write_stage_artifact("analysis/design-document.json", "analysis"),
    )
    engine.execute(
        ProjectStage.PLAN,
        StageInputs(files=(Path("analysis/design-document.json"),)),
        _write_stage_artifact("plans/composition-plan.json", "plan"),
    )
    approval = request_approval(
        root,
        gate=ApprovalGate.PORTAL_MUTATION,
        requested_by="Agency Operator",
    )
    resolve_approval(
        root,
        approval.id,
        approved=True,
        resolved_by="Agency Operator",
    )
    return root


def test_build_dry_run_emits_detached_zero_write_receipt(
    runner, monkeypatch
) -> None:
    receipt = _receipt()
    prepared = PreparedBuildReview(
        receipt=receipt,
        execution=_execution(),
        spec=SimpleNamespace(stage=ProjectStage.ASSETS),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        project_build_cmd, "prepare_next_build_review", lambda *args, **kwargs: prepared
    )

    result = runner.invoke(
        cli,
        ["project", "build", "workspace", "--dry-run", "--by", "Agency Operator", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "preview"
    assert payload["portal_mutated"] is False
    assert payload["workspace_mutated"] is False
    assert payload["receipt"] == receipt
    assert len(payload["executions"]) == 1


def test_real_receipt_preparation_is_deterministic_and_workspace_zero_write(
    tmp_path: Path, monkeypatch
) -> None:
    root = _review_workspace(tmp_path)
    before = _workspace_bytes(root)
    operation_calls = []

    def forbidden_operation(context):
        operation_calls.append(context)
        raise AssertionError("dry-run called the stage operation")

    monkeypatch.setattr(
        project_build_review, "preserve_project_theme", forbidden_operation
    )
    monkeypatch.setattr(
        project_build_review,
        "preview_preserve_project_theme",
        lambda workspace, manifest: {
            "schema_version": "1.0",
            "mode": "preserve",
            "target": {
                "profile": "receipt-review",
                "base_url": "http://portal.test",
                "portal_id": 7,
                "health_status": "ok",
                "dnn_version": "9",
                "vanjaro_version": "1",
                "user_name": "host",
            },
            "portal_actions": [],
            "local_writes": ["build/theme-result.json"],
        },
    )

    first = project_build_review.prepare_next_build_review(
        root,
        theme_mode="preserve",
        through="theme",
        page_mode="isolated",
        operator="Agency Operator",
    )
    second = project_build_review.prepare_next_build_review(
        root,
        theme_mode="preserve",
        through="theme",
        page_mode="isolated",
        operator="Agency Operator",
    )

    assert first.receipt == second.receipt
    assert first.receipt["stage"] == "theme"
    assert first.receipt["preview"]["local_writes"] == ["build/theme-result.json"]
    assert operation_calls == []
    assert _workspace_bytes(root) == before


def test_real_build_requires_all_action_time_authority(runner, monkeypatch) -> None:
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("prepare must not run")

    monkeypatch.setattr(project_build_cmd, "apply_build_review", forbidden)
    result = runner.invoke(
        cli,
        ["project", "build", "workspace", "--by", "Agency Operator", "--json"],
    )

    assert result.exit_code == 1
    assert called is False
    assert "--review-receipt" in json.loads(result.output)["message"]


def test_real_build_loads_receipt_and_applies_exactly_one_stage(
    runner, tmp_path: Path, monkeypatch
) -> None:
    receipt = _receipt()
    review_path = tmp_path / "build-review.json"
    review_path.write_text(json.dumps(receipt), encoding="utf-8")
    calls = []

    def apply(*args, **kwargs):
        calls.append(kwargs)
        return _execution(action="execute", status="completed")

    monkeypatch.setattr(project_build_cmd, "apply_build_review", apply)
    result = runner.invoke(
        cli,
        [
            "project",
            "build",
            "workspace",
            "--review-receipt",
            str(review_path),
            "--confirm-build",
            receipt["fingerprint"],
            "--by",
            "Agency Operator",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0]["reviewed_receipt"] == receipt
    assert len(json.loads(result.output)["executions"]) == 1


def test_apply_revalidates_before_and_after_authority_lock(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = _receipt()
    prepared = SimpleNamespace(
        receipt=receipt,
        spec=SimpleNamespace(stage=ProjectStage.ASSETS),
        manifest=SimpleNamespace(
            model_dump=lambda **kwargs: {"manifest": "locked"}
        ),
    )
    prepares = []

    def prepare(*args, **kwargs):
        prepares.append(kwargs)
        return prepared

    locks = []

    @contextmanager
    def lock(*args, **kwargs):
        locks.append(kwargs)
        yield {}

    executions = []

    class Engine:
        def __init__(self, root):
            self.root = root

        def execute(
            self,
            stage,
            inputs,
            operation,
            *,
            dry_run=False,
            expected_manifest_fingerprint=None,
            expected_input_fingerprint=None,
            pre_operation=None,
        ):
            if pre_operation is not None:
                pre_operation(SimpleNamespace())
            executions.append(
                (
                    stage,
                    dry_run,
                    expected_manifest_fingerprint,
                    expected_input_fingerprint,
                )
            )
            return _execution(action="execute", status="completed")

    prepared.spec.inputs = SimpleNamespace()  # type: ignore[attr-defined]
    prepared.spec.operation = lambda context: None  # type: ignore[attr-defined]
    prepared.spec.preview = (  # type: ignore[attr-defined]
        lambda root, manifest: project_build_review._raw_preview_from_receipt(receipt)
    )
    monkeypatch.setattr(project_build_review, "prepare_next_build_review", prepare)
    monkeypatch.setattr(project_build_review, "publish_operation_lock", lock)
    monkeypatch.setattr(project_build_review, "StageEngine", Engine)

    root = tmp_path / "workspace"
    root.mkdir()
    result = project_build_review.apply_build_review(
        root,
        reviewed_receipt=receipt,
        confirmation=receipt["fingerprint"],
        operator="Agency Operator",
        theme_mode="preserve",
        through="verify",
        page_mode="isolated",
    )

    assert result.status == "completed"
    assert len(prepares) == 2
    assert len(locks) == 1
    assert executions == [
        (
            ProjectStage.ASSETS,
            False,
            project_build_review.fingerprint_data({"manifest": "locked"}),
            "1" * 64,
        )
    ]
    transaction_path = (
        root
        / "history/build"
        / receipt["fingerprint"]
        / "transaction.json"
    )
    transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
    assert transaction["status"] == "completed"
    assert transaction["operator"] == "Agency Operator"


def test_apply_rejects_stale_receipt_before_lock(monkeypatch) -> None:
    receipt = _receipt()
    changed = dict(receipt)
    changed["fingerprint"] = "f" * 64
    monkeypatch.setattr(
        project_build_review,
        "prepare_next_build_review",
        lambda *args, **kwargs: SimpleNamespace(receipt=changed),
    )
    lock_called = False

    @contextmanager
    def forbidden_lock(*args, **kwargs):
        nonlocal lock_called
        lock_called = True
        yield {}

    monkeypatch.setattr(project_build_review, "publish_operation_lock", forbidden_lock)

    try:
        project_build_review.apply_build_review(
            Path("workspace"),
            reviewed_receipt=receipt,
            confirmation=receipt["fingerprint"],
            operator="Agency Operator",
            theme_mode="preserve",
            through="verify",
            page_mode="isolated",
        )
    except project_build_review.ProjectBuildReviewError as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("stale review was accepted")
    assert lock_called is False


def test_apply_rejects_drift_after_authority_lock(monkeypatch) -> None:
    receipt = _receipt()
    changed = _receipt()
    changed["preview"]["details"] = {"drift": True}
    changed = finalize_build_receipt(
        {key: value for key, value in changed.items() if key != "fingerprint"}
    )
    preparations = iter(
        [
            SimpleNamespace(
                receipt=receipt,
                spec=SimpleNamespace(
                    stage=ProjectStage.ASSETS,
                    inputs=SimpleNamespace(),
                    operation=lambda context: None,
                ),
            ),
            SimpleNamespace(
                receipt=changed,
                spec=SimpleNamespace(
                    stage=ProjectStage.ASSETS,
                    inputs=SimpleNamespace(),
                    operation=lambda context: None,
                ),
            ),
        ]
    )
    monkeypatch.setattr(
        project_build_review,
        "prepare_next_build_review",
        lambda *args, **kwargs: next(preparations),
    )
    locks = []

    @contextmanager
    def lock(*args, **kwargs):
        locks.append(kwargs)
        yield {}

    class ForbiddenEngine:
        def __init__(self, root):
            raise AssertionError("drifted receipt reached stage execution")

    monkeypatch.setattr(project_build_review, "publish_operation_lock", lock)
    monkeypatch.setattr(project_build_review, "StageEngine", ForbiddenEngine)

    with pytest.raises(project_build_review.ProjectBuildReviewError, match="stale"):
        project_build_review.apply_build_review(
            Path("workspace"),
            reviewed_receipt=receipt,
            confirmation=receipt["fingerprint"],
            operator="Agency Operator",
            theme_mode="preserve",
            through="verify",
            page_mode="isolated",
        )

    assert len(locks) == 1


def test_prepare_rejects_a_fully_resumed_ceiling(
    tmp_path: Path, monkeypatch
) -> None:
    root = _review_workspace(tmp_path)
    engine = StageEngine(root)
    monkeypatch.setattr(
        project_build_review,
        "preview_preserve_project_theme",
        lambda workspace, manifest: {
            "target": {
                "profile": "receipt-review",
                "base_url": "http://portal.test",
                "portal_id": 7,
                "health_status": "ok",
                "dnn_version": "9",
                "vanjaro_version": "1",
                "user_name": "host",
            },
            "portal_actions": [],
            "local_writes": ["build/theme-result.json"],
        },
    )
    spec = project_build_review.build_stage_spec(
        root,
        load_manifest(root),
        stage=ProjectStage.THEME,
        theme_mode="preserve",
        page_mode="isolated",
    )
    engine.execute(
        ProjectStage.THEME,
        spec.inputs,
        _write_stage_artifact("build/theme-result.json", "theme"),
    )

    with pytest.raises(
        project_build_review.ProjectBuildReviewError,
        match="no executable build stage",
    ):
        project_build_review.prepare_next_build_review(
            root,
            theme_mode="preserve",
            through="theme",
            page_mode="isolated",
            operator="Agency Operator",
        )
