"""Resumable project asset upload and local-to-portal URL rewriting."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from vanjaro_cli.design.models import DesignDocument


UPLOAD_ENDPOINT = "/API/VanjaroAI/AIAsset/Upload"


class ProjectAssetError(ValueError):
    """Raised when a project asset cannot be uploaded or reconciled safely."""


def preview_project_assets(
    *,
    root: Path,
    project_id: str,
    document: DesignDocument,
) -> dict[str, Any]:
    """Return the deterministic, local-only plan for project asset uploads."""

    workspace = root.resolve()
    manifest_path = root / "build" / "asset-manifest.json"
    records = _load_records(manifest_path)
    by_asset_id = {record["asset_id"]: record for record in records}
    folder = f"Images/agency/{project_id}/"
    assets: list[dict[str, Any]] = []

    for asset in document.assets:
        if not asset.local_path:
            continue
        supplied = Path(asset.local_path)
        local = (root / supplied).resolve()
        try:
            relative = local.relative_to(workspace)
        except ValueError as exc:
            raise ProjectAssetError(
                f"asset path escapes project workspace: {asset.local_path}"
            ) from exc
        if not local.is_file():
            raise ProjectAssetError(f"local asset is missing: {asset.local_path}")

        content = local.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        size_bytes = len(content)
        previous = by_asset_id.get(asset.id)
        reusable = bool(
            previous
            and previous.get("sha256") == digest
            and previous.get("uploaded") is True
            and isinstance(previous.get("vanjaro_url"), str)
            and previous["vanjaro_url"]
        )
        payload_identity = {
            "fileName": local.name,
            "folderPath": folder,
            "sha256": digest,
            "sizeBytes": size_bytes,
        }
        planned_local_path = (
            relative.as_posix() if supplied.is_absolute() else supplied.as_posix()
        )
        item: dict[str, Any] = {
            "asset_id": asset.id,
            "local_path": planned_local_path,
            "sha256": digest,
            "size_bytes": size_bytes,
            "folder": folder,
            "filename": local.name,
            "action": "reuse" if reusable else "upload",
            "checkpoint_write_path": None
            if reusable
            else "build/asset-manifest.json",
        }
        if reusable:
            observed = {
                "vanjaro_url": previous["vanjaro_url"],
                "vanjaro_file_id": previous.get("vanjaro_file_id"),
                "variants": previous.get("variants", []),
                "uploaded": previous.get("uploaded"),
                "sha256": previous.get("sha256"),
            }
            item.update(
                {
                    "observed": observed,
                    "before_state_fingerprint": _canonical_hash(observed),
                }
            )
        else:
            item.update(
                {
                    "method": "POST",
                    "endpoint": UPLOAD_ENDPOINT,
                    "payload_fingerprint": hashlib.sha256(
                        json.dumps(
                            payload_identity,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode("utf-8")
                    ).hexdigest(),
                    "response_binding": f"asset-upload://{asset.id}",
                }
            )
        assets.append(item)

    return {
        "schema_version": "1.0",
        "assets": assets,
        "checkpoint_write_path": "build/asset-manifest.json",
        "final_write_path": "build/asset-manifest.json",
    }


def upload_project_assets(
    client: Any,
    *,
    root: Path,
    project_id: str,
    document: DesignDocument,
    library_plan: list[dict[str, Any]],
) -> tuple[DesignDocument, list[dict[str, Any]], list[dict[str, Any]]]:
    """Upload local design assets once and rewrite build inputs to portal URLs."""

    plan = preview_project_assets(root=root, project_id=project_id, document=document)
    manifest_path = root / plan["final_write_path"]
    records = _load_records(manifest_path)
    by_asset_id = {record["asset_id"]: record for record in records}
    replacements: dict[str, str] = {}

    for item in plan["assets"]:
        previous = by_asset_id.get(item["asset_id"])
        if item["action"] == "reuse":
            observed = item["observed"]
            replacements[item["local_path"]] = observed["vanjaro_url"]
            continue

        local = root / item["local_path"]
        content = local.read_bytes()
        if (
            hashlib.sha256(content).hexdigest() != item["sha256"]
            or len(content) != item["size_bytes"]
        ):
            raise ProjectAssetError(
                f"asset bytes changed after review: {item['local_path']}"
            )
        payload = {
            "fileName": item["filename"],
            "folderPath": item["folder"],
            "base64Content": base64.b64encode(content).decode("ascii"),
        }
        response = client.post(item["endpoint"], json=payload)
        body = response.json() if getattr(response, "content", True) else {}
        portal_url = body.get("url") or body.get("Url")
        if not isinstance(portal_url, str) or not portal_url:
            raise ProjectAssetError(
                f"asset upload returned no portal URL for {item['local_path']}"
            )
        record = {
            "asset_id": item["asset_id"],
            "local_path": item["local_path"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
            "folder": item["folder"],
            "filename": item["filename"],
            "vanjaro_url": portal_url,
            "vanjaro_file_id": body.get("fileId") or body.get("FileId"),
            "variants": body.get("variants") or body.get("Variants") or [],
            "uploaded": True,
        }
        if previous is None:
            records.append(record)
        else:
            records[records.index(previous)] = record
        by_asset_id[item["asset_id"]] = record
        replacements[item["local_path"]] = portal_url
        _write_records(manifest_path, records)

    _write_records(manifest_path, records)
    assets = []
    for asset in document.assets:
        portal_url = replacements.get(asset.local_path or "")
        if portal_url is None:
            assets.append(asset)
            continue
        assets.append(
            asset.model_copy(
                update={
                    "source_url": portal_url,
                    "local_path": None,
                    "metadata": {
                        **asset.metadata,
                        "project_local_path": asset.local_path,
                        "vanjaro_url": portal_url,
                    },
                }
            )
        )
    rewritten_plan = _replace_strings(library_plan, replacements)
    return (
        DesignDocument.model_validate(
            document.model_copy(update={"assets": assets}).model_dump()
        ),
        rewritten_plan,
        records,
    )


def _replace_strings(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_strings(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_strings(item, replacements) for key, item in value.items()}
    return value


def _canonical_hash(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectAssetError(f"invalid asset manifest {path}: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("assets"), list):
        raise ProjectAssetError(f"invalid asset manifest shape: {path}")
    return value["assets"]


def _write_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(
            {"schema_version": "1.0", "assets": records},
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
    "ProjectAssetError",
    "UPLOAD_ENDPOINT",
    "preview_project_assets",
    "upload_project_assets",
]
