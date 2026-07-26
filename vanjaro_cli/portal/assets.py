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


def upload_project_assets(
    client: Any,
    *,
    root: Path,
    project_id: str,
    document: DesignDocument,
    library_plan: list[dict[str, Any]],
) -> tuple[DesignDocument, list[dict[str, Any]], list[dict[str, Any]]]:
    """Upload local design assets once and rewrite build inputs to portal URLs."""

    manifest_path = root / "build" / "asset-manifest.json"
    records = _load_records(manifest_path)
    by_asset_id = {record["asset_id"]: record for record in records}
    folder = f"Images/agency/{project_id}/"
    replacements: dict[str, str] = {}

    for asset in document.assets:
        if not asset.local_path:
            continue
        local = (root / asset.local_path).resolve()
        try:
            local.relative_to(root.resolve())
        except ValueError as exc:
            raise ProjectAssetError(
                f"asset path escapes project workspace: {asset.local_path}"
            ) from exc
        if not local.is_file():
            raise ProjectAssetError(f"local asset is missing: {asset.local_path}")
        digest = hashlib.sha256(local.read_bytes()).hexdigest()
        previous = by_asset_id.get(asset.id)
        if (
            previous
            and previous.get("sha256") == digest
            and previous.get("uploaded") is True
            and isinstance(previous.get("vanjaro_url"), str)
            and previous["vanjaro_url"]
        ):
            replacements[asset.local_path] = previous["vanjaro_url"]
            continue

        payload = {
            "fileName": local.name,
            "folderPath": folder,
            "base64Content": base64.b64encode(local.read_bytes()).decode("ascii"),
        }
        response = client.post(UPLOAD_ENDPOINT, json=payload)
        body = response.json() if getattr(response, "content", True) else {}
        portal_url = body.get("url") or body.get("Url")
        if not isinstance(portal_url, str) or not portal_url:
            raise ProjectAssetError(
                f"asset upload returned no portal URL for {asset.local_path}"
            )
        record = {
            "asset_id": asset.id,
            "local_path": asset.local_path,
            "sha256": digest,
            "size_bytes": local.stat().st_size,
            "folder": folder,
            "filename": local.name,
            "vanjaro_url": portal_url,
            "vanjaro_file_id": body.get("fileId") or body.get("FileId"),
            "variants": body.get("variants") or body.get("Variants") or [],
            "uploaded": True,
        }
        if previous is None:
            records.append(record)
        else:
            records[records.index(previous)] = record
        by_asset_id[asset.id] = record
        replacements[asset.local_path] = portal_url
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


__all__ = ["ProjectAssetError", "UPLOAD_ENDPOINT", "upload_project_assets"]
