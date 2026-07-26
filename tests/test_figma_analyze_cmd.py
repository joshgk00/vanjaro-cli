"""CliRunner and mocked-REST coverage for `vanjaro figma analyze`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import responses
from click.testing import CliRunner

from vanjaro_cli.cli import cli
from vanjaro_cli.figma import FIGMA_API_BASE


FILE_KEY = "Abc123Design"
FILE_URL = f"https://www.figma.com/design/{FILE_KEY}/Synthetic"


@pytest.fixture(autouse=True)
def figma_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIGMA_ACCESS_TOKEN", "test-token")


def _section(node_id: str, name: str, y: int, image_ref: str | None = None) -> dict:
    children = [{
        "id": f"{node_id}:1", "type": "TEXT", "name": "Heading",
        "characters": f"{name} heading",
        "style": {"fontFamily": "Test Sans", "fontSize": 48, "fontWeight": 700},
    }]
    if image_ref:
        children.append({
            "id": f"{node_id}:2", "type": "RECTANGLE", "name": f"{name} photo",
            "fills": [{"type": "IMAGE", "imageRef": image_ref}],
            "absoluteBoundingBox": {"x": 700, "y": y + 20, "width": 500, "height": 300},
        })
    return {
        "id": node_id, "type": "FRAME", "name": name, "layoutMode": "HORIZONTAL",
        "absoluteBoundingBox": {"x": 0, "y": y, "width": 1440, "height": 600},
        "children": children,
    }


def _frame(node_id: str, name: str, image_ref: str = "image-one") -> dict:
    return {
        "id": node_id, "type": "FRAME", "name": name, "layoutMode": "VERTICAL",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1440, "height": 2400},
        "children": [
            _section(f"{node_id}:10", "Hero", 0, image_ref),
            _section(f"{node_id}:20", "Feature cards", 700),
            _section(f"{node_id}:30", "Final CTA", 1500),
        ],
    }


def _file_payload(frame_count: int = 1) -> dict:
    frames = [_frame("10:1", "Home Desktop")]
    if frame_count > 1:
        frames.append(_frame("20:1", "About Desktop", "image-two"))
    return {
        "name": "Synthetic File",
        "document": {"id": "0:0", "type": "DOCUMENT", "name": "Document", "children": [{
            "id": "1:0", "type": "CANVAS", "name": "Pages", "children": frames,
        }]},
    }


def _add_file(frame_count: int = 1, status: int = 200) -> None:
    responses.add(
        responses.GET, f"{FIGMA_API_BASE}/v1/files/{FILE_KEY}",
        json=_file_payload(frame_count) if status == 200 else {"error": "denied"}, status=status,
    )


def _add_node(node_id: str = "10:1") -> None:
    responses.add(
        responses.GET, f"{FIGMA_API_BASE}/v1/files/{FILE_KEY}/nodes",
        json={"nodes": {node_id: {"document": _frame(node_id, "Home Desktop")}}}, status=200,
    )


def _add_fills(two: bool = False) -> None:
    images = {"image-one": "https://signed.invalid/image-one.png"}
    if two:
        images["image-two"] = "https://signed.invalid/image-two.png"
    responses.add(
        responses.GET, f"{FIGMA_API_BASE}/v1/files/{FILE_KEY}/images",
        json={"meta": {"images": images}}, status=200,
    )


class TestAnalyzeArtifacts:
    @responses.activate
    def test_node_mode_writes_all_four_artifacts_without_downloading(self) -> None:
        _add_node()
        _add_fills()
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, [
                "figma", "analyze", FILE_URL, "--node", "10-1",
                "--output-dir", "analysis", "--json",
            ])
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["selected_frames"] == ["10:1"]
            assert payload["downloaded"] == []
            assert set(path.name for path in Path("analysis").iterdir()) == {
                "design-document.json", "design-tokens.json",
                "theme-palette.json", "asset-manifest.json",
            }
            design = json.loads(Path("analysis/design-document.json").read_text(encoding="utf-8"))
            assert design["schema_version"] == "1.0"
            assert design["source"]["kind"] == "figma"
            assert len(design["pages"][0]["sections"]) == 3
            assert "https://signed.invalid" not in json.dumps(design)
            assert design["assets"][0]["source_url"].startswith("figma://")
            manifest = json.loads(Path("analysis/asset-manifest.json").read_text(encoding="utf-8"))
            assert manifest[0]["image_ref"] == "image-one"
            assert manifest[0]["original_available"] is True
            assert manifest[0]["downloaded"] is False
            assert not any(call.request.url.startswith("https://signed.invalid") for call in responses.calls)

    @responses.activate
    def test_all_page_frames_writes_combined_analysis(self) -> None:
        _add_file(frame_count=2)
        _add_fills(two=True)
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, [
                "figma", "analyze", FILE_URL, "--all-page-frames",
                "--output-dir", "all", "--json",
            ])
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["selected_frames"] == ["10:1", "20:1"]
            assert payload["pages"] == 2
            assert payload["assets"] == 2

    @responses.activate
    def test_single_detected_page_frame_needs_no_selection_flag(self) -> None:
        _add_file(frame_count=1)
        _add_fills()
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["figma", "analyze", FILE_URL, "--output-dir", "auto", "--json"])
            assert result.exit_code == 0, result.output
            assert json.loads(result.output)["selected_frames"] == ["10:1"]

    @responses.activate
    def test_export_assets_downloads_original_and_records_manifest(self) -> None:
        _add_node()
        _add_fills()
        responses.add(
            responses.GET, "https://signed.invalid/image-one.png",
            body=b"\x89PNG\r\n\x1a\nfixture", status=200, content_type="image/png",
        )
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, [
                "figma", "analyze", FILE_URL, "--node", "10:1",
                "--output-dir", "exported", "--export-assets", "--json",
            ])
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["downloaded"] == ["assets/hero-photo-image-on.png"]
            assert Path("exported/assets/hero-photo-image-on.png").read_bytes().startswith(b"\x89PNG")
            manifest = json.loads(Path("exported/asset-manifest.json").read_text(encoding="utf-8"))
            assert manifest[0]["downloaded"] is True
            assert manifest[0]["local_file"] == "assets/hero-photo-image-on.png"
            design = json.loads(Path("exported/design-document.json").read_text(encoding="utf-8"))
            assert "https://signed.invalid" not in json.dumps(design)
            assert design["assets"][0]["local_path"] == "assets/hero-photo-image-on.png"


class TestAnalyzeDryRunAndErrors:
    @responses.activate
    def test_dry_run_performs_analysis_without_any_files_or_downloads(self) -> None:
        _add_node()
        _add_fills()
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, [
                "figma", "analyze", FILE_URL, "--node", "10:1",
                "--output-dir", "planned", "--export-assets", "--dry-run", "--json",
            ])
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["dry_run"] is True
            assert not Path("planned").exists()
            assert not any(call.request.url.startswith("https://signed.invalid") for call in responses.calls)

    @responses.activate
    def test_ambiguous_frames_return_category_action_and_choices(self) -> None:
        _add_file(frame_count=2)
        result = CliRunner().invoke(cli, ["figma", "analyze", FILE_URL, "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["category"] == "frame_selection_required"
        assert payload["action"] == "Pass --node FRAME_ID or --all-page-frames."
        assert [frame["id"] for frame in payload["frames"]] == ["10:1", "20:1"]

    def test_conflicting_selection_flags_are_structured(self) -> None:
        result = CliRunner().invoke(cli, [
            "figma", "analyze", FILE_URL, "--node", "10:1",
            "--all-page-frames", "--json",
        ])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["category"] == "input_error"
        assert payload["action"] == "Choose one frame-selection mode."

    @responses.activate
    def test_figma_rest_failure_is_structured(self) -> None:
        _add_file(status=403)
        result = CliRunner().invoke(cli, ["figma", "analyze", FILE_URL, "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["category"] == "figma_api_error"
        assert "Verify the file URL" in payload["action"]
