"""Tests for deterministic project-local Figma asset acquisition."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

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
from vanjaro_cli.orchestration.figma_assets import acquire_figma_image_fills


class FakeDownloadClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def download(self, url: str, dest: Path) -> tuple[int, str]:
        self.urls.append(url)
        content = b"\x89PNG\r\n\x1a\nimage"
        dest.write_bytes(content)
        return len(content), "image/png"


def _document() -> DesignDocument:
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
                id="hero-image",
                kind=AssetKind.IMAGE,
                role=AssetRole.EDITORIAL,
                source_url="figma://file/ref-1",
                metadata={"figma_image_ref": "ref-1"},
            ),
            AssetRecord(
                id="missing-image",
                kind=AssetKind.IMAGE,
                role=AssetRole.EDITORIAL,
                source_url="figma://file/ref-2",
                metadata={"figma_image_ref": "ref-2"},
            ),
        ],
        pages=[],
        warnings=[],
        analysis=DesignAnalysis(
            section_confidence_mean=0,
            unsupported_traits=[],
        ),
    )


def test_acquire_figma_image_fills_writes_stable_paths_and_safe_manifest(
    tmp_path: Path,
) -> None:
    client = FakeDownloadClient()
    signed_url = "https://signed.example/image?temporary=secret"

    document, artifacts = acquire_figma_image_fills(
        root=tmp_path,
        source_id="figma-1",
        document=_document(),
        fill_urls={"ref-1": signed_url},
        client=client,
    )

    assert client.urls == [signed_url]
    assert document.assets[0].local_path == "sources/figma-1/assets/hero-image.png"
    assert document.assets[0].mime_type == "image/png"
    assert document.assets[1].local_path is None
    assert artifacts == (
        "sources/figma-1/assets/hero-image.png",
        "sources/figma-1/asset-manifest.json",
    )
    manifest_text = (tmp_path / artifacts[-1]).read_text(encoding="utf-8")
    assert signed_url not in manifest_text
    manifest = json.loads(manifest_text)
    assert manifest["assets"][0]["downloaded"] is True
    assert manifest["assets"][1]["downloaded"] is False


def test_acquire_figma_image_fills_overwrites_same_stable_file_on_retry(
    tmp_path: Path,
) -> None:
    client = FakeDownloadClient()
    first, first_artifacts = acquire_figma_image_fills(
        root=tmp_path,
        source_id="figma-1",
        document=_document(),
        fill_urls={"ref-1": "https://signed.example/first"},
        client=client,
    )
    second, second_artifacts = acquire_figma_image_fills(
        root=tmp_path,
        source_id="figma-1",
        document=_document(),
        fill_urls={"ref-1": "https://signed.example/second"},
        client=client,
    )

    assert first.assets[0].local_path == second.assets[0].local_path
    assert first_artifacts == second_artifacts
    assert not list((tmp_path / "sources" / "figma-1" / "assets").glob("*.download"))
