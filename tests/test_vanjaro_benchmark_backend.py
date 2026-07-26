"""Mocked-HTTP coverage for the page-scoped Vanjaro benchmark adapter."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from vanjaro_cli.client import ApiError, VanjaroClient
from vanjaro_cli.config import Config
from vanjaro_cli.design.vanjaro_benchmark_backend import (
    CREATE_PAGE,
    DELETE_PAGE,
    GET_PAGE,
    PUBLISH_PAGE,
    UPDATE_PAGE,
    VanjaroBenchmarkBackend,
    VanjaroBenchmarkPayloadError,
    VanjaroBenchmarkSafetyError,
    VanjaroPageSnapshot,
)


BASE_URL = "https://benchmark.vanjaro.test"
TOKEN_HTML = (
    '<input name="__RequestVerificationToken" type="hidden" value="benchmark-token" />'
)


def _backend(*, anonymous_session: requests.Session | None = None) -> VanjaroBenchmarkBackend:
    config = Config(
        base_url=BASE_URL,
        cookies={".DOTNETNUKE": "admin-cookie"},
        api_key="benchmark-api-key",
    )
    return VanjaroBenchmarkBackend(
        VanjaroClient(config),
        BASE_URL,
        anonymous_session=anonymous_session,
        anonymous_timeout=7,
    )


def _mock_homepage() -> None:
    responses.add(responses.GET, f"{BASE_URL}/", body=TOKEN_HTML, status=200)


def _page(
    *,
    version: int = 1,
    published: bool = False,
    components: list[dict] | None = None,
    styles: list[dict] | dict | None = None,
    content_html: str = "<main>before</main>",
) -> dict:
    return {
        "tabId": 41,
        "path": "/benchmark-page",
        "version": version,
        "isPublished": published,
        "hasVanjaroContent": True,
        "contentJSON": components if components is not None else [{"type": "main"}],
        "styleJSON": styles if styles is not None else [],
        "contentHtml": content_html,
    }


def _no_content() -> dict:
    return {
        "tabId": 41,
        "path": "/benchmark-page",
        "version": 0,
        "isPublished": False,
        "hasVanjaroContent": False,
        "contentJSON": None,
        "styleJSON": None,
        "contentHtml": None,
    }


def _sent_json(call_index: int) -> dict:
    body = responses.calls[call_index].request.body
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    return json.loads(body)


@responses.activate
def test_created_page_flow_is_hidden_published_anonymously_and_deleted() -> None:
    _mock_homepage()
    responses.add(
        responses.POST,
        BASE_URL + CREATE_PAGE,
        json={"pageId": 41, "name": "vanjaro-benchmark-run", "version": 1, "path": "/benchmark-page"},
        status=201,
    )
    responses.add(responses.GET, BASE_URL + GET_PAGE, json=_page(styles={}), status=200)
    responses.add(responses.GET, BASE_URL + GET_PAGE, json=_no_content(), status=200)
    responses.add(responses.POST, BASE_URL + UPDATE_PAGE, json={"pageId": 41, "version": 2}, status=200)
    responses.add(responses.POST, BASE_URL + PUBLISH_PAGE, json={"pageId": 41, "version": 2}, status=200)
    responses.add(
        responses.GET,
        f"{BASE_URL}/benchmark-page",
        body="<main>anonymous benchmark content</main>",
        headers={"Content-Type": "text/html"},
        status=200,
    )
    responses.add(responses.POST, BASE_URL + DELETE_PAGE, json={"pageId": 41, "deleted": True}, status=200)
    backend = _backend()

    target = backend.create_isolated_page("Benchmark Run", "vanjaro-benchmark-run")
    snapshot = backend.snapshot_page(target.page_id)
    backend.publish_page(
        target.page_id,
        {
            "components": [{"tagName": "main", "content": "anonymous benchmark content"}],
            "styles": [{"selectors": ["hero"], "style": {"color": "red"}}],
        },
    )
    anonymous = backend.fetch_anonymous(target.url)
    backend.delete_page(target.page_id)

    assert target.page_id == "41"
    assert target.url == f"{BASE_URL}/benchmark-page"
    assert target.name == "Benchmark Run"
    assert target.isolated
    assert isinstance(snapshot, VanjaroPageSnapshot)
    assert snapshot.published is None
    assert anonymous.status_code == 200
    assert anonymous.html == "<main>anonymous benchmark content</main>"

    create_request = _sent_json(1)
    assert create_request == {
        "name": "vanjaro-benchmark-run",
        "title": "Benchmark Run",
        "isVisible": False,
    }
    get_calls = [call for call in responses.calls if urlparse(call.request.url).path == GET_PAGE]
    assert [parse_qs(urlparse(call.request.url).query)["includeDraft"] for call in get_calls] == [
        ["true"],
        ["false"],
    ]
    update_call = next(call for call in responses.calls if urlparse(call.request.url).path == UPDATE_PAGE)
    update_body = json.loads(update_call.request.body)
    assert update_body["pageId"] == 41
    assert update_body["expectedVersion"] == 1
    assert json.loads(update_body["contentJSON"])[0]["tagName"] == "main"
    assert json.loads(update_body["styleJSON"])[0]["style"] == {"color": "red"}
    assert update_body["contentHtml"].startswith("<style>.hero{color:red}</style><main>")
    publish_call = next(call for call in responses.calls if urlparse(call.request.url).path == PUBLISH_PAGE)
    assert json.loads(publish_call.request.body) == {"pageId": 41, "version": 2}
    anonymous_call = next(
        call for call in responses.calls if urlparse(call.request.url).path == "/benchmark-page"
    )
    assert "Cookie" not in anonymous_call.request.headers
    assert "X-Api-Key" not in anonymous_call.request.headers
    assert "RequestVerificationToken" not in anonymous_call.request.headers


@responses.activate
def test_restore_reconstructs_original_published_version_then_unpublished_draft() -> None:
    _mock_homepage()
    original_draft = _page(
        version=3,
        published=False,
        components=[{"type": "draft"}],
        content_html="<main>original draft</main>",
    )
    original_published = _page(
        version=2,
        published=True,
        components=[{"type": "published"}],
        content_html="<main>original published</main>",
    )
    responses.add(responses.GET, BASE_URL + GET_PAGE, json=original_draft, status=200)
    responses.add(responses.GET, BASE_URL + GET_PAGE, json=original_published, status=200)
    responses.add(responses.POST, BASE_URL + UPDATE_PAGE, json={"version": 4}, status=200)
    responses.add(responses.POST, BASE_URL + PUBLISH_PAGE, json={"version": 4}, status=200)
    responses.add(responses.POST, BASE_URL + UPDATE_PAGE, json={"version": 5}, status=200)
    responses.add(responses.POST, BASE_URL + PUBLISH_PAGE, json={"version": 5}, status=200)
    responses.add(responses.POST, BASE_URL + UPDATE_PAGE, json={"version": 6}, status=200)
    backend = _backend()

    snapshot = backend.snapshot_page("41")
    backend.publish_page("41", {"components": [{"type": "benchmark"}], "styles": []})
    backend.restore_page("41", snapshot)

    mutations = [
        call for call in responses.calls if urlparse(call.request.url).path in {UPDATE_PAGE, PUBLISH_PAGE}
    ]
    assert [urlparse(call.request.url).path for call in mutations] == [
        UPDATE_PAGE,
        PUBLISH_PAGE,
        UPDATE_PAGE,
        PUBLISH_PAGE,
        UPDATE_PAGE,
    ]
    first_restore = json.loads(mutations[2].request.body)
    assert first_restore["expectedVersion"] == 4
    assert json.loads(first_restore["contentJSON"]) == [{"type": "published"}]
    assert first_restore["contentHtml"] == "<main>original published</main>"
    assert json.loads(mutations[3].request.body) == {"pageId": 41, "version": 5}
    second_restore = json.loads(mutations[4].request.body)
    assert second_restore["expectedVersion"] == 5
    assert json.loads(second_restore["contentJSON"]) == [{"type": "draft"}]
    assert second_restore["contentHtml"] == "<main>original draft</main>"


@responses.activate
def test_existing_never_published_page_is_refused_before_mutation() -> None:
    _mock_homepage()
    responses.add(responses.GET, BASE_URL + GET_PAGE, json=_page(), status=200)
    responses.add(responses.GET, BASE_URL + GET_PAGE, json=_no_content(), status=200)
    backend = _backend()
    snapshot = backend.snapshot_page("41")

    with pytest.raises(VanjaroBenchmarkSafetyError, match="no published version"):
        backend.publish_page("41", {"components": [], "styles": []})
    backend.restore_page("41", snapshot)

    assert all(
        urlparse(call.request.url).path not in {UPDATE_PAGE, PUBLISH_PAGE}
        for call in responses.calls
    )


@responses.activate
def test_failed_update_does_not_trigger_destructive_restore() -> None:
    _mock_homepage()
    responses.add(responses.GET, BASE_URL + GET_PAGE, json=_page(version=7), status=200)
    responses.add(responses.GET, BASE_URL + GET_PAGE, json=_page(version=7, published=True), status=200)
    responses.add(
        responses.POST,
        BASE_URL + UPDATE_PAGE,
        json={"Message": "Version conflict"},
        status=409,
    )
    backend = _backend()
    snapshot = backend.snapshot_page("41")

    with pytest.raises(ApiError, match="Version conflict"):
        backend.publish_page("41", {"components": [], "styles": []})
    backend.restore_page("41", snapshot)

    mutation_calls = [
        call for call in responses.calls if urlparse(call.request.url).path in {UPDATE_PAGE, PUBLISH_PAGE}
    ]
    assert len(mutation_calls) == 1


@responses.activate
def test_create_without_path_resolves_it_from_confirmed_page_get() -> None:
    _mock_homepage()
    responses.add(responses.POST, BASE_URL + CREATE_PAGE, json={"pageId": 41}, status=201)
    responses.add(responses.GET, BASE_URL + GET_PAGE, json=_page(), status=200)
    backend = _backend()

    target = backend.create_isolated_page("Benchmark", "benchmark")

    assert target.url == f"{BASE_URL}/benchmark-page"


@responses.activate
def test_create_without_recoverable_path_deletes_page_before_raising() -> None:
    _mock_homepage()
    responses.add(responses.POST, BASE_URL + CREATE_PAGE, json={"pageId": 41}, status=201)
    detail = _page()
    detail["path"] = ""
    responses.add(responses.GET, BASE_URL + GET_PAGE, json=detail, status=200)
    responses.add(responses.POST, BASE_URL + DELETE_PAGE, json={"deleted": True}, status=200)
    backend = _backend()

    with pytest.raises(VanjaroBenchmarkSafetyError, match="created page was deleted"):
        backend.create_isolated_page("Benchmark", "benchmark")

    assert urlparse(responses.calls[-1].request.url).path == DELETE_PAGE
    assert json.loads(responses.calls[-1].request.body) == {"pageId": 41}


def test_delete_refuses_any_page_not_created_by_this_backend() -> None:
    backend = _backend()

    with pytest.raises(VanjaroBenchmarkSafetyError, match="only accepts pages created"):
        backend.delete_page("41")


def test_publish_requires_snapshot_and_strict_generated_payload() -> None:
    backend = _backend()

    with pytest.raises(VanjaroBenchmarkSafetyError, match="snapshot_page must succeed"):
        backend.publish_page("41", {"components": [], "styles": []})


@responses.activate
@pytest.mark.parametrize(
    "payload",
    [
        {"components": {}, "styles": []},
        {"components": [], "styles": "not-json"},
        {"components": [], "styles": [], "contentHtml": 123},
        {"components": [], "styles": [], "portalSettings": {}},
    ],
)
def test_publish_rejects_malformed_or_out_of_scope_payload(payload: dict) -> None:
    _mock_homepage()
    responses.add(responses.GET, BASE_URL + GET_PAGE, json=_page(published=True), status=200)
    responses.add(responses.GET, BASE_URL + GET_PAGE, json=_page(published=True), status=200)
    backend = _backend()
    backend.snapshot_page("41")

    with pytest.raises(VanjaroBenchmarkPayloadError):
        backend.publish_page("41", payload)

    assert all(urlparse(call.request.url).path != UPDATE_PAGE for call in responses.calls)


def test_anonymous_session_must_start_without_cookies() -> None:
    session = requests.Session()
    session.cookies.set(".DOTNETNUKE", "accidental-admin-cookie")

    with pytest.raises(VanjaroBenchmarkSafetyError, match="must not contain cookies"):
        _backend(anonymous_session=session)
