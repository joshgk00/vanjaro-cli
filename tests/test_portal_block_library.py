"""Tests for safe, resumable project custom-block registration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vanjaro_cli.portal.block_library import (
    ADD_BLOCK,
    BlockLibraryError,
    compose_project_library,
    preview_project_library,
    register_project_library,
)


class Response:
    def __init__(self, value: object) -> None:
        self.value = value

    def json(self) -> object:
        return self.value


class FakeClient:
    def __init__(self, rows: list[dict] | None = None, *, fail_on_post: int | None = None) -> None:
        self.rows = list(rows or [])
        self.posts: list[dict] = []
        self.fail_on_post = fail_on_post

    def get(self, path: str) -> Response:
        return Response(self.rows)

    def post_form(self, path: str, form: dict) -> Response:
        self.posts.append(form)
        if self.fail_on_post == len(self.posts):
            raise RuntimeError("portal interrupted")
        self.rows.append(
            {
                "ID": len(self.rows) + 1,
                "Guid": f"guid-{len(self.rows) + 1}",
                "Name": form["Name"],
                "Category": form["Category"],
                "ContentJSON": form["ContentJSON"],
                "StyleJSON": form["StyleJSON"],
            }
        )
        return Response({"Status": "Success"})


def _template_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "templates" / "Heroes"
    directory.mkdir(parents=True)
    template = {
        "name": "Test Hero",
        "category": "Heroes",
        "template": {
            "type": "section",
            "attributes": {"id": "section-1"},
            "components": [
                {
                    "type": "heading",
                    "attributes": {"id": "heading-1"},
                    "content": "Placeholder",
                }
            ],
        },
        "styles": [],
    }
    (directory / "test-hero.json").write_text(json.dumps(template), encoding="utf-8")
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(tmp_path / "templates"))


def _plan(
    name: str = "project / Hero",
    key: str = "page.section.1",
    heading: str = "Welcome",
) -> list[object]:
    return [
        {
            "key": key,
            "template": "Test Hero",
            "name": name,
            "category": "Agency - project",
            "type": "custom",
            "overrides": {"heading_1": heading},
        }
    ]


def _desired_row(desired: dict, *, name: str, guid: str) -> dict:
    return {
        "ID": 99,
        "Guid": guid,
        "Name": name,
        "Category": desired["category"],
        "ContentJSON": json.dumps(desired["content_json"]),
        "StyleJSON": json.dumps(desired["style_json"]),
    }


def test_preflight_composes_entire_plan_before_any_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _template_dir(tmp_path, monkeypatch)
    client = FakeClient()
    plan = _plan() + [
        {
            "key": "page.section.2",
            "template": "Missing",
            "name": "project / Missing",
            "type": "custom",
            "overrides": {},
        }
    ]

    with pytest.raises(BlockLibraryError, match="not found"):
        register_project_library(
            client,
            plan=plan,
            manifest_path=tmp_path / "build/block-manifest.json",
        )

    assert client.posts == []


def test_preflight_rejects_template_changed_after_plan_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _template_dir(tmp_path, monkeypatch)
    plan = _plan()
    plan[0]["template_digest"] = "0" * 64

    with pytest.raises(BlockLibraryError, match="changed after plan approval"):
        compose_project_library(plan)


def test_existing_different_content_blocks_all_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _template_dir(tmp_path, monkeypatch)
    client = FakeClient(
        [
            {
                "Guid": "existing",
                "Name": "project / Hero",
                "Category": "Agency - project",
                "ContentJSON": "[]",
                "StyleJSON": "[]",
            }
        ]
    )

    with pytest.raises(BlockLibraryError, match="different content"):
        register_project_library(
            client,
            plan=_plan(),
            manifest_path=tmp_path / "build/block-manifest.json",
        )

    assert client.posts == []


def test_registration_persists_identity_and_retry_reuses_without_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _template_dir(tmp_path, monkeypatch)
    client = FakeClient()
    manifest_path = tmp_path / "build/block-manifest.json"

    _, records = register_project_library(
        client,
        plan=_plan(),
        manifest_path=manifest_path,
    )

    assert len(client.posts) == 1
    assert records[0]["guid"] == "guid-1"
    assert records[0]["status"] == "created"
    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted["blocks"][0]["key"] == "page.section.1"

    client.posts.clear()
    _, resumed = register_project_library(
        client,
        plan=_plan(),
        manifest_path=manifest_path,
    )
    assert client.posts == []
    assert resumed[0]["status"] == "reused"


def test_changed_content_creates_immutable_deterministic_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _template_dir(tmp_path, monkeypatch)
    client = FakeClient()
    manifest_path = tmp_path / "build/block-manifest.json"
    register_project_library(client, plan=_plan(), manifest_path=manifest_path)
    original = dict(client.rows[0])
    client.posts.clear()

    desired, records = register_project_library(
        client,
        plan=_plan(heading="Updated"),
        manifest_path=manifest_path,
    )

    replacement_name = f"project / Hero [{desired[0]['desired_hash'][:8]}]"
    assert [post["Name"] for post in client.posts] == [replacement_name]
    assert client.rows[0] == original
    assert len(client.rows) == 2
    assert records[0]["name"] == "project / Hero"
    assert records[0]["portal_name"] == replacement_name
    assert records[0]["guid"] == "guid-2"


def test_exact_replacement_is_adopted_after_crash_with_legacy_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _template_dir(tmp_path, monkeypatch)
    client = FakeClient()
    manifest_path = tmp_path / "build/block-manifest.json"
    register_project_library(client, plan=_plan(), manifest_path=manifest_path)
    legacy = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy["blocks"][0].pop("portal_name")
    manifest_path.write_text(json.dumps(legacy), encoding="utf-8")

    desired = compose_project_library(_plan(heading="Updated"))
    replacement_name = f"project / Hero [{desired[0]['desired_hash'][:8]}]"
    client.rows.append(
        _desired_row(desired[0], name=replacement_name, guid="crash-guid")
    )
    client.posts.clear()

    _, records = register_project_library(
        client,
        plan=_plan(heading="Updated"),
        manifest_path=manifest_path,
    )

    assert client.posts == []
    assert records[0]["status"] == "adopted"
    assert records[0]["guid"] == "crash-guid"
    assert records[0]["portal_name"] == replacement_name
    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted["blocks"][0]["guid"] == "crash-guid"


def test_replacement_name_collision_with_different_content_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _template_dir(tmp_path, monkeypatch)
    client = FakeClient()
    manifest_path = tmp_path / "build/block-manifest.json"
    register_project_library(client, plan=_plan(), manifest_path=manifest_path)
    desired = compose_project_library(_plan(heading="Updated"))
    replacement_name = f"project / Hero [{desired[0]['desired_hash'][:8]}]"
    client.rows.append(
        {
            "Guid": "collision-guid",
            "Name": replacement_name,
            "Category": desired[0]["category"],
            "ContentJSON": "[]",
            "StyleJSON": "[]",
        }
    )
    client.posts.clear()

    with pytest.raises(BlockLibraryError, match="replacement block collision"):
        register_project_library(
            client,
            plan=_plan(heading="Updated"),
            manifest_path=manifest_path,
        )

    assert client.posts == []
    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted["blocks"][0]["guid"] == "guid-1"


def test_unchanged_revision_is_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _template_dir(tmp_path, monkeypatch)
    client = FakeClient()
    manifest_path = tmp_path / "build/block-manifest.json"
    register_project_library(client, plan=_plan(), manifest_path=manifest_path)
    _, revised = register_project_library(
        client,
        plan=_plan(heading="Updated"),
        manifest_path=manifest_path,
    )
    client.posts.clear()

    _, resumed = register_project_library(
        client,
        plan=_plan(heading="Updated"),
        manifest_path=manifest_path,
    )

    assert client.posts == []
    assert resumed[0]["status"] == "reused"
    assert resumed[0]["guid"] == revised[0]["guid"]
    assert resumed[0]["portal_name"] == revised[0]["portal_name"]


def test_preview_is_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _template_dir(tmp_path, monkeypatch)
    client = FakeClient()
    manifest_path = tmp_path / "build/block-manifest.json"

    result = preview_project_library(
        client,
        plan=_plan(),
        manifest_path=manifest_path,
    )

    assert result["to_create"] == 1
    assert result["reused"] == 0
    planned = result["blocks"][0]
    assert planned["endpoint"] == ADD_BLOCK
    assert planned["payload_fingerprint"]
    assert planned["response_binding"].startswith("custom-block-guid://")
    assert [operation["kind"] for operation in planned["operations"]] == [
        "local_checkpoint",
        "portal_request",
        "portal_readback",
        "local_checkpoint",
    ]
    assert client.posts == []
    assert not manifest_path.exists()
