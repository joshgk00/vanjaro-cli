"""Tests for vanjaro_cli.migration.assets download helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
import responses

from vanjaro_cli.migration import assets as assets_module
from vanjaro_cli.migration.assets import (
    _should_waf_retry,
    _waf_session,
    download_assets,
    safe_filename,
)

IMAGE_URL = "https://example.com/photo.jpg"
FAKE_IMAGE_BYTES = b"\xff\xd8\xff\xe0fake-jpeg"


# ── _should_waf_retry ────────────────────────────────────────────────────────


def test_should_waf_retry_ssl_error():
    exc = requests.exceptions.SSLError("SSL handshake failure")
    assert _should_waf_retry(exc, None) is True


def test_should_waf_retry_connection_reset():
    exc = requests.exceptions.ConnectionError("connection reset by peer")
    assert _should_waf_retry(exc, None) is True


def test_should_waf_retry_403():
    assert _should_waf_retry(None, 403) is True


def test_should_waf_retry_not_triggered_on_timeout():
    exc = requests.exceptions.Timeout("timed out")
    assert _should_waf_retry(exc, None) is False


def test_should_waf_retry_not_triggered_on_404():
    assert _should_waf_retry(None, 404) is False


def test_should_waf_retry_not_triggered_on_500():
    exc = requests.exceptions.HTTPError("500 Server Error")
    assert _should_waf_retry(exc, None) is False


# ── _waf_session ─────────────────────────────────────────────────────────────


def test_waf_session_is_reused():
    assets_module._waf_session_cache = None
    session1 = _waf_session()
    session2 = _waf_session()
    assert session1 is session2
    assets_module._waf_session_cache = None


def test_waf_session_has_browser_headers():
    assets_module._waf_session_cache = None
    session = _waf_session()
    assert "Chrome" in session.headers.get("User-Agent", "")
    assert "Accept" in session.headers
    assert "Accept-Language" in session.headers
    assets_module._waf_session_cache = None


# ── _stream_download via download_assets ─────────────────────────────────────


@responses.activate
def test_download_succeeds_without_waf_fallback(tmp_path: Path):
    """Happy path: first attempt succeeds, WAF session is never created."""
    responses.add(responses.GET, IMAGE_URL, body=FAKE_IMAGE_BYTES, status=200, content_type="image/jpeg")

    warnings: list[str] = []
    assets_module._waf_session_cache = None

    manifest = download_assets([IMAGE_URL], tmp_path, warnings.append)

    assert len(manifest) == 1
    assert manifest[0]["source_url"] == IMAGE_URL
    assert manifest[0]["uploaded"] is False
    assert warnings == []
    assert assets_module._waf_session_cache is None, "WAF session must not be created on success"


@responses.activate
def test_waf_fallback_engages_on_ssl_error(tmp_path: Path):
    """SSLError on first attempt triggers WAF retry; success on retry is recorded."""
    responses.add(responses.GET, IMAGE_URL, body=requests.exceptions.SSLError("TLS reset"))

    assets_module._waf_session_cache = None
    warnings: list[str] = []

    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.iter_content.return_value = iter([FAKE_IMAGE_BYTES])
    mock_response.close.return_value = None
    mock_response.raise_for_status.return_value = None

    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    with patch.object(assets_module, "_waf_session", return_value=mock_session):
        manifest = download_assets([IMAGE_URL], tmp_path, warnings.append)

    assert len(manifest) == 1
    assert warnings == [], f"Unexpected warnings: {warnings}"
    mock_session.get.assert_called_once_with(IMAGE_URL, timeout=30, stream=True)


@responses.activate
def test_waf_fallback_engages_on_403(tmp_path: Path):
    """HTTP 403 on first attempt triggers WAF retry."""
    responses.add(responses.GET, IMAGE_URL, status=403)

    assets_module._waf_session_cache = None
    warnings: list[str] = []

    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "image/png"}
    mock_response.iter_content.return_value = iter([FAKE_IMAGE_BYTES])
    mock_response.close.return_value = None
    mock_response.raise_for_status.return_value = None

    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    with patch.object(assets_module, "_waf_session", return_value=mock_session):
        manifest = download_assets([IMAGE_URL], tmp_path, warnings.append)

    assert len(manifest) == 1
    mock_session.get.assert_called_once()


@responses.activate
def test_waf_fallback_not_used_on_404(tmp_path: Path):
    """404 does not trigger WAF retry — it's reported as a warning, not retried."""
    responses.add(responses.GET, IMAGE_URL, status=404)

    assets_module._waf_session_cache = None
    warnings: list[str] = []

    mock_session = MagicMock()
    with patch.object(assets_module, "_waf_session", return_value=mock_session):
        manifest = download_assets([IMAGE_URL], tmp_path, warnings.append)

    assert manifest == []
    assert len(warnings) == 1
    assert IMAGE_URL in warnings[0]
    mock_session.get.assert_not_called()


@responses.activate
def test_waf_fallback_failure_reports_warning(tmp_path: Path):
    """When both attempts fail, a warning is emitted and the asset is skipped."""
    responses.add(responses.GET, IMAGE_URL, body=requests.exceptions.SSLError("TLS reset"))

    assets_module._waf_session_cache = None
    warnings: list[str] = []

    mock_session = MagicMock()
    mock_session.get.side_effect = requests.exceptions.ConnectionError("still blocked")

    with patch.object(assets_module, "_waf_session", return_value=mock_session):
        manifest = download_assets([IMAGE_URL], tmp_path, warnings.append)

    assert manifest == []
    assert len(warnings) == 1
    assert "WAF retry" in warnings[0]


# ── safe_filename ─────────────────────────────────────────────────────────────


def test_safe_filename_strips_path_and_query():
    assert safe_filename("https://example.com/images/photo.jpg?w=800") == "photo.jpg"


def test_safe_filename_rejects_windows_reserved():
    assert safe_filename("https://example.com/CON.jpg") == "asset"


def test_safe_filename_sanitizes_spaces():
    assert safe_filename("https://example.com/my image.png") == "my_image.png"
