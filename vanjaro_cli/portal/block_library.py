"""Idempotent, project-scoped custom-block registration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from vanjaro_cli.utils.block_compose import (
    TemplateNotFoundError,
    apply_overrides,
    check_overflow,
    find_template,
)
from vanjaro_cli.utils.grapesjs import render_styles


LIST_BLOCKS = "/API/Vanjaro/Block/GetAllCustomBlock"
ADD_BLOCK = "/API/Vanjaro/Block/AddCustomBlock"


class BlockLibraryError(ValueError):
    """Raised before or during an unsafe library reconciliation."""


def compose_project_library(plan: list[object]) -> list[dict[str, Any]]:
    """Validate and compose the complete plan before any portal mutation."""

    errors: list[str] = []
    composed: list[dict[str, Any]] = []
    names: set[str] = set()
    keys: set[str] = set()
    for index, raw in enumerate(plan, 1):
        if not isinstance(raw, dict):
            errors.append(f"entry {index} must be an object")
            continue
        entry_errors: list[str] = []
        key = raw.get("key")
        name = raw.get("name")
        template_name = raw.get("template")
        block_type = raw.get("type", "custom")
        overrides = raw.get("overrides", {})
        if not isinstance(key, str) or not key.strip():
            entry_errors.append(f"entry {index} requires a non-empty stable key")
        elif key.casefold() in keys:
            entry_errors.append(f"entry {index} duplicates key {key!r}")
        else:
            keys.add(key.casefold())
        if not isinstance(name, str) or not name.strip():
            entry_errors.append(f"entry {index} requires a non-empty name")
        elif name.casefold() in names:
            entry_errors.append(f"entry {index} duplicates name {name!r}")
        else:
            names.add(name.casefold())
        if not isinstance(template_name, str) or not template_name.strip():
            entry_errors.append(f"entry {index} requires a non-empty template")
        if block_type != "custom":
            entry_errors.append(
                f"entry {index} has type {block_type!r}; project library stage accepts custom blocks only"
            )
        if not isinstance(overrides, dict):
            entry_errors.append(f"entry {index} overrides must be an object")
        if entry_errors:
            errors.extend(entry_errors)
            continue
        try:
            template = find_template(str(template_name))
        except TemplateNotFoundError as exc:
            errors.append(f"entry {index}: {exc}")
            continue
        expected_template_digest = raw.get("template_digest")
        actual_template_digest = _state_hash(template)
        if (
            expected_template_digest is not None
            and expected_template_digest != actual_template_digest
        ):
            errors.append(
                f"entry {index} template content changed after plan approval"
            )
            continue
        unused = check_overflow(template, overrides)
        if unused:
            errors.append(
                f"entry {index} would drop override slot(s): {', '.join(sorted(unused))}"
            )
            continue
        category = raw.get("category") or template.get("category", "general")
        if not isinstance(category, str) or not category.strip():
            errors.append(f"entry {index} requires a non-empty category")
            continue
        rendered = apply_overrides(template, overrides)
        desired = {
            "type": "custom",
            "name": name,
            "category": category,
            "content_json": [rendered["template"]],
            "style_json": rendered.get("styles", []),
        }
        composed.append(
            {
                "key": key,
                "template": template_name,
                "template_digest": actual_template_digest,
                "name": name,
                "category": category,
                "type": "custom",
                "content_json": desired["content_json"],
                "style_json": desired["style_json"],
                "desired_hash": _state_hash(desired),
            }
        )
    if errors:
        raise BlockLibraryError("block library preflight failed:\n- " + "\n- ".join(errors))
    return composed


def preview_project_library(
    client: object,
    *,
    plan: list[object],
    manifest_path: Path,
) -> dict[str, Any]:
    """Compose and compare a plan with live state without writing or posting."""

    desired = compose_project_library(plan)
    live = _list_custom_blocks(client)
    manifest = _load_manifest(manifest_path)
    states, missing = _preflight(desired, live, manifest)
    return {
        "schema_version": "1.0",
        "total": len(desired),
        "reused": len(states),
        "to_create": len(missing),
        "blocks": states
        + [
            {
                "key": item["key"],
                "name": item["name"],
                "status": "create",
                "desired_hash": item["desired_hash"],
            }
            for item in missing
        ],
    }


def register_project_library(
    client: object,
    *,
    plan: list[object],
    manifest_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reconcile and register missing custom blocks, persisting after each POST."""

    desired = compose_project_library(plan)
    live = _list_custom_blocks(client)
    manifest = _load_manifest(manifest_path)
    records, missing = _preflight(desired, live, manifest)
    by_key = {
        record["key"]: record
        for record in manifest.get("blocks", [])
        if isinstance(record, dict) and isinstance(record.get("key"), str)
    }
    by_key.update({record["key"]: record for record in records})
    _persist_manifest(manifest_path, desired, by_key)

    for item in missing:
        portal_name = item.get("portal_name", item["name"])
        form = {
            "Name": portal_name,
            "Category": item["category"],
            "Html": "",
            "Css": render_styles(item["style_json"]),
            "IsGlobal": "false",
            "ContentJSON": json.dumps(item["content_json"], ensure_ascii=False),
            "StyleJSON": json.dumps(item["style_json"], ensure_ascii=False),
        }
        response = client.post_form(ADD_BLOCK, form)  # type: ignore[attr-defined]
        payload = response.json()
        if payload.get("Status") not in {"Success", "Exist"}:
            raise BlockLibraryError(
                f"registration failed for {portal_name!r}: {payload}"
            )
        refreshed = _list_custom_blocks(client)
        matches = _matching_rows(refreshed, portal_name)
        if len(matches) != 1:
            raise BlockLibraryError(
                f"portal did not expose one unambiguous row for {portal_name!r} after registration"
            )
        observed = _server_state(matches[0])
        observed_hash = _state_hash(observed)
        if (
            payload.get("Status") == "Exist"
            and observed_hash != _expected_server_hash(item, portal_name)
        ):
            raise BlockLibraryError(
                f"concurrent name collision for {portal_name!r}; existing content differs"
            )
        record = _record(item, matches[0], observed_hash, "created")
        by_key[item["key"]] = record
        _persist_manifest(manifest_path, desired, by_key)

    ordered = [by_key[item["key"]] for item in desired]
    return desired, ordered


