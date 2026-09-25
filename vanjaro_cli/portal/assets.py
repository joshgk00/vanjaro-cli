"""Resumable project asset upload and local-to-portal URL rewriting."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from vanjaro_cli.design.models import DesignDocument
from vanjaro_cli.migration.url_rewrite import RewriteReport, substitute_css_urls
from vanjaro_cli.utils.image_links import is_safe_link_href


UPLOAD_ENDPOINT = "/API/VanjaroAI/AIAsset/Upload"

# Upload-acceptance boundary for a resolved asset destination (a fresh upload
# response's URL, or a cached manifest record considered for reuse). Raw
# control characters and CSS/HTML breakout characters are rejected outright
# because this value can land unquoted inside a generated ``url(...)`` token
# or an ``<img src>`` attribute; percent-encoded characters and ordinary
# ``?``/``&``/``=`` query strings pass through untouched.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*):")
_SAFE_RESOURCE_SCHEMES = frozenset({"http", "https"})
_BREAKOUT_CHARS = frozenset("\"'()<>\\`")


class ProjectAssetError(ValueError):
    """Raised when a project asset cannot be uploaded or reconciled safely."""


def _is_safe_resource_destination(url: Any) -> bool:
    """Whether ``url`` may be accepted as an uploaded-or-reused asset destination.

    This is the acceptance boundary itself: nothing reaches a manifest
    record, a rewritten override, or a CSS ``url(...)`` substitution unless
    it passes here first. Consistent with -- and stricter than -- the
    downstream CSS-safety filter in ``_build_css_asset_lookup``
    (``is_safe_link_href``): a portal-relative path or a safe ``http``/
    ``https`` URL is accepted, but ``mailto:``/``tel:`` (valid link
    destinations, meaningless as an image resource) are not.
    """
    if not isinstance(url, str):
        return False
    text = url.strip()
    if not text or text != url:
        return False
    if _CONTROL_CHARS.search(text):
        return False
    if any(char in _BREAKOUT_CHARS for char in text):
        return False
    if not is_safe_link_href(text):
        return False
    match = _SCHEME.match(text)
    if match is not None and match.group(1).casefold() not in _SAFE_RESOURCE_SCHEMES:
        return False
    return True


def _conflicting_source_aliases(document: DesignDocument) -> dict[str, list[str]]:
    """Original ``source_url`` values shared by more than one distinct asset.

    A shared alias is inherently ambiguous -- CSS authored against it could
    resolve to either asset's uploaded destination -- so it must be rejected
    explicitly by ``upload_project_assets`` rather than silently dropped or
    guessed at.
    """
    by_source: dict[str, list[str]] = {}
    for asset in document.assets:
        source_url = asset.source_url
        if not isinstance(source_url, str) or not source_url:
            continue
        by_source.setdefault(source_url, []).append(asset.id)
    return {
        source_url: ids for source_url, ids in by_source.items() if len(set(ids)) > 1
    }


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
        if reusable and not _is_safe_resource_destination(previous["vanjaro_url"]):
            raise ProjectAssetError(
                f"cached asset manifest entry for {asset.id!r} has an unsafe "
                "or malformed destination and cannot be reused; remove or "
                "correct the manifest entry before retrying"
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

    conflicts = _conflicting_source_aliases(document)
    if conflicts:
        detail = "; ".join(
            f"{source_url!r} -> assets {sorted(ids)}"
            for source_url, ids in sorted(conflicts.items())
        )
        raise ProjectAssetError(
            "ambiguous original source URL(s) are shared by more than one "
            f"asset and cannot be resolved to a single upload: {detail}"
        )

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
        if not _is_safe_resource_destination(portal_url):
            raise ProjectAssetError(
                "asset upload returned an unsafe or malformed destination "
                f"for {item['local_path']}; refusing to accept it as a "
                "successful upload"
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
    css_lookup = _build_css_asset_lookup(document, replacements)
    rewritten_plan = _rewrite_style_declarations(
        _replace_strings(library_plan, replacements), css_lookup, RewriteReport()
    )
    return (
        DesignDocument.model_validate(
            document.model_copy(update={"assets": assets}).model_dump()
        ),
        rewritten_plan,
        records,
    )


def _build_css_asset_lookup(
    document: DesignDocument, replacements: dict[str, str]
) -> dict[str, str]:
    """Map both an asset's local path and its original source URL to the
    portal URL it resolved to, for rewriting ``url(...)`` references in
    library-plan CSS (``_rewrite_style_declarations``).

    ``replacements`` already keys by local path (both reused and freshly
    uploaded assets); this adds the pre-upload ``source_url`` alongside it
    so CSS authored against the original absolute source URL resolves too.
    A source URL shared by two assets that resolved to different portal
    URLs is ambiguous and is dropped rather than guessed -- any CSS
    referencing it stays unmigrated and explicit. A portal URL that is not
    a safe link destination (see ``is_safe_link_href``) never enters the
    lookup, so it can never land inside generated CSS.
    """

    lookup: dict[str, str] = {
        local_path: portal_url
        for local_path, portal_url in replacements.items()
        if is_safe_link_href(portal_url)
    }
    ambiguous: set[str] = set()
    for asset in document.assets:
        source_url = asset.source_url
        if not isinstance(source_url, str) or not source_url:
            continue
        portal_url = replacements.get(asset.local_path or "")
        if portal_url is None or not is_safe_link_href(portal_url):
            continue
        existing = lookup.get(source_url)
        if existing is not None and existing != portal_url:
            ambiguous.add(source_url)
            continue
        lookup[source_url] = portal_url
    for alias in ambiguous:
        lookup.pop(alias, None)
    return lookup


def _rewrite_style_declarations(
    value: Any, css_lookup: dict[str, str], report: RewriteReport
) -> Any:
    """Rewrite ``url(...)`` tokens inside every ``style_declarations`` map
    found while walking a library plan, leaving everything else untouched.

    Reuses ``migration.url_rewrite.substitute_css_urls`` -- the same CSS
    ``url(...)`` substitution already applied to migrated page content --
    rather than a second, redundant parser. Breakpoint-prefixed keys
    (``"tablet:background-image"``) are ordinary dict keys here and need no
    special casing: every string value in a ``style_declarations`` map is
    checked. Non-string values, and non-CSS-url strings, pass through
    unchanged; a value is rebuilt only when it actually contains a
    ``url(...)`` token.
    """

    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if key == "style_declarations" and isinstance(item, dict):
                result[key] = {
                    prop: substitute_css_urls(css_value, css_lookup, report)
                    if isinstance(css_value, str) and "url(" in css_value.lower()
                    else css_value
                    for prop, css_value in item.items()
                }
            else:
                result[key] = _rewrite_style_declarations(item, css_lookup, report)
        return result
    if isinstance(value, list):
        return [_rewrite_style_declarations(item, css_lookup, report) for item in value]
    return value


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
