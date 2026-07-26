"""`vanjaro figma analyze` orchestration.

This module intentionally owns only the new analysis command.  The existing
inspect/tokens/export implementations remain unchanged in ``figma_cmd``.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import re
from typing import NoReturn

import click

from vanjaro_cli.design.figma_adapter import FigmaAdapterError
from vanjaro_cli.design.serialization import serialize_design_document
from vanjaro_cli.design.sources import FigmaSourceRequest, analyze_source
from vanjaro_cli.figma import FigmaClient, FigmaError, parse_file_key, parse_node_id
from vanjaro_cli.utils.figma_tokens import (
    build_design_tokens,
    build_theme_palette,
    collect_image_fills,
)

_PAGE_MIN_WIDTH = 320
_PAGE_HEIGHT_RATIO = 1.5
_EXTENSIONS = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg",
    "image/gif": ".gif", "image/webp": ".webp", "image/svg+xml": ".svg",
}


def _error(
    message: str, *, category: str, action: str, as_json: bool,
) -> NoReturn:
    """Exit with a stable machine-readable category and recovery action."""

    if as_json:
        click.echo(json.dumps({
            "status": "error", "category": category,
            "message": message, "action": action,
        }))
        raise SystemExit(1)
    raise click.ClickException(f"{message}\nAction: {action}")


def _client(as_json: bool) -> FigmaClient:
    try:
        return FigmaClient()
    except FigmaError as exc:
        _error(
            str(exc), category="authentication_error",
            action="Set FIGMA_ACCESS_TOKEN to a token that can read this file.",
            as_json=as_json,
        )


def _page_like(frame: Mapping[str, object]) -> bool:
    box = frame.get("absoluteBoundingBox")
    if not isinstance(box, Mapping):
        return False
    try:
        width = float(box.get("width") or 0)
        height = float(box.get("height") or 0)
    except (TypeError, ValueError):
        return False
    return width >= _PAGE_MIN_WIDTH and height >= width * _PAGE_HEIGHT_RATIO


def _page_frames(document: Mapping[str, object]) -> list[tuple[str | None, dict]]:
    frames: list[tuple[str | None, dict]] = []
    for canvas in document.get("children", []) or []:
        if not isinstance(canvas, dict):
            continue
        canvas_id = str(canvas.get("id")) if canvas.get("id") is not None else None
        for frame in canvas.get("children", []) or []:
            if isinstance(frame, dict) and frame.get("type") in {"FRAME", "SECTION"} and _page_like(frame):
                frames.append((canvas_id, frame))
    return frames


def _filtered_document(document: Mapping[str, object], selected_ids: set[str]) -> dict:
    """Copy a Figma document retaining selected page-frame subtrees only."""

    result = {key: value for key, value in document.items() if key != "children"}
    canvases = []
    for canvas in document.get("children", []) or []:
        if not isinstance(canvas, dict):
            continue
        selected = [
            frame for frame in canvas.get("children", []) or []
            if isinstance(frame, dict) and str(frame.get("id")) in selected_ids
        ]
        if selected:
            copy = {key: value for key, value in canvas.items() if key != "children"}
            copy["children"] = selected
            canvases.append(copy)
    result["children"] = canvases
    return result


def _resolve_scope(
    client: FigmaClient, key: str, node_id: str | None,
    all_page_frames: bool, as_json: bool,
) -> tuple[dict, dict, list[str]]:
    """Return adapter payload, token/asset scope, and selected frame IDs."""

    try:
        if node_id:
            payload = client.get_nodes(key, [node_id])
            entry = (payload.get("nodes") or {}).get(node_id)
            if not entry or not isinstance(entry.get("document"), dict):
                _error(
                    f"Node {node_id} was not found in this Figma file.",
                    category="input_error",
                    action="Run `vanjaro figma inspect URL --json` and pass an existing frame ID.",
                    as_json=as_json,
                )
            frame = entry["document"]
            return frame, frame, [node_id]

        file_payload = client.get_file(key)
        document = file_payload.get("document")
        if not isinstance(document, dict):
            raise FigmaError("Figma file response did not contain a document tree.")
        frames = _page_frames(document)
        if not frames:
            _error(
                "No page-like frames were found in this Figma file.",
                category="frame_selection_error",
                action="Pass --node with the frame ID you want to analyze.",
                as_json=as_json,
            )
        if len(frames) > 1 and not all_page_frames:
            choices = [{"id": str(frame.get("id")), "name": frame.get("name")} for _, frame in frames]
            if as_json:
                click.echo(json.dumps({
                    "status": "error", "category": "frame_selection_required",
                    "message": "Multiple page-like frames were found.",
                    "action": "Pass --node FRAME_ID or --all-page-frames.",
                    "frames": choices,
                }))
                raise SystemExit(1)
            formatted = ", ".join(f"{item['id']} ({item['name']})" for item in choices)
            _error(
                f"Multiple page-like frames were found: {formatted}",
                category="frame_selection_required",
                action="Pass --node FRAME_ID or --all-page-frames.",
                as_json=False,
            )
        selected = frames if all_page_frames else frames[:1]
        selected_ids = {str(frame.get("id")) for _, frame in selected}
        filtered = _filtered_document(document, selected_ids)
        adapter_payload = {**{key_: value for key_, value in file_payload.items() if key_ != "document"}, "document": filtered}
        token_scope: dict = filtered if len(selected) > 1 else selected[0][1]
        return adapter_payload, token_scope, sorted(selected_ids)
    except FigmaError as exc:
        _error(
            str(exc), category="figma_api_error",
            action="Verify the file URL, frame access, and Figma token, then retry.",
            as_json=as_json,
        )


def _slug(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "asset").lower()).strip("-") or "asset"


def _extension(content_type: str, first_bytes: bytes) -> str:
    normalized = (content_type or "").lower()
    if normalized in _EXTENSIONS:
        return _EXTENSIONS[normalized]
    if first_bytes.startswith(b"\x89PNG"):
        return ".png"
    if first_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if first_bytes.lstrip().lower().startswith(b"<svg"):
        return ".svg"
    return ".bin"


def _asset_manifest(
    *, client: FigmaClient, key: str, scope: dict,
    fill_urls: Mapping[str, str], output_dir: Path,
    export_assets: bool, dry_run: bool, as_json: bool,
) -> tuple[list[dict], list[str]]:
    grouped: dict[str, list[dict]] = {}
    for fill in collect_image_fills(scope):
        grouped.setdefault(fill["image_ref"], []).append(fill)

    entries: list[dict] = []
    downloaded: list[str] = []
    for image_ref, owners in sorted(grouped.items()):
        signed_url = fill_urls.get(image_ref)
        first = owners[0]
        filename = None
        local_file = None
        size_bytes = None
        content_type = None
        if export_assets and not dry_run and signed_url:
            assets_dir = output_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            base = f"{_slug(first.get('node_name'))}-{image_ref[:8]}"
            temporary = assets_dir / base
            try:
                size_bytes, content_type = client.download(signed_url, temporary)
            except FigmaError as exc:
                _error(
                    str(exc), category="asset_download_error",
                    action="Retry before the Figma signed URL expires, or omit --export-assets.",
                    as_json=as_json,
                )
            suffix = _extension(content_type, temporary.read_bytes()[:16])
            final_path = temporary.with_name(base + suffix)
            temporary.replace(final_path)
            filename = final_path.name
            local_file = final_path.relative_to(output_dir).as_posix()
            downloaded.append(local_file)
        entries.append({
            "id": f"figma-image-{image_ref}",
            "source_url": f"figma://{key}/{image_ref}",
            "image_ref": image_ref,
            "owner_node_ids": [owner.get("node_id") for owner in owners],
            "owner_node_names": [owner.get("node_name") for owner in owners],
            "original_available": signed_url is not None,
            "downloaded": local_file is not None,
            "local_file": local_file,
            "filename": filename,
            "size_bytes": size_bytes,
            "content_type": content_type,
        })
    return entries, downloaded


def _sanitize_design_assets(design_document, manifest: list[dict], key: str):
    """Replace expiring signed URLs with stable Figma identities/local paths."""

    by_ref = {entry["image_ref"]: entry for entry in manifest}
    assets = []
    for asset in design_document.assets:
        image_ref = asset.metadata.get("figma_image_ref")
        if not isinstance(image_ref, str):
            assets.append(asset)
            continue
        manifest_entry = by_ref.get(image_ref, {})
        assets.append(
            asset.model_copy(
                update={
                    "source_url": f"figma://{key}/{image_ref}",
                    "local_path": manifest_entry.get("local_file"),
                    "missing_reason": None,
                }
            )
        )
    return design_document.model_copy(update={"assets": assets})


@click.command("analyze")
@click.argument("url")
@click.option("--node", default=None, help="Analyze one page frame by ID.")
@click.option("--all-page-frames", is_flag=True, help="Analyze every detected page-like frame.")
@click.option("--output-dir", default="figma-analysis", show_default=True, help="Artifact output directory.")
@click.option("--export-assets", is_flag=True, help="Download original image fills into OUTPUT_DIR/assets.")
@click.option("--dry-run", is_flag=True, help="Analyze and report planned outputs without writing or downloading files.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def figma_analyze(
    url: str, node: str | None, all_page_frames: bool, output_dir: str,
    export_assets: bool, dry_run: bool, as_json: bool,
) -> None:
    """Analyze Figma page frames into Design Document v1 artifacts."""

    if node and all_page_frames:
        _error(
            "--node and --all-page-frames cannot be used together.",
            category="input_error", action="Choose one frame-selection mode.",
            as_json=as_json,
        )
    try:
        key = parse_file_key(url)
        node_id = parse_node_id(node)
    except FigmaError as exc:
        _error(
            str(exc), category="input_error",
            action="Provide a Figma file URL/key and an optional numeric frame ID.",
            as_json=as_json,
        )

    client = _client(as_json)
    adapter_payload, scope, selected_ids = _resolve_scope(
        client, key, node_id, all_page_frames, as_json,
    )
    try:
        fill_urls = client.get_image_fills(key)
    except FigmaError as exc:
        _error(
            str(exc), category="figma_api_error",
            action="Verify image-fill access for this file, then retry.",
            as_json=as_json,
        )

    try:
        design_document = analyze_source(FigmaSourceRequest(
            payload=adapter_payload, file_key=key, node_id=node_id,
            image_fill_urls=fill_urls,
        ))
        design_tokens = build_design_tokens(scope, extracted_from=url)
        palette = build_theme_palette(scope)
    except (FigmaAdapterError, ValueError, TypeError) as exc:
        _error(
            f"Figma analysis failed: {exc}", category="analysis_error",
            action="Inspect the selected frame structure and retry with a page-level frame.",
            as_json=as_json,
        )

    destination = Path(output_dir)
    manifest, downloaded = _asset_manifest(
        client=client, key=key, scope=scope, fill_urls=fill_urls,
        output_dir=destination, export_assets=export_assets,
        dry_run=dry_run, as_json=as_json,
    )
    design_document = _sanitize_design_assets(design_document, manifest, key)
    artifact_names = {
        "design_document": "design-document.json",
        "design_tokens": "design-tokens.json",
        "palette": "theme-palette.json",
        "asset_manifest": "asset-manifest.json",
    }
    artifacts = {name: str(destination / filename) for name, filename in artifact_names.items()}

    if not dry_run:
        try:
            destination.mkdir(parents=True, exist_ok=True)
            (destination / artifact_names["design_document"]).write_text(
                serialize_design_document(design_document), encoding="utf-8",
            )
            (destination / artifact_names["design_tokens"]).write_text(
                json.dumps(design_tokens, indent=2) + "\n", encoding="utf-8",
            )
            (destination / artifact_names["palette"]).write_text(
                json.dumps(palette, indent=2) + "\n", encoding="utf-8",
            )
            (destination / artifact_names["asset_manifest"]).write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
            )
        except OSError as exc:
            _error(
                f"Cannot write analysis artifacts to {destination}: {exc}",
                category="artifact_write_error",
                action="Choose a writable --output-dir and retry.",
                as_json=as_json,
            )

    result = {
        "status": "ok", "dry_run": dry_run,
        "selected_frames": selected_ids, "output_dir": str(destination),
        "artifacts": artifacts,
        "pages": len(design_document.pages),
        "sections": sum(len(page.sections) for page in design_document.pages),
        "assets": len(manifest), "downloaded": downloaded,
        "warnings": [warning.model_dump(mode="json") for warning in design_document.warnings],
    }
    if as_json:
        click.echo(json.dumps(result))
    else:
        prefix = "Dry run: would write" if dry_run else "Wrote"
        click.echo(f"{prefix} four Figma analysis artifacts in {destination}.")
        if export_assets:
            click.echo(f"Downloaded {len(downloaded)} original image fill(s).")
