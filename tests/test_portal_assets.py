"""Tests for resumable, project-scoped portal asset uploads."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from vanjaro_cli.design.models import (
    AssetKind,
    AssetRecord,
    AssetRole,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    SourceKind,
)
from vanjaro_cli.portal.assets import (
    ProjectAssetError,
    preview_project_assets,
    upload_project_assets,
)


class Response:
    content = b"json"

    def __init__(self, value: dict) -> None:
        self.value = value

    def json(self):
        return self.value


class FakeClient:
    def __init__(self, fail_on_call: int | None = None) -> None:
        self.fail_on_call = fail_on_call
        self.posts: list[dict] = []

    def post(self, path: str, *, json: dict):
        self.posts.append({"path": path, "json": json})
        if self.fail_on_call == len(self.posts):
            raise RuntimeError("upload interrupted")
        index = len(self.posts)
        return Response(
            {
                "url": f"/Portals/7/Images/agency/project/{json['fileName']}",
                "fileId": 100 + index,
                "variants": [],
            }
        )


def _document(root: Path) -> DesignDocument:
    first = root / "sources" / "first.png"
    second = root / "sources" / "second.jpg"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.FIGMA,
            identifier="file",
            captured_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
            adapter_version="test",
        ),
        tokens=DesignTokens(),
        assets=[
            AssetRecord(
                id="first",
                kind=AssetKind.IMAGE,
                role=AssetRole.EDITORIAL,
                local_path="sources/first.png",
            ),
            AssetRecord(
                id="second",
                kind=AssetKind.IMAGE,
                role=AssetRole.EDITORIAL,
                local_path="sources/second.jpg",
            ),
        ],
        pages=[],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=0, unsupported_traits=[]),
    )


def test_upload_project_assets_rewrites_plan_and_resumes_without_posts(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    plan = [
        {
            "name": "Block",
            "overrides": {
                "image_1_src": "sources/first.png",
                "image_2_src": "sources/second.jpg",
            },
        }
    ]
    client = FakeClient()

    portal_document, portal_plan, records = upload_project_assets(
        client,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=plan,
    )

    assert len(client.posts) == 2
    assert all(
        call["json"]["folderPath"] == "Images/agency/project/"
        for call in client.posts
    )
    assert portal_document.assets[0].local_path is None
    assert portal_plan[0]["overrides"]["image_1_src"].startswith("/Portals/7/")
    assert len(records) == 2

    resumed_client = FakeClient()
    _, resumed_plan, resumed_records = upload_project_assets(
        resumed_client,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=plan,
    )
    assert resumed_client.posts == []
    assert resumed_plan == portal_plan
    assert resumed_records == records


def test_upload_project_assets_persists_each_success_for_partial_retry(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    interrupted = FakeClient(fail_on_call=2)

    with pytest.raises(RuntimeError, match="interrupted"):
        upload_project_assets(
            interrupted,
            root=tmp_path,
            project_id="project",
            document=document,
            library_plan=[],
        )
    manifest = json.loads(
        (tmp_path / "build" / "asset-manifest.json").read_text(encoding="utf-8")
    )
    assert [record["asset_id"] for record in manifest["assets"]] == ["first"]

    retry = FakeClient()
    _, _, records = upload_project_assets(
        retry,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=[],
    )
    assert len(retry.posts) == 1
    assert retry.posts[0]["json"]["fileName"] == "second.jpg"
    assert [record["asset_id"] for record in records] == ["first", "second"]


def test_upload_rejects_asset_bytes_changed_after_plan(tmp_path: Path) -> None:
    document = _document(tmp_path)

    class MutatingClient(FakeClient):
        def post(self, path: str, *, json: dict):
            response = super().post(path, json=json)
            if len(self.posts) == 1:
                (tmp_path / "sources/second.jpg").write_bytes(b"changed")
            return response

    client = MutatingClient()
    with pytest.raises(ProjectAssetError, match="changed after review"):
        upload_project_assets(
            client,
            root=tmp_path,
            project_id="project",
            document=document,
            library_plan=[],
        )

    assert len(client.posts) == 1


def _workspace_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_preview_project_assets_is_deterministic_and_zero_write(tmp_path: Path) -> None:
    document = _document(tmp_path)
    before = _workspace_bytes(tmp_path)

    first = preview_project_assets(
        root=tmp_path, project_id="project", document=document
    )
    second = preview_project_assets(
        root=tmp_path, project_id="project", document=document
    )

    assert first == second
    assert _workspace_bytes(tmp_path) == before
    encoded = json.dumps(first, sort_keys=True)
    assert "base64" not in encoded.lower()
    assert str(tmp_path) not in encoded
    assert [item["asset_id"] for item in first["assets"]] == ["first", "second"]
    assert [item["action"] for item in first["assets"]] == ["upload", "upload"]
    assert all(item["method"] == "POST" for item in first["assets"])


def test_preview_and_apply_decisions_match_and_changed_bytes_change_plan(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    preview = preview_project_assets(
        root=tmp_path, project_id="project", document=document
    )
    client = FakeClient()
    upload_project_assets(
        client,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=[],
    )
    assert [call["path"] for call in client.posts] == [
        item["endpoint"] for item in preview["assets"] if item["action"] == "upload"
    ]

    resumed = preview_project_assets(
        root=tmp_path, project_id="project", document=document
    )
    assert [item["action"] for item in resumed["assets"]] == ["reuse", "reuse"]
    assert resumed["assets"][0]["observed"]["vanjaro_url"].startswith("/Portals/")
    assert resumed["assets"][0]["before_state_fingerprint"]
    resumed_client = FakeClient()
    upload_project_assets(
        resumed_client,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=[],
    )
    assert resumed_client.posts == []

    old_digest = resumed["assets"][0]["sha256"]
    (tmp_path / "sources" / "first.png").write_bytes(b"changed")
    changed = preview_project_assets(
        root=tmp_path, project_id="project", document=document
    )
    assert changed["assets"][0]["action"] == "upload"
    assert changed["assets"][0]["sha256"] != old_digest
    assert changed["assets"][0]["payload_fingerprint"]
    assert changed["assets"][1]["action"] == "reuse"


@pytest.mark.parametrize("local_path", ["sources/missing.png", "../escape.png"])
def test_preview_project_assets_rejects_missing_or_escaping_files(
    tmp_path: Path, local_path: str
) -> None:
    document = _document(tmp_path)
    document.assets[0].local_path = local_path

    with pytest.raises(ProjectAssetError, match="missing|escapes"):
        preview_project_assets(root=tmp_path, project_id="project", document=document)
