"""Tests for deterministic, draft-only project page assembly."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from vanjaro_cli.design.models import (
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    LayoutKind,
    LayoutObservation,
    NavigationVisibility,
    Page,
    Section,
    SourceKind,
    StyleSet,
)
from vanjaro_cli.portal.pages import (
    ProjectPageError,
    compose_project_pages,
    preview_project_pages,
    reconcile_project_pages,
)


class Response:
    def __init__(self, value: object) -> None:
        self.value = value

    def json(self) -> object:
        return self.value


class FakeClient:
    def __init__(self) -> None:
        self.pages: dict[int, dict] = {}
        self.posts: list[tuple[str, dict]] = []

    def get(self, path: str, *, params: dict) -> Response:
        if path.endswith("/List"):
            return Response(
                {
                    "total": len(self.pages),
                    "pages": [
                        {"tabId": key, "name": value["name"], "title": value["title"]}
                        for key, value in self.pages.items()
                    ],
                }
            )
        return Response(self.pages[params["pageId"]])

    def post(self, path: str, *, json: dict) -> Response:
        self.posts.append((path, json))
        if path.endswith("/Create"):
            page_id = len(self.pages) + 100
            self.pages[page_id] = {
                "tabId": page_id,
                "name": json["name"],
                "title": json["title"],
                "path": f"/{json['name']}",
                "version": 1,
                "isPublished": False,
                "contentJSON": json["contentJSON"],
                "styleJSON": json["styleJSON"],
                "contentHtml": json["contentHtml"],
            }
            return Response({"pageId": page_id, "version": 1})
        page = self.pages[json["pageId"]]
        page.update(
            {
                "version": page["version"] + 1,
                "contentJSON": json["contentJSON"],
                "styleJSON": json["styleJSON"],
                "contentHtml": json["contentHtml"],
            }
        )
        return Response({"pageId": json["pageId"], "version": page["version"]})


def _section(key: str, order: int) -> Section:
    return Section(
        id=key,
        order=order,
        semantic_role="content",
        role_confidence=1,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.STACK, contained=True),
        content=[],
        groups=[],
        style=StyleSet(),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )


def _document(*, section_count: int = 1) -> DesignDocument:
    sections = [_section(f"home.section.{index}", index) for index in range(section_count)]
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.LIVE_HTML,
            identifier="https://source.test",
            captured_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
            adapter_version="test",
        ),
        tokens=DesignTokens(),
        assets=[],
        pages=[
            Page(
                id="home",
                source_reference="https://source.test",
                title="Home",
                slug="home",
                sections=sections,
                breakpoints=[],
                navigation_visibility=NavigationVisibility.VISIBLE,
                provenance=[],
            )
        ],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1, unsupported_traits=[]),
    )


def _blocks(count: int) -> list[object]:
    return [
        {
            "key": f"home.section.{index}",
            "content_json": [
                {
                    "type": "section",
                    "attributes": {"id": "template-section"},
                    "components": [],
                }
            ],
            "style_json": [
                {
                    "selectors": [{"name": "template-section", "type": 2}],
                    "style": {"color": "red"},
                }
            ],
        }
        for index in range(count)
    ]


def test_page_assembly_is_deterministic_and_caps_top_level_children() -> None:
    first = compose_project_pages(
        _document(section_count=10),
        _blocks(10),
        {"entries": []},
        project_id="project",
        isolated=True,
    )
    second = compose_project_pages(
        _document(section_count=10),
        _blocks(10),
        {"entries": []},
        project_id="project",
        isolated=True,
    )

    assert first == second
    assert len(first[0]["components"]) == 3
    assert first[0]["name"] == "project-home"
    assert first[0]["is_visible"] is False
    assert "data-agency-project=\"project\"" in first[0]["content_html"]


def test_create_draft_and_retry_without_post(tmp_path: Path) -> None:
    desired = compose_project_pages(
        _document(), _blocks(1), {"entries": []}, project_id="project", isolated=True
    )
    client = FakeClient()
    manifest = tmp_path / "page-manifest.json"

    preview = preview_project_pages(client, desired=desired, manifest_path=manifest)
    assert preview["to_create"] == 1
    assert client.posts == []

    records = reconcile_project_pages(
        client,
        desired=desired,
        manifest_path=manifest,
        snapshots_dir=tmp_path / "snapshots",
    )
    assert records[0]["status"] == "created"
    assert len(client.posts) == 1
    assert client.posts[0][0].endswith("/Create")
    assert client.posts[0][1]["isVisible"] is False
    assert "contentHtml" in client.posts[0][1]

    client.posts.clear()
    resumed = reconcile_project_pages(
        client,
        desired=desired,
        manifest_path=manifest,
        snapshots_dir=tmp_path / "snapshots",
    )
    assert resumed[0]["status"] == "reuse"
    assert client.posts == []


def test_unmanaged_page_collision_fails_before_post(tmp_path: Path) -> None:
    desired = compose_project_pages(
        _document(), _blocks(1), {"entries": []}, project_id="project", isolated=True
    )
    client = FakeClient()
    client.pages[55] = {
        "tabId": 55,
        "name": "project-home",
        "title": "Unmanaged",
        "version": 1,
        "isPublished": False,
        "contentJSON": "[]",
        "styleJSON": "[]",
        "contentHtml": "",
    }

    with pytest.raises(ProjectPageError, match="unmanaged page collision"):
        reconcile_project_pages(
            client,
            desired=desired,
            manifest_path=tmp_path / "page-manifest.json",
            snapshots_dir=tmp_path / "snapshots",
        )
    assert client.posts == []


def test_page_assembly_wraps_uploaded_image_variants() -> None:
    blocks = _blocks(1)
    blocks[0]["content_json"][0]["components"] = [
        {
            "type": "image",
            "attributes": {"id": "photo", "src": "/Portals/2/photo.jpg?ver=x", "alt": "Photo"},
        }
    ]
    desired = compose_project_pages(
        _document(),
        blocks,
        {"entries": []},
        project_id="project",
        isolated=True,
        asset_records=[
            {
                "vanjaro_url": "/Portals/2/photo.jpg?ver=x",
                "variants": [
                    {"type": "image", "url": "/Portals/2/.versions/photo_720w.jpg", "width": 720},
                    {"type": "webp", "url": "/Portals/2/.versions/photo_720w.webp", "width": 720},
                ],
            }
        ],
    )

    section = desired[0]["components"][0]
    picture = section["components"][0]
    assert picture["type"] == "image-box"
    assert "/.versions/" in desired[0]["content_html"]
