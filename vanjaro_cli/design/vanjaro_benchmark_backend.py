"""Vanjaro AIPage adapter for the page-scoped live benchmark harness.

This adapter deliberately exposes no theme, branding, navigation, or portal
settings operations.  Existing pages are only eligible when their published
state can be reconstructed with the confirmed AIPage Update/Publish endpoints.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin

import requests
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from vanjaro_cli.client import VanjaroClient
from vanjaro_cli.design.live_benchmark import AnonymousPage, LivePageTarget
from vanjaro_cli.utils.grapesjs import render_components, render_styles

__all__ = [
    "VanjaroBenchmarkBackend",
    "VanjaroBenchmarkPayloadError",
    "VanjaroBenchmarkSafetyError",
    "VanjaroContentState",
    "VanjaroPageSnapshot",
]


CREATE_PAGE = "/API/VanjaroAI/AIPage/Create"
GET_PAGE = "/API/VanjaroAI/AIPage/Get"
UPDATE_PAGE = "/API/VanjaroAI/AIPage/Update"
PUBLISH_PAGE = "/API/VanjaroAI/AIPage/Publish"
DELETE_PAGE = "/API/VanjaroAI/AIPage/Delete"


class VanjaroBenchmarkSafetyError(RuntimeError):
    """An operation cannot be reversed with the available page APIs."""


class VanjaroBenchmarkPayloadError(ValueError):
    """Generated benchmark content does not match the GrapesJS page shape."""


class _BackendModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VanjaroContentState(_BackendModel):
    """Restorable visitor/editor content for one page version."""

    components: list[dict[str, JsonValue]]
    styles: list[dict[str, JsonValue]]
    content_html: str
    version: int = Field(ge=1)
    is_published: bool

    @field_validator("components", "styles")
    @classmethod
    def _copy_tree(cls, value: list[dict[str, JsonValue]]) -> list[dict[str, JsonValue]]:
        # JSON round-tripping prevents a caller from mutating the cached snapshot
        # through a nested reference after it has been captured.
        return json.loads(json.dumps(value))


class VanjaroPageSnapshot(_BackendModel):
    """Draft and anonymous-visible state captured before benchmark mutation."""

    page_id: int = Field(gt=0)
    draft: VanjaroContentState | None
    published: VanjaroContentState | None


def _page_id(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise VanjaroBenchmarkSafetyError(f"page id must be a positive integer, got {value!r}") from exc
    if parsed <= 0 or str(parsed) != str(value).strip():
        raise VanjaroBenchmarkSafetyError(f"page id must be a positive integer, got {value!r}")
    return parsed


def _response_object(response: requests.Response, operation: str) -> dict[str, Any]:
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise VanjaroBenchmarkSafetyError(f"{operation} returned invalid JSON") from exc
    if not isinstance(body, dict):
        raise VanjaroBenchmarkSafetyError(f"{operation} returned a non-object response")
    return body


def _json_array(value: Any, field: str, *, allow_empty_object: bool = False) -> list[dict[str, JsonValue]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError) as exc:
            raise VanjaroBenchmarkSafetyError(f"{field} is not valid JSON") from exc
    if allow_empty_object and value == {}:
        value = []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise VanjaroBenchmarkSafetyError(f"{field} must be an array of JSON objects")
    return json.loads(json.dumps(value))


def _content_state(body: dict[str, Any]) -> VanjaroContentState | None:
    if not body.get("hasVanjaroContent"):
        return None
    version = body.get("version")
    content_html = body.get("contentHtml")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise VanjaroBenchmarkSafetyError("page snapshot is missing a valid content version")
    if not isinstance(content_html, str):
        raise VanjaroBenchmarkSafetyError(
            "page snapshot has no rendered contentHtml and cannot be restored safely"
        )
    return VanjaroContentState(
        components=_json_array(body.get("contentJSON"), "contentJSON"),
        styles=_json_array(body.get("styleJSON"), "styleJSON", allow_empty_object=True),
        content_html=content_html,
        version=version,
        is_published=body.get("isPublished") is True,
    )


def _payload_array(payload: Mapping[str, JsonValue], field: str) -> list[dict[str, JsonValue]]:
    value = payload.get(field)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise VanjaroBenchmarkPayloadError(f"page payload {field!r} must be an array of objects")
    return json.loads(json.dumps(value))


class VanjaroBenchmarkBackend:
    """Concrete, mutation-bounded backend for :func:`run_live_benchmark`."""

    def __init__(
        self,
        client: VanjaroClient,
        base_url: str,
        *,
        anonymous_session: requests.Session | None = None,
        anonymous_timeout: float = 30.0,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url is required")
        if anonymous_timeout <= 0:
            raise ValueError("anonymous_timeout must be greater than zero")
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._anonymous_session = anonymous_session or requests.Session()
        if self._anonymous_session.cookies:
            raise VanjaroBenchmarkSafetyError(
                "anonymous_session must not contain cookies when the backend is created"
            )
        self._anonymous_timeout = anonymous_timeout
        self._created_page_ids: set[int] = set()
        self._snapshots: dict[int, VanjaroPageSnapshot] = {}
        self._benchmark_versions: dict[int, int] = {}

    def create_isolated_page(self, name: str, slug: str) -> LivePageTarget:
        response = self._client.post(
            CREATE_PAGE,
            json={"name": slug, "title": name, "isVisible": False},
        )
        body = _response_object(response, "page creation")
        raw_id = body.get("pageId")
        if not isinstance(raw_id, int) or isinstance(raw_id, bool) or raw_id <= 0:
            raise VanjaroBenchmarkSafetyError("page creation returned no valid pageId")

        self._created_page_ids.add(raw_id)
        path = body.get("path")
        if not isinstance(path, str) or not path.strip():
            try:
                detail = self._get_page(raw_id, include_draft=True)
                path = detail.get("path")
            except Exception:
                self._delete_created_after_failed_create(raw_id)
                raise
        if not isinstance(path, str) or not path.strip():
            self._delete_created_after_failed_create(raw_id)
            raise VanjaroBenchmarkSafetyError(
                "page creation returned no anonymous path; the created page was deleted"
            )

        return LivePageTarget(
            page_id=str(raw_id),
            url=urljoin(self._base_url + "/", path.lstrip("/")),
            name=name,
            isolated=True,
        )

    def snapshot_page(self, page_id: str) -> VanjaroPageSnapshot:
        parsed_id = _page_id(page_id)
        draft = _content_state(self._get_page(parsed_id, include_draft=True))
        published = _content_state(self._get_page(parsed_id, include_draft=False))
        if published is not None and not published.is_published:
            raise VanjaroBenchmarkSafetyError(
                "published page lookup returned an unpublished version; snapshot is unsafe"
            )
        snapshot = VanjaroPageSnapshot(page_id=parsed_id, draft=draft, published=published)
        self._snapshots[parsed_id] = snapshot
        return snapshot

    def publish_page(self, page_id: str, payload: Mapping[str, JsonValue]) -> None:
        parsed_id = _page_id(page_id)
        snapshot = self._snapshots.get(parsed_id)
        if snapshot is None:
            raise VanjaroBenchmarkSafetyError("snapshot_page must succeed before publish_page")
        if parsed_id not in self._created_page_ids and snapshot.published is None:
            raise VanjaroBenchmarkSafetyError(
                "existing page has no published version and cannot be restored after publishing"
            )

        unexpected = set(payload) - {"components", "styles", "contentHtml"}
        if unexpected:
            raise VanjaroBenchmarkPayloadError(
                f"unsupported page payload fields: {', '.join(sorted(unexpected))}"
            )
        components = _payload_array(payload, "components")
        styles = _payload_array(payload, "styles")
        supplied_html = payload.get("contentHtml")
        if supplied_html is not None and not isinstance(supplied_html, str):
            raise VanjaroBenchmarkPayloadError("page payload 'contentHtml' must be a string")
        content_html = supplied_html if isinstance(supplied_html, str) else render_components(components)
        css = render_styles(styles)
        if css:
            content_html = f"<style>{css}</style>{content_html}"

        expected_version = snapshot.draft.version if snapshot.draft is not None else None
        new_version = self._update_content(
            parsed_id,
            components,
            styles,
            content_html,
            expected_version=expected_version,
        )
        # Record immediately: if Publish fails, Update has still created a draft
        # and restore_page must use that version as its concurrency guard.
        self._benchmark_versions[parsed_id] = new_version
        self._publish_version(parsed_id, new_version)

    def fetch_anonymous(self, url: str) -> AnonymousPage:
        response = self._anonymous_session.get(url, timeout=self._anonymous_timeout)
        return AnonymousPage(
            url=response.url or url,
            status_code=response.status_code,
            html=response.text,
            headers=dict(response.headers),
        )

    def restore_page(self, page_id: str, snapshot: object) -> None:
        parsed_id = _page_id(page_id)
        if not isinstance(snapshot, VanjaroPageSnapshot):
            raise VanjaroBenchmarkSafetyError("snapshot was not created by VanjaroBenchmarkBackend")
        if snapshot.page_id != parsed_id:
            raise VanjaroBenchmarkSafetyError("snapshot page id does not match restore target")
        cached = self._snapshots.get(parsed_id)
        if cached != snapshot:
            raise VanjaroBenchmarkSafetyError("snapshot does not match the cached pre-publish state")

        benchmark_version = self._benchmark_versions.get(parsed_id)
        if benchmark_version is None:
            # Publish was rejected or failed before Update mutated page content.
            return
        if snapshot.published is None:
            raise VanjaroBenchmarkSafetyError(
                "the original page was unpublished and AIPage exposes no safe unpublish operation"
            )

        restored_published_version = self._update_state(
            parsed_id,
            snapshot.published,
            expected_version=benchmark_version,
        )
        self._benchmark_versions[parsed_id] = restored_published_version
        self._publish_version(parsed_id, restored_published_version)

        if snapshot.draft is not None and snapshot.draft != snapshot.published:
            restored_draft_version = self._update_state(
                parsed_id,
                snapshot.draft,
                expected_version=restored_published_version,
            )
            self._benchmark_versions[parsed_id] = restored_draft_version

        self._benchmark_versions.pop(parsed_id, None)
        self._snapshots.pop(parsed_id, None)

    def delete_page(self, page_id: str) -> None:
        parsed_id = _page_id(page_id)
        if parsed_id not in self._created_page_ids:
            raise VanjaroBenchmarkSafetyError(
                "delete_page only accepts pages created by this backend instance"
            )
        self._client.post(DELETE_PAGE, json={"pageId": parsed_id})
        self._created_page_ids.remove(parsed_id)
        self._snapshots.pop(parsed_id, None)
        self._benchmark_versions.pop(parsed_id, None)

    def _get_page(self, page_id: int, *, include_draft: bool) -> dict[str, Any]:
        response = self._client.get(
            GET_PAGE,
            params={"pageId": page_id, "includeDraft": str(include_draft).lower()},
        )
        return _response_object(response, "page lookup")

    def _update_state(
        self,
        page_id: int,
        state: VanjaroContentState,
        *,
        expected_version: int,
    ) -> int:
        return self._update_content(
            page_id,
            state.components,
            state.styles,
            state.content_html,
            expected_version=expected_version,
        )

    def _update_content(
        self,
        page_id: int,
        components: list[dict[str, JsonValue]],
        styles: list[dict[str, JsonValue]],
        content_html: str,
        *,
        expected_version: int | None,
    ) -> int:
        payload: dict[str, Any] = {
            "pageId": page_id,
            "contentJSON": json.dumps(components),
            "styleJSON": json.dumps(styles),
            "contentHtml": content_html,
        }
        if expected_version is not None:
            payload["expectedVersion"] = expected_version
        response = self._client.post(UPDATE_PAGE, json=payload)
        body = _response_object(response, "page update")
        version = body.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise VanjaroBenchmarkSafetyError("page update returned no valid version")
        return version

    def _publish_version(self, page_id: int, version: int) -> None:
        self._client.post(PUBLISH_PAGE, json={"pageId": page_id, "version": version})

    def _delete_created_after_failed_create(self, page_id: int) -> None:
        try:
            self.delete_page(str(page_id))
        except Exception as exc:
            raise VanjaroBenchmarkSafetyError(
                f"created page {page_id} has no usable path and cleanup failed: {exc}"
            ) from exc
