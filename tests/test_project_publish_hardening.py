"""Adversarial safety checks for reviewed project publication."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from tests.test_project_publish import (
    APPLIED_AT,
    _PublishClient,
    _Response,
    _approve,
    _patch_portal,
    _publish_workspace,
    _write,
)
from vanjaro_cli.orchestration.project_publish import (
    ProjectPublishError,
    apply_project_publish,
    prepare_project_publish,
)
from vanjaro_cli.portal.project_publication import GET_GLOBAL, PUBLISH_PAGE
from vanjaro_cli.project import ProjectStage, StageStatus, load_manifest
from vanjaro_cli.orchestration.project_launch_plan import (
    _read_object as read_launch_plan_object,
)
from vanjaro_cli.orchestration.project_launch_state import (
    _read_object as read_launch_object,
)
from vanjaro_cli.orchestration.project_publish_state import read_publish_object
from vanjaro_cli.project.launch_receipt import load_launch_payload
from vanjaro_cli.project.publish_lock import PUBLISH_LOCK_PATH, inspect_publish_lock
from vanjaro_cli.project.publish_receipt import (
    _require_publish_ready_handoff,
    load_publish_review,
)


def _authority_readers(root: Path):
    return (
        ("publish review", root / "publish-review.json", load_publish_review),
        (
            "maintenance scorecard",
            root / "qa/maintenance-scorecard.json",
            lambda _path: _require_publish_ready_handoff(root, {}),
        ),
        (
            "launch payload",
            root / "launch-review.json",
            lambda path: load_launch_payload(path, label="launch review receipt"),
        ),
        (
            "launch plan",
            root / "launch-plan.json",
            lambda path: load_launch_payload(path, label="launch plan"),
        ),
        ("launch plan input", root / "page-manifest.json", read_launch_plan_object),
        ("publish journal", root / "publish-transaction.json", read_publish_object),
        ("launch journal", root / "launch-transaction.json", read_launch_object),
        (
            "publish lock",
            root / PUBLISH_LOCK_PATH,
            lambda _path: inspect_publish_lock(root),
        ),
    )


@pytest.mark.parametrize(
    "label",
    [
        "publish review",
        "maintenance scorecard",
        "launch payload",
        "launch plan",
        "launch plan input",
        "publish journal",
        "launch journal",
        "publish lock",
    ],
)
def test_all_authority_readers_reject_duplicate_keys(tmp_path: Path, label: str) -> None:
    selected = next(item for item in _authority_readers(tmp_path) if item[0] == label)
    _, path, reader = selected
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = b'{"schema_version":"x","schema_version":"y"}\n'
    path.write_bytes(raw)

    with pytest.raises(ValueError, match="duplicate JSON object key"):
        reader(path)

    assert path.read_bytes() == raw


@pytest.mark.parametrize(
    "label",
    [
        "publish review",
        "maintenance scorecard",
        "launch payload",
        "launch plan",
        "launch plan input",
        "publish journal",
        "launch journal",
        "publish lock",
    ],
)
def test_all_authority_readers_reject_nonfinite(tmp_path: Path, label: str) -> None:
    selected = next(item for item in _authority_readers(tmp_path) if item[0] == label)
    _, path, reader = selected
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = b'{"authority":NaN}\n'
    path.write_bytes(raw)

    with pytest.raises(ValueError, match="non-finite JSON number"):
        reader(path)

    assert path.read_bytes() == raw


def _apply(root: Path, receipt: dict, approval_id: str) -> dict:
    return apply_project_publish(
        root,
        receipt_fingerprint=receipt["fingerprint"],
        approval_id=approval_id,
        confirmation=receipt["fingerprint"],
        published_by="operator",
        clock=lambda: APPLIED_AT,
    )


def _file_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_completed_reentry_reconciles_live_state_before_resuming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    _patch_portal(monkeypatch, client, portal)
    receipt = prepare_project_publish(root)["receipt"]
    approval_id = _approve(root, receipt["fingerprint"])
    _apply(root, receipt, approval_id)
    post_count = len(client.posts)
    client.pages[101]["isPublished"] = False

    with pytest.raises(ProjectPublishError, match="published_state_drifted"):
        _apply(root, receipt, approval_id)

    assert len(client.posts) == post_count


class _FinalReadbackDriftClient(_PublishClient):
    def __init__(self, pages: dict[int, dict], globals_: dict[str, dict]) -> None:
        super().__init__(pages, globals_)
        self.drifted = False

    def get(self, endpoint: str, params: dict | None = None) -> _Response:
        if (
            endpoint == GET_GLOBAL
            and not self.drifted
            and all(item["isPublished"] for item in self.pages.values())
            and all(item["isPublished"] for item in self.globals.values())
        ):
            first = next(iter(self.globals.values()))
            first["isPublished"] = False
            self.drifted = True
        return super().get(endpoint, params)


def test_final_whole_set_readback_blocks_false_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, original, portal = _publish_workspace(tmp_path)
    client = _FinalReadbackDriftClient(
        copy.deepcopy(original.pages), copy.deepcopy(original.globals)
    )
    _patch_portal(monkeypatch, client, portal)
    receipt = prepare_project_publish(root)["receipt"]
    approval_id = _approve(root, receipt["fingerprint"])

    with pytest.raises(ValueError, match="publication was interrupted"):
        _apply(root, receipt, approval_id)

    assert len(client.posts) == 3
    assert not (root / "qa/publish-result.json").exists()
    assert load_manifest(root).stages[ProjectStage.PUBLISH].status == StageStatus.FAILED
    journal = json.loads(
        (
            root
            / "history/publish"
            / receipt["fingerprint"]
            / "transaction.json"
        ).read_text(encoding="utf-8")
    )
    assert journal["status"] == "interrupted"


def test_unknown_post_outcome_is_adopted_without_duplicate_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    _patch_portal(monkeypatch, client, portal)
    receipt = prepare_project_publish(root)["receipt"]
    approval_id = _approve(root, receipt["fingerprint"])
    client.fail_after_mutation_post = 3

    with pytest.raises(ValueError, match="publication was interrupted"):
        _apply(root, receipt, approval_id)
    assert client.pages[101]["isPublished"] is True
    assert len(client.posts) == 3
    client.fail_after_mutation_post = None

    result = _apply(root, receipt, approval_id)

    assert result["status"] == "completed"
    assert len(client.posts) == 3


def test_exact_prepublished_objects_are_reconciled_without_duplicate_posts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    for detail in client.globals.values():
        detail["isPublished"] = True
    client.pages[101]["isPublished"] = True
    _patch_portal(monkeypatch, client, portal)
    receipt = prepare_project_publish(root)["receipt"]
    approval_id = _approve(root, receipt["fingerprint"])

    result = _apply(root, receipt, approval_id)

    assert result["status"] == "completed"
    assert result["portal_mutated"] is False
    assert client.posts == []
    journal = json.loads(
        (
            root / "history/publish" / receipt["fingerprint"] / "transaction.json"
        ).read_text(encoding="utf-8")
    )
    assert all(entry["status"] == "committed" for entry in journal["actions"])
    assert all(entry["before"] is None for entry in journal["actions"])


@pytest.mark.parametrize("value", ["false", 1, None, {}, []])
def test_prepare_rejects_non_boolean_publication_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: object,
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    first = next(iter(client.globals.values()))
    first["isPublished"] = value
    _patch_portal(monkeypatch, client, portal)

    with pytest.raises(ProjectPublishError, match="must be a boolean"):
        prepare_project_publish(root)

    assert client.posts == []


def test_prepare_rejects_non_string_page_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    client.pages[101]["contentHtml"] = {"unexpected": True}
    _patch_portal(monkeypatch, client, portal)

    with pytest.raises(ProjectPublishError, match="contentHtml must be a string"):
        prepare_project_publish(root)


def test_prepare_rejects_missing_global_project_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    first = next(iter(client.globals.values()))
    first["contentJSON"][0]["attributes"].pop("data-agency-project")
    _patch_portal(monkeypatch, client, portal)

    with pytest.raises(ProjectPublishError, match="ownership marker"):
        prepare_project_publish(root)


def test_prepare_refuses_server_without_exact_version_publish_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    next(iter(client.globals.values())).pop("supportsExactVersionPublish")
    _patch_portal(monkeypatch, client, portal)

    with pytest.raises(ProjectPublishError, match="exact-version publication support"):
        prepare_project_publish(root)

    assert client.posts == []


def test_journal_impossible_transition_fails_before_retry_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    _patch_portal(monkeypatch, client, portal)
    receipt = prepare_project_publish(root)["receipt"]
    approval_id = _approve(root, receipt["fingerprint"])
    client.fail_post = 3
    with pytest.raises(ValueError):
        _apply(root, receipt, approval_id)
    post_count = len(client.posts)
    journal_path = (
        root / "history/publish" / receipt["fingerprint"] / "transaction.json"
    )
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["actions"][2]["before"] = None
    _write(journal_path, journal)
    client.fail_post = None

    with pytest.raises(ValueError, match="journal_tampered"):
        _apply(root, receipt, approval_id)

    assert len(client.posts) == post_count


def test_failed_authority_is_zero_write_and_zero_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    _patch_portal(monkeypatch, client, portal)
    receipt = prepare_project_publish(root)["receipt"]
    approval_id = _approve(root, receipt["fingerprint"])
    before = _file_snapshot(root)

    with pytest.raises(ProjectPublishError, match="confirmation_mismatch"):
        apply_project_publish(
            root,
            receipt_fingerprint=receipt["fingerprint"],
            approval_id=approval_id,
            confirmation="0" * 64,
            published_by="operator",
        )

    assert _file_snapshot(root) == before
    assert client.posts == []
    assert not (root / ".project-publish.lock").exists()


class _SecretFailureClient(_PublishClient):
    def post(self, endpoint: str, json: dict) -> _Response:
        if endpoint == PUBLISH_PAGE:
            self.posts.append((endpoint, copy.deepcopy(json)))
            raise RuntimeError("Authorization: Bearer supersecret password=hunter2")
        return super().post(endpoint, json)


def test_raw_portal_secret_never_reaches_manifest_or_cli_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, original, portal = _publish_workspace(tmp_path)
    client = _SecretFailureClient(
        copy.deepcopy(original.pages), copy.deepcopy(original.globals)
    )
    _patch_portal(monkeypatch, client, portal)
    receipt = prepare_project_publish(root)["receipt"]
    approval_id = _approve(root, receipt["fingerprint"])

    with pytest.raises(ValueError) as failure:
        _apply(root, receipt, approval_id)

    assert "supersecret" not in str(failure.value)
    assert "hunter2" not in str(failure.value)
    manifest_text = (root / "project.json").read_text(encoding="utf-8")
    assert "supersecret" not in manifest_text
    assert "hunter2" not in manifest_text
    journal_text = (
        root / "history/publish" / receipt["fingerprint"] / "transaction.json"
    ).read_text(encoding="utf-8")
    assert "supersecret" not in journal_text
    assert "hunter2" not in journal_text
    assert "[REDACTED]" in journal_text


def test_receipt_adoption_restores_manifest_after_post_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    _patch_portal(monkeypatch, client, portal)
    before = (root / "project.json").read_bytes()
    from vanjaro_cli.orchestration import project_publish_state

    original_write = project_publish_state.write_manifest

    def write_then_fail(*args, **kwargs):
        original_write(*args, **kwargs)
        raise OSError("injected post-replace failure")

    monkeypatch.setattr(project_publish_state, "write_manifest", write_then_fail)

    with pytest.raises(OSError, match="post-replace"):
        prepare_project_publish(root)

    assert (root / "project.json").read_bytes() == before
    assert not (root / "qa/publish-review.json").exists()
    assert client.posts == []
