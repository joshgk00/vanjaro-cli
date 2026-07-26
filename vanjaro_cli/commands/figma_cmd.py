"""vanjaro figma commands — inspect a Figma file, extract tokens, export assets.

These commands talk only to the Figma REST API (via ``vanjaro_cli.figma``)
and never touch the Vanjaro client or profile, so they skip ``get_client``.
Authentication is the ``FIGMA_ACCESS_TOKEN`` env var.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import click

from vanjaro_cli.commands.helpers import exit_error, output_result
from vanjaro_cli.figma import FigmaClient, FigmaError, parse_file_key, parse_node_id
from vanjaro_cli.utils.figma_tokens import (
    build_design_tokens,
    build_theme_palette,
    collect_image_fills,
    collect_solid_fills,
    collect_text_styles,
    figma_color_to_hex,
    iter_nodes,
)

# A frame reads as a full page when it's desktop-wide and much taller than wide.
PAGE_LIKE_MIN_WIDTH = 1200
PAGE_LIKE_HEIGHT_RATIO = 1.5

_EXTENSION_BY_CONTENT_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


def _build_client(as_json: bool) -> FigmaClient:
    try:
        return FigmaClient()
    except FigmaError as exc:
        exit_error(str(exc), as_json)


def _sanitize_name(name: str | None) -> str:
    """Turn a Figma node name into a filesystem-safe slug."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", (name or "asset").strip().lower()).strip("-")
    return slug or "asset"


def _sniff_extension(content_type: str, first_bytes: bytes) -> str:
    """Pick a file extension from content-type, falling back to byte signatures."""
    normalized = (content_type or "").lower()
    if normalized in _EXTENSION_BY_CONTENT_TYPE:
        return _EXTENSION_BY_CONTENT_TYPE[normalized]
    if first_bytes.startswith(b"\x89PNG"):
        return ".png"
    if first_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if first_bytes.startswith(b"GIF8"):
        return ".gif"
    if first_bytes[:4] == b"RIFF" and first_bytes[8:12] == b"WEBP":
        return ".webp"
    if first_bytes.lstrip()[:5].lower() == b"<?xml" or first_bytes.lstrip()[:4].lower() == b"<svg":
        return ".svg"
    return ".png"


def _resolve_scope(client: FigmaClient, key: str, node_id: str | None) -> dict:
    """Return the document node for the whole file or a single frame."""
    if node_id:
        payload = client.get_nodes(key, [node_id])
        entry = (payload.get("nodes") or {}).get(node_id)
        if not entry or "document" not in entry:
            raise FigmaError(f"Node {node_id} not found in this Figma file.")
        return entry["document"]
    return client.get_file(key)["document"]


@click.group()
def figma() -> None:
    """Inspect Figma designs and pull tokens and assets."""


