"""Draft-only portal reconciliation for project-owned global blocks.

Composition is intentionally kept in :mod:`vanjaro_cli.portal.global_blocks`.
This module owns the live-state comparison, immutable replacement workflow,
and resumable manifest mechanics used by both preview and execution.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from vanjaro_cli.portal.global_block_manifest import (
    ProjectGlobalBlockError,
    load_global_block_manifest,
    persist_global_block_manifest,
    write_json,
)
from vanjaro_cli.utils.grapesjs import render_components


LIST_BLOCKS = "/API/VanjaroAI/AIGlobalBlock/List"
GET_BLOCK = "/API/VanjaroAI/AIGlobalBlock/Get"
CREATE_BLOCK = "/API/Vanjaro/Block/AddCustomBlock"
UPDATE_BLOCK = "/API/VanjaroAI/AIGlobalBlock/Update"


def preview_project_global_blocks(
    client: object,
    *,
    desired: list[dict[str, Any]],
    manifest_path: Path,
) -> dict[str, Any]:
    actions = _preflight(client, desired, load_global_block_manifest(manifest_path))
    return {
        "schema_version": "1.0",
        "total": len(actions),
        "to_create": sum(item["action"] == "create" for item in actions),
        "to_replace": sum(
            item["action"] in {"replace_create", "replace_finish"}
            for item in actions
        ),
        "reused": sum(item["action"] in {"reuse", "adopt"} for item in actions),
        "blocks": actions,
    }


def reconcile_project_global_blocks(
    client: object,
    *,
    desired: list[dict[str, Any]],
    manifest_path: Path,
    snapshots_dir: Path | None = None,
) -> list[dict[str, Any]]:
    manifest = load_global_block_manifest(manifest_path)
    actions = _preflight(client, desired, manifest)
    desired_by_key = {item["key"]: item for item in desired}
    records: dict[str, dict[str, Any]] = {}
    prior = {
        item["key"]: item
        for item in manifest.get("blocks", [])
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }
    for action in actions:
        item = desired_by_key[action["key"]]
        if action["action"] in {"reuse", "adopt"}:
            detail = _get(client, action["guid"])
            record = _record(item, detail, action["action"])
        elif action["action"] in {"replace_finish", "replace_create"}:
            record = _reconcile_replacement(
                client,
                item=item,
                action=action,
                manifest_path=manifest_path,
                desired=desired,
                records=records,
                prior=prior,
                snapshots_dir=snapshots_dir,
            )
        elif action["action"] == "create":
            record = _create_draft(
                client,
                item=item,
                manifest_path=manifest_path,
                desired=desired,
                records=records,
                prior=prior,
            )
        else:
            raise ProjectGlobalBlockError(
                f"unsupported global reconciliation action: {action['action']!r}"
            )
        records[item["key"]] = record
        persist_global_block_manifest(manifest_path, desired, records, prior)
    return [records[item["key"]] for item in desired]


def _reconcile_replacement(
    client: object,
    *,
    item: dict[str, Any],
    action: dict[str, Any],
    manifest_path: Path,
    desired: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    prior: dict[str, dict[str, Any]],
    snapshots_dir: Path | None,
) -> dict[str, Any]:
    replacement_name = action["replacement_name"]
    guid = action.get("guid")
    if action["action"] == "replace_create":
        guid = _create_placeholder(client, item, replacement_name)
        placeholder_detail = _get(client, guid)
        records[item["key"]] = _record(
            item,
            placeholder_detail,
            "placeholder_created",
            desired=False,
        )
        persist_global_block_manifest(manifest_path, desired, records, prior)
    assert isinstance(guid, str)
    detail = _get(client, guid)
    if snapshots_dir is not None:
        write_json(
            snapshots_dir / item["key"] / f"before-v{detail.get('version', 0)}.json",
            detail,
        )
    response_payload = _update_draft(client, item, guid)
    refreshed = _get(client, guid)
    if _server_hash(refreshed) != item["desired_hash"]:
        raise ProjectGlobalBlockError(
            f"replacement global verification failed for {replacement_name!r}; "
            f"response={response_payload}"
        )
    _require_unpublished(refreshed, replacement_name, replacement=True)
    return _record(item, refreshed, "replaced")


def _create_draft(
    client: object,
    *,
    item: dict[str, Any],
    manifest_path: Path,
    desired: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    prior: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    guid = _create_placeholder(client, item, item["name"])
    placeholder_detail = _get(client, guid)
    records[item["key"]] = _record(
        item, placeholder_detail, "placeholder_created", desired=False
    )
    persist_global_block_manifest(manifest_path, desired, records, prior)
    response_payload = _update_draft(client, item, guid)
    detail = _get(client, guid)
    if _server_hash(detail) != item["desired_hash"]:
        raise ProjectGlobalBlockError(
            f"global draft verification failed for {item['name']!r}; "
            f"response={response_payload}"
        )
    _require_unpublished(detail, item["name"])
    return _record(item, detail, "created")


def _create_placeholder(
    client: object,
    item: dict[str, Any],
    portal_name: str,
) -> str:
    placeholder = _placeholder(item)
    response = client.post_form(  # type: ignore[attr-defined]
        CREATE_BLOCK,
        {
            "Name": portal_name,
            "Category": item["category"],
            "Html": render_components(placeholder),
            "Css": "",
            "IsGlobal": "true",
            "ContentJSON": json.dumps(placeholder, ensure_ascii=False),
            "StyleJSON": "[]",
        },
    )
    payload = response.json()
    guid = payload.get("Guid") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or payload.get("Status") != "Success" or not guid:
        prefix = "replacement global" if portal_name != item["name"] else "global"
        raise ProjectGlobalBlockError(
            f"{prefix} create failed for {portal_name!r}: {payload}"
        )
    return str(guid)


def _update_draft(
    client: object,
    item: dict[str, Any],
    guid: str,
) -> object:
    response = client.post(  # type: ignore[attr-defined]
        UPDATE_BLOCK,
        json={
            "guid": guid,
            "contentJSON": json.dumps(item["components"], ensure_ascii=False),
            "styleJSON": json.dumps(item["styles"], ensure_ascii=False),
            "html": item["html"],
        },
    )
    return response.json()


def _require_unpublished(
    detail: dict[str, Any],
    name: str,
    *,
    replacement: bool = False,
) -> None:
    if bool(detail.get("isPublished", False)):
        if replacement:
            raise ProjectGlobalBlockError(
                f"replacement global {name!r} unexpectedly remained published"
            )
        raise ProjectGlobalBlockError(
            f"desired draft for {name!r} unexpectedly remained published"
        )


def _preflight(
    client: object,
    desired: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    payload = client.get(LIST_BLOCKS).json()  # type: ignore[attr-defined]
    live = payload.get("blocks", []) if isinstance(payload, dict) else []
    if not isinstance(live, list):
        raise ProjectGlobalBlockError("global list returned an unexpected response")
    prior = {
        item.get("key"): item
        for item in manifest.get("blocks", [])
        if isinstance(item, dict)
    }
    actions: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in desired:
        matches = [
            block
            for block in live
            if str(block.get("name", "")).casefold() == item["name"].casefold()
        ]
        if len(matches) > 1:
            errors.append(f"ambiguous global name {item['name']!r}")
            continue
        previous = prior.get(item["key"])
        if previous:
            _preflight_managed(
                client,
                item=item,
                previous=previous,
                live=live,
                actions=actions,
                errors=errors,
            )
        elif not matches:
            actions.append({"key": item["key"], "name": item["name"], "action": "create"})
        else:
            guid = matches[0].get("guid")
            detail = _get(client, guid)
            if _server_hash(detail) == item["desired_hash"]:
                actions.append(
                    {
                        "key": item["key"],
                        "name": item["name"],
                        "guid": guid,
                        "action": "adopt",
                    }
                )
            else:
                errors.append(f"unmanaged global collision for {item['name']!r}")
    if errors:
        raise ProjectGlobalBlockError("global reconciliation failed:\n- " + "\n- ".join(errors))
    return actions


def _preflight_managed(
    client: object,
    *,
    item: dict[str, Any],
    previous: dict[str, Any],
    live: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    errors: list[str],
) -> None:
    guid = previous.get("guid")
    detail = _get(client, guid)
    if _server_hash(detail) == item["desired_hash"]:
        actions.append(
            {"key": item["key"], "name": item["name"], "guid": guid, "action": "reuse"}
        )
        return
    if previous.get("status") == "placeholder_created" and _is_placeholder(
        detail, item["key"]
    ):
        actions.append(
            {
                "key": item["key"],
                "name": item["name"],
                "guid": guid,
                "replacement_name": detail.get("name", ""),
                "action": "replace_finish",
            }
        )
        return
    if detail.get("version") != previous.get("observed_version"):
        errors.append(f"managed global content drift for {item['name']!r}")
        return
    replacement_name = f"{item['name']} [{item['desired_hash'][:8]}]"
    replacements = [
        block
        for block in live
        if str(block.get("name", "")).casefold() == replacement_name.casefold()
    ]
    if not replacements:
        actions.append(
            {
                "key": item["key"],
                "name": item["name"],
                "replacement_name": replacement_name,
                "action": "replace_create",
            }
        )
        return
    if len(replacements) > 1:
        errors.append(f"ambiguous replacement global {replacement_name!r}")
        return
    replacement_guid = replacements[0].get("guid")
    replacement_detail = _get(client, replacement_guid)
    if _server_hash(replacement_detail) == item["desired_hash"]:
        actions.append(
            {
                "key": item["key"],
                "name": item["name"],
                "guid": replacement_guid,
                "action": "adopt",
            }
        )
    elif _is_placeholder(replacement_detail, item["key"]):
        actions.append(
            {
                "key": item["key"],
                "name": item["name"],
                "guid": replacement_guid,
                "replacement_name": replacement_name,
                "action": "replace_finish",
            }
        )
    else:
        errors.append(f"replacement global collision for {replacement_name!r}")


def _placeholder(item: dict[str, Any]) -> list[dict[str, Any]]:
    digest = hashlib.sha256(item["key"].encode("utf-8")).hexdigest()[:10]
    return [
        {
            "type": "default",
            "attributes": {
                "id": f"ag-global-placeholder-{digest}",
                "data-agency-global-placeholder": item["key"],
            },
            "components": [],
        }
    ]


def _get(client: object, guid: object) -> dict[str, Any]:
    if not isinstance(guid, str) or not guid:
        raise ProjectGlobalBlockError("global GUID is invalid")
    payload = client.get(GET_BLOCK, params={"guid": guid}).json()  # type: ignore[attr-defined]
    if not isinstance(payload, dict):
        raise ProjectGlobalBlockError(f"global {guid} returned an unexpected response")
    return payload


def _server_hash(detail: dict[str, Any]) -> str:
    return _hash(
        {
            "content_json": _json_value(detail.get("contentJSON"), "contentJSON"),
            "style_json": _json_value(detail.get("styleJSON"), "styleJSON"),
        }
    )


def _json_value(value: object, label: str) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProjectGlobalBlockError(f"global {label} contains invalid JSON") from exc
    if isinstance(value, (list, dict)):
        return value
    raise ProjectGlobalBlockError(f"global {label} has an unexpected type")


def _record(
    item: dict[str, Any],
    detail: dict[str, Any],
    status: str,
    *,
    desired: bool = True,
) -> dict[str, Any]:
    return {
        "key": item["key"],
        "kind": item["kind"],
        "name": item["name"],
        "portal_name": detail.get("name", item["name"]),
        "category": item["category"],
        "guid": detail.get("guid", ""),
        "desired_hash": item["desired_hash"] if desired else None,
        "observed_version": detail.get("version", 0),
        "published": bool(detail.get("isPublished", False)),
        "status": status,
        "warnings": item["warnings"],
    }


def _is_placeholder(detail: dict[str, Any], key: str) -> bool:
    content = _json_value(detail.get("contentJSON"), "contentJSON")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(component, dict)
        and component.get("attributes", {}).get("data-agency-global-placeholder") == key
        for component in content
    )


def _hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "ProjectGlobalBlockError",
    "preview_project_global_blocks",
    "reconcile_project_global_blocks",
]