def _preflight(
    desired: list[dict[str, Any]],
    live: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prior = {
        record.get("key"): record
        for record in manifest.get("blocks", [])
        if isinstance(record, dict) and isinstance(record.get("key"), str)
    }
    records: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in desired:
        previous = prior.get(item["key"])
        if previous:
            previous_portal_name = str(
                previous.get("portal_name") or previous.get("name") or item["name"]
            )
            previous_matches = _matching_rows(live, previous_portal_name)
            if len(previous_matches) > 1:
                errors.append(
                    f"portal has ambiguous case-insensitive matches for {previous_portal_name!r}"
                )
                continue
            if not previous_matches:
                errors.append(
                    f"previously managed block {previous_portal_name!r} "
                    f"({previous.get('guid', '')}) is missing"
                )
                continue
            previous_row = previous_matches[0]
            previous_observed_hash = _state_hash(_server_state(previous_row))
            if previous.get("guid") != previous_row.get("Guid", ""):
                errors.append(f"managed identity drift for {item['name']!r}")
                continue
            if previous.get("observed_server_hash") != previous_observed_hash:
                errors.append(f"portal content drift for managed block {item['name']!r}")
                continue
            if previous.get("desired_hash") == item["desired_hash"]:
                records.append(
                    _record(item, previous_row, previous_observed_hash, "reused")
                )
                continue

            replacement_name = _replacement_name(item)
            replacement_matches = _matching_rows(live, replacement_name)
            if len(replacement_matches) > 1:
                errors.append(f"ambiguous replacement block {replacement_name!r}")
            elif not replacement_matches:
                missing.append({**item, "portal_name": replacement_name})
            else:
                replacement_row = replacement_matches[0]
                replacement_observed_hash = _state_hash(_server_state(replacement_row))
                if replacement_observed_hash == _expected_server_hash(
                    item, replacement_name
                ):
                    records.append(
                        _record(
                            item,
                            replacement_row,
                            replacement_observed_hash,
                            "adopted",
                        )
                    )
                else:
                    errors.append(
                        f"replacement block collision for {replacement_name!r}"
                    )
            continue
        matches = _matching_rows(live, item["name"])
        if len(matches) > 1:
            errors.append(f"portal has ambiguous case-insensitive matches for {item['name']!r}")
            continue
        if not matches:
            missing.append(item)
            continue
        row = matches[0]
        observed_hash = _state_hash(_server_state(row))
        if observed_hash == _expected_server_hash(item, item["name"]):
            records.append(_record(item, row, observed_hash, "adopted"))
        else:
            errors.append(
                f"portal block {item['name']!r} already exists with different content"
            )
    if errors:
        raise BlockLibraryError("block library reconciliation failed:\n- " + "\n- ".join(errors))
    return records, missing


def _matching_rows(rows: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("Name", "")).casefold() == name.casefold()]


def _list_custom_blocks(client: object) -> list[dict[str, Any]]:
    payload = client.get(LIST_BLOCKS).json()  # type: ignore[attr-defined]
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise BlockLibraryError("custom-block list returned an unexpected response")
    return payload


def _server_state(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "custom",
        "name": str(row.get("Name", "")),
        "category": str(row.get("Category", "")),
        "content_json": _json_field(row.get("ContentJSON"), "ContentJSON"),
        "style_json": _json_field(row.get("StyleJSON"), "StyleJSON"),
    }


def _expected_server_hash(item: dict[str, Any], portal_name: str) -> str:
    """Hash desired content using the immutable portal revision's actual name."""

    return _state_hash(
        {
            "type": "custom",
            "name": portal_name,
            "category": item["category"],
            "content_json": item["content_json"],
            "style_json": item["style_json"],
        }
    )


def _replacement_name(item: dict[str, Any]) -> str:
    return f"{item['name']} [{item['desired_hash'][:8]}]"


def _json_field(value: object, label: str) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise BlockLibraryError(f"portal {label} contains invalid JSON") from exc
    if isinstance(value, (list, dict)):
        return value
    raise BlockLibraryError(f"portal {label} has an unexpected type")


def _record(
    item: dict[str, Any],
    row: dict[str, Any],
    observed_hash: str,
    status: str,
) -> dict[str, Any]:
    guid = str(row.get("Guid", ""))
    if not guid:
        raise BlockLibraryError(f"portal row for {item['name']!r} has no GUID")
    return {
        "key": item["key"],
        "type": "custom",
        "name": item["name"],
        "portal_name": str(row.get("Name", item["name"])),
        "category": item["category"],
        "guid": guid,
        "desired_hash": item["desired_hash"],
        "observed_server_hash": observed_hash,
        "status": status,
    }


def _state_hash(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": "1.0", "blocks": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BlockLibraryError(f"cannot read block manifest: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("blocks"), list):
        raise BlockLibraryError("block manifest has an unexpected format")
    return payload


def _persist_manifest(
    path: Path,
    desired: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
) -> None:
    ordered = [records[item["key"]] for item in desired if item["key"] in records]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(
            {"schema_version": "1.0", "blocks": ordered},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


__all__ = [
    "BlockLibraryError",
    "compose_project_library",
    "preview_project_library",
    "register_project_library",
]