@figma.command("inspect")
@click.argument("url")
@click.option("--node", "node", default=None, help="Summarize one frame's subtree instead of the page list.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def inspect(url: str, node: str | None, as_json: bool) -> None:
    """Summarize a Figma file's pages and top-level frames."""
    try:
        key = parse_file_key(url)
        node_id = parse_node_id(node)
    except FigmaError as exc:
        exit_error(str(exc), as_json)

    client = _build_client(as_json)

    if node_id:
        try:
            document = _resolve_scope(client, key, node_id)
        except FigmaError as exc:
            exit_error(str(exc), as_json)
        summary = _summarize_frame(document)
        if as_json:
            output_result(as_json, "ok", "", node=node_id, summary=summary)
        else:
            click.echo(f"Frame: {document.get('name')} ({node_id})")
            box = document.get("absoluteBoundingBox") or {}
            click.echo(f"  size: {box.get('width')}x{box.get('height')}")
            click.echo(f"  text nodes: {summary['text_nodes']}")
            click.echo(f"  image fills: {summary['image_fills']}")
            click.echo("  top colors: " + ", ".join(summary["top_colors"]))
            click.echo("  top fonts: " + ", ".join(summary["top_fonts"]))
        return

    try:
        document = client.get_file(key, depth=2)["document"]
    except FigmaError as exc:
        exit_error(str(exc), as_json)

    pages = _summarize_pages(document)
    if as_json:
        output_result(as_json, "ok", "", file_key=key, pages=pages)
        return
    for page in pages:
        click.echo(f"Page: {page['name']}")
        for frame in page["frames"]:
            flag = "  [page-like]" if frame["page_like"] else ""
            click.echo(f"  {frame['id']}  {frame['name']}  {frame['width']}x{frame['height']}{flag}")


def _is_page_like(width: float, height: float) -> bool:
    return width >= PAGE_LIKE_MIN_WIDTH and height >= PAGE_LIKE_HEIGHT_RATIO * width


def _summarize_pages(document: dict) -> list[dict]:
    pages: list[dict] = []
    for page in document.get("children", []) or []:
        frames = []
        for frame in page.get("children", []) or []:
            box = frame.get("absoluteBoundingBox") or {}
            width = float(box.get("width") or 0)
            height = float(box.get("height") or 0)
            frames.append(
                {
                    "id": frame.get("id"),
                    "name": frame.get("name"),
                    "width": width,
                    "height": height,
                    "page_like": _is_page_like(width, height),
                }
            )
        pages.append({"name": page.get("name"), "frames": frames})
    return pages


def _summarize_frame(document: dict) -> dict:
    text_styles = collect_text_styles(document)
    fills = collect_solid_fills(document)
    image_fills = collect_image_fills(document)

    top_colors = [
        hex_value
        for hex_value, _area in sorted(fills.items(), key=lambda kv: kv[1], reverse=True)[:5]
    ]
    font_counter = Counter(s["font_family"] for s in text_styles if s.get("font_family"))
    top_fonts = [name for name, _count in font_counter.most_common(5)]

    return {
        "text_nodes": sum(1 for _ in iter_nodes(document) if _.get("type") == "TEXT"),
        "image_fills": len(image_fills),
        "top_colors": top_colors,
        "top_fonts": top_fonts,
    }


@figma.command("tokens")
@click.argument("url")
@click.option("--node", "node", default=None, help="Extract from one frame instead of the whole file.")
@click.option("-o", "--output", "output", default="design-tokens.json", help="Where to write design-tokens.json.")
@click.option("--palette", "palette_path", default=None, help="Also write a flat theme-palette.json here.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def tokens(url: str, node: str | None, output: str, palette_path: str | None, as_json: bool) -> None:
    """Extract design tokens from a Figma file or frame."""
    try:
        key = parse_file_key(url)
        node_id = parse_node_id(node)
    except FigmaError as exc:
        exit_error(str(exc), as_json)

    client = _build_client(as_json)
    try:
        document = _resolve_scope(client, key, node_id)
    except FigmaError as exc:
        exit_error(str(exc), as_json)

    design_tokens = build_design_tokens(
        document,
        extracted_from=url,
    )
    output_file = Path(output)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(design_tokens, indent=2), encoding="utf-8")

    written = {"design_tokens": output}
    if palette_path:
        palette = build_theme_palette(document)
        palette_file = Path(palette_path)
        palette_file.parent.mkdir(parents=True, exist_ok=True)
        palette_file.write_text(json.dumps(palette, indent=2), encoding="utf-8")
        written["palette"] = palette_path

    output_result(
        as_json,
        "ok",
        f"Wrote {output}" + (f" and {palette_path}" if palette_path else ""),
        **written,
        colors=design_tokens["colors"],
        notes=design_tokens["custom_css_needed"],
    )


@figma.command("export")
@click.argument("url")
@click.option("--node", "node", default=None, help="Export image fills from one frame instead of the whole file.")
@click.option("-o", "--output", "output", default="figma-assets", help="Directory to write assets and manifest.json into.")
@click.option("--render", "render", is_flag=True, help="Also export @2x frame renders (capped ~4096px).")
@click.option("--dry-run", "dry_run", is_flag=True, help="List assets without downloading.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def export(url: str, node: str | None, output: str, render: bool, dry_run: bool, as_json: bool) -> None:
    """Download original-resolution image fills used in the design."""
    try:
        key = parse_file_key(url)
        node_id = parse_node_id(node)
    except FigmaError as exc:
        exit_error(str(exc), as_json)

    client = _build_client(as_json)
    try:
        document = _resolve_scope(client, key, node_id)
        image_fills = collect_image_fills(document)
        fill_urls = client.get_image_fills(key)
    except FigmaError as exc:
        exit_error(str(exc), as_json)

    planned = [f for f in image_fills if f["image_ref"] in fill_urls]
    missing = [f["image_ref"] for f in image_fills if f["image_ref"] not in fill_urls]

    if dry_run:
        output_result(
            as_json,
            "ok",
            f"Dry run: {len(planned)} image fill(s) would be exported to {output}.",
            dry_run=True,
            planned=[{"node_name": f["node_name"], "image_ref": f["image_ref"]} for f in planned],
            missing_refs=missing,
        )
        if not as_json:
            for fill in planned:
                click.echo(f"  {fill['node_name']}  {fill['image_ref'][:8]}")
        return

    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    exported: list[str] = []

    for fill in planned:
        image_ref = fill["image_ref"]
        base = f"{_sanitize_name(fill['node_name'])}-{image_ref[:8]}"
        temp_path = output_dir / base
        try:
            size_bytes, content_type = client.download(fill_urls[image_ref], temp_path)
        except FigmaError as exc:
            exit_error(str(exc), as_json)
        extension = _sniff_extension(content_type, temp_path.read_bytes()[:16])
        final_path = temp_path.with_name(base + extension)
        temp_path.replace(final_path)

        manifest.append(
            {
                "source_url": f"figma://{key}/{image_ref}",
                "local_file": final_path.relative_to(output_dir).as_posix(),
                "filename": final_path.name,
                "size_bytes": size_bytes,
                "content_type": content_type or _EXTENSION_BY_CONTENT_TYPE.get(extension, ""),
                "vanjaro_url": None,
                "vanjaro_file_id": None,
                "variants": [],
                "uploaded": False,
            }
        )
        exported.append(final_path.name)

    renders: list[str] = []
    if render and node_id:
        try:
            render_map = client.get_image_renders(key, [node_id], scale=2, image_format="png")
            render_url = (render_map.get("images") or {}).get(node_id)
            if render_url:
                render_name = f"{_sanitize_name(document.get('name'))}-render@2x.png"
                client.download(render_url, output_dir / render_name)
                renders.append(render_name)
        except FigmaError as exc:
            exit_error(str(exc), as_json)

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    output_result(
        as_json,
        "ok",
        f"Exported {len(exported)} asset(s) to {output} (manifest.json written).",
        directory=str(output_dir),
        exported=exported,
        renders=renders,
        missing_refs=missing,
    )


# Imported after the existing command definitions to keep the analysis command
# isolated and avoid changing inspect/tokens/export behavior.
from vanjaro_cli.commands.figma_analyze_cmd import figma_analyze  # noqa: E402

figma.add_command(figma_analyze)
