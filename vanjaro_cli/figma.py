"""Read-only client for the Figma REST API.

Fetches file/node JSON, image-fill originals, and frame renders so the
site-builder pipeline can pull exact design tokens and original-resolution
assets from a Figma design instead of eyeballing a mockup.

Authentication uses a personal access token from the ``FIGMA_ACCESS_TOKEN``
environment variable (``.env`` is loaded by ``cli.py``), sent as the
``X-Figma-Token`` header.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import requests

__all__ = [
    "FIGMA_API_BASE",
    "FigmaError",
    "FigmaClient",
    "parse_file_key",
    "parse_node_id",
]

FIGMA_API_BASE = "https://api.figma.com"
_TOKEN_ENV_VAR = "FIGMA_ACCESS_TOKEN"
_REQUEST_TIMEOUT = 60

# figma.com/file/<KEY>/... or figma.com/design/<KEY>/...
_FILE_URL_RE = re.compile(r"figma\.com/(?:file|design)/([A-Za-z0-9]+)")
# A bare key is alphanumeric with no slashes.
_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9]+$")
_NODE_QUERY_RE = re.compile(r"[?&]node-id=([^&]+)")


class FigmaError(Exception):
    """Raised when a Figma request fails or the client is misconfigured."""


def parse_file_key(url_or_key: str) -> str:
    """Extract a Figma file key from a share URL or accept a bare key.

    Accepts ``figma.com/file/<KEY>/...``, ``figma.com/design/<KEY>/...``,
    or a raw key. Raises ``FigmaError`` when no key can be found.
    """
    value = (url_or_key or "").strip()
    if not value:
        raise FigmaError("No Figma file URL or key provided.")

    match = _FILE_URL_RE.search(value)
    if match:
        return match.group(1)
    if "figma.com" not in value and _BARE_KEY_RE.match(value):
        return value
    raise FigmaError(
        f"Could not parse a Figma file key from {url_or_key!r}. "
        "Expected a figma.com/file|design/<KEY> URL or a bare file key."
    )


def parse_node_id(url_or_id: str | None) -> str | None:
    """Extract and normalize a node id to the colon form the API returns.

    Accepts a bare id (``156-890`` or ``156:890``) or a Figma URL carrying a
    ``node-id`` query param. Figma URLs use the dash form; API responses key
    nodes by the colon form, so this always returns colon form. Returns None
    when nothing is supplied.
    """
    if not url_or_id:
        return None
    value = url_or_id.strip()

    query_match = _NODE_QUERY_RE.search(value)
    if query_match:
        value = query_match.group(1)

    value = value.replace("-", ":")
    if not re.match(r"^[0-9]+:[0-9]+$", value):
        raise FigmaError(
            f"Could not parse a node id from {url_or_id!r}. "
            "Expected e.g. 156-890, 156:890, or a URL with a node-id param."
        )
    return value


class FigmaClient:
    """Minimal read-only wrapper over the Figma REST API."""

    def __init__(self, token: str | None = None) -> None:
        resolved = token or os.environ.get(_TOKEN_ENV_VAR)
        if not resolved:
            raise FigmaError(
                f"Missing Figma access token. Set {_TOKEN_ENV_VAR} in your "
                "environment or .env file (a personal access token from "
                "figma.com > Settings > Personal access tokens)."
            )
        self._session = requests.Session()
        self._session.headers.update({"X-Figma-Token": resolved})

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict:
        url = f"{FIGMA_API_BASE}{path}"
        try:
            response = self._session.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise FigmaError(f"Figma request failed ({url}): {exc}") from exc

        if response.status_code == 403:
            raise FigmaError(
                "Figma returned 403 Forbidden. Check that FIGMA_ACCESS_TOKEN is "
                "valid and has access to this file."
            )
        if response.status_code == 404:
            raise FigmaError(f"Figma returned 404 Not Found for {path}.")
        if response.status_code != 200:
            raise FigmaError(
                f"Figma request to {path} failed ({response.status_code}): "
                f"{response.text[:200]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise FigmaError(f"Figma returned invalid JSON for {path}: {exc}") from exc

    def get_file(
        self,
        key: str,
        depth: int | None = None,
        node_ids: list[str] | None = None,
    ) -> dict:
        """GET /v1/files/:key — the document tree (optionally depth-limited)."""
        params: dict[str, str] = {}
        if depth is not None:
            params["depth"] = str(depth)
        if node_ids:
            params["ids"] = ",".join(node_ids)
        return self._get(f"/v1/files/{key}", params or None)

    def get_nodes(self, key: str, ids: list[str]) -> dict:
        """GET /v1/files/:key/nodes — subtrees for specific node ids."""
        if not ids:
            raise FigmaError("get_nodes requires at least one node id.")
        return self._get(f"/v1/files/{key}/nodes", {"ids": ",".join(ids)})

    def get_image_renders(
        self,
        key: str,
        ids: list[str],
        scale: float = 2,
        image_format: str = "png",
    ) -> dict:
        """GET /v1/images/:key — rendered images for nodes.

        Returns ``{"images": {id: signed_url}, "err": ...}``. Figma caps
        renders at ~4096px on the longest side regardless of ``scale``.
        """
        if not ids:
            raise FigmaError("get_image_renders requires at least one node id.")
        params = {
            "ids": ",".join(ids),
            "scale": str(scale),
            "format": image_format,
        }
        return self._get(f"/v1/images/{key}", params)

    def get_image_fills(self, key: str) -> dict[str, str]:
        """GET /v1/files/:key/images — imageRef -> signed original URL.

        Returns the ``meta.images`` map. These are the original uploaded
        assets at full resolution (preferred over renders for export).
        """
        payload = self._get(f"/v1/files/{key}/images")
        meta = payload.get("meta") or {}
        images = meta.get("images") or {}
        if not isinstance(images, dict):
            raise FigmaError("Figma image-fills response had an unexpected shape.")
        return images

    def download(self, url: str, dest: Path) -> tuple[int, str]:
        """Download ``url`` to ``dest``; return (size_bytes, content_type)."""
        try:
            response = self._session.get(url, timeout=_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise FigmaError(
                f"Download failed: {exc.__class__.__name__}."
            ) from exc
        if response.status_code != 200:
            raise FigmaError(
                f"Download failed: HTTP {response.status_code}."
            )
        content = response.content
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
        return len(content), content_type
