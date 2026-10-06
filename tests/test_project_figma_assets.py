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
from vanjaro_cli.design.models import DesignWarning
from vanjaro_cli.figma import FigmaError
from vanjaro_cli.orchestration.figma_assets import (
    acquire_figma_image_fills,
    acquire_figma_vector_exports,
)


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


class FakeVectorClient:
    def __init__(self, urls: dict[str, str | None], *, fail_batches: set[int] | None = None,
                 fail_downloads: set[str] | None = None) -> None:
        self.urls = urls
        self.fail_batches = fail_batches or set()
        self.fail_downloads = fail_downloads or set()
        self.batches: list[list[str]] = []
        self.formats: list[str] = []

    def get_image_renders(self, key: str, ids: list[str], scale: float = 2, image_format: str = "png") -> dict:
        self.batches.append(list(ids))
        self.formats.append(image_format)
        if len(self.batches) - 1 in self.fail_batches:
            raise FigmaError("Figma returned 429")
        return {"images": {node_id: self.urls.get(node_id) for node_id in ids}, "err": None}

    def download(self, url: str, dest: Path) -> tuple[int, str]:
        if url in self.fail_downloads:
            raise FigmaError("Download failed: HTTP 403.")
        content = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        dest.write_bytes(content)
        return len(content), "image/svg+xml"


def _vector_document(node_ids: list[str]) -> DesignDocument:
    return _document().model_copy(update={
        "assets": [
            AssetRecord(
                id=f"vec-{node_id.replace(':', '-')}", kind=AssetKind.SVG, role=AssetRole.DECORATIVE,
                missing_reason="Vector export URL was not supplied",
                metadata={"figma_node_id": node_id},
            )
            for node_id in node_ids
        ],
        "warnings": [
            DesignWarning(
                code="FIGMA_VECTOR_EXPORT_UNRESOLVED", message="unresolved",
                path=f"figma.nodes[{node_id}]",
            )
            for node_id in node_ids
        ],
        "analysis": DesignAnalysis(
            section_confidence_mean=0, unsupported_traits=["FIGMA_VECTOR_EXPORT_UNRESOLVED"],
        ),
    })


def test_vector_exports_download_one_svg_per_node_and_clear_their_warnings(tmp_path: Path) -> None:
    client = FakeVectorClient({"1:1": "https://signed.example/a", "1:2": "https://signed.example/b"})

    document, artifacts = acquire_figma_vector_exports(
        root=tmp_path, source_id="figma-1", file_key="file",
        document=_vector_document(["1:1", "1:2"]), client=client,
    )

    assert client.formats == ["svg"]
    assert [asset.local_path for asset in document.assets] == [
        "sources/figma-1/assets/vec-1-1.svg", "sources/figma-1/assets/vec-1-2.svg",
    ]
    assert all(asset.missing_reason is None for asset in document.assets)
    assert document.assets[0].source_url == "figma://file/node/1:1"
    assert document.warnings == []
    assert document.analysis.unsupported_traits == []
    assert (tmp_path / artifacts[0]).read_bytes().startswith(b"<svg")
    manifest = json.loads((tmp_path / "sources/figma-1/asset-manifest.json").read_text(encoding="utf-8"))
    assert [entry["downloaded"] for entry in manifest["assets"]] == [True, True]


def test_vector_exports_batch_requests_and_keep_the_warning_for_a_node_figma_cannot_render(
    tmp_path: Path,
) -> None:
    node_ids = [f"9:{index}" for index in range(45)]
    urls = {node_id: f"https://signed.example/{node_id}" for node_id in node_ids}
    urls["9:3"] = None
    client = FakeVectorClient(urls)

    document, _ = acquire_figma_vector_exports(
        root=tmp_path, source_id="figma-1", file_key="file",
        document=_vector_document(node_ids), client=client,
    )

    assert [len(batch) for batch in client.batches] == [40, 5]
    unresolved = [asset for asset in document.assets if not asset.local_path]
    assert [asset.metadata["figma_node_id"] for asset in unresolved] == ["9:3"]
    assert unresolved[0].missing_reason == "Figma did not render this vector node as an SVG."
    assert [warning.path for warning in document.warnings] == ["figma.nodes[9:3]"]
    assert document.analysis.unsupported_traits == ["FIGMA_VECTOR_EXPORT_UNRESOLVED"]


