"""Exact-version portal primitives for project-owned publication actions."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from vanjaro_cli.portal.page_composition import page_content_hash


GET_PAGE = "/API/VanjaroAI/AIPage/Get"
PUBLISH_PAGE = "/API/VanjaroAI/AIPage/Publish"
GET_GLOBAL = "/API/VanjaroAI/AIGlobalBlock/Get"
PUBLISH_GLOBAL = "/API/VanjaroAI/AIGlobalBlock/Publish"


class ProjectPublicationError(ValueError):
    """Raised when an exact project-owned publication cannot proceed safely."""


def prepare_publication_actions(
    client: object,
    *,
    project_id: str,
    page_records: Sequence[Mapping[str, Any]],
    global_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Observe all managed drafts and return a stable, mutation-free action list."""

    actions: list[dict[str, Any]] = []
    globals_sorted = sorted(
        global_records,
        key=lambda item: (
            {"header": 0, "footer": 1}.get(str(item.get("kind")), 2),
            str(item.get("kind", "")),
            str(item.get("guid", "")),
        ),
    )
    for record in globals_sorted:
        action = _global_action(record, project_id)
        observed = observe_publication_action(client, action)
        action["prepared_published"] = observed["published"]
        actions.append(action)
    for record in page_records:
        action = _page_action(record, project_id)
        observed = observe_publication_action(client, action)
        action["prepared_published"] = observed["published"]
        actions.append(action)
    if not actions:
        raise ProjectPublicationError("project has no managed pages or global blocks to publish")
    return actions


def observe_publication_action(
    client: object, action: Mapping[str, Any]
) -> dict[str, Any]:
    """Read and validate one action's exact live object without mutation."""

    object_type = action.get("object_type")
    project_id = action.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise ProjectPublicationError("publication project ownership is invalid")
    if object_type == "global_block":
        detail = _get_global(client, action.get("object_id"))
        _require_exact_publish_capability(detail, "global block")
        if not _owned_by_component(detail, "data-agency-project", project_id):
            raise ProjectPublicationError(
                f"global block {action.get('object_id')} no longer contains project "
                f"ownership marker {project_id!r}"
            )
        observed = {
            "object_type": "global_block",
            "object_id": str(detail.get("guid", action.get("object_id", ""))),
            "project_id": project_id,
            "version": _positive_int(detail.get("version"), "global version"),
            "desired_hash": _global_hash(detail),
            "published": _published_bool(detail, "global block"),
        }
    elif object_type == "page":
        page_id = _positive_int_text(action.get("object_id"), "page ID")
        detail = _get_page(client, page_id)
        _require_exact_publish_capability(detail, "page")
        page_key = action.get("page_key")
        if (
            not isinstance(page_key, str)
            or not _owned_by_component(detail, "data-agency-page", page_key)
            or not _owned_by_component(detail, "data-agency-project", project_id)
        ):
            raise ProjectPublicationError(
                f"page {page_id} no longer contains project/page ownership markers "
                f"{project_id!r}/{page_key!r}"
            )
        observed = {
            "object_type": "page",
            "object_id": str(page_id),
            "project_id": project_id,
            "page_key": page_key,
            "version": _positive_int(detail.get("version"), "page version"),
            "desired_hash": _page_hash(detail),
            "published": _published_bool(detail, "page"),
        }
    else:
        raise ProjectPublicationError(f"unsupported publication object: {object_type!r}")
    _require_expected_state(action, observed)
    return observed


def publish_publication_action(
    client: object, action: Mapping[str, Any]
) -> dict[str, Any]:
    """Publish one exact receipted object and prove the resulting live state."""

    before = observe_publication_action(client, action)
    if before["published"]:
        return before
    object_type = action["object_type"]
    version = int(action["version"])
    if object_type == "global_block":
        client.post(  # type: ignore[attr-defined]
            PUBLISH_GLOBAL,
            json={"guid": action["object_id"], "version": version},
        )
    else:
        client.post(  # type: ignore[attr-defined]
            PUBLISH_PAGE,
            json={"pageId": int(action["object_id"]), "version": version},
        )
    after = observe_publication_action(client, action)
    if not after["published"]:
        raise ProjectPublicationError(
            f"{object_type} {action['object_id']} did not become published"
        )
    return after


def publication_state_matches(
    action: Mapping[str, Any], observed: Mapping[str, Any], *, published: bool
) -> bool:
    """Return whether observed state is the exact intended before/after state."""

    keys = ("object_type", "object_id", "project_id", "version", "desired_hash")
    return all(action.get(key) == observed.get(key) for key in keys) and observed.get(
        "published"
    ) is published


