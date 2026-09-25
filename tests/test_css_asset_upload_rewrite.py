"""CSS url(...) rewriting for uploaded project assets inside design CSS.

``upload_project_assets`` (vanjaro_cli/portal/assets.py) resolves each local
design asset to an uploaded-or-reused portal URL and must rewrite every
``url(...)`` reference to that asset inside a library plan's
``style_declarations`` -- not just the whole-string ``overrides`` values
``_replace_strings`` already handled. These tests exercise that CSS-aware
rewrite path with fake upload clients only; no live requests are made.

See also artifacts/test_css_asset_upload_rewrite_independent.py (root-owned,
immutable) for the acceptance proof this file must also keep passing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
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
from vanjaro_cli.portal.assets import ProjectAssetError, upload_project_assets


class Response:
    content = b"json"

    def __init__(self, value: dict) -> None:
        self.value = value

    def json(self):
        return self.value


class FakeClient:
    """Fake upload client returning source-grounded, deterministic portal
    URLs -- ``url_overrides`` lets one test force a specific (and, for the
    unsafe-destination test, deliberately unsafe) URL for one file name.
    """

    def __init__(
        self,
        *,
        fail_on_call: int | None = None,
        url_overrides: dict[str, str] | None = None,
    ) -> None:
        self.fail_on_call = fail_on_call
        self.url_overrides = url_overrides or {}
        self.posts: list[dict] = []

    def post(self, path: str, *, json: dict):
        self.posts.append({"path": path, "json": json})
        if self.fail_on_call == len(self.posts):
            raise RuntimeError("upload interrupted")
        file_name = json["fileName"]
        url = self.url_overrides.get(
            file_name, f"/Portals/7/Images/agency/project/{file_name}"
        )
        return Response({"url": url, "fileId": 100 + len(self.posts), "variants": []})


def _asset(
    root: Path,
    asset_id: str,
    filename: str,
    *,
    source_url: str | None = None,
    content: bytes = b"data",
) -> AssetRecord:
    path = root / "sources" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return AssetRecord(
        id=asset_id,
        kind=AssetKind.IMAGE,
        role=AssetRole.EDITORIAL,
        local_path=f"sources/{filename}",
        source_url=source_url,
    )


def _document(root: Path, assets: list[AssetRecord]) -> DesignDocument:
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.FIGMA,
            identifier="file",
            captured_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
            adapter_version="test",
        ),
        tokens=DesignTokens(),
        assets=assets,
        pages=[],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=0, unsupported_traits=[]),
    )


def test_local_and_source_url_css_references_rewrite_on_first_run_and_reuse(
    tmp_path: Path,
) -> None:
    asset = _asset(
        tmp_path, "first", "first.png", source_url="https://source.invalid/first.png"
    )
    document = _document(tmp_path, [asset])
    plan = [
        {
            "name": "Hero",
            "style_scope": ".proj .hero",
            "style_declarations": {"background-image": 'url("sources/first.png")'},
        },
        {
            "name": "HeroFallback",
            "style_scope": ".proj .hero-fallback",
            "style_declarations": {
                "background-image": "url(https://source.invalid/first.png)"
            },
        },
    ]
    client = FakeClient()

    _, rewritten, records = upload_project_assets(
        client,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=plan,
    )
    migrated = next(r["vanjaro_url"] for r in records if r["asset_id"] == "first")

    assert rewritten[0]["style_declarations"]["background-image"] == f'url("{migrated}")'
    assert rewritten[1]["style_declarations"]["background-image"] == f"url({migrated})"
    # Caller's input plan is never mutated in place.
    assert plan[0]["style_declarations"]["background-image"] == 'url("sources/first.png")'
    assert plan[1]["style_declarations"]["background-image"] == (
        "url(https://source.invalid/first.png)"
    )

    resumed_client = FakeClient()
    _, resumed, _ = upload_project_assets(
        resumed_client,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=plan,
    )
    assert resumed_client.posts == []
    assert resumed == rewritten


def test_breakpoint_prefixed_style_keys_rewrite(tmp_path: Path) -> None:
    asset = _asset(tmp_path, "first", "first.png")
    document = _document(tmp_path, [asset])
    plan = [
        {
            "name": "Hero",
            "style_scope": ".proj .hero",
            "style_declarations": {
                "background-image": "url(sources/first.png)",
                "tablet:background-image": "url(sources/first.png)",
                "mobile:background-image": "url(sources/first.png)",
            },
        }
    ]
    client = FakeClient()

    _, rewritten, records = upload_project_assets(
        client,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=plan,
    )
    migrated = records[0]["vanjaro_url"]
    declarations = rewritten[0]["style_declarations"]
    assert declarations["background-image"] == f"url({migrated})"
    assert declarations["tablet:background-image"] == f"url({migrated})"
    assert declarations["mobile:background-image"] == f"url({migrated})"


def test_multiple_and_mixed_quoted_url_tokens_preserve_surrounding_text(
    tmp_path: Path,
) -> None:
    first = _asset(tmp_path, "first", "first.png")
    second = _asset(tmp_path, "second", "second.jpg")
    document = _document(tmp_path, [first, second])
    plan = [
        {
            "name": "Layered",
            "style_scope": ".proj .layered",
            "style_declarations": {
                "background-image": (
                    "URL('sources/first.png') no-repeat center, "
                    "url(sources/second.jpg) repeat-x"
                )
            },
        }
    ]
    client = FakeClient()

    _, rewritten, records = upload_project_assets(
        client,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=plan,
    )
    first_url = next(r["vanjaro_url"] for r in records if r["asset_id"] == "first")
    second_url = next(r["vanjaro_url"] for r in records if r["asset_id"] == "second")
    value = rewritten[0]["style_declarations"]["background-image"]
    assert value == (
        f"url('{first_url}') no-repeat center, url({second_url}) repeat-x"
    )


def test_non_url_style_values_and_unknown_references_pass_through_untouched(
    tmp_path: Path,
) -> None:
    asset = _asset(tmp_path, "first", "first.png")
    document = _document(tmp_path, [asset])
    plan = [
        {
            "name": "Hero",
            "style_scope": ".proj .hero",
            "style_declarations": {
                "background-color": "#112233",
                "background-image": "url(sources/first.png)",
                "background-position": "url(https://unrelated.example/not-an-asset.png)",
                "content": "'sources/first.png'",
            },
        }
    ]
    client = FakeClient()

    _, rewritten, records = upload_project_assets(
        client,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=plan,
    )
    migrated = records[0]["vanjaro_url"]
    declarations = rewritten[0]["style_declarations"]
    assert declarations["background-color"] == "#112233"
    assert declarations["background-image"] == f"url({migrated})"
    # Not a design asset -- stays explicit, never fabricated.
    assert declarations["background-position"] == (
        "url(https://unrelated.example/not-an-asset.png)"
    )
    # A matching substring outside a url(...) token is never touched --
    # only real CSS url() references are rewritten.
    assert declarations["content"] == "'sources/first.png'"


def test_partial_retry_completes_without_duplicate_upload_and_matches_css(
    tmp_path: Path,
) -> None:
    first = _asset(tmp_path, "first", "first.png")
    second = _asset(tmp_path, "second", "second.jpg")
    document = _document(tmp_path, [first, second])
    plan = [
        {
            "name": "Hero",
            "style_scope": ".proj .hero",
            "style_declarations": {"background-image": 'url("sources/first.png")'},
        },
        {
            "name": "Footer",
            "style_scope": ".proj .footer",
            "style_declarations": {"background-image": "url(sources/second.jpg)"},
        },
    ]
    interrupted = FakeClient(fail_on_call=2)
    with pytest.raises(RuntimeError, match="interrupted"):
        upload_project_assets(
            interrupted,
            root=tmp_path,
            project_id="project",
            document=document,
            library_plan=plan,
        )
    assert len(interrupted.posts) == 2

    retry = FakeClient()
    _, rewritten, records = upload_project_assets(
        retry,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=plan,
    )
    assert len(retry.posts) == 1
    assert retry.posts[0]["json"]["fileName"] == "second.jpg"
    first_url = next(r["vanjaro_url"] for r in records if r["asset_id"] == "first")
    second_url = next(r["vanjaro_url"] for r in records if r["asset_id"] == "second")
    assert rewritten[0]["style_declarations"]["background-image"] == f'url("{first_url}")'
    assert rewritten[1]["style_declarations"]["background-image"] == f"url({second_url})"

    resumed_client = FakeClient()
    _, resumed_again, _ = upload_project_assets(
        resumed_client,
        root=tmp_path,
        project_id="project",
        document=document,
        library_plan=plan,
    )
    assert resumed_client.posts == []
    assert resumed_again == rewritten


def test_ambiguous_shared_source_url_is_rejected_before_upload(
    tmp_path: Path,
) -> None:
    shared_source = "https://cdn.test/shared.png"
    first = _asset(tmp_path, "first", "first.png", source_url=shared_source)
    second = _asset(tmp_path, "second", "second.jpg", source_url=shared_source)
    document = _document(tmp_path, [first, second])
    plan = [
        {
            "name": "Ambiguous",
            "style_scope": ".proj .ambiguous",
            "style_declarations": {"background-image": f"url({shared_source})"},
        },
    ]
    client = FakeClient()

    # Two assets share this original source URL -- accepting either
    # resolution silently would be a guess. The whole upload is rejected
    # up front, before any network call, rather than accepted with a
    # silently unrewritten CSS reference.
    with pytest.raises(ProjectAssetError, match="(?i)ambig"):
        upload_project_assets(
            client,
            root=tmp_path,
            project_id="project",
            document=document,
            library_plan=plan,
        )
    assert client.posts == []


def test_unsafe_resolved_destination_is_never_accepted(
    tmp_path: Path,
) -> None:
    asset = _asset(tmp_path, "first", "first.png")
    document = _document(tmp_path, [asset])
    plan = [
        {
            "name": "Hero",
            "style_scope": ".proj .hero",
            "style_declarations": {"background-image": "url(sources/first.png)"},
        }
    ]
    client = FakeClient(url_overrides={"first.png": "javascript:alert(1)"})

    # An unsafe resolved destination must never become a successful output --
    # not in the manifest, not in overrides, and not in generated CSS.
    with pytest.raises(ProjectAssetError, match="(?i)unsafe|invalid|destination"):
        upload_project_assets(
            client,
            root=tmp_path,
            project_id="project",
            document=document,
            library_plan=plan,
        )
    manifest_path = tmp_path / "build" / "asset-manifest.json"
    assert not manifest_path.exists() or not json.loads(
        manifest_path.read_text(encoding="utf-8")
    )["assets"]
