"""Idempotent, project-scoped custom-block registration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from vanjaro_cli.design.element_style_transport import (
    ElementStyleTransportError,
    apply_element_styles,
)
from vanjaro_cli.design.native_style_transport import (
    NativeStyleTransportError,
    apply_important_to_buckets,
    apply_native_class_actions,
    important_css_properties_for_component,
    validate_native_class_actions,
)
from vanjaro_cli.design.style_transport import (
    StyleTransportError,
    build_style_rules,
    ensure_scoped_selector_id,
    validate_style_payload,
)
from vanjaro_cli.utils.block_compose import (
    TemplateNotFoundError,
    apply_overrides_with_owners,
    attach_form_placeholder,
    check_overflow,
    find_template,
)


LIST_BLOCKS = "/API/Vanjaro/Block/GetAllCustomBlock"
ADD_BLOCK = "/API/Vanjaro/Block/AddCustomBlock"


class BlockLibraryError(ValueError):
    """Raised before or during an unsafe library reconciliation."""


def compose_project_library(
    plan: list[object], *, agency_utilities: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    """Validate and compose the complete plan before any portal mutation.

    ``agency_utilities`` declares which ``AGENCY_UTILITY``-layer native class
    each entry's ``native_classes`` is allowed to apply; without it, an entry
    claiming an agency-utility class is rejected rather than trusted, since
    this stage has no other way to confirm the class is a real, deliberately
    configured one. Platform-utility and safe theme-slot classes need no such
    declaration -- they come from ``native_style_transport``'s own static,
    project-independent tables.
    """

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
        rendered, owners = apply_overrides_with_owners(template, overrides)
        form_fields = raw.get("form_fields")
        if isinstance(form_fields, list) and form_fields:
            # The legacy migration path has marked forms this way since it was
            # built; the project path did not, so a migrated page carried a
            # heading where a contact form used to be and nothing said so.
            attach_form_placeholder(rendered["template"], form_fields)
        # library-plan.json is untrusted serialized input by the time it
        # reaches this stage (project_build.py reads it off disk with no
        # schema check), so a planner-accepted style is re-validated here,
        # not merely trusted because emit_library_plan validated it once.
        #
        # native_classes is applied to the section root before style_declarations
        # is even validated, so that -- by the time a scoped rule for the same
        # property is checked for a colliding class -- this request's own
        # class already landed next to whatever the matched template baked in
        # by default (e.g. feature-cards-3up.json's heading always carries
        # text-center, independent of any style decision at all). See
        # native_style_transport.important_css_properties_for_component.
        native_classes = raw.get("native_classes")
        if "native_classes" in raw and native_classes != []:
            try:
                actions = validate_native_class_actions(
                    native_classes, agency_utilities=agency_utilities
                )
            except NativeStyleTransportError as exc:
                errors.append(f"entry {index}: {exc}")
                continue
            apply_native_class_actions(rendered["template"], actions)
        style_declarations = raw.get("style_declarations")
        # A truthiness check here would treat an explicitly malformed value
        # (False, 0, '', []) the same as a legacy plan that never mentions
        # style_declarations at all -- both are falsy, but only the latter
        # is a legitimate "no styles" absence. An empty dict is the one
        # falsy shape that IS a deliberate, valid "no styles" payload (an
        # entry that opted into style metadata but has nothing to declare),
        # so it is excluded from validation the same way an absent key is,
        # rather than tripping validate_style_payload's own non-empty check.
        if "style_declarations" in raw and style_declarations != {}:
            try:
                buckets = validate_style_payload(raw.get("style_scope"), style_declarations)
            except StyleTransportError as exc:
                errors.append(f"entry {index}: {exc}")
                continue
            # A Bootstrap utility class already on the section root (from the
            # native_classes action just applied above, or a baked-in
            # template default) compiles with !important on this
            # root-inspected target, so a same-property scoped rule at
            # normal priority is otherwise inert against it.
            important = important_css_properties_for_component(
                rendered["template"],
                {prop: value for style in buckets.values() for prop, value in style.items()},
            )
            buckets = apply_important_to_buckets(buckets, important)
            # Target the section root by a stable id selector -- the same
            # convention block_compose.py's palette-background rules use --
            # rather than the plan's descendant-class css_scope string,
            # which no rendered component ever carries a matching class for.
            element_id = ensure_scoped_selector_id(rendered["template"], key)
            rendered["styles"] = [
                *rendered.get("styles", []),
                *build_style_rules(element_id, buckets),
            ]
        # element_styles targets a specific bound owner component (a card's
        # own heading/action/image), never the section root -- resolved
        # through `owners`, the same slot-key vocabulary `overrides` uses,
        # captured by apply_overrides_with_owners before pruning could
        # renumber a later slot out from under it.
        if "element_styles" in raw:
            try:
                apply_element_styles(
                    rendered,
                    owners,
                    raw.get("element_styles"),
                    library_key=key,
                    agency_utilities=agency_utilities,
                )
            except ElementStyleTransportError as exc:
                errors.append(f"entry {index}: {exc}")
                continue
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
        "blocks": [
            {**state, "action": state["status"]}
            for state in states
        ]
        + [_planned_registration(item) for item in missing],
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
        form = _registration_form(item, portal_name)
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


def _registration_form(item: dict[str, Any], portal_name: str) -> dict[str, str]:
    # Vanjaro's BlockManager.Add (BlockController.AddCustomBlock) selects
    # custom-block storage only when BOTH Html and Css are empty; any
    # nonempty Css takes the global-block branch regardless of IsGlobal.
    # Editor styling and visitor-facing CSS are carried by StyleJSON/
    # ContentJSON and by page composition's own render_styles pass, not by
    # this form's Css field, so leaving it empty loses nothing.
    return {
        "Name": portal_name,
        "Category": item["category"],
        "Html": "",
        "Css": "",
        "IsGlobal": "false",
        "ContentJSON": json.dumps(item["content_json"], ensure_ascii=False),
        "StyleJSON": json.dumps(item["style_json"], ensure_ascii=False),
    }


def _planned_registration(item: dict[str, Any]) -> dict[str, Any]:
    portal_name = str(item.get("portal_name", item["name"]))
    form = _registration_form(item, portal_name)
    return {
        "key": item["key"],
        "name": item["name"],
        "portal_name": portal_name,
        "action": "create",
        "status": "create",
        "desired_hash": item["desired_hash"],
        "method": "POST_FORM",
        "endpoint": ADD_BLOCK,
        "payload_fingerprint": _state_hash(form),
        "response_binding": f"custom-block-guid://{item['key']}",
        "operations": [
            {
                "sequence": 1,
                "kind": "local_checkpoint",
                "path": "build/block-manifest.json",
            },
            {
                "sequence": 2,
                "kind": "portal_request",
                "method": "POST_FORM",
                "endpoint": ADD_BLOCK,
                "payload_fingerprint": _state_hash(form),
                "produces": f"custom-block-guid://{item['key']}",
            },
            {
                "sequence": 3,
                "kind": "portal_readback",
                "method": "GET",
                "endpoint": LIST_BLOCKS,
            },
            {
                "sequence": 4,
                "kind": "local_checkpoint",
                "path": "build/block-manifest.json",
            },
        ],
    }


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
