"""Tests for acquiring the remote images an HTML source references."""

from __future__ import annotations

import json
from pathlib import Path

from datetime import datetime, timezone

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
from vanjaro_cli.orchestration.html_assets import acquire_html_assets


def _asset(asset_id: str, source_url: str | None, local_path: str | None = None) -> AssetRecord:
    return AssetRecord(
        id=asset_id,
        kind=AssetKind.IMAGE,
        role=AssetRole.EDITORIAL,
        source_url=source_url,
        local_path=local_path,
    )


def _document(*assets: AssetRecord) -> DesignDocument:
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.LIVE_HTML,
            identifier="http://example.test/",
            captured_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
            adapter_version="test",
        ),
        tokens=DesignTokens(),
        assets=list(assets),
        pages=[],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=0, unsupported_traits=[]),
    )


def _downloader(written: dict[str, bytes], failures: tuple[str, ...] = ()):
    def download(urls, output_dir: Path, on_warning) -> list[dict]:
        directory = output_dir / "assets"
        directory.mkdir(parents=True, exist_ok=True)
        entries = []
        for index, url in enumerate(urls, 1):
            if url in failures:
                on_warning(f"Failed to download {url}: 404")
                continue
            filename = f"image-{index}.png"
            (directory / filename).write_bytes(written.get(url, b"\x89PNG"))
            entries.append(
                {
                    "source_url": url,
                    "local_file": filename,
                    "content_type": "image/png",
                    "size_bytes": 4,
                }
            )
        return entries

    return download


def test_a_remote_image_is_acquired_into_the_workspace(tmp_path: Path) -> None:
    """A live page analyses with local_path unset on every asset, so a template
    whose media field is required cannot bind at all."""

    document = _document(_asset("asset-1", "http://example.test/hero.png"))

    updated, artifacts = acquire_html_assets(
        root=tmp_path,
        source_id="live-html-1",
        document=document,
        downloader=_downloader({}),
    )

    assert updated.assets[0].local_path == "sources/live-html-1/assets/image-1.png"
    assert (tmp_path / updated.assets[0].local_path).is_file()
    assert "sources/live-html-1/asset-manifest.json" in artifacts


def test_the_manifest_records_what_was_acquired(tmp_path: Path) -> None:
    document = _document(_asset("asset-1", "http://example.test/hero.png"))

    acquire_html_assets(
        root=tmp_path,
        source_id="live-html-1",
        document=document,
        downloader=_downloader({}),
    )

    manifest = json.loads((tmp_path / "sources/live-html-1/asset-manifest.json").read_text())
    assert manifest["assets"][0]["asset_id"] == "asset-1"
    assert manifest["assets"][0]["downloaded"] is True
    assert manifest["assets"][0]["sha256"]


def test_a_relative_source_is_left_alone(tmp_path: Path) -> None:
    """A relative path already loads in a portal page; downloading it would be
    fetching the site being built."""

    document = _document(_asset("asset-1", "/Portals/2/hero.png"))

    updated, artifacts = acquire_html_assets(
        root=tmp_path,
        source_id="live-html-1",
        document=document,
        downloader=_downloader({}),
    )

    assert updated.assets[0].local_path is None
    assert artifacts == ()


def test_an_already_acquired_asset_is_not_downloaded_again(tmp_path: Path) -> None:
    def refuse(urls, output_dir, on_warning):
        raise AssertionError("should not download an asset that has a local path")

    document = _document(
        _asset("asset-1", "http://example.test/hero.png", local_path="sources/x/assets/a.png")
    )

    updated, artifacts = acquire_html_assets(
        root=tmp_path, source_id="live-html-1", document=document, downloader=refuse
    )

    assert updated.assets[0].local_path == "sources/x/assets/a.png"
    assert artifacts == ()


def test_a_failed_download_is_recorded_twice_not_dropped(tmp_path: Path) -> None:
    document = _document(_asset("asset-1", "http://example.test/gone.png"))

    updated, _ = acquire_html_assets(
        root=tmp_path,
        source_id="live-html-1",
        document=document,
        downloader=_downloader({}, failures=("http://example.test/gone.png",)),
    )

    assert updated.assets[0].local_path is None
    assert updated.assets[0].missing_reason
    assert [warning.code for warning in updated.warnings] == ["html_asset_download_failed"]


def test_the_same_url_is_requested_once(tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def record(urls, output_dir, on_warning):
        seen.append(list(urls))
        return _downloader({})(urls, output_dir, on_warning)

    document = _document(
        _asset("asset-1", "http://example.test/hero.png"),
        _asset("asset-2", "http://example.test/hero.png"),
    )

    updated, _ = acquire_html_assets(
        root=tmp_path, source_id="live-html-1", document=document, downloader=record
    )

    assert seen == [["http://example.test/hero.png"]]
    assert {asset.local_path for asset in updated.assets} == {"sources/live-html-1/assets/image-1.png"}
