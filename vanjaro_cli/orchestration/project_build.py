"""Approved project build stages composed from reusable portal services."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.design.serialization import (
    read_design_document,
    serialize_design_document,
)
from vanjaro_cli.orchestration.portal_identity import verify_project_portal
from vanjaro_cli.portal.assets import preview_project_assets, upload_project_assets
from vanjaro_cli.portal.block_library import (
    preview_project_library,
    register_project_library,
)
from vanjaro_cli.portal.pages import (
    attach_global_wrappers,
    compose_project_pages,
    preview_project_pages,
    reconcile_project_pages,
)
from vanjaro_cli.portal.global_blocks import (
    compose_project_global_blocks,
    preview_project_global_blocks,
    reconcile_project_global_blocks,
)
from vanjaro_cli.project.models import ProjectManifest
from vanjaro_cli.project.stage_engine import StageContext, StageResult
from vanjaro_cli.reliability import atomic_write_json


def preserve_project_theme(context: StageContext) -> StageResult:
    """Explicitly preserve an already-approved portal theme after identity preflight."""

    _, verified = verify_project_portal(context.manifest)
    relative = "build/theme-result.json"
    _write_json(
        context.root / relative,
        {
            "schema_version": "1.0",
            "mode": "preserve",
            "mutated": False,
            "target": verified.as_dict(),
            "reason": "Operator selected preserve-theme mode for this build.",
        },
    )
    return StageResult(
        artifacts=(relative,),
        message="Verified target identity and preserved the existing portal theme.",
    )


def preview_preserve_project_theme(
    root: Path, manifest: ProjectManifest
) -> dict[str, object]:
    """Verify the preserve target without changing either workspace or portal."""

    del root
    _, verified = verify_project_portal(manifest)
    return {
        "schema_version": "1.0",
        "mode": "preserve",
        "target": verified.as_dict(),
        "portal_actions": [],
        "local_writes": ["build/theme-result.json"],
    }


def upload_project_asset_stage(context: StageContext) -> StageResult:
    """Upload resolved design assets and rewrite the library plan to portal URLs."""

    client, verified = verify_project_portal(context.manifest)
    document = read_design_document(
        context.root / "plans/resolved-design-document.json"
    )
    library_path = context.root / "plans/library-plan.json"
    library_plan = json.loads(library_path.read_text(encoding="utf-8"))
    if not isinstance(library_plan, list):
        raise ValueError("library plan must contain a JSON array")
    manifest_path = context.root / "build/asset-manifest.json"
    previous_records = _read_asset_records(manifest_path)
    portal_document, portal_plan, records = upload_project_assets(
        client,
        root=context.root,
        project_id=context.manifest.project.id,
        document=document,
        library_plan=library_plan,
    )
    document_relative = "build/design-document.json"
    library_relative = "build/library-plan.json"
    report_relative = "build/assets-result.json"
    manifest_relative = "build/asset-manifest.json"
    _write_text(
        context.root / document_relative,
        serialize_design_document(portal_document),
    )
    _write_json(context.root / library_relative, portal_plan)
    _write_json(
        context.root / report_relative,
        {
            "schema_version": "1.0",
            "target": verified.as_dict(),
            "folder": f"Images/agency/{context.manifest.project.id}/",
            "managed_assets": len(records),
            "uploaded_this_run": sum(
                previous_records.get(record.get("asset_id"))
                != (record.get("sha256"), record.get("vanjaro_url"))
                for record in records
            ),
            "assets": records,
        },
    )
    return StageResult(
        artifacts=(
            manifest_relative,
            document_relative,
            library_relative,
            report_relative,
        ),
        message=f"Reconciled {len(records)} project asset(s) on portal {verified.portal_id}.",
    )


def preview_project_asset_stage(
    root: Path, manifest: ProjectManifest
) -> dict[str, object]:
    """Plan exact asset reuse/uploads after a GET-only target identity check."""

    _, verified = verify_project_portal(manifest)
    document = read_design_document(root / "plans/resolved-design-document.json")
    library_plan = _read_list(root / "plans/library-plan.json", "library plan")
    if any(not isinstance(item, dict) for item in library_plan):
        raise ValueError("library plan contains a non-object entry")
    plan = preview_project_assets(
        root=root,
        project_id=manifest.project.id,
        document=document,
    )
    return {
        **plan,
        "target": verified.as_dict(),
        "portal_actions": plan["assets"],
        "local_writes": [
            "build/asset-manifest.json",
            "build/design-document.json",
            "build/library-plan.json",
            "build/assets-result.json",
        ],
    }


def preview_project_library_stage(
    root: Path, manifest: ProjectManifest
) -> dict[str, object]:
    """Run the library compose and live-collision checks without writes or POSTs."""

    client, verified = verify_project_portal(manifest)
    plan = _read_list(root / "build/library-plan.json", "library plan")
    result = preview_project_library(
        client,
        plan=plan,
        manifest_path=root / "build/block-manifest.json",
    )
    return {
        **result,
        "target": verified.as_dict(),
        "portal_actions": result.get("blocks", []),
        "local_writes": [
            "build/block-manifest.json",
            "build/composed-blocks.json",
            "build/library-result.json",
        ],
    }


def register_project_library_stage(context: StageContext) -> StageResult:
    """Register the approved custom-block library without publishing anything."""

    client, verified = verify_project_portal(context.manifest)
    plan = _read_list(context.root / "build/library-plan.json", "library plan")
    desired, records = register_project_library(
        client,
        plan=plan,
        manifest_path=context.root / "build/block-manifest.json",
    )
    catalog_relative = "build/composed-blocks.json"
    report_relative = "build/library-result.json"
    _write_json(context.root / catalog_relative, desired)
    _write_json(
        context.root / report_relative,
        {
            "schema_version": "1.0",
            "target": verified.as_dict(),
            "total": len(records),
            "created": sum(record["status"] == "created" for record in records),
            "reused": sum(record["status"] in {"reused", "adopted"} for record in records),
            "published": False,
            "blocks": records,
        },
    )
    return StageResult(
        artifacts=(
            "build/block-manifest.json",
            catalog_relative,
            report_relative,
        ),
        message=f"Reconciled {len(records)} custom block(s) on portal {verified.portal_id}.",
    )


def preview_project_page_stage(
    root: Path,
    manifest: ProjectManifest,
    *,
    isolated: bool,
) -> dict[str, object]:
    """Assemble and compare page drafts without local writes or portal posts."""

    client, verified = verify_project_portal(manifest)
    desired = _compose_pages(root, manifest, isolated=isolated)
    result = preview_project_pages(
        client,
        desired=desired,
        manifest_path=_latest_page_manifest_path(root),
    )
    snapshot_writes = _planned_snapshot_paths(result.get("pages", []))
    return {
        **result,
        "target": verified.as_dict(),
        "portal_actions": result.get("pages", []),
        "local_writes": [
            "build/pages-desired.json",
            "build/page-manifest.json",
            "build/pages-result.json",
            *snapshot_writes,
        ],
    }


def reconcile_project_page_stage(
    context: StageContext,
    *,
    isolated: bool,
) -> StageResult:
    """Create or safely update complete page drafts without publishing them."""

    client, verified = verify_project_portal(context.manifest)
    _promote_latest_page_manifest(context.root)
    desired = _compose_pages(context.root, context.manifest, isolated=isolated)
    desired_relative = "build/pages-desired.json"
    manifest_relative = "build/page-manifest.json"
    result_relative = "build/pages-result.json"
    _write_json(context.root / desired_relative, desired)
    records = reconcile_project_pages(
        client,
        desired=desired,
        manifest_path=context.root / manifest_relative,
        snapshots_dir=context.root / "build/page-snapshots",
    )
    _write_json(
        context.root / result_relative,
        {
            "schema_version": "1.0",
            "target": verified.as_dict(),
            "isolated": isolated,
            "total": len(records),
            "created": sum(record["status"] == "created" for record in records),
            "updated": sum(record["status"] == "updated" for record in records),
            "reused": sum(record["status"] in {"reuse", "adopt"} for record in records),
            "published": False,
            "pages": records,
        },
    )
    return StageResult(
        artifacts=(desired_relative, manifest_relative, result_relative),
        message=f"Reconciled {len(records)} unpublished page draft(s) on portal {verified.portal_id}.",
    )


def preview_project_global_stage(
    root: Path,
    manifest: ProjectManifest,
) -> dict[str, object]:
    """Compose global blocks and inspect live collisions without mutation."""

    client, verified = verify_project_portal(manifest)
    desired = _compose_globals(root, manifest)
    global_preview = preview_project_global_blocks(
        client,
        desired=desired,
        manifest_path=root / "build/global-block-manifest.json",
    )
    actions_by_key = {
        action.get("key"): action
        for action in global_preview.get("blocks", [])
        if isinstance(action, dict)
    }
    bindings: list[dict[str, object]] = []
    projected_records: list[dict[str, object]] = []
    for item in desired:
        action = actions_by_key.get(item["key"], {})
        observed_guid = action.get("guid") if isinstance(action, dict) else None
        guid = (
            observed_guid
            if isinstance(observed_guid, str) and observed_guid
            else f"agency-binding://global/{item['key']}"
        )
        bindings.append(
            {
                "key": item["key"],
                "guid": guid,
                "resolved": not guid.startswith("agency-binding://"),
            }
        )
        projected_records.append(
            {
                "key": item["key"],
                "kind": item["kind"],
                "guid": guid,
            }
        )
    page_desired = _read_list(root / "build/pages-desired.json", "desired page catalog")
    if any(not isinstance(item, dict) for item in page_desired):
        raise ValueError("desired page catalog contains a non-object entry")
    with_globals, chrome_warnings = attach_global_wrappers(
        page_desired, projected_records
    )
    page_preview = preview_project_pages(
        client,
        desired=with_globals,
        manifest_path=_global_page_preview_manifest_path(root),
        snapshot_root="build/global-page-snapshots",
        manifest_write_path="build/global-page-manifest.json",
    )
    unresolved_bindings = [
        entry["guid"]
        for entry in bindings
        if not bool(entry["resolved"])
    ]
    planned_page_actions = [
        _parameterize_page_action(action, unresolved_bindings)
        for action in page_preview.get("pages", [])
        if isinstance(action, dict)
    ]
    page_preview = {**page_preview, "pages": planned_page_actions}
    global_snapshots = [
        item["snapshot_write_path"]
        for item in global_preview.get("blocks", [])
        if isinstance(item, dict)
        and item.get("action") in {"replace_create", "replace_finish"}
    ]
    page_snapshots = _planned_snapshot_paths(planned_page_actions)
    return {
        "schema_version": "1.1",
        "target": verified.as_dict(),
        "globals": global_preview,
        "pages": page_preview,
        "bindings": bindings,
        "warnings": list(chrome_warnings),
        "portal_actions": [
            *global_preview.get("blocks", []),
            *planned_page_actions,
        ],
        "local_writes": [
            "build/global-blocks-desired.json",
            "build/global-block-manifest.json",
            "build/global-blocks-result.json",
            "build/pages-with-globals-desired.json",
            "build/global-page-manifest.json",
            "build/pages-with-globals-result.json",
            *global_snapshots,
            *page_snapshots,
        ],
    }


def _parameterize_page_action(
    action: dict[str, object], unresolved_bindings: list[object]
) -> dict[str, object]:
    """Label binding-bearing page work as a template, never as a concrete payload."""

    if not unresolved_bindings:
        return action
    planned = dict(action)
    provisional_action = str(planned["action"])
    planned["action"] = "resolve_bindings_then_reconcile"
    planned["provisional_action"] = provisional_action
    planned["binding_mode"] = "parameterized"
    planned["global_guid_bindings"] = list(unresolved_bindings)
    planned["resolved_payload_fingerprint"] = None
    if "desired_hash" in planned:
        planned["template_preview_hash"] = planned.pop("desired_hash")
    if "desired_state_fingerprint" in planned:
        planned["desired_template_fingerprint"] = planned.pop(
            "desired_state_fingerprint"
        )
    if "payload_fingerprint" in planned:
        value = planned.pop("payload_fingerprint")
        planned["payload_template_fingerprint"] = value
    operations = []
    for raw in planned.get("operations", []):
        if not isinstance(raw, dict):
            continue
        operation = dict(raw)
        if "payload_fingerprint" in operation:
            operation["payload_template_fingerprint"] = operation.pop(
                "payload_fingerprint"
            )
        operation["global_guid_bindings"] = list(unresolved_bindings)
        operations.append(operation)
    planned["operations"] = operations
    return planned


def _planned_snapshot_paths(actions: object) -> list[str]:
    result: list[str] = []
    if not isinstance(actions, list):
        return result
    for action in actions:
        if not isinstance(action, dict):
            continue
        for operation in action.get("operations", []):
            if (
                isinstance(operation, dict)
                and operation.get("kind") == "local_snapshot"
                and isinstance(operation.get("path"), str)
            ):
                result.append(operation["path"])
    return result


def reconcile_project_global_stage(context: StageContext) -> StageResult:
    """Create unpublished shared chrome and attach it to project page drafts."""

    client, verified = verify_project_portal(context.manifest)
    desired_globals = _compose_globals(context.root, context.manifest)
    globals_desired_relative = "build/global-blocks-desired.json"
    globals_manifest_relative = "build/global-block-manifest.json"
    globals_result_relative = "build/global-blocks-result.json"
    pages_desired_relative = "build/pages-with-globals-desired.json"
    pages_manifest_relative = "build/global-page-manifest.json"
    pages_result_relative = "build/pages-with-globals-result.json"
    _write_json(context.root / globals_desired_relative, desired_globals)
    global_records = reconcile_project_global_blocks(
        client,
        desired=desired_globals,
        manifest_path=context.root / globals_manifest_relative,
        snapshots_dir=context.root / "build/global-block-snapshots",
    )
    _write_json(
        context.root / globals_result_relative,
        {
            "schema_version": "1.0",
            "target": verified.as_dict(),
            "total": len(global_records),
            "published": False,
            "blocks": global_records,
        },
    )
    page_desired = _read_list(
        context.root / "build/pages-desired.json", "desired page catalog"
    )
    if any(not isinstance(item, dict) for item in page_desired):
        raise ValueError("desired page catalog contains a non-object entry")
    with_globals, chrome_warnings = attach_global_wrappers(page_desired, global_records)  # type: ignore[arg-type]
    _write_json(context.root / pages_desired_relative, with_globals)
    global_page_manifest = context.root / pages_manifest_relative
    page_seed = json.loads(
        (context.root / "build/page-manifest.json").read_text(encoding="utf-8")
    )
    if (
        not global_page_manifest.is_file()
        or _manifest_version(page_seed)
        > _manifest_version(json.loads(global_page_manifest.read_text(encoding="utf-8")))
    ):
        _write_json(global_page_manifest, page_seed)
    page_records = reconcile_project_pages(
        client,
        desired=with_globals,
        manifest_path=global_page_manifest,
        snapshots_dir=context.root / "build/global-page-snapshots",
    )
    _write_json(
        context.root / pages_result_relative,
        {
            "schema_version": "1.0",
            "target": verified.as_dict(),
            "total": len(page_records),
            "published": False,
            "pages": page_records,
            "warnings": list(chrome_warnings),
        },
    )
    return StageResult(
        artifacts=(
            globals_desired_relative,
            globals_manifest_relative,
            globals_result_relative,
            pages_desired_relative,
            pages_manifest_relative,
            pages_result_relative,
        ),
        message=(
            f"Reconciled {len(global_records)} unpublished global block(s) and "
            f"attached them to {len(page_records)} page draft(s)."
            + ("".join(f" Warning: {warning}." for warning in chrome_warnings))
        ),
    )


def _compose_globals(
    root: Path, manifest: ProjectManifest
) -> list[dict[str, object]]:
    document = read_design_document(root / "build/design-document.json")
    global_plan = json.loads(
        (root / "plans/global-block-plan.json").read_text(encoding="utf-8")
    )
    if not isinstance(global_plan, dict):
        raise ValueError("global block plan must contain a JSON object")
    return compose_project_global_blocks(
        document,
        global_plan,
        project_id=manifest.project.id,
    )


def _compose_pages(
    root: Path,
    manifest: ProjectManifest,
    *,
    isolated: bool,
) -> list[dict[str, object]]:
    document = read_design_document(root / "build/design-document.json")
    blocks = _read_list(root / "build/composed-blocks.json", "composed block catalog")
    global_plan = json.loads(
        (root / "plans/global-block-plan.json").read_text(encoding="utf-8")
    )
    if not isinstance(global_plan, dict):
        raise ValueError("global block plan must contain a JSON object")
    asset_manifest = json.loads(
        (root / "build/asset-manifest.json").read_text(encoding="utf-8")
    )
    asset_records = (
        asset_manifest.get("assets", []) if isinstance(asset_manifest, dict) else []
    )
    if not isinstance(asset_records, list):
        raise ValueError("asset manifest has an unexpected format")
    return compose_project_pages(
        document,
        blocks,
        global_plan,
        project_id=manifest.project.id,
        isolated=isolated,
        asset_records=asset_records,
    )


def _promote_latest_page_manifest(root: Path) -> None:
    primary = root / "build/page-manifest.json"
    downstream = root / "build/global-page-manifest.json"
    if not downstream.is_file() or not primary.is_file():
        return
    primary_value = json.loads(primary.read_text(encoding="utf-8"))
    downstream_value = json.loads(downstream.read_text(encoding="utf-8"))
    if _manifest_version(downstream_value) > _manifest_version(primary_value):
        _write_json(primary, downstream_value)


def _latest_page_manifest_path(root: Path) -> Path:
    """Select the newest page manifest for a read-only reconciliation preview."""

    primary = root / "build/page-manifest.json"
    downstream = root / "build/global-page-manifest.json"
    if not downstream.is_file():
        return primary
    if not primary.is_file():
        return downstream
    primary_value = json.loads(primary.read_text(encoding="utf-8"))
    downstream_value = json.loads(downstream.read_text(encoding="utf-8"))
    if _manifest_version(downstream_value) > _manifest_version(primary_value):
        return downstream
    return primary


def _global_page_preview_manifest_path(root: Path) -> Path:
    """Model the apply-time page-manifest seed decision without writing it."""

    primary = root / "build/page-manifest.json"
    downstream = root / "build/global-page-manifest.json"
    if not downstream.is_file() or not primary.is_file():
        return primary if primary.is_file() else downstream
    primary_value = json.loads(primary.read_text(encoding="utf-8"))
    downstream_value = json.loads(downstream.read_text(encoding="utf-8"))
    if _manifest_version(primary_value) > _manifest_version(downstream_value):
        return primary
    return downstream


def _manifest_version(value: object) -> int:
    if not isinstance(value, dict) or not isinstance(value.get("pages"), list):
        return 0
    return max(
        (
            int(record.get("observed_version", 0))
            for record in value["pages"]
            if isinstance(record, dict)
        ),
        default=0,
    )


def _read_list(path: Path, label: str) -> list[object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError(f"{label} must contain a JSON array")
    return payload


def _read_asset_records(path: Path) -> dict[object, tuple[object, object]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    records = payload.get("assets", []) if isinstance(payload, dict) else []
    if not isinstance(records, list):
        return {}
    return {
        record.get("asset_id"): (record.get("sha256"), record.get("vanjaro_url"))
        for record in records
        if isinstance(record, dict)
    }


def _write_json(path: Path, value: object) -> None:
    atomic_write_json(path, value)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


__all__ = [
    "preserve_project_theme",
    "preview_preserve_project_theme",
    "preview_project_asset_stage",
    "preview_project_library_stage",
    "preview_project_page_stage",
    "preview_project_global_stage",
    "reconcile_project_page_stage",
    "reconcile_project_global_stage",
    "register_project_library_stage",
    "upload_project_asset_stage",
]
