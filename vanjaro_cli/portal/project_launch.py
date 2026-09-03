"""Strict client contract for previewing and applying managed-site launch metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from vanjaro_cli.portal.project_publication import (
    observe_publication_action,
    publication_state_matches,
)
from vanjaro_cli.project.launch_plan import LaunchPlan


PREVIEW_LAUNCH = "/API/VanjaroAI/AILaunch/Preview"
APPLY_LAUNCH = "/API/VanjaroAI/AILaunch/Apply"
GET_LAUNCH_PAGE = "/API/VanjaroAI/AILaunch/Get"


class ProjectLaunchError(ValueError):
    """Raised when live launch metadata is stale, malformed, or unsafe."""


def prepare_launch_preview(
    client: object,
    *,
    project_id: str,
    plan: LaunchPlan,
    publish_actions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Verify exact published ownership and request an authoritative no-write preview."""

    published = {
        action.get("page_key"): action
        for action in publish_actions
        if action.get("object_type") == "page"
    }
    if len(published) != len(plan.pages):
        raise ProjectLaunchError("published page set does not match the launch plan")
    for page in plan.pages:
        action = published.get(page.page_key)
        if not isinstance(action, Mapping) or action.get("project_id") != project_id:
            raise ProjectLaunchError(
                f"page {page.page_key!r} has no project-owned publication action"
            )
        if str(action.get("object_id")) != str(page.page_id):
            raise ProjectLaunchError(
                f"page {page.page_key!r} publication identity does not match launch plan"
            )
        observed = observe_publication_action(client, action)
        if not publication_state_matches(action, observed, published=True):
            raise ProjectLaunchError(
                f"page {page.page_key!r} is not the exact published managed revision"
            )

    desired_home = (
        None
        if plan.preserve_current_home
        else next(page.page_id for page in plan.pages if page.page_key == plan.home_page_key)
    )
    response = client.post(
        PREVIEW_LAUNCH,
        json={
            "pages": [
                {
                    "pageId": page.page_id,
                    "desiredName": page.desired_name,
                    "desiredTitle": page.desired_title,
                    "desiredVisible": page.navigation_visible,
                    "parentId": page.parent_id,
                    # The design document owns relative sibling order, while
                    # DNN's TabOrder is a sparse implementation detail.  The
                    # server preserves and returns the raw value; the client
                    # validates the relative managed-page order below.
                    "tabOrder": None,
                }
                for page in plan.pages
            ],
            "preserveCurrentHome": plan.preserve_current_home,
            "desiredHomePageId": desired_home,
        },
    ).json()
    return _validated_preview(response, project_id=project_id, plan=plan)


def observe_launch_action(client: object, action: Mapping[str, Any]) -> dict[str, Any]:
    page_id = _integer(action.get("page_id"), "launch page ID", minimum=0)
    payload = client.get(GET_LAUNCH_PAGE, params={"pageId": page_id}).json()
    root = _mapping(payload, "launch state response")
    if root.get("schemaVersion") != "agency-launch-state-v1":
        raise ProjectLaunchError("unsupported launch state schema")
    if root.get("supportsExactLaunch") is not True:
        raise ProjectLaunchError("server does not advertise exact launch support")
    home_page_id = _integer(root.get("homePageId"), "home page ID")
    state = _state(root.get("page"), include_token=True)
    if state["page_id"] != page_id:
        raise ProjectLaunchError("launch state returned a different page")
    state["home_page_id"] = home_page_id
    return state


def launch_state_matches(
    action: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    after: bool,
    exact_after_token: str | None = None,
) -> bool:
    expected = action.get("after" if after else "before")
    if not isinstance(expected, Mapping):
        return False
    fields = (
        "page_id",
        "name",
        "title",
        "path",
        "is_visible",
        "parent_id",
        "tab_order",
        "culture_code",
    )
    if any(observed.get(field) != expected.get(field) for field in fields):
        return False
    if not after:
        return observed.get("metadata_token") == expected.get("metadata_token")
    token = observed.get("metadata_token")
    return isinstance(token, str) and bool(token) and (
        exact_after_token is None or token == exact_after_token
    )


