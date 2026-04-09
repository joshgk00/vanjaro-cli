"""vanjaro migrate build-id-map — generate a source URL → Vanjaro page ID map.

Phase 5 verify requires a ``page-id-map.json`` with one entry per migrated
page. Building this by hand on a 50-page site is tedious and error-prone, so
this command fetches the Vanjaro page list and automatically matches each
inventory page to its Vanjaro counterpart by path, title, or slug. Anything
that can't be matched is printed as a warning so the caller can hand-edit
the result.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.commands.helpers import (
    exit_error,
    get_client,
    output_result,
    read_json_object,
)
from vanjaro_cli.commands.pages_cmd import _list_ai_pages
from vanjaro_cli.config import ConfigError
from vanjaro_cli.models.page import Page

__all__ = ["build_id_map"]


@click.command("build-id-map")
@click.option(
    "--inventory",
    "inventory_file",
    type=click.Path(),
    required=True,
    help="site-inventory.json from a completed crawl.",
)
@click.option(
    "--output",
    "-o",
    "output_file",
    type=click.Path(),
    required=True,
    help="Destination path for the generated page-id-map JSON.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def build_id_map(inventory_file: str, output_file: str, as_json: bool) -> None:
    """Build a page-id-map by matching inventory pages to Vanjaro pages.

    Matching order for each inventory page:

    \b
      1. Exact path match (case-insensitive, trailing-slash tolerant)
      2. Portal home (source path "/" → the Vanjaro page with is_portal_home)
      3. Exact title match (case- and whitespace-normalized)
      4. Slug against normalized Vanjaro name

    Inventory pages that can't be matched are reported as warnings. The
    caller can hand-edit the resulting JSON to fix them.
    """
    inventory_path = Path(inventory_file)
    inventory = read_json_object(inventory_path, "Inventory", as_json)

    client, _ = get_client()
    try:
        vanjaro_pages = _list_ai_pages(client)
    except (ApiError, ConfigError) as exc:
        exit_error(f"Cannot list Vanjaro pages: {exc}", as_json)

    index = _build_vanjaro_index(vanjaro_pages)
    mapping, unmatched = _match_inventory_to_vanjaro(inventory, index)

    output_path = Path(output_file)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    except OSError as exc:
        exit_error(f"Cannot write {output_path}: {exc}", as_json)

    if unmatched and not as_json:
        for source_url in unmatched:
            click.echo(
                f"warning: no Vanjaro page found for {source_url}", err=True
            )

    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Built page-id-map with {len(mapping)} entries -> {output_path}. "
            f"Unmatched: {len(unmatched)}."
        ),
        output=str(output_path),
        matched=len(mapping),
        unmatched=list(unmatched),
    )


def _build_vanjaro_index(pages: list[Page]) -> dict:
    """Index Vanjaro pages by normalized path and name for fast lookup.

    First-wins when two pages share the same normalized key, so a callers'
    manual edit is the escape hatch for the rare collision case.
    """
    by_path: dict[str, int] = {}
    by_name: dict[str, int] = {}
    portal_home_id: int | None = None

    for page in pages:
        if page.is_portal_home and portal_home_id is None:
            portal_home_id = page.id

        if page.url:
            normalized_path = _normalize_path(page.url)
            if normalized_path:
                by_path.setdefault(normalized_path, page.id)

        if page.name:
            by_name.setdefault(_normalize_name(page.name), page.id)
        if page.title and page.title != page.name:
            by_name.setdefault(_normalize_name(page.title), page.id)

    return {
        "by_path": by_path,
        "by_name": by_name,
        "portal_home_id": portal_home_id,
    }


def _match_inventory_to_vanjaro(
    inventory: dict, index: dict
) -> tuple[dict[str, int], list[str]]:
    """Return (source_url -> vanjaro_page_id, unmatched_source_urls)."""
    mapping: dict[str, int] = {}
    unmatched: list[str] = []

    for source_page in inventory.get("pages") or []:
        if not isinstance(source_page, dict):
            continue
        source_url = source_page.get("url", "")
        if not isinstance(source_url, str) or not source_url:
            continue

        vanjaro_id = _match_single_page(source_page, index)
        if vanjaro_id is not None:
            mapping[source_url] = vanjaro_id
        else:
            unmatched.append(source_url)

    return mapping, unmatched


def _match_single_page(source_page: dict, index: dict) -> int | None:
    source_path = source_page.get("path", "") or ""
    source_title = source_page.get("title", "") or ""
    source_slug = source_page.get("slug", "") or ""

    normalized_source_path = _normalize_path(source_path)
    if normalized_source_path and normalized_source_path in index["by_path"]:
        return index["by_path"][normalized_source_path]

    if normalized_source_path == "/" and index["portal_home_id"] is not None:
        return index["portal_home_id"]

    if source_title:
        normalized_title = _normalize_name(source_title)
        if normalized_title in index["by_name"]:
            return index["by_name"][normalized_title]

    if source_slug:
        normalized_slug = _normalize_name(source_slug.replace("-", " "))
        if normalized_slug in index["by_name"]:
            return index["by_name"][normalized_slug]

    return None


def _normalize_path(path: str) -> str:
    """Lowercase and strip trailing slashes. Returns ``/`` for the root."""
    if not isinstance(path, str) or not path:
        return ""
    trimmed = path.strip().lower().rstrip("/")
    return trimmed or "/"


def _normalize_name(name: str) -> str:
    """Lowercase and collapse whitespace runs."""
    if not isinstance(name, str) or not name:
        return ""
    return " ".join(name.strip().lower().split())
