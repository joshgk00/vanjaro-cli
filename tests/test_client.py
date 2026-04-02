"""Tests for the VanjaroClient HTTP wrapper."""

from __future__ import annotations

import pytest
import responses

from vanjaro_cli.auth import AuthError
from vanjaro_cli.client import ApiError, VanjaroClient
from vanjaro_cli.config import Config, ConfigError
from tests.conftest import BASE_URL, FAKE_TOKEN, FAKE_REFRESH_TOKEN

CSRF_URL = f"{BASE_URL}/API/PersonaBar/Security/GetAntiForgeryToken"
TEST_PATH = "/API/PersonaBar/Pages/SearchPages"
TEST_URL = f"{BASE_URL}{TEST_PATH}"
REISSUE_URL = f"{BASE_URL}/API/JwtAuth/ReIssueToken"


def make_client(token=FAKE_TOKEN, refresh=FAKE_REFRESH_TOKEN) -> VanjaroClient:
    config = Config(base_url=BASE_URL, token=token, refresh_token=refresh)
    return VanjaroClient(config)


@responses.activate
def test_get_injects_auth_header():
    responses.add(responses.GET, TEST_URL, json={"pages": []}, status=200)

    client = make_client()
    resp = client.get(TEST_PATH, params={"portalId": 0})

    assert resp.status_code == 200
    sent = responses.calls[0].request
    assert "Authorization" in sent.headers
    assert sent.headers["Authorization"].startswith("Bearer ")


@responses.activate
def test_post_fetches_csrf_token():
    responses.add(responses.GET, CSRF_URL, json={"token": "csrf-xyz"}, status=200)
    responses.add(responses.POST, TEST_URL, json={}, status=200)

    client = make_client()
    client.post(TEST_PATH, json={"data": 1})

    # CSRF endpoint was called
    assert any(CSRF_URL in call.request.url for call in responses.calls)
    # POST had the token in header
    post_call = responses.calls[-1]
    assert post_call.request.headers.get("RequestVerificationToken") == "csrf-xyz"


@responses.activate
def test_csrf_token_reused_across_calls():
    responses.add(responses.GET, CSRF_URL, json={"token": "csrf-xyz"}, status=200)
    responses.add(responses.POST, TEST_URL, json={}, status=200)
    responses.add(responses.POST, TEST_URL, json={}, status=200)

    client = make_client()
    client.post(TEST_PATH, json={})
    client.post(TEST_PATH, json={})

    csrf_calls = [c for c in responses.calls if CSRF_URL in c.request.url]
    assert len(csrf_calls) == 1, "CSRF token should be fetched only once per session"


@responses.activate
def test_401_triggers_token_refresh():
    new_token = FAKE_TOKEN + "_new"
    responses.add(responses.GET, TEST_URL, status=401)
    responses.add(responses.GET, REISSUE_URL, json={"Token": new_token}, status=200)
    responses.add(responses.GET, TEST_URL, json={"pages": []}, status=200)

    client = make_client()
    resp = client.get(TEST_PATH)

    assert resp.status_code == 200
    # Reissue was called
    assert any(REISSUE_URL in call.request.url for call in responses.calls)


@responses.activate
def test_double_401_raises_auth_error():
    responses.add(responses.GET, TEST_URL, status=401)
    responses.add(responses.GET, REISSUE_URL, status=401)

    client = make_client()

    with pytest.raises(AuthError):
        client.get(TEST_PATH)


@responses.activate
def test_404_raises_api_error():
    responses.add(
        responses.GET, TEST_URL, json={"Message": "Not found"}, status=404
    )

    client = make_client()

    with pytest.raises(ApiError) as exc_info:
        client.get(TEST_PATH)

    assert exc_info.value.status_code == 404
    assert "Not found" in str(exc_info.value)


@responses.activate
def test_500_raises_api_error():
    responses.add(responses.GET, TEST_URL, body="Internal Server Error", status=500)

    client = make_client()

    with pytest.raises(ApiError) as exc_info:
        client.get(TEST_PATH)

    assert exc_info.value.status_code == 500


def test_no_token_raises_config_error():
    config = Config(base_url=BASE_URL, token=None)
    client = VanjaroClient(config)

    with pytest.raises(ConfigError):
        client.get(TEST_PATH)


@responses.activate
def test_error_message_extracted_from_json():
    responses.add(
        responses.GET, TEST_URL, json={"ExceptionMessage": "Portal mismatch"}, status=400
    )

    client = make_client()

    with pytest.raises(ApiError) as exc_info:
        client.get(TEST_PATH)

    assert "Portal mismatch" in str(exc_info.value)
