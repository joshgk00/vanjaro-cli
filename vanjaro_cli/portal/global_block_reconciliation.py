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
    global_block_content_hash,
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
            _require_unpublished(detail, item["name"])
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
    response = client.post_form(  # type: ignore[attr-defined]
        CREATE_BLOCK,
        _placeholder_form(item, portal_name),
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
        json=_update_payload(item, guid),
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
                if bool(detail.get("isPublished", False)):
                    errors.append(f"adoptable global {item['name']!r} is published")
                else:
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
    desired_by_key = {item["key"]: item for item in desired}
    return [
        _planned_global_action(client, desired_by_key[action["key"]], action)
        for action in actions
    ]


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
    if previous.get("status") == "placeholder_created" and _is_placeholder(
        detail, item["key"]
    ) and detail.get("version") == previous.get("observed_version"):
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
    if bool(detail.get("isPublished", False)):
        errors.append(f"managed global {item['name']!r} is published")
        return
    if _server_hash(detail) == item["desired_hash"]:
        actions.append(
            {"key": item["key"], "name": item["name"], "guid": guid, "action": "reuse"}
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
                "replaces_guid": guid,
                "replaces_version": detail.get("version", 0),
                "replaces_hash": _server_hash(detail),
                "replaces_published": bool(detail.get("isPublished", False)),
                "action": "replace_create",
            }
        )
        return
    if len(replacements) > 1:
        errors.append(f"ambiguous replacement global {replacement_name!r}")
        return
    replacement_guid = replacements[0].get("guid")
    replacement_detail = _get(client, replacement_guid)
    if bool(replacement_detail.get("isPublished", False)):
        errors.append(f"replacement global {replacement_name!r} is published")
    elif _server_hash(replacement_detail) == item["desired_hash"]:
        actions.append(
            {
                "key": item["key"],
                "name": item["name"],
                "guid": replacement_guid,
                "action": "adopt",
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


def _placeholder_form(item: dict[str, Any], portal_name: str) -> dict[str, str]:
    placeholder = _placeholder(item)
    return {
        "Name": portal_name,
        "Category": item["category"],
        "Html": render_components(placeholder),
        "Css": "",
        "IsGlobal": "true",
        "ContentJSON": json.dumps(placeholder, ensure_ascii=False),
        "StyleJSON": "[]",
    }


def _update_payload(item: dict[str, Any], guid: object) -> dict[str, Any]:
    return {
        "guid": guid,
        "contentJSON": json.dumps(item["components"], ensure_ascii=False),
        "styleJSON": json.dumps(item["styles"], ensure_ascii=False),
        "html": item["html"],
    }


def _planned_global_action(
    client: object,
    item: dict[str, Any],
    action: dict[str, Any],
) -> dict[str, Any]:
    result = {
        **action,
        "desired_hash": item["desired_hash"],
        "desired_state_fingerprint": _plan_hash(
            {
                "components": item["components"],
                "styles": item["styles"],
                "html": item["html"],
                "category": item["category"],
            }
        ),
    }
    guid = action.get("guid")
    detail = _get(client, guid) if isinstance(guid, str) and guid else None
    if detail is not None:
        result.update(
            {
                "observed_version": detail.get("version", 0),
                "observed_hash": _server_hash(detail),
                "observed_published": bool(detail.get("isPublished", False)),
            }
        )

    operation = action["action"]
    if operation in {"reuse", "adopt"}:
        assert detail is not None
        _require_unpublished(detail, item["name"])
        if _server_hash(detail) != item["desired_hash"]:
            raise ProjectGlobalBlockError(
                f"global {item['name']!r} changed while its preview was being prepared"
            )
        result["operations"] = [
            {
                "sequence": 1,
                "kind": "portal_readback",
                "method": "GET",
                "endpoint": GET_BLOCK,
                "guid": guid,
            },
            {
                "sequence": 2,
                "kind": "local_checkpoint",
                "path": "build/global-block-manifest.json",
            },
        ]
        return result

    creates_placeholder = operation in {"create", "replace_create"}
    portal_name = str(action.get("replacement_name") or item["name"])
    binding = f"global-guid://{item['key']}"
    effective_guid: object = {"$binding": binding} if creates_placeholder else guid
    update_fingerprint = _plan_hash(_update_payload(item, effective_guid))
    operations: list[dict[str, Any]] = []
    sequence = 1
    if creates_placeholder:
        form = _placeholder_form(item, portal_name)
        operations.extend(
            [
                {
                    "sequence": sequence,
                    "kind": "portal_request",
                    "method": "POST_FORM",
                    "endpoint": CREATE_BLOCK,
                    "payload_fingerprint": _plan_hash(form),
                    "produces": binding,
                },
                {
                    "sequence": sequence + 1,
                    "kind": "portal_readback",
                    "method": "GET",
                    "endpoint": GET_BLOCK,
                    "guid_binding": binding,
                },
                {
                    "sequence": sequence + 2,
                    "kind": "local_checkpoint",
                    "path": "build/global-block-manifest.json",
                },
            ]
        )
        sequence += 3
    if operation in {"replace_create", "replace_finish"}:
        snapshot_version: object = (
            {"$binding": f"global-version://{item['key']}"}
            if creates_placeholder
            else result.get("observed_version", 0)
        )
        snapshot_path = (
            f"build/global-block-snapshots/{item['key']}/"
            f"before-v{snapshot_version if isinstance(snapshot_version, int) else '{resolved_version}'}.json"
        )
        result["snapshot_write_path"] = snapshot_path
        operations.extend(
            [
                {
                    "sequence": sequence,
                    "kind": "portal_readback",
                    "method": "GET",
                    "endpoint": GET_BLOCK,
                    "guid_binding": binding if creates_placeholder else None,
                    "guid": None if creates_placeholder else guid,
                },
                {
                    "sequence": sequence + 1,
                    "kind": "local_snapshot",
                    "path": snapshot_path,
                    "version_binding": snapshot_version,
                },
            ]
        )
        sequence += 2
    operations.extend(
        [
            {
                "sequence": sequence,
                "kind": "portal_request",
                "method": "POST",
                "endpoint": UPDATE_BLOCK,
                "payload_template_fingerprint": update_fingerprint,
                "guid_binding": binding if creates_placeholder else None,
                "guid": None if creates_placeholder else guid,
            },
            {
                "sequence": sequence + 1,
                "kind": "portal_readback",
                "method": "GET",
                "endpoint": GET_BLOCK,
                "guid_binding": binding if creates_placeholder else None,
                "guid": None if creates_placeholder else guid,
            },
            {
                "sequence": sequence + 2,
                "kind": "local_checkpoint",
                "path": "build/global-block-manifest.json",
            },
        ]
    )
    result.update(
        {
            "method": "POST_FORM" if creates_placeholder else "POST",
            "endpoint": CREATE_BLOCK if creates_placeholder else UPDATE_BLOCK,
            "payload_template_fingerprint": update_fingerprint,
            "response_binding": binding if creates_placeholder else None,
            "operations": operations,
        }
    )
    return result


def _plan_hash(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get(client: object, guid: object) -> dict[str, Any]:
    if not isinstance(guid, str) or not guid:
        raise ProjectGlobalBlockError("global GUID is invalid")
    payload = client.get(GET_BLOCK, params={"guid": guid}).json()  # type: ignore[attr-defined]
    if not isinstance(payload, dict):
        raise ProjectGlobalBlockError(f"global {guid} returned an unexpected response")
    return payload


def _server_hash(detail: dict[str, Any]) -> str:
    return global_block_content_hash(
        _json_value(detail.get("contentJSON"), "contentJSON"),
        _json_value(detail.get("styleJSON"), "styleJSON"),
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


__all__ = [
    "ProjectGlobalBlockError",
    "preview_project_global_blocks",
    "reconcile_project_global_blocks",
]
