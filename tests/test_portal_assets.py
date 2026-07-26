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
from vanjaro_cli.portal.assets import upload_project_assets


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
