"""CLI tests for the `vanjaro figma` command group."""

from __future__ import annotations

import json

import pytest
import responses
from click.testing import CliRunner

from vanjaro_cli.cli import cli
from vanjaro_cli.figma import FIGMA_API_BASE

FILE_KEY = "6VgN83G6YTBWrEAmiM2wTK"
FILE_URL = f"https://www.figma.com/design/{FILE_KEY}/Keys-to-success?node-id=156-890"


@pytest.fixture(autouse=True)
def figma_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIGMA_ACCESS_TOKEN", "test-figma-token")


def solid_fill(r: float, g: float, b: float) -> dict:
    return {"type": "SOLID", "color": {"r": r, "g": g, "b": b, "a": 1.0}}


def frame_document() -> dict:
    return {
        "id": "156:890",
        "name": "Home",
        "type": "FRAME",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1440, "height": 8090},
        "children": [
            {
                "id": "1",
                "name": "band",
                "type": "RECTANGLE",
                "fills": [solid_fill(0.0588, 0.1843, 0.1843)],
                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1440, "height": 900},
            },
            {
                "id": "2",
                "name": "hero image",
                "type": "RECTANGLE",
                "fills": [{"type": "IMAGE", "imageRef": "aaaa1111"}],
                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1440, "height": 900},
            },
            {
                "id": "3",
                "name": "Heading",
                "type": "TEXT",
                "characters": "Hi",
                "fills": [solid_fill(1, 1, 1)],
                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 400, "height": 56},
                "style": {"fontFamily": "Genova", "fontWeight": 700, "fontSize": 56, "lineHeightPx": 60},
            },
        ],
    }


def file_document() -> dict:
    return {
        "id": "0:0",
        "name": "Document",
        "type": "DOCUMENT",
        "children": [
            {
                "id": "0:1",
                "name": "Page 1",
                "type": "CANVAS",
                "children": [
                    {
                        "id": "156:890",
                        "name": "Home",
                        "type": "FRAME",
                        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1440, "height": 8090},
                    },
                    {
                        "id": "156:900",
                        "name": "Icon",
                        "type": "FRAME",
                        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 40, "height": 40},
                    },
                ],
            }
        ],
    }


def add_get_file() -> None:
    responses.add(
        responses.GET,
        f"{FIGMA_API_BASE}/v1/files/{FILE_KEY}",
        json={"document": file_document()},
        status=200,
    )


def add_get_nodes() -> None:
    responses.add(
        responses.GET,
        f"{FIGMA_API_BASE}/v1/files/{FILE_KEY}/nodes",
        json={"nodes": {"156:890": {"document": frame_document()}}},
        status=200,
    )


class TestInspect:
    @responses.activate
    def test_inspect_lists_pages(self) -> None:
        add_get_file()
        result = CliRunner().invoke(cli, ["figma", "inspect", FILE_URL, "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        frames = payload["pages"][0]["frames"]
        home = next(f for f in frames if f["id"] == "156:890")
        assert home["page_like"] is True
        icon = next(f for f in frames if f["id"] == "156:900")
        assert icon["page_like"] is False

    @responses.activate
    def test_inspect_node_summary(self) -> None:
        add_get_nodes()
        result = CliRunner().invoke(cli, ["figma", "inspect", FILE_URL, "--node", "156-890", "--json"])
        assert result.exit_code == 0, result.output
        summary = json.loads(result.output)["summary"]
        assert summary["text_nodes"] == 1
        assert summary["image_fills"] == 1
        assert "#0f2f2f" in summary["top_colors"]


class TestTokens:
    @responses.activate
    def test_tokens_writes_file(self) -> None:
        add_get_nodes()
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli,
                ["figma", "tokens", FILE_URL, "--node", "156-890", "-o", "tokens.json", "--json"],
            )
            assert result.exit_code == 0, result.output
            written = json.loads(open("tokens.json", encoding="utf-8").read())
            assert written["colors"]["$darkcolor"] == "#0f2f2f"
            assert written["fonts"]["assignments"]["headings"].startswith("Genova")

    @responses.activate
    def test_tokens_with_palette(self) -> None:
        add_get_nodes()
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli,
                ["figma", "tokens", FILE_URL, "--node", "156-890", "-o", "t.json", "--palette", "p.json"],
            )
            assert result.exit_code == 0, result.output
            palette = json.loads(open("p.json", encoding="utf-8").read())
            assert palette["dark"] == "#0f2f2f"


class TestExport:
    @responses.activate
    def test_export_dry_run(self) -> None:
        add_get_nodes()
        responses.add(
            responses.GET,
            f"{FIGMA_API_BASE}/v1/files/{FILE_KEY}/images",
            json={"meta": {"images": {"aaaa1111": "https://s3/original.png"}}},
            status=200,
        )
        result = CliRunner().invoke(
            cli, ["figma", "export", FILE_URL, "--node", "156-890", "--dry-run", "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["dry_run"] is True
        assert payload["planned"][0]["image_ref"] == "aaaa1111"

    @responses.activate
    def test_export_downloads_and_manifests(self) -> None:
        add_get_nodes()
        responses.add(
            responses.GET,
            f"{FIGMA_API_BASE}/v1/files/{FILE_KEY}/images",
            json={"meta": {"images": {"aaaa1111": "https://s3/original.png"}}},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://s3/original.png",
            body=b"\x89PNG\r\n\x1a\nfakepng",
            status=200,
            content_type="image/png",
        )
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli, ["figma", "export", FILE_URL, "--node", "156-890", "-o", "assets", "--json"]
            )
            assert result.exit_code == 0, result.output
            manifest = json.loads(open("assets/manifest.json", encoding="utf-8").read())
            assert len(manifest) == 1
            entry = manifest[0]
            assert entry["source_url"] == f"figma://{FILE_KEY}/aaaa1111"
            assert entry["filename"].endswith(".png")
            assert entry["uploaded"] is False
            assert entry["local_file"] == entry["filename"]


class TestErrors:
    def test_missing_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FIGMA_ACCESS_TOKEN", raising=False)
        result = CliRunner().invoke(cli, ["figma", "inspect", FILE_URL, "--json"])
        assert result.exit_code == 1
        assert "Missing Figma access token" in result.output

    def test_bad_url(self) -> None:
        result = CliRunner().invoke(cli, ["figma", "inspect", "https://example.com/x", "--json"])
        assert result.exit_code == 1
        assert "Could not parse" in result.output
