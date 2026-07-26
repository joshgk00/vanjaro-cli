"""Tests for unpublished project global-block reconciliation."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from vanjaro_cli.portal.global_blocks import (
    ProjectGlobalBlockError,
    preview_project_global_blocks,
    reconcile_project_global_blocks,
)
from vanjaro_cli.utils.grapesjs import render_components


class Response:
    def __init__(self, value: object) -> None:
        self.value = value

    def json(self) -> object:
        return self.value


class FakeClient:
    def __init__(self) -> None:
        self.blocks: dict[str, dict] = {}
        self.posts: list[tuple[str, dict]] = []
        self.fail_next_update = False

    def get(self, path: str, *, params: dict | None = None) -> Response:
        if path.endswith("/List"):
            return Response(
                {
                    "blocks": [
                        {
                            "guid": guid,
                            "name": detail["name"],
                            "category": detail["category"],
                            "version": detail["version"],
                            "isPublished": detail["isPublished"],
                        }
                        for guid, detail in self.blocks.items()
                    ]
                }
            )
        return Response(self.blocks[params["guid"]])

    def post_form(self, path: str, form: dict) -> Response:
        self.posts.append((path, form))
        guid = f"global-{len(self.blocks) + 1}"
        self.blocks[guid] = {
            "id": len(self.blocks) + 1,
            "guid": guid,
            "name": form["Name"],
            "category": form["Category"].casefold(),
            "version": 1,
            "isPublished": True,
            "contentJSON": form["ContentJSON"],
            "styleJSON": form["StyleJSON"],
        }
        return Response({"Status": "Success", "Guid": guid})

    def post(self, path: str, *, json: dict) -> Response:
        self.posts.append((path, json))
        if self.fail_next_update:
            self.fail_next_update = False
            raise RuntimeError("simulated interrupted replacement update")
        block = self.blocks[json["guid"]]
        block.update(
            {
                "version": 2,
                "isPublished": False,
                "contentJSON": json["contentJSON"],
                "styleJSON": json["styleJSON"],
            }
        )
        return Response({"guid": json["guid"], "version": 2})


def _desired(copy: str = "Original") -> list[dict]:
    components = [
        {
            "type": "section",
            "attributes": {"id": "global-header", "data-copy": copy},
            "components": [],
        }
    ]
    return [
        {
            "key": "global-header",
            "kind": "header",
            "source_section_id": "header-section",
            "name": "project / Site Header",
            "category": "Agency - project",
            "components": components,
            "styles": [],
            "html": render_components(components),
            "desired_hash": _hash(
                {
                    "content_json": components,
                    "style_json": [],
                }
            ),
            "warnings": [],
        }
    ]


def _hash(value: object) -> str:
    import hashlib

    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def test_global_create_uses_placeholder_then_unpublished_desired_v2(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    manifest = tmp_path / "global-manifest.json"
    preview = preview_project_global_blocks(
        client, desired=_desired(), manifest_path=manifest
    )
    assert preview["to_create"] == 1
    assert client.posts == []

    records = reconcile_project_global_blocks(
        client, desired=_desired(), manifest_path=manifest
    )

    assert [path.rsplit("/", 1)[-1] for path, _ in client.posts] == [
        "AddCustomBlock",
        "Update",
    ]
    assert records[0]["observed_version"] == 2
    assert records[0]["published"] is False
    assert records[0]["status"] == "created"

    client.posts.clear()
    preview = preview_project_global_blocks(
        client, desired=_desired(), manifest_path=manifest
    )
    assert preview["to_create"] == 0
    assert preview["to_replace"] == 0
    assert preview["reused"] == 1
    assert preview["blocks"][0]["action"] == "reuse"

    resumed = reconcile_project_global_blocks(
        client, desired=_desired(), manifest_path=manifest
    )
    assert resumed[0]["status"] == "reuse"
    assert client.posts == []


def test_changed_managed_global_creates_deterministic_immutable_replacement(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    manifest = tmp_path / "global-manifest.json"
    original = reconcile_project_global_blocks(
        client, desired=_desired(), manifest_path=manifest
    )[0]
    original_guid = original["guid"]
    original_detail = deepcopy(client.blocks[original_guid])
    changed = _desired("Changed")
    replacement_name = f"{changed[0]['name']} [{changed[0]['desired_hash'][:8]}]"

    client.posts.clear()
    preview = preview_project_global_blocks(
        client, desired=changed, manifest_path=manifest
    )
    assert preview["to_create"] == 0
    assert preview["to_replace"] == 1
    assert preview["reused"] == 0
    assert preview["blocks"][0] == {
        "key": "global-header",
        "name": "project / Site Header",
        "replacement_name": replacement_name,
        "action": "replace_create",
    }
    assert client.posts == []

    replaced = reconcile_project_global_blocks(
        client, desired=changed, manifest_path=manifest
    )[0]

    assert replaced["status"] == "replaced"
    assert replaced["guid"] != original_guid
    assert replaced["portal_name"] == replacement_name
    assert client.blocks[original_guid] == original_detail
    assert [
        payload["guid"]
        for path, payload in client.posts
        if path.endswith("/Update")
    ] == [replaced["guid"]]


def test_interrupted_replacement_retries_the_persisted_placeholder(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    manifest = tmp_path / "global-manifest.json"
    original = reconcile_project_global_blocks(
        client, desired=_desired(), manifest_path=manifest
    )[0]
    original_detail = deepcopy(client.blocks[original["guid"]])
    changed = _desired("Changed")

    client.posts.clear()
    client.fail_next_update = True
    with pytest.raises(RuntimeError, match="interrupted replacement update"):
        reconcile_project_global_blocks(
            client, desired=changed, manifest_path=manifest
        )

    interrupted = json.loads(manifest.read_text(encoding="utf-8"))["blocks"][0]
    replacement_guid = interrupted["guid"]
    assert interrupted["status"] == "placeholder_created"
    assert replacement_guid != original["guid"]
    assert client.blocks[original["guid"]] == original_detail

    client.posts.clear()
    preview = preview_project_global_blocks(
        client, desired=changed, manifest_path=manifest
    )
    assert preview["to_replace"] == 1
    assert preview["blocks"][0]["action"] == "replace_finish"

    retried = reconcile_project_global_blocks(
        client, desired=changed, manifest_path=manifest
    )[0]
    assert retried["status"] == "replaced"
    assert retried["guid"] == replacement_guid
    assert [
        payload["guid"]
        for path, payload in client.posts
        if path.endswith("/Update")
    ] == [replacement_guid]
    assert client.blocks[original["guid"]] == original_detail


def test_exact_completed_replacement_is_adopted_after_manifest_retry(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    manifest = tmp_path / "global-manifest.json"
    reconcile_project_global_blocks(
        client, desired=_desired(), manifest_path=manifest
    )
    original_manifest = manifest.read_text(encoding="utf-8")
    changed = _desired("Changed")
    replaced = reconcile_project_global_blocks(
        client, desired=changed, manifest_path=manifest
    )[0]

    manifest.write_text(original_manifest, encoding="utf-8")
    client.posts.clear()
    preview = preview_project_global_blocks(
        client, desired=changed, manifest_path=manifest
    )
    assert preview["to_replace"] == 0
    assert preview["reused"] == 1
    assert preview["blocks"][0]["action"] == "adopt"

    adopted = reconcile_project_global_blocks(
        client, desired=changed, manifest_path=manifest
    )[0]
    assert adopted["status"] == "adopt"
    assert adopted["guid"] == replaced["guid"]
    assert client.posts == []


def test_replacement_name_collision_is_rejected_without_mutation(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    manifest = tmp_path / "global-manifest.json"
    original = reconcile_project_global_blocks(
        client, desired=_desired(), manifest_path=manifest
    )[0]
    original_detail = deepcopy(client.blocks[original["guid"]])
    changed = _desired("Changed")
    replacement_name = f"{changed[0]['name']} [{changed[0]['desired_hash'][:8]}]"
    client.blocks["collision"] = {
        "id": 2,
        "guid": "collision",
        "name": replacement_name,
        "category": "agency - project",
        "version": 1,
        "isPublished": False,
        "contentJSON": "[]",
        "styleJSON": "[]",
    }

    client.posts.clear()
    with pytest.raises(ProjectGlobalBlockError, match="replacement global collision"):
        reconcile_project_global_blocks(
            client, desired=changed, manifest_path=manifest
        )

    assert client.posts == []
    assert client.blocks[original["guid"]] == original_detail


def test_unmanaged_global_collision_fails_without_post(tmp_path: Path) -> None:
    client = FakeClient()
    client.blocks["other"] = {
        "id": 1,
        "guid": "other",
        "name": "project / Site Header",
        "category": "agency - project",
        "version": 1,
        "isPublished": True,
        "contentJSON": "[]",
        "styleJSON": "[]",
    }

    with pytest.raises(ProjectGlobalBlockError, match="unmanaged global collision"):
        reconcile_project_global_blocks(
            client,
            desired=_desired(),
            manifest_path=tmp_path / "global-manifest.json",
        )
    assert client.posts == []