def _global_action(record: Mapping[str, Any], project_id: str) -> dict[str, Any]:
    guid = record.get("guid")
    kind = record.get("kind")
    if not isinstance(guid, str) or not guid or not isinstance(kind, str) or not kind:
        raise ProjectPublicationError("global manifest contains an invalid GUID or kind")
    return {
        "object_type": "global_block",
        "object_id": guid,
        "project_id": project_id,
        "global_kind": kind,
        "version": _positive_int(record.get("observed_version"), "global version"),
        "desired_hash": _sha256(record.get("desired_hash"), "global desired hash"),
    }


def _page_action(record: Mapping[str, Any], project_id: str) -> dict[str, Any]:
    page_id = _positive_int(record.get("page_id"), "page ID")
    page_key = record.get("key")
    if not isinstance(page_key, str) or not page_key:
        raise ProjectPublicationError("page manifest contains an invalid page key")
    return {
        "object_type": "page",
        "object_id": str(page_id),
        "project_id": project_id,
        "page_key": page_key,
        "version": _positive_int(record.get("observed_version"), "page version"),
        "desired_hash": _sha256(record.get("desired_hash"), "page desired hash"),
    }


def _require_expected_state(
    action: Mapping[str, Any], observed: Mapping[str, Any]
) -> None:
    for key in ("object_type", "object_id", "project_id", "version", "desired_hash"):
        if observed.get(key) != action.get(key):
            raise ProjectPublicationError(
                f"{action.get('object_type')} {action.get('object_id')} {key} drifted; "
                f"expected {action.get(key)!r}, observed {observed.get(key)!r}"
            )


def _get_global(client: object, guid: object) -> dict[str, Any]:
    if not isinstance(guid, str) or not guid:
        raise ProjectPublicationError("global publication GUID is invalid")
    value = client.get(GET_GLOBAL, params={"guid": guid}).json()  # type: ignore[attr-defined]
    if not isinstance(value, dict):
        raise ProjectPublicationError(f"global {guid} returned an unexpected response")
    return value


def _get_page(client: object, page_id: int) -> dict[str, Any]:
    value = client.get(  # type: ignore[attr-defined]
        GET_PAGE,
        params={"pageId": page_id, "includeDraft": "true", "locale": "en-US"},
    ).json()
    if not isinstance(value, dict):
        raise ProjectPublicationError(f"page {page_id} returned an unexpected response")
    return value


def _global_hash(detail: Mapping[str, Any]) -> str:
    return _hash(
        {
            "content_json": _json_array(detail.get("contentJSON"), "contentJSON"),
            "style_json": _json_array(detail.get("styleJSON"), "styleJSON"),
        }
    )


def _page_hash(detail: Mapping[str, Any]) -> str:
    html = detail.get("contentHtml", "")
    if not isinstance(html, str):
        raise ProjectPublicationError("portal page contentHtml must be a string")
    return page_content_hash(
        _json_array(detail.get("contentJSON"), "contentJSON"),
        _json_array(detail.get("styleJSON"), "styleJSON"),
        html,
    )


def _owned_by_component(
    detail: Mapping[str, Any], attribute: str, expected: str
) -> bool:
    components = _json_array(detail.get("contentJSON"), "contentJSON")
    stack = list(components)
    while stack:
        component = stack.pop()
        if not isinstance(component, dict):
            continue
        attributes = component.get("attributes", {})
        if isinstance(attributes, dict) and attributes.get(attribute) == expected:
            return True
        children = component.get("components", [])
        if isinstance(children, list):
            stack.extend(children)
    return False


def _published_bool(detail: Mapping[str, Any], label: str) -> bool:
    value = detail.get("isPublished")
    if not isinstance(value, bool):
        raise ProjectPublicationError(f"portal {label} isPublished must be a boolean")
    return value


def _require_exact_publish_capability(
    detail: Mapping[str, Any], label: str
) -> None:
    if detail.get("supportsExactVersionPublish") is not True:
        raise ProjectPublicationError(
            f"portal {label} endpoint does not advertise exact-version publication support"
        )


def _json_value(value: object, label: str) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value, parse_constant=_reject_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProjectPublicationError(f"portal {label} contains invalid JSON") from exc
    if isinstance(value, (list, dict)):
        return value
    raise ProjectPublicationError(f"portal {label} has an unexpected type")


def _json_array(value: object, label: str) -> list[object]:
    parsed = _json_value(value, label)
    if not isinstance(parsed, list):
        raise ProjectPublicationError(f"portal {label} must contain a JSON array")
    return parsed


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProjectPublicationError(f"{label} is invalid")
    return value


def _positive_int_text(value: object, label: str) -> int:
    if not isinstance(value, str) or not value.isdigit():
        raise ProjectPublicationError(f"{label} is invalid")
    return _positive_int(int(value), label)


def _sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ProjectPublicationError(f"{label} is invalid")
    return value


def _hash(value: object) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")


__all__ = [
    "ProjectPublicationError",
    "observe_publication_action",
    "prepare_publication_actions",
    "publication_state_matches",
    "publish_publication_action",
]
