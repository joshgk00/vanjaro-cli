"""Unit tests for the Figma REST client and URL parsing."""

from __future__ import annotations

import json

import pytest
import responses

from vanjaro_cli.figma import (
    FIGMA_API_BASE,
    FigmaClient,
    FigmaError,
    parse_file_key,
    parse_node_id,
)

FILE_KEY = "6VgN83G6YTBWrEAmiM2wTK"


def make_client() -> FigmaClient:
    return FigmaClient(token="test-figma-token")


class TestParseFileKey:
    def test_bare_key(self) -> None:
        assert parse_file_key(FILE_KEY) == FILE_KEY

    def test_design_url(self) -> None:
        url = f"https://www.figma.com/design/{FILE_KEY}/Keys-to-success?node-id=156-890"
        assert parse_file_key(url) == FILE_KEY

    def test_file_url(self) -> None:
        url = f"https://www.figma.com/file/{FILE_KEY}/Some-Name"
        assert parse_file_key(url) == FILE_KEY

    def test_empty_raises(self) -> None:
        with pytest.raises(FigmaError, match="No Figma file URL"):
            parse_file_key("")

    def test_unparseable_raises(self) -> None:
        with pytest.raises(FigmaError, match="Could not parse"):
            parse_file_key("https://example.com/not-figma")


class TestParseNodeId:
    def test_none(self) -> None:
        assert parse_node_id(None) is None

    def test_dash_to_colon(self) -> None:
        assert parse_node_id("156-890") == "156:890"

    def test_colon_passthrough(self) -> None:
        assert parse_node_id("156:890") == "156:890"

    def test_from_url(self) -> None:
        url = f"https://www.figma.com/design/{FILE_KEY}/Name?node-id=156-890&t=abc"
        assert parse_node_id(url) == "156:890"

    def test_invalid_raises(self) -> None:
        with pytest.raises(FigmaError, match="Could not parse a node id"):
            parse_node_id("not-a-node")


class TestFigmaClient:
    def test_missing_token_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FIGMA_ACCESS_TOKEN", raising=False)
        with pytest.raises(FigmaError, match="Missing Figma access token"):
            FigmaClient()

    def test_token_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FIGMA_ACCESS_TOKEN", "env-token")
        client = FigmaClient()
        assert client._session.headers["X-Figma-Token"] == "env-token"

    @responses.activate
    def test_get_file_sends_token_and_depth(self) -> None:
        responses.add(
            responses.GET,
            f"{FIGMA_API_BASE}/v1/files/{FILE_KEY}",
            json={"document": {"id": "0:0"}},
            status=200,
        )
        result = make_client().get_file(FILE_KEY, depth=2)
        assert result["document"]["id"] == "0:0"
        request = responses.calls[0].request
        assert request.headers["X-Figma-Token"] == "test-figma-token"
        assert "depth=2" in request.url

    @responses.activate
    def test_get_nodes_sends_ids(self) -> None:
        responses.add(
            responses.GET,
            f"{FIGMA_API_BASE}/v1/files/{FILE_KEY}/nodes",
            json={"nodes": {"156:890": {"document": {}}}},
            status=200,
        )
        make_client().get_nodes(FILE_KEY, ["156:890"])
        assert "ids=156%3A890" in responses.calls[0].request.url

    def test_get_nodes_requires_ids(self) -> None:
        with pytest.raises(FigmaError, match="at least one node id"):
            make_client().get_nodes(FILE_KEY, [])

    @responses.activate
    def test_get_image_renders_params(self) -> None:
        responses.add(
            responses.GET,
            f"{FIGMA_API_BASE}/v1/images/{FILE_KEY}",
            json={"images": {"156:890": "https://s3/render.png"}, "err": None},
            status=200,
        )
        result = make_client().get_image_renders(FILE_KEY, ["156:890"], scale=2)
        assert result["images"]["156:890"] == "https://s3/render.png"
        url = responses.calls[0].request.url
        assert "scale=2" in url and "format=png" in url

    @responses.activate
    def test_get_image_fills_returns_meta_images(self) -> None:
        responses.add(
            responses.GET,
            f"{FIGMA_API_BASE}/v1/files/{FILE_KEY}/images",
            json={"meta": {"images": {"abc123": "https://s3/original.png"}}},
            status=200,
        )
        fills = make_client().get_image_fills(FILE_KEY)
        assert fills == {"abc123": "https://s3/original.png"}

    @responses.activate
    def test_403_raises_clear_error(self) -> None:
        responses.add(
            responses.GET,
            f"{FIGMA_API_BASE}/v1/files/{FILE_KEY}",
            status=403,
        )
        with pytest.raises(FigmaError, match="403 Forbidden"):
            make_client().get_file(FILE_KEY)

    @responses.activate
    def test_404_raises(self) -> None:
        responses.add(
            responses.GET,
            f"{FIGMA_API_BASE}/v1/files/{FILE_KEY}",
            status=404,
        )
        with pytest.raises(FigmaError, match="404 Not Found"):
            make_client().get_file(FILE_KEY)

    @responses.activate
    def test_download_writes_bytes(self, tmp_path) -> None:
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"fake"
        responses.add(
            responses.GET,
            "https://s3/original.png",
            body=png_bytes,
            status=200,
            content_type="image/png",
        )
        dest = tmp_path / "sub" / "image.png"
        size, content_type = make_client().download("https://s3/original.png", dest)
        assert dest.read_bytes() == png_bytes
        assert size == len(png_bytes)
        assert content_type == "image/png"

    @responses.activate
    def test_download_error_never_leaks_signed_url(self, tmp_path) -> None:
        signed = "https://s3.invalid/original.png?X-Amz-Signature=secret&Expires=60"
        responses.add(responses.GET, signed, status=403)

        with pytest.raises(FigmaError) as error:
            make_client().download(signed, tmp_path / "image.png")

        assert "X-Amz-Signature" not in str(error.value)
        assert "secret" not in str(error.value)
        assert "HTTP 403" in str(error.value)