def test_vector_exports_survive_a_failed_batch_and_a_failed_download(tmp_path: Path) -> None:
    node_ids = [f"8:{index}" for index in range(41)]
    urls = {node_id: f"https://signed.example/{node_id}" for node_id in node_ids}
    client = FakeVectorClient(urls, fail_batches={1}, fail_downloads={"https://signed.example/8:0"})

    document, _ = acquire_figma_vector_exports(
        root=tmp_path, source_id="figma-1", file_key="file",
        document=_vector_document(node_ids), client=client,
    )

    by_node = {asset.metadata["figma_node_id"]: asset for asset in document.assets}
    assert by_node["8:0"].local_path is None
    assert by_node["8:0"].missing_reason == "Download failed: HTTP 403."
    failed_batch_node = sorted(node_ids)[-1]
    assert by_node[failed_batch_node].missing_reason == "Figma returned 429"
    assert by_node["8:1"].local_path is not None
    assert {warning.path for warning in document.warnings} == {
        "figma.nodes[8:0]", f"figma.nodes[{failed_batch_node}]",
    }


def test_vector_exports_do_nothing_without_unresolved_vectors(tmp_path: Path) -> None:
    client = FakeVectorClient({})

    document, artifacts = acquire_figma_vector_exports(
        root=tmp_path, source_id="figma-1", file_key="file", document=_document(), client=client,
    )

    assert client.batches == []
    assert artifacts == ()
    assert document == _document()


def test_project_analysis_exports_a_vector_logo_from_a_remote_figma_source(tmp_path: Path) -> None:
    from vanjaro_cli.orchestration import project_analysis
    from vanjaro_cli.project.models import ProjectSource

    frame = {
        "id": "1:1", "type": "FRAME", "name": "Home Desktop",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1000, "height": 1600},
        "children": [{
            "id": "5:0", "type": "INSTANCE", "name": "Navigation",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1000, "height": 100},
            "children": [
                {"id": "5:1", "type": "GROUP", "name": "Group 2",
                 "absoluteBoundingBox": {"x": 20, "y": 10, "width": 90, "height": 80},
                 "children": [
                     {"id": f"5:{index}", "type": "VECTOR", "name": "Vector", "fills": [{"type": "SOLID"}]}
                     for index in range(2, 6)
                 ]},
                {"id": "5:9", "type": "TEXT", "name": "Home", "characters": "Home",
                 "absoluteBoundingBox": {"x": 500, "y": 40, "width": 40, "height": 13}},
            ],
        }],
    }

    class RemoteFigma(FakeVectorClient):
        def get_nodes(self, key: str, ids: list[str]) -> dict:
            return {"name": "Studio (Copy)", "nodes": {ids[0]: {"document": frame}}}

        def get_image_fills(self, key: str) -> dict[str, str]:
            return {}

    client = RemoteFigma({"5:1": "https://signed.example/logo"})
    source = ProjectSource(
        id="figma-1", kind="figma", page_reference="home",
        reference="https://www.figma.com/design/FILEKEY/Studio?node-id=1-1",
    )

    document, artifacts = project_analysis._analyze_source(
        tmp_path, source, project_id="studio", captured_at=None,
        html_fetcher=lambda url: "", figma_client_factory=lambda: client,
    )

    assert client.batches == [["5:1"]]
    logo = next(asset for asset in document.assets if asset.metadata.get("role_hint") == "logo")
    assert logo.local_path == f"sources/figma-1/assets/{logo.id}.svg"
    assert "FIGMA_VECTOR_EXPORT_UNRESOLVED" not in {warning.code for warning in document.warnings}
    assert logo.local_path in artifacts
