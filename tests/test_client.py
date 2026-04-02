"""Tests for the VanjaroClient HTTP wrapper."""

from __future__ import annotations

import json

import pytest
import responses

from vanjaro_cli.auth import AuthError
from vanjaro_cli.client import ApiError, VanjaroClient
from vanjaro_cli.config import Config, ConfigError
from tests.conftest import (
    BASE_URL, FAKE_COOKIES,
    FAKE_ANTIFORGERY_TOKEN, FAKE_HOMEPAGE_HTML,
)

TEST_PATH = "/API/Vanjaro/Page/GetPages"
TEST_URL = f"{BASE_URL}{TEST_PATH}"
HOMEPAGE_URL = f"{BASE_URL}/"


def make_client(cookies=FAKE_COOKIES) -> VanjaroClient:
    config = Config(base_url=BASE_URL, cookies=cookies)
    return VanjaroClient(config)


def _mock_homepage():
    responses.add(responses.GET, HOMEPAGE_URL, body=FAKE_HOMEPAGE_HTML, status=200)


@responses.activate
def test_get_sends_request():
    _mock_homepage()
    responses.add(responses.GET, TEST_URL, json=[], status=200)

    client = make_client()
    resp = client.get(TEST_PATH)

    assert resp.status_code == 200


@responses.activate
def test_antiforgery_token_fetched_and_sent():
    _mock_homepage()
    responses.add(responses.GET, TEST_URL, json=[], status=200)

    client = make_client()
    client.get(TEST_PATH)

    # Homepage was fetched for anti-forgery token
    assert any(c.request.url.rstrip("/") == BASE_URL for c in responses.calls)
    # Anti-forgery token was sent with the API call
    api_call = [c for c in responses.calls if TEST_PATH in c.request.url][0]
    assert api_call.request.headers["RequestVerificationToken"] == FAKE_ANTIFORGERY_TOKEN


@responses.activate
def test_antiforgery_token_reused_across_calls():
    _mock_homepage()
    responses.add(responses.GET, TEST_URL, json=[], status=200)
    responses.add(responses.GET, TEST_URL, json=[], status=200)

    client = make_client()
    client.get(TEST_PATH)
    client.get(TEST_PATH)

    homepage_calls = [c for c in responses.calls if c.request.url.rstrip("/") == BASE_URL]
    assert len(homepage_calls) == 1, "Homepage should be fetched only once per session"


@responses.activate
def test_post_sends_json_content_type():
    _mock_homepage()
    responses.add(responses.POST, TEST_URL, json={}, status=200)

    client = make_client()
    client.post(TEST_PATH, json={"data": 1})

    api_call = [c for c in responses.calls if TEST_PATH in c.request.url][0]
    assert api_call.request.headers["Content-Type"] == "application/json"


@responses.activate
def test_401_raises_auth_error():
    _mock_homepage()
    responses.add(responses.GET, TEST_URL, status=401)

    client = make_client()

    with pytest.raises(AuthError, match="Session expired"):
        client.get(TEST_PATH)


@responses.activate
def test_404_raises_api_error():
    _mock_homepage()
    responses.add(
        responses.GET, TEST_URL, json={"Message": "Not found"}, status=404
    )

    client = make_client()

    with pytest.raises(ApiError) as exc_info:
        client.get(TEST_PATH)

    assert exc_info.value.status_code == 404
    assert "Not found" in str(exc_info.value)


@responses.activate
def test_html_error_response_truncated():
    _mock_homepage()
    responses.add(
        responses.GET, TEST_URL,
        body="<html><body>404 Error Page</body></html>",
        status=404,
        content_type="text/html",
    )

    client = make_client()

    with pytest.raises(ApiError) as exc_info:
        client.get(TEST_PATH)

    assert exc_info.value.status_code == 404
    assert "HTML error page" in str(exc_info.value)
    assert "<html>" not in str(exc_info.value)


@responses.activate
def test_500_raises_api_error():
    _mock_homepage()
    responses.add(responses.GET, TEST_URL, body="Internal Server Error", status=500)

    client = make_client()

    with pytest.raises(ApiError) as exc_info:
        client.get(TEST_PATH)

    assert exc_info.value.status_code == 500


def test_no_cookies_raises_config_error():
    config = Config(base_url=BASE_URL, cookies=None)
    client = VanjaroClient(config)

    with pytest.raises(ConfigError):
        client.get(TEST_PATH)


@responses.activate
def test_error_message_extracted_from_json():
    _mock_homepage()
    responses.add(
        responses.GET, TEST_URL, json={"ExceptionMessage": "Portal mismatch"}, status=400
    )

    client = make_client()

    with pytest.raises(ApiError) as exc_info:
        client.get(TEST_PATH)

    assert "Portal mismatch" in str(exc_info.value)
