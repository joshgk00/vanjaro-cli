"""Deterministic project page assembly and draft-only portal reconciliation."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from vanjaro_cli.portal.page_composition import (
    ProjectPageError,
    attach_global_wrappers,
    compose_project_pages,
    namespace_component_payload,
    page_content_hash,
    page_slug,
)
from vanjaro_cli.utils.grapesjs import render_styles


LIST_PAGES = "/API/VanjaroAI/AIPage/List"
GET_PAGE = "/API/VanjaroAI/AIPage/Get"
CREATE_PAGE = "/API/VanjaroAI/AIPage/Create"
UPDATE_PAGE = "/API/VanjaroAI/AIPage/Update"


def preview_project_pages(
    client: object,
    *,
    desired: list[dict[str, Any]],
    manifest_path: Path,
    snapshot_root: str = "build/page-snapshots",
    manifest_write_path: str = "build/page-manifest.json",
) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    live = _list_pages(client)
    actions = _preflight(
        client,
        desired,
        live,
        manifest,
        snapshot_root=snapshot_root,
        manifest_write_path=manifest_write_path,
    )
    return {
        "schema_version": "1.0",
        "total": len(actions),
        "to_create": sum(item["action"] == "create" for item in actions),
        "to_update": sum(item["action"] == "update" for item in actions),
        "reused": sum(item["action"] in {"reuse", "adopt"} for item in actions),
        "pages": actions,
    }


def reconcile_project_pages(
    client: object,
    *,
    desired: list[dict[str, Any]],
    manifest_path: Path,
    snapshots_dir: Path,
) -> list[dict[str, Any]]:
    manifest = _load_manifest(manifest_path)
    live = _list_pages(client)
    actions = _preflight(client, desired, live, manifest)
    prior = {
        item["key"]: item
        for item in manifest.get("pages", [])
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }
    records: dict[str, dict[str, Any]] = {}
    desired_by_key = {item["key"]: item for item in desired}

    for action in actions:
        item = desired_by_key[action["key"]]
        parent_id = (
            records.get(item["parent_key"], prior.get(item["parent_key"], {})).get("page_id")
            if item["parent_key"]
            else None
        )
        if item["parent_key"] and not parent_id:
            raise ProjectPageError(f"parent page is unresolved for {item['name']!r}")
        if action["action"] in {"reuse", "adopt"}:
            detail = _get_page(client, action["page_id"])
            _require_page_draft(detail, item["name"])
            record = _record(item, detail, action["action"], parent_id)
        elif action["action"] == "create":
            payload = _create_payload(item, parent_id)
            response = client.post(CREATE_PAGE, json=payload)  # type: ignore[attr-defined]
            body = response.json()
            page_id = body.get("pageId")
            if not isinstance(page_id, int) or page_id <= 0:
                raise ProjectPageError(f"create returned no page ID for {item['name']!r}")
            detail = _get_page(client, page_id)
            if _server_content_hash(detail) != item["content_hash"]:
                raise ProjectPageError(f"created draft verification failed for {item['name']!r}")
            _require_page_draft(detail, item["name"])
            record = _record(item, detail, "created", parent_id)
        else:
            detail = _get_page(client, action["page_id"])
            snapshot_path = (
                snapshots_dir
                / page_slug(item["key"])
                / f"before-v{detail.get('version', 0)}.json"
            )
            _write_json(snapshot_path, detail)
            payload = _update_payload(
                item,
                page_id=action["page_id"],
                expected_version=detail.get("version", 0),
            )
            client.post(UPDATE_PAGE, json=payload)  # type: ignore[attr-defined]
            refreshed = _get_page(client, action["page_id"])
            if _server_content_hash(refreshed) != item["content_hash"]:
                raise ProjectPageError(f"updated draft verification failed for {item['name']!r}")
            _require_page_draft(refreshed, item["name"])
            record = _record(item, refreshed, "updated", parent_id)
        records[item["key"]] = record
        _persist_manifest(manifest_path, desired, records, prior)

    return [records[item["key"]] for item in desired]


def _preflight(
    client: object,
    desired: list[dict[str, Any]],
    live: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    snapshot_root: str = "build/page-snapshots",
    manifest_write_path: str = "build/page-manifest.json",
) -> list[dict[str, Any]]:
    prior = {
        item.get("key"): item
        for item in manifest.get("pages", [])
        if isinstance(item, dict)
    }
    actions: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in desired:
        if bool(item.get("is_visible", False)):
            errors.append(f"desired page {item['name']!r} must be hidden")
            continue
        previous = prior.get(item["key"])
        matches = [
            row for row in live
            if str(row.get("name", row.get("Name", ""))).casefold() == item["name"].casefold()
        ]
        if len(matches) > 1:
            errors.append(f"ambiguous live page name {item['name']!r}")
            continue
        if previous:
            page_id = previous.get("page_id")
            if not isinstance(page_id, int):
                errors.append(f"managed page {item['name']!r} has no page ID")
                continue
            detail = _get_page(client, page_id)
            if _page_is_visible_or_published(detail):
                errors.append(f"managed page {item['name']!r} is visible or published")
                continue
            if not _owned_by(detail, item["key"]):
                errors.append(f"ownership marker drift for managed page {item['name']!r}")
                continue
            current_hash = _server_content_hash(detail)
            if current_hash == item["content_hash"]:
                actions.append(
                    _planned_page_action(
                        item,
                        "reuse",
                        page_id=page_id,
                        detail=detail,
                        snapshot_root=snapshot_root,
                        manifest_write_path=manifest_write_path,
                    )
                )
            elif detail.get("version") != previous.get("observed_version"):
                errors.append(f"external draft edit detected for {item['name']!r}")
            else:
                actions.append(
                    _planned_page_action(
                        item,
                        "update",
                        page_id=page_id,
                        detail=detail,
                        snapshot_root=snapshot_root,
                        manifest_write_path=manifest_write_path,
                    )
                )
            continue
        if not matches:
            actions.append(
                _planned_page_action(
                    item,
                    "create",
                    snapshot_root=snapshot_root,
                    manifest_write_path=manifest_write_path,
                )
            )
            continue
        page_id = matches[0].get("tabId", matches[0].get("id"))
        detail = _get_page(client, page_id)
        if _page_is_visible_or_published(detail):
            errors.append(f"adoptable page {item['name']!r} is visible or published")
            continue
        if _owned_by(detail, item["key"]) and _server_content_hash(detail) == item["content_hash"]:
            actions.append(
                _planned_page_action(
                    item,
                    "adopt",
                    page_id=page_id,
                    detail=detail,
                    snapshot_root=snapshot_root,
                    manifest_write_path=manifest_write_path,
                )
            )
        else:
            errors.append(f"unmanaged page collision for {item['name']!r}")
    if errors:
        raise ProjectPageError("page reconciliation failed:\n- " + "\n- ".join(errors))
    return actions


def _create_payload(item: dict[str, Any], parent_id: int | None) -> dict[str, Any]:
    payload = {
        "name": item["name"],
        "title": item["title"],
        "description": item["description"],
        "keywords": item["keywords"],
        "isVisible": False,
        "isPublished": False,
        "contentJSON": json.dumps(item["components"], ensure_ascii=False),
        "styleJSON": json.dumps(item["styles"], ensure_ascii=False),
        "contentHtml": item["content_html"],
        "styleCss": render_styles(item["styles"]),
    }
    if parent_id is not None:
        payload["parentId"] = parent_id
    return payload


def _update_payload(
    item: dict[str, Any], *, page_id: int, expected_version: object
) -> dict[str, Any]:
    return {
        "pageId": page_id,
        "contentJSON": json.dumps(item["components"], ensure_ascii=False),
        "styleJSON": json.dumps(item["styles"], ensure_ascii=False),
        "contentHtml": item["content_html"],
        "locale": "en-US",
        "expectedVersion": expected_version,
        "isVisible": False,
        "isPublished": False,
    }


def _planned_page_action(
    item: dict[str, Any],
    action: str,
    *,
    page_id: int | None = None,
    detail: dict[str, Any] | None = None,
    snapshot_root: str = "build/page-snapshots",
    manifest_write_path: str = "build/page-manifest.json",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "key": item["key"],
        "name": item["name"],
        "action": action,
        "desired_hash": item["content_hash"],
        "desired_state_fingerprint": _canonical_hash(item),
        "method": "POST" if action in {"create", "update"} else None,
        "endpoint": CREATE_PAGE if action == "create" else UPDATE_PAGE if action == "update" else None,
    }
    if page_id is not None:
        result["page_id"] = page_id
    if detail is not None:
        result.update(
            {
                "observed_version": detail.get("version", 0),
                "observed_hash": _server_content_hash(detail),
                "observed_visible": bool(detail.get("isVisible", False)),
                "observed_published": bool(detail.get("isPublished", False)),
            }
        )
    if action == "create":
        binding = (
            f"page-id://{item['parent_key']}" if item.get("parent_key") else None
        )
        payload_template = _create_payload(item, None)
        if binding is not None:
            payload_template["parentId"] = {"$binding": binding}
        template_fingerprint = _canonical_hash(payload_template)
        result.update(
            {
                "payload_template_fingerprint": template_fingerprint,
                "payload_fingerprint": template_fingerprint
                if binding is None
                else None,
                "parent_id_binding": binding,
                "response_binding": f"page-id://{item['key']}",
                "operations": [
                    {
                        "sequence": 1,
                        "kind": "portal_request",
                        "method": "POST",
                        "endpoint": CREATE_PAGE,
                        "payload_template_fingerprint": template_fingerprint,
                        "bindings": [binding] if binding else [],
                        "produces": f"page-id://{item['key']}",
                    },
                    {
                        "sequence": 2,
                        "kind": "portal_readback",
                        "method": "GET",
                        "endpoint": GET_PAGE,
                        "page_id_binding": f"page-id://{item['key']}",
                    },
                    {
                        "sequence": 3,
                        "kind": "local_checkpoint",
                        "path": manifest_write_path,
                    },
                ],
            }
        )
    elif action == "update":
        assert page_id is not None and detail is not None
        payload = _update_payload(
            item,
            page_id=page_id,
            expected_version=detail.get("version", 0),
        )
        result.update(
            {
                "payload_fingerprint": _canonical_hash(payload),
                "operations": [
                    {
                        "sequence": 1,
                        "kind": "portal_readback",
                        "method": "GET",
                        "endpoint": GET_PAGE,
                        "page_id": page_id,
                    },
                    {
                        "sequence": 2,
                        "kind": "local_snapshot",
                        "path": (
                            f"{snapshot_root}/{page_slug(item['key'])}/"
                            f"before-v{detail.get('version', 0)}.json"
                        ),
                    },
                    {
                        "sequence": 3,
                        "kind": "portal_request",
                        "method": "POST",
                        "endpoint": UPDATE_PAGE,
                        "payload_fingerprint": _canonical_hash(payload),
                        "expected_version": detail.get("version", 0),
                    },
                    {
                        "sequence": 4,
                        "kind": "portal_readback",
                        "method": "GET",
                        "endpoint": GET_PAGE,
                        "page_id": page_id,
                    },
                    {
                        "sequence": 5,
                        "kind": "local_checkpoint",
                        "path": manifest_write_path,
                    },
                ],
            }
        )
    else:
        result["operations"] = [
            {
                "sequence": 1,
                "kind": "portal_readback",
                "method": "GET",
                "endpoint": GET_PAGE,
                "page_id": page_id,
            },
            {
                "sequence": 2,
                "kind": "local_checkpoint",
                "path": manifest_write_path,
            },
        ]
    return result


def _canonical_hash(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _list_pages(client: object) -> list[dict[str, Any]]:
    response = client.get(LIST_PAGES, params={"skip": 0, "take": 1000})  # type: ignore[attr-defined]
    payload = response.json()
    pages = payload if isinstance(payload, list) else payload.get("pages", [])
    if not isinstance(pages, list) or any(not isinstance(item, dict) for item in pages):
        raise ProjectPageError("page list returned an unexpected response")
    return pages


def _get_page(client: object, page_id: object) -> dict[str, Any]:
    if not isinstance(page_id, int):
        raise ProjectPageError("portal page ID is invalid")
    payload = client.get(  # type: ignore[attr-defined]
        GET_PAGE,
        params={"pageId": page_id, "includeDraft": "true", "locale": "en-US"},
    ).json()
    if not isinstance(payload, dict):
        raise ProjectPageError(f"page {page_id} returned an unexpected response")
    return payload


def _server_content_hash(detail: dict[str, Any]) -> str:
    components = _json_value(detail.get("contentJSON"), "contentJSON")
    styles = _json_value(detail.get("styleJSON"), "styleJSON")
    html = detail.get("contentHtml", "")
    return page_content_hash(components, styles, html)


def _page_is_visible_or_published(detail: dict[str, Any]) -> bool:
    return bool(detail.get("isVisible", False)) or bool(
        detail.get("isPublished", False)
    )


def _require_page_draft(detail: dict[str, Any], name: str) -> None:
    if _page_is_visible_or_published(detail):
        raise ProjectPageError(
            f"page {name!r} unexpectedly remained visible or published"
        )


def _json_value(value: object, label: str) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProjectPageError(f"portal {label} contains invalid JSON") from exc
    if isinstance(value, (list, dict)):
        return value
    raise ProjectPageError(f"portal {label} has an unexpected type")


def _owned_by(detail: dict[str, Any], page_key: str) -> bool:
    components = _json_value(detail.get("contentJSON"), "contentJSON")
    stack = list(components) if isinstance(components, list) else []
    while stack:
        component = stack.pop()
        if not isinstance(component, dict):
            continue
        if component.get("attributes", {}).get("data-agency-page") == page_key:
            return True
        stack.extend(component.get("components", []))
    return False


def _record(
    item: dict[str, Any],
    detail: dict[str, Any],
    status: str,
    parent_id: int | None,
) -> dict[str, Any]:
    page_id = detail.get("tabId", detail.get("pageId"))
    if not isinstance(page_id, int):
        raise ProjectPageError(f"page detail has no ID for {item['name']!r}")
    return {
        "key": item["key"],
        "name": item["name"],
        "title": item["title"],
        "page_id": page_id,
        "path": detail.get("path", ""),
        "parent_id": parent_id,
        "desired_hash": item["content_hash"],
        "observed_version": detail.get("version", 0),
        "status": status,
        "published": bool(detail.get("isPublished", False)),
        "visible": bool(detail.get("isVisible", False)),
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": "1.0", "pages": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectPageError(f"cannot read page manifest: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("pages"), list):
        raise ProjectPageError("page manifest has an unexpected format")
    return payload


def _persist_manifest(
    path: Path,
    desired: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    prior: dict[str, dict[str, Any]],
) -> None:
    merged = {**prior, **records}
    _write_json(
        path,
        {
            "schema_version": "1.0",
            "pages": [merged[item["key"]] for item in desired if item["key"] in merged],
        },
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


__all__ = [
    "ProjectPageError",
    "attach_global_wrappers",
    "compose_project_pages",
    "namespace_component_payload",
    "preview_project_pages",
    "reconcile_project_pages",
]
