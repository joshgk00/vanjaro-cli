"""Safety, recovery, and CLI contracts for reviewed site launch promotion."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from tests.test_portal_pages import _document
from tests.test_project_handoff import _refresh_stage_fingerprint, _write
from tests.test_project_publish import (
    _PublishClient,
    _Response,
    _approve as _approve_publish,
    _publish_workspace,
)
from vanjaro_cli.commands.project_cmd import project
from vanjaro_cli.design.serialization import write_design_document
from vanjaro_cli.orchestration.project_launch import (
    ProjectLaunchWorkflowError,
    apply_project_launch,
    prepare_project_launch,
)
from vanjaro_cli.orchestration.project_fidelity import ProjectFidelityError
from vanjaro_cli.orchestration.project_launch_plan import create_project_launch_plan
from vanjaro_cli.orchestration.project_publish import (
    apply_project_publish,
    prepare_project_publish,
)
from vanjaro_cli.portal.project_launch import (
    APPLY_LAUNCH,
    GET_LAUNCH_PAGE,
    PREVIEW_LAUNCH,
)
from vanjaro_cli.project import (
    ApprovalGate,
    ProjectStage,
    load_manifest,
    request_approval,
    resolve_approval,
    write_manifest,
)
from vanjaro_cli.project.launch_receipt import LAUNCH_REVIEW_PATH


NOW = datetime(2026, 8, 30, 16, 0, tzinfo=timezone.utc)
TOKEN_BEFORE = "11111111-1111-1111-1111-111111111111"
TOKEN_AFTER = "22222222-2222-2222-2222-222222222222"
_PASSING_FIDELITY = {"status": "scored", "passed": True, "legacy": False}


class _LaunchClient(_PublishClient):
    def __init__(self, base: _PublishClient, *, portal_id: int) -> None:
        super().__init__(base.pages, base.globals)
        self.portal_id = portal_id
        self.home_page_id = 1
        self.namespace_fingerprint = "a" * 64
        self.launch_pages = {
            101: {
                "pageId": 101,
                "metadataToken": TOKEN_BEFORE,
                "name": "agency-handoff-home",
                "title": "[Agency Draft] Home",
                "path": "/agency-handoff-home",
                "isVisible": False,
                "parentId": None,
                "tabOrder": 7,
                "cultureCode": "en-US",
            }
        }
        self.launch_preview_posts = 0
        self.launch_apply_posts = 0
        self.fail_preview = False
        self.fail_after_launch_apply = False
        self.preview_after_home: int | None = None
        self.apply_schema = "agency-launch-result-v1"
        self.apply_warnings: list[str] = []
        self.apply_reported_token: str | None = None

    def get(self, endpoint: str, params: dict | None = None) -> _Response:
        if endpoint == GET_LAUNCH_PAGE:
            self.gets.append((endpoint, copy.deepcopy(params)))
            page_id = int(params["pageId"])
            return _Response(
                {
                    "schemaVersion": "agency-launch-state-v1",
                    "supportsExactLaunch": True,
                    "portalId": self.portal_id,
                    "homePageId": self.home_page_id,
                    "page": self.launch_pages[page_id],
                }
            )
        return super().get(endpoint, params)

    def post(self, endpoint: str, json: dict) -> _Response:
        if endpoint == PREVIEW_LAUNCH:
            self.posts.append((endpoint, copy.deepcopy(json)))
            self.launch_preview_posts += 1
            if self.fail_preview:
                raise RuntimeError(
                    "preview failed at http://admin:secret@vanjarocli.local/?api_key=secret"
                )
            actions = []
            for intent in json["pages"]:
                before = copy.deepcopy(self.launch_pages[int(intent["pageId"])])
                after = copy.deepcopy(before)
                after.update(
                    {
                        "metadataToken": None,
                        "name": intent["desiredName"],
                        "title": intent["desiredTitle"],
                        "path": "/" + intent["desiredName"].replace(" ", ""),
                        "isVisible": intent["desiredVisible"],
                    }
                )
                actions.append({"before": before, "after": after})
            desired_home = (
                self.home_page_id
                if json["preserveCurrentHome"]
                else int(json["desiredHomePageId"])
            )
            if self.preview_after_home is not None:
                desired_home = self.preview_after_home
            return _Response(
                {
                    "schemaVersion": "agency-launch-preview-v1",
                    "supportsExactLaunch": True,
                    "portalId": self.portal_id,
                    "namespaceFingerprint": self.namespace_fingerprint,
                    "actions": actions,
                    "home": {
                        "beforePageId": self.home_page_id,
                        "afterPageId": desired_home,
                    },
                    "warnings": ["Temporary draft routes are not retained."],
                }
            )
        if endpoint == APPLY_LAUNCH:
            self.posts.append((endpoint, copy.deepcopy(json)))
            self.launch_apply_posts += 1
            assert json["expectedNamespaceFingerprint"] == self.namespace_fingerprint
            assert json["expectedHomePageId"] == self.home_page_id
            for action in json["actions"]:
                page_id = int(action["before"]["pageId"])
                assert action["before"] == self.launch_pages[page_id]
            for action in json["actions"]:
                page_id = int(action["before"]["pageId"])
                self.launch_pages[page_id] = {
                    **copy.deepcopy(action["after"]),
                    "metadataToken": TOKEN_AFTER,
                }
            self.home_page_id = int(json["desiredHomePageId"])
            if self.fail_after_launch_apply:
                self.fail_after_launch_apply = False
                raise RuntimeError("injected unknown launch outcome")
            return _Response(
                {
                    "schemaVersion": self.apply_schema,
                    "supportsExactLaunch": True,
                    "portalId": self.portal_id,
                    "homePageId": self.home_page_id,
                    "pages": [
                        {
                            **copy.deepcopy(page),
                            "metadataToken": self.apply_reported_token
                            or page["metadataToken"],
                        }
                        for page in self.launch_pages.values()
                    ],
                    "warnings": self.apply_warnings,
                }
            )
        return super().post(endpoint, json)


def _launch_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, _LaunchClient]:
    root, base, portal = _publish_workspace(tmp_path)
    design_path = root / "plans/resolved-design-document.json"
    write_design_document(design_path, _document())
    manifest = load_manifest(root)
    manifest.stages[ProjectStage.PLAN].artifacts.append(
        "plans/resolved-design-document.json"
    )
    write_manifest(root, manifest)
    _refresh_stage_fingerprint(root, ProjectStage.PLAN)

    client = _LaunchClient(base, portal_id=portal.portal_id)
    _set_fidelity(monkeypatch, report=_PASSING_FIDELITY, blockers=[])
    monkeypatch.setattr(
        "vanjaro_cli.orchestration.project_publish.verify_project_portal",
        lambda manifest: (client, portal),
    )
    monkeypatch.setattr(
        "vanjaro_cli.orchestration.project_launch.verify_project_portal",
        lambda manifest: (client, portal),
    )
    publish = prepare_project_publish(root, clock=lambda: NOW)["receipt"]
    publish_approval = _approve_publish(root, publish["fingerprint"])
    apply_project_publish(
        root,
        receipt_fingerprint=publish["fingerprint"],
        approval_id=publish_approval,
        confirmation=publish["fingerprint"],
        published_by="publisher",
        clock=lambda: NOW,
    )
    create_project_launch_plan(
        root,
        home_page_key="home",
        preserve_current_home=False,
        clock=lambda: NOW,
    )
    return root, client


def _set_fidelity(
    monkeypatch: pytest.MonkeyPatch, *, report: dict, blockers: list[str]
) -> None:
    monkeypatch.setattr(
        "vanjaro_cli.orchestration.project_launch.evaluate_project_fidelity",
        lambda root, manifest: (report, blockers),
    )


def _approve_launch(root: Path, fingerprint: str) -> str:
    requested = request_approval(
        root,
        gate=ApprovalGate.LAUNCH,
        requested_by="launch-reviewer",
        fingerprint=fingerprint,
        clock=lambda: NOW,
    )
    return resolve_approval(
        root,
        requested.id,
        approved=True,
        resolved_by="launch-approver",
        clock=lambda: NOW,
    ).id


def _apply(root: Path, receipt: dict, approval_id: str) -> dict:
    return apply_project_launch(
        root,
        receipt_fingerprint=receipt["fingerprint"],
        approval_id=approval_id,
        confirmation=receipt["fingerprint"],
        home_confirmation=101,
        launched_by="operator",
        clock=lambda: NOW,
    )


def test_launch_prepare_dry_run_is_read_only_and_zero_workspace_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    before = (root / "project.json").read_bytes()

    result = prepare_project_launch(root, dry_run=True)

    assert result["portal_mutated"] is False
    assert result["workspace_mutated"] is False
    assert client.launch_preview_posts == 1
    assert client.launch_apply_posts == 0
    assert (root / "project.json").read_bytes() == before
    assert not (root / LAUNCH_REVIEW_PATH).exists()


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("receipt_fingerprint", "0" * 64, "confirmation"),
        ("confirmation", "0" * 64, "confirmation"),
        ("approval_id", "approval-missing", "approval"),
        ("home_confirmation", None, "home-page acknowledgement"),
    ],
)
def test_launch_apply_requires_every_exact_authority_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    match: str,
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    receipt = prepare_project_launch(root, clock=lambda: NOW)["receipt"]
    approval_id = _approve_launch(root, receipt["fingerprint"])
    values = {
        "receipt_fingerprint": receipt["fingerprint"],
        "approval_id": approval_id,
        "confirmation": receipt["fingerprint"],
        "home_confirmation": 101,
        "launched_by": "operator",
    }
    values[field] = value

    with pytest.raises(ProjectLaunchWorkflowError, match=match):
        apply_project_launch(root, **values)

    assert client.launch_apply_posts == 0


def test_launch_batch_applies_once_and_completed_reentry_is_get_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    receipt = prepare_project_launch(root, clock=lambda: NOW)["receipt"]
    approval_id = _approve_launch(root, receipt["fingerprint"])

    first = _apply(root, receipt, approval_id)
    second = _apply(root, receipt, approval_id)

    assert first["status"] == "completed"
    assert second["status"] == "resumed"
    assert client.launch_apply_posts == 1
    assert client.launch_pages[101]["name"] == "Home"
    assert client.launch_pages[101]["isVisible"] is True
    assert client.home_page_id == 101


def test_prepare_refuses_launch_when_visual_fidelity_does_not_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    _set_fidelity(
        monkeypatch,
        report={"status": "not_scored", "passed": False},
        blockers=["page home: visual fidelity was not scored"],
    )

    with pytest.raises(ProjectLaunchWorkflowError) as excinfo:
        prepare_project_launch(root, dry_run=True)

    assert excinfo.value.code == "visual_fidelity_failed"
    assert "not scored" in excinfo.value.detail
    assert client.launch_preview_posts == 0
    assert client.launch_apply_posts == 0


def test_apply_refuses_when_fidelity_evidence_changed_after_prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    receipt = prepare_project_launch(root, clock=lambda: NOW)["receipt"]
    approval_id = _approve_launch(root, receipt["fingerprint"])
    _set_fidelity(
        monkeypatch,
        report={**_PASSING_FIDELITY, "overall_score": 88.0},
        blockers=[],
    )

    with pytest.raises(ProjectLaunchWorkflowError) as excinfo:
        _apply(root, receipt, approval_id)

    assert excinfo.value.code == "visual_fidelity_stale"
    assert client.launch_apply_posts == 0


def test_apply_refuses_when_fidelity_fails_after_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    receipt = prepare_project_launch(root, clock=lambda: NOW)["receipt"]
    approval_id = _approve_launch(root, receipt["fingerprint"])
    _set_fidelity(
        monkeypatch,
        report={"status": "scored", "passed": False},
        blockers=["page home: overall 61.0 is below the draft minimum 75"],
    )

    with pytest.raises(ProjectLaunchWorkflowError) as excinfo:
        _apply(root, receipt, approval_id)

    assert excinfo.value.code == "visual_fidelity_failed"
    assert client.launch_apply_posts == 0


def test_prepare_refuses_launch_on_legacy_single_file_fidelity_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    _set_fidelity(
        monkeypatch,
        report={"status": "scored", "passed": True, "legacy": True},
        blockers=[],
    )

    with pytest.raises(ProjectLaunchWorkflowError) as excinfo:
        prepare_project_launch(root, dry_run=True)

    assert excinfo.value.code == "visual_fidelity_failed"
    assert "per-page capture evidence" in excinfo.value.detail
    assert client.launch_preview_posts == 0


def test_prepare_reports_unreadable_fidelity_evidence_as_a_launch_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)

    def unreadable(root: Path, manifest: object) -> None:
        raise ProjectFidelityError("qa/fidelity-evidence.json must contain an object")

    monkeypatch.setattr(
        "vanjaro_cli.orchestration.project_launch.evaluate_project_fidelity", unreadable
    )

    with pytest.raises(ProjectLaunchWorkflowError) as excinfo:
        prepare_project_launch(root, dry_run=True)

    assert excinfo.value.code == "visual_fidelity_failed"
    assert "must contain an object" in excinfo.value.detail
    assert client.launch_preview_posts == 0


def test_completed_reentry_ignores_evidence_recaptured_after_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    receipt = prepare_project_launch(root, clock=lambda: NOW)["receipt"]
    approval_id = _approve_launch(root, receipt["fingerprint"])
    _apply(root, receipt, approval_id)
    _set_fidelity(
        monkeypatch,
        report={**_PASSING_FIDELITY, "overall_score": 93.0},
        blockers=[],
    )

    second = _apply(root, receipt, approval_id)

    assert second["status"] == "resumed"
    assert client.launch_apply_posts == 1


def test_apply_result_tokens_and_warnings_are_verified_and_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    receipt = prepare_project_launch(root, clock=lambda: NOW)["receipt"]
    approval_id = _approve_launch(root, receipt["fingerprint"])
    client.apply_warnings = ["DNN lifecycle reconciliation is required."]

    _apply(root, receipt, approval_id)

    result = json.loads((root / "qa/launch-result.json").read_text(encoding="utf-8"))
    journal = json.loads(
        (
            root
            / "history/launch"
            / receipt["fingerprint"]
            / "transaction.json"
        ).read_text(encoding="utf-8")
    )
    assert result["warnings"][-1] == "DNN lifecycle reconciliation is required."
    assert journal["apply_warnings"] == ["DNN lifecycle reconciliation is required."]
    assert journal["actions"][0]["after"]["metadata_token"] == TOKEN_AFTER


def test_malformed_apply_result_is_not_reported_as_success_and_retry_is_get_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    receipt = prepare_project_launch(root, clock=lambda: NOW)["receipt"]
    approval_id = _approve_launch(root, receipt["fingerprint"])
    client.apply_schema = "unexpected-result"

    with pytest.raises(ProjectLaunchWorkflowError, match="interrupted"):
        _apply(root, receipt, approval_id)
    client.apply_schema = "agency-launch-result-v1"
    result = _apply(root, receipt, approval_id)

    assert result["status"] == "completed"
    assert client.launch_apply_posts == 1


def test_unknown_batch_outcome_is_adopted_without_duplicate_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    receipt = prepare_project_launch(root, clock=lambda: NOW)["receipt"]
    approval_id = _approve_launch(root, receipt["fingerprint"])
    client.fail_after_launch_apply = True

    with pytest.raises(ProjectLaunchWorkflowError, match="interrupted"):
        _apply(root, receipt, approval_id)
    result = _apply(root, receipt, approval_id)

    assert result["status"] == "completed"
    assert client.launch_apply_posts == 1
    journal = json.loads(
        (
            root
            / "history/launch"
            / receipt["fingerprint"]
            / "transaction.json"
        ).read_text(encoding="utf-8")
    )
    assert journal["status"] == "completed"
    assert journal["actions"][0]["after"]["metadata_token"] == TOKEN_AFTER


def test_completed_reentry_rejects_live_drift_without_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    receipt = prepare_project_launch(root, clock=lambda: NOW)["receipt"]
    approval_id = _approve_launch(root, receipt["fingerprint"])
    _apply(root, receipt, approval_id)
    client.launch_pages[101]["title"] = "Operator changed title"

    with pytest.raises(ProjectLaunchWorkflowError, match="drifted"):
        _apply(root, receipt, approval_id)

    assert client.launch_apply_posts == 1


def test_tampered_interrupted_journal_fails_closed_without_duplicate_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    receipt = prepare_project_launch(root, clock=lambda: NOW)["receipt"]
    approval_id = _approve_launch(root, receipt["fingerprint"])
    client.fail_after_launch_apply = True
    with pytest.raises(ProjectLaunchWorkflowError):
        _apply(root, receipt, approval_id)
    path = root / "history/launch" / receipt["fingerprint"] / "transaction.json"
    journal = json.loads(path.read_text(encoding="utf-8"))
    journal["actions"][0]["before"]["name"] = "tampered"
    _write(path, journal)

    with pytest.raises(ValueError, match="before-state was modified"):
        _apply(root, receipt, approval_id)

    assert client.launch_apply_posts == 1


def test_stale_plan_source_does_not_call_preview_or_adopt_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    design_path = root / "plans/resolved-design-document.json"
    payload = json.loads(design_path.read_text(encoding="utf-8"))
    payload["pages"][0]["title"] = "Changed"
    _write(design_path, payload)

    with pytest.raises(ProjectLaunchWorkflowError, match="changed after launch planning"):
        prepare_project_launch(root)
    assert client.launch_preview_posts == 0
    assert not (root / LAUNCH_REVIEW_PATH).exists()


def test_preview_transport_failure_is_safe_and_does_not_adopt_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    client.fail_preview = True

    result = runner.invoke(project, ["launch", "prepare", str(root), "--json"])

    assert result.exit_code != 0
    assert "launch preview request did not complete" in result.output
    assert "admin:secret" not in result.output
    assert "api_key=secret" not in result.output
    assert client.launch_preview_posts == 1
    assert client.launch_apply_posts == 0
    assert not (root / LAUNCH_REVIEW_PATH).exists()

    client.fail_preview = False
    retry = runner.invoke(project, ["launch", "prepare", str(root), "--json"])
    assert retry.exit_code == 0, retry.output
    assert (root / LAUNCH_REVIEW_PATH).is_file()


def test_preview_cannot_change_reviewed_home_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    client.preview_after_home = 999

    with pytest.raises(ProjectLaunchWorkflowError, match="home-page decision"):
        prepare_project_launch(root)

    assert client.launch_apply_posts == 0
    assert not (root / LAUNCH_REVIEW_PATH).exists()


def test_preview_cannot_change_preserved_home_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    client.home_page_id = 999
    create_project_launch_plan(
        root,
        home_page_key=None,
        preserve_current_home=True,
        clock=lambda: NOW,
    )
    client.preview_after_home = 101

    with pytest.raises(ProjectLaunchWorkflowError, match="home-page decision"):
        prepare_project_launch(root)

    assert client.launch_apply_posts == 0
    assert not (root / LAUNCH_REVIEW_PATH).exists()


def test_preserve_unmanaged_current_home_is_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    client.home_page_id = 999
    create_project_launch_plan(
        root,
        home_page_key=None,
        preserve_current_home=True,
        clock=lambda: NOW,
    )
    receipt = prepare_project_launch(root, clock=lambda: NOW)["receipt"]
    approval_id = _approve_launch(root, receipt["fingerprint"])

    result = apply_project_launch(
        root,
        receipt_fingerprint=receipt["fingerprint"],
        approval_id=approval_id,
        confirmation=receipt["fingerprint"],
        home_confirmation=None,
        launched_by="operator",
        clock=lambda: NOW,
    )

    assert result["status"] == "completed"
    assert client.home_page_id == 999
    assert client.launch_apply_posts == 1


def test_mixed_atomic_batch_state_fails_closed_without_apply_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)
    receipt = prepare_project_launch(root, clock=lambda: NOW)["receipt"]
    approval_id = _approve_launch(root, receipt["fingerprint"])
    # Home is after-state while the managed page is still before-state. The
    # server contract is atomic, so this is integrity drift, never a partial
    # batch for the client to continue.
    client.home_page_id = 101

    with pytest.raises(ProjectLaunchWorkflowError, match="interrupted"):
        _apply(root, receipt, approval_id)

    journal = json.loads(
        (
            root
            / "history/launch"
            / receipt["fingerprint"]
            / "transaction.json"
        ).read_text(encoding="utf-8")
    )
    assert journal["batch_attempted"] is False
    assert client.launch_apply_posts == 0


def test_launch_cli_plan_prepare_and_apply_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner
) -> None:
    root, client = _launch_workspace(tmp_path, monkeypatch)

    plan_result = runner.invoke(
        project,
        ["launch", "plan", str(root), "--home-page", "home", "--json"],
    )
    prepare_result = runner.invoke(
        project, ["launch", "prepare", str(root), "--json"]
    )
    help_result = runner.invoke(project, ["launch", "apply", "--help"])

    assert plan_result.exit_code == 0, plan_result.output
    assert json.loads(plan_result.output)["portal_mutated"] is False
    assert prepare_result.exit_code == 0, prepare_result.output
    assert json.loads(prepare_result.output)["status"] == "ready_for_review"
    assert help_result.exit_code == 0
    assert "--confirm-launch" in help_result.output
    assert "--confirm-home" in help_result.output
    assert client.launch_apply_posts == 0