def apply_launch_preview(client: object, receipt: Mapping[str, Any]) -> dict[str, Any]:
    actions = receipt.get("actions")
    home = receipt.get("home")
    if not isinstance(actions, list) or not isinstance(home, Mapping):
        raise ProjectLaunchError("launch receipt action/home contract is invalid")
    response = client.post(
        APPLY_LAUNCH,
        json={
            "schemaVersion": "agency-launch-apply-v1",
            "expectedNamespaceFingerprint": receipt.get("namespace_fingerprint"),
            "actions": [
                {
                    "before": _api_state(action["before"]),
                    "after": _api_state(action["after"]),
                }
                for action in actions
            ],
            "expectedHomePageId": home.get("before_page_id"),
            "desiredHomePageId": home.get("after_page_id"),
        },
    ).json()
    result = _validated_apply_result(response, receipt=receipt)
    observations = [observe_launch_action(client, action) for action in actions]
    for action, observed, committed in zip(
        actions, observations, result["pages"], strict=True
    ):
        if not launch_state_matches(
            action,
            observed,
            after=True,
            exact_after_token=committed["metadata_token"],
        ):
            raise ProjectLaunchError(
                f"page {action['page_key']!r} changed after the launch commit"
            )
        if observed.get("home_page_id") != result["home_page_id"]:
            raise ProjectLaunchError("launch home page changed after the commit")
    return {
        "observations": observations,
        "warnings": result["warnings"],
    }


def _validated_preview(
    value: object, *, project_id: str, plan: LaunchPlan
) -> dict[str, Any]:
    response = _mapping(value, "launch preview response")
    if response.get("schemaVersion") != "agency-launch-preview-v1":
        raise ProjectLaunchError("unsupported launch preview schema")
    if response.get("supportsExactLaunch") is not True:
        raise ProjectLaunchError("server does not advertise exact launch support")
    portal_id = _integer(response.get("portalId"), "launch preview portal ID", minimum=0)
    namespace = response.get("namespaceFingerprint")
    if not _sha256(namespace):
        raise ProjectLaunchError("launch namespace fingerprint is invalid")
    raw_actions = response.get("actions")
    if not isinstance(raw_actions, list) or len(raw_actions) != len(plan.pages):
        raise ProjectLaunchError("launch preview does not cover every planned page")
    actions: list[dict[str, Any]] = []
    for page, raw in zip(plan.pages, raw_actions, strict=True):
        item = _mapping(raw, "launch preview action")
        before = _state(item.get("before"), include_token=True)
        after = _state(item.get("after"), include_token=False)
        if before["page_id"] != page.page_id or after["page_id"] != page.page_id:
            raise ProjectLaunchError("launch preview page order/identity changed")
        expected = {
            "name": page.desired_name,
            "title": page.desired_title,
            "is_visible": page.navigation_visible,
            "parent_id": page.parent_id,
        }
        if any(after.get(key) != value for key, value in expected.items()):
            raise ProjectLaunchError(
                f"launch preview altered intended metadata for page {page.page_key!r}"
            )
        actions.append(
            {
                "project_id": project_id,
                "page_key": page.page_key,
                "page_id": page.page_id,
                "before": before,
                "after": after,
            }
        )
    _require_reviewed_relative_order(plan, actions)
    home = _mapping(response.get("home"), "launch preview home")
    before_home = _integer(home.get("beforePageId"), "current home page ID")
    after_home = _integer(home.get("afterPageId"), "desired home page ID")
    if plan.preserve_current_home:
        intended_home = before_home
    else:
        intended_home = next(
            page.page_id for page in plan.pages if page.page_key == plan.home_page_key
        )
    if after_home != intended_home:
        raise ProjectLaunchError("launch preview changed the reviewed home-page decision")
    warnings = response.get("warnings")
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise ProjectLaunchError("launch preview warnings are invalid")
    return {
        "portal_id": portal_id,
        "namespace_fingerprint": namespace,
        "actions": actions,
        "home": {"before_page_id": before_home, "after_page_id": after_home},
        "warnings": warnings,
    }


