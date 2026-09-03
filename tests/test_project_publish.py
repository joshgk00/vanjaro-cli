"""Safety and recovery contracts for reviewed project publication."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from tests.test_project_handoff import (
    _refresh_stage_fingerprint,
    _workspace,
    _write,
)
from vanjaro_cli.commands.project_cmd import project
from vanjaro_cli.orchestration.portal_identity import VerifiedPortal
from vanjaro_cli.orchestration.project_handoff import generate_project_handoff
from vanjaro_cli.orchestration.project_publish import (
    ProjectPublishError,
    apply_project_publish,
    prepare_project_publish,
)
from vanjaro_cli.portal.page_composition import page_content_hash
from vanjaro_cli.portal.project_publication import (
    GET_GLOBAL,
    GET_PAGE,
    PUBLISH_GLOBAL,
    PUBLISH_PAGE,
)
from vanjaro_cli.project import (
    ApprovalGate,
    ProjectApprovalError,
    ProjectStage,
    StageStatus,
    load_manifest,
    request_approval,
    resolve_approval,
)
from vanjaro_cli.project.publish_receipt import (
    PUBLISH_REVIEW_PATH,
    PublishReceiptError,
    current_publish_review,
)


APPLIED_AT = datetime(2026, 8, 30, 15, 0, tzinfo=timezone.utc)


class _Response:
    def __init__(self, value: object) -> None:
        self.value = value

    def json(self) -> object:
        return copy.deepcopy(self.value)


class _PublishClient:
    def __init__(self, pages: dict[int, dict], globals_: dict[str, dict]) -> None:
        self.pages = pages
        self.globals = globals_
        self.gets: list[tuple[str, dict | None]] = []
        self.posts: list[tuple[str, dict]] = []
        self.fail_post: int | None = None
        self.fail_after_mutation_post: int | None = None

    def get(self, endpoint: str, params: dict | None = None) -> _Response:
        self.gets.append((endpoint, params))
        if endpoint == GET_GLOBAL:
            return _Response(self.globals[str(params["guid"])])
        if endpoint == GET_PAGE:
            return _Response(self.pages[int(params["pageId"])])
        raise AssertionError(f"unexpected GET {endpoint}")

    def post(self, endpoint: str, json: dict) -> _Response:
        self.posts.append((endpoint, copy.deepcopy(json)))
        call_number = len(self.posts)
        if self.fail_post == call_number:
            raise RuntimeError(f"injected publish failure {self.fail_post}")
        if endpoint == PUBLISH_GLOBAL:
            detail = self.globals[str(json["guid"])]
            assert json["version"] == detail["version"]
            detail["isPublished"] = True
            if self.fail_after_mutation_post == call_number:
                raise RuntimeError(f"injected unknown outcome {call_number}")
            return _Response({"guid": json["guid"], "published": True})
        if endpoint == PUBLISH_PAGE:
            detail = self.pages[int(json["pageId"])]
            assert json["version"] == detail["version"]
            detail["isPublished"] = True
            if self.fail_after_mutation_post == call_number:
                raise RuntimeError(f"injected unknown outcome {call_number}")
            return _Response({"pageId": json["pageId"], "isPublished": True})
        raise AssertionError(f"unexpected POST {endpoint}")


def _global_hash(components: list[dict], styles: list[dict]) -> str:
    raw = json.dumps(
        {"content_json": components, "style_json": styles},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _publish_workspace(tmp_path: Path) -> tuple[Path, _PublishClient, VerifiedPortal]:
    root = _workspace(tmp_path)
    page_components = [
        {
            "type": "default",
            "attributes": {
                "id": "agency-page",
                "data-agency-page": "home",
                "data-agency-project": "agency-handoff",
            },
            "components": [{"type": "text", "content": "Published home"}],
        }
    ]
    page_styles: list[dict] = []
    page_html = '<div id="agency-page" data-agency-page="home">Published home</div>'
    page_hash = page_content_hash(page_components, page_styles, page_html)
    page_manifest_path = root / "build/global-page-manifest.json"
    page_manifest = json.loads(page_manifest_path.read_text(encoding="utf-8"))
    page_manifest["pages"][0].update(
        {
            "key": "home",
            "desired_hash": page_hash,
            "observed_version": 3,
        }
    )
    _write(page_manifest_path, page_manifest)

    global_manifest_path = root / "build/global-block-manifest.json"
    global_manifest = json.loads(global_manifest_path.read_text(encoding="utf-8"))
    globals_: dict[str, dict] = {}
    for index, record in enumerate(global_manifest["blocks"], start=1):
        guid = f"00000000-0000-0000-0000-00000000000{index}"
        components = [
            {
                "type": "default",
                "attributes": {
                    "id": f"global-{record['kind']}",
                    "data-agency-project": "agency-handoff",
                },
                "components": [],
            }
        ]
        styles: list[dict] = []
        desired_hash = _global_hash(components, styles)
        record.update(
            {
                "guid": guid,
                "desired_hash": desired_hash,
                "observed_version": 2,
            }
        )
        globals_[guid] = {
            "guid": guid,
            "kind": record["kind"],
            "version": 2,
            "isPublished": False,
            "supportsExactVersionPublish": True,
            "contentJSON": components,
            "styleJSON": styles,
        }
    _write(global_manifest_path, global_manifest)
    _refresh_stage_fingerprint(root, ProjectStage.GLOBAL_BLOCKS)
    generate_project_handoff(root)

    pages = {
        101: {
            "pageId": 101,
            "tabId": 101,
            "version": 3,
            "isPublished": False,
            "supportsExactVersionPublish": True,
            "contentJSON": page_components,
            "styleJSON": page_styles,
            "contentHtml": page_html,
        }
    }
    client = _PublishClient(pages, globals_)
    portal = VerifiedPortal(
        profile="client-one",
        base_url="https://vanjaro.example/client-one",
        portal_id=7,
        health_status="ok",
        dnn_version="9.13.7",
        vanjaro_version="1.3.0",
        user_name="host",
    )
    return root, client, portal


def _patch_portal(
    monkeypatch: pytest.MonkeyPatch,
    client: _PublishClient,
    portal: VerifiedPortal,
) -> None:
    monkeypatch.setattr(
        "vanjaro_cli.orchestration.project_publish.verify_project_portal",
        lambda manifest: (client, portal),
    )


def _approve(root: Path, fingerprint: str) -> str:
    approval = request_approval(
        root,
        gate=ApprovalGate.PUBLISH,
        requested_by="reviewer",
        fingerprint=fingerprint,
        clock=lambda: APPLIED_AT,
    )
    resolved = resolve_approval(
        root,
        approval.id,
        approved=True,
        resolved_by="publisher-approver",
        clock=lambda: APPLIED_AT,
    )
    return resolved.id


def test_publish_prepare_dry_run_is_get_only_and_zero_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    before = (root / "project.json").read_bytes()
    _patch_portal(monkeypatch, client, portal)

    result = prepare_project_publish(root, dry_run=True)

    assert result["dry_run"] is True
    assert result["portal_mutated"] is False
    assert result["workspace_mutated"] is False
    assert len(result["receipt"]["actions"]) == 3
    assert client.gets
    assert client.posts == []
    assert (root / "project.json").read_bytes() == before
    assert not (root / PUBLISH_REVIEW_PATH).exists()


def test_prepare_adopts_deterministic_receipt_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    _patch_portal(monkeypatch, client, portal)

    first = prepare_project_publish(root, clock=lambda: APPLIED_AT)
    receipt_bytes = (root / PUBLISH_REVIEW_PATH).read_bytes()
    second = prepare_project_publish(root, clock=lambda: APPLIED_AT)

    assert first["workspace_mutated"] is True
    assert second["workspace_mutated"] is False
    assert first["receipt"] == second["receipt"]
    assert (root / PUBLISH_REVIEW_PATH).read_bytes() == receipt_bytes
    manifest = load_manifest(root)
    assert manifest.metadata["publish_review"]["fingerprint"] == first["receipt"]["fingerprint"]
    assert client.posts == []


def test_publish_approval_requires_an_adopted_receipt(tmp_path: Path) -> None:
    root, _, _ = _publish_workspace(tmp_path)

    with pytest.raises(ProjectApprovalError, match="no publish review"):
        request_approval(
            root,
            gate=ApprovalGate.PUBLISH,
            requested_by="reviewer",
        )


@pytest.mark.parametrize("authority", ["receipt", "confirmation", "approval"])
def test_apply_requires_all_three_exact_authorities_before_posts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority: str,
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    _patch_portal(monkeypatch, client, portal)
    receipt = prepare_project_publish(root)["receipt"]
    approval_id = _approve(root, receipt["fingerprint"])
    accepted = receipt["fingerprint"]
    confirmed = receipt["fingerprint"]
    if authority == "receipt":
        accepted = "0" * 64
    elif authority == "confirmation":
        confirmed = "0" * 64
    else:
        approval_id = "approval-missing"

    with pytest.raises(ProjectPublishError):
        apply_project_publish(
            root,
            receipt_fingerprint=accepted,
            approval_id=approval_id,
            confirmation=confirmed,
            published_by="operator",
        )

    assert client.posts == []


def test_apply_publishes_globals_then_exact_page_and_resumes_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    _patch_portal(monkeypatch, client, portal)
    receipt = prepare_project_publish(root)["receipt"]
    approval_id = _approve(root, receipt["fingerprint"])

    first = apply_project_publish(
        root,
        receipt_fingerprint=receipt["fingerprint"],
        approval_id=approval_id,
        confirmation=receipt["fingerprint"],
        published_by="operator",
        clock=lambda: APPLIED_AT,
    )
    post_count = len(client.posts)
    second = apply_project_publish(
        root,
        receipt_fingerprint=receipt["fingerprint"],
        approval_id=approval_id,
        confirmation=receipt["fingerprint"],
        published_by="operator",
        clock=lambda: APPLIED_AT,
    )

    assert first["status"] == "completed"
    assert second["status"] == "resumed"
    assert len(client.posts) == post_count == 3
    assert [endpoint for endpoint, _ in client.posts] == [
        PUBLISH_GLOBAL,
        PUBLISH_GLOBAL,
        PUBLISH_PAGE,
    ]
    assert client.posts[0][1]["version"] == 2
    assert client.posts[2][1] == {"pageId": 101, "version": 3}
    assert load_manifest(root).stages[ProjectStage.PUBLISH].status == StageStatus.COMPLETED
    result = json.loads((root / "qa/publish-result.json").read_text(encoding="utf-8"))
    assert result["status"] == "published_hidden_content"


def test_apply_preflights_all_drift_before_first_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    _patch_portal(monkeypatch, client, portal)
    receipt = prepare_project_publish(root)["receipt"]
    approval_id = _approve(root, receipt["fingerprint"])
    client.pages[101]["version"] = 4

    with pytest.raises(ValueError, match="publication was interrupted"):
        apply_project_publish(
            root,
            receipt_fingerprint=receipt["fingerprint"],
            approval_id=approval_id,
            confirmation=receipt["fingerprint"],
            published_by="operator",
        )

    assert client.posts == []


def test_partial_failure_journal_reconciles_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    _patch_portal(monkeypatch, client, portal)
    receipt = prepare_project_publish(root)["receipt"]
    approval_id = _approve(root, receipt["fingerprint"])
    client.fail_post = 3

    with pytest.raises(ValueError, match="publication was interrupted") as failure:
        apply_project_publish(
            root,
            receipt_fingerprint=receipt["fingerprint"],
            approval_id=approval_id,
            confirmation=receipt["fingerprint"],
            published_by="operator",
            clock=lambda: APPLIED_AT,
        )
    assert "injected publish failure" not in str(failure.value)
    journal_path = root / "history/publish" / receipt["fingerprint"] / "transaction.json"
    interrupted = json.loads(journal_path.read_text(encoding="utf-8"))
    assert interrupted["status"] == "interrupted"
    assert interrupted["error"] == "injected publish failure 3"
    assert [item["status"] for item in interrupted["actions"]] == [
        "committed",
        "committed",
        "attempting",
    ]
    client.fail_post = None

    result = apply_project_publish(
        root,
        receipt_fingerprint=receipt["fingerprint"],
        approval_id=approval_id,
        confirmation=receipt["fingerprint"],
        published_by="operator",
        clock=lambda: APPLIED_AT,
    )

    assert result["status"] == "completed"
    assert [endpoint for endpoint, _ in client.posts] == [
        PUBLISH_GLOBAL,
        PUBLISH_GLOBAL,
        PUBLISH_PAGE,
        PUBLISH_PAGE,
    ]


def test_receipt_tamper_and_live_identity_change_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    _patch_portal(monkeypatch, client, portal)
    receipt = prepare_project_publish(root)["receipt"]
    path = root / PUBLISH_REVIEW_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["actions"][0]["version"] = 99
    _write(path, payload)

    with pytest.raises(PublishReceiptError, match="fingerprint"):
        current_publish_review(root, load_manifest(root))

    assert client.posts == []


def test_prepare_reconstructs_exact_already_published_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    first_guid = next(iter(client.globals))
    client.globals[first_guid]["isPublished"] = True
    _patch_portal(monkeypatch, client, portal)

    result = prepare_project_publish(root)

    assert client.posts == []
    assert result["receipt"]["actions"][0]["prepared_published"] is True
    assert (root / PUBLISH_REVIEW_PATH).exists()


def test_publish_cli_prepare_json_and_apply_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    _patch_portal(monkeypatch, client, portal)

    result = runner.invoke(project, ["publish", "prepare", str(root), "--json"])
    help_result = runner.invoke(project, ["publish", "apply", "--help"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ready_for_review"
    assert payload["portal_mutated"] is False
    assert help_result.exit_code == 0
    assert "--confirm-publish" in help_result.output