def _validated_apply_result(
    value: object, *, receipt: Mapping[str, Any]
) -> dict[str, Any]:
    response = _mapping(value, "launch apply response")
    if response.get("schemaVersion") != "agency-launch-result-v1":
        raise ProjectLaunchError("unsupported launch apply response schema")
    if response.get("supportsExactLaunch") is not True:
        raise ProjectLaunchError("server did not confirm exact launch support")
    portal_id = _integer(response.get("portalId"), "launch result portal ID", minimum=0)
    observed_portal = receipt.get("observed_portal")
    if not isinstance(observed_portal, Mapping) or portal_id != observed_portal.get(
        "portal_id"
    ):
        raise ProjectLaunchError("launch result returned a different portal")
    home = receipt.get("home")
    if not isinstance(home, Mapping):
        raise ProjectLaunchError("launch receipt home state is invalid")
    home_page_id = _integer(response.get("homePageId"), "launch result home page ID")
    if home_page_id != home.get("after_page_id"):
        raise ProjectLaunchError("launch result changed the reviewed home page")
    actions = receipt.get("actions")
    raw_pages = response.get("pages")
    if not isinstance(actions, list) or not isinstance(raw_pages, list):
        raise ProjectLaunchError("launch result page set is invalid")
    if len(actions) != len(raw_pages):
        raise ProjectLaunchError("launch result does not cover every page")
    pages: list[dict[str, Any]] = []
    for action, raw_page in zip(actions, raw_pages, strict=True):
        committed = _state(raw_page, include_token=True)
        if not launch_state_matches(action, committed, after=True):
            raise ProjectLaunchError(
                f"launch result altered intended page {action.get('page_key')!r}"
            )
        pages.append(committed)
    warnings = response.get("warnings")
    if not isinstance(warnings, list) or any(
        not isinstance(item, str) for item in warnings
    ):
        raise ProjectLaunchError("launch result warnings are invalid")
    return {
        "portal_id": portal_id,
        "home_page_id": home_page_id,
        "pages": pages,
        "warnings": warnings,
    }


def _require_reviewed_relative_order(
    plan: LaunchPlan, actions: Sequence[Mapping[str, Any]]
) -> None:
    """Require DNN's raw sibling order to agree with reviewed semantic order."""

    by_id = {action["page_id"]: action for action in actions}
    parent_keys = {page.parent_key for page in plan.pages}
    for parent_key in parent_keys:
        planned = sorted(
            (page for page in plan.pages if page.parent_key == parent_key),
            key=lambda page: page.navigation_order,
        )
        observed = sorted(
            (by_id[page.page_id]["after"] for page in planned),
            key=lambda state: (state["tab_order"], state["page_id"]),
        )
        if [page.page_id for page in planned] != [state["page_id"] for state in observed]:
            label = parent_key if parent_key is not None else "root"
            raise ProjectLaunchError(
                f"managed page order under {label!r} does not match the reviewed launch plan"
            )


def _state(value: object, *, include_token: bool) -> dict[str, Any]:
    item = _mapping(value, "launch page state")
    token = item.get("metadataToken")
    if include_token and (not isinstance(token, str) or not token):
        raise ProjectLaunchError("launch metadata token is invalid")
    state = {
        "page_id": _integer(item.get("pageId"), "launch page ID", minimum=0),
        "name": _string(item.get("name"), "launch page name"),
        "title": _string(item.get("title"), "launch page title"),
        "path": _string(item.get("path"), "launch page path"),
        "is_visible": _boolean(item.get("isVisible"), "launch page visibility"),
        "parent_id": _nullable_integer(item.get("parentId"), "launch parent ID"),
        "tab_order": _integer(item.get("tabOrder"), "launch tab order", minimum=0),
        "culture_code": _nullable_string(item.get("cultureCode"), "launch culture"),
    }
    if include_token:
        state["metadata_token"] = token
    return state


def _api_state(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pageId": value.get("page_id"),
        "metadataToken": value.get("metadata_token"),
        "name": value.get("name"),
        "title": value.get("title"),
        "path": value.get("path"),
        "isVisible": value.get("is_visible"),
        "parentId": value.get("parent_id"),
        "tabOrder": value.get("tab_order"),
        "cultureCode": value.get("culture_code"),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectLaunchError(f"{label} must be a JSON object")
    return value


def _integer(value: object, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProjectLaunchError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise ProjectLaunchError(f"{label} must be at least {minimum}")
    return value


def _nullable_integer(value: object, label: str) -> int | None:
    return None if value is None else _integer(value, label, minimum=0)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectLaunchError(f"{label} must be a nonempty string")
    return value


def _nullable_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProjectLaunchError(f"{label} must be a string or null")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ProjectLaunchError(f"{label} must be a boolean")
    return value


def _sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


__all__ = [
    "APPLY_LAUNCH",
    "GET_LAUNCH_PAGE",
    "PREVIEW_LAUNCH",
    "ProjectLaunchError",
    "apply_launch_preview",
    "launch_state_matches",
    "observe_launch_action",
    "prepare_launch_preview",
]
