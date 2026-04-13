"""vanjaro migrate create-pages — create Vanjaro pages from a site-inventory.

This command is the counterpart to ``migrate build-id-map``. ``build-id-map``
matches inventory pages to *existing* Vanjaro pages; ``create-pages`` creates
brand-new pages based on the inventory and the hierarchy inferred during
crawl.

Pages are created in a topological order — parents first — so each child can
reference its parent's freshly assigned ``tabId``. DNN/Vanjaro's built-in menu
renders the hierarchy automatically from these parent-child relationships, so
the migrated site gets dropdowns and sub-menus for free without any custom
header block or menu API call.

The command also reads ``global/header.json`` (if present) to mark which
pages should appear in the menu based on whether they're linked from the
source site's ``<nav>`` tree.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.commands.helpers import (
    exit_error,
    get_client,
    output_result,
    print_table,
    read_json_object,
)
from vanjaro_cli.commands.pages_cmd import CREATE_PAGE
from vanjaro_cli.config import ConfigError

__all__ = ["create_pages"]


@click.command("create-pages")
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
    default=None,
    help="Destination for the generated page-id-map JSON. "
    "Defaults to <inventory-dir>/page-id-map.json.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the planned creation order without calling the Vanjaro API.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def create_pages(
    inventory_file: str,
    output_file: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Create Vanjaro pages from a crawled site-inventory in parent-first order."""
    inventory_path = Path(inventory_file)
    inventory = read_json_object(inventory_path, "Inventory", as_json)

    raw_pages = inventory.get("pages")
    if not isinstance(raw_pages, list) or not raw_pages:
        exit_error(f"Inventory {inventory_path} has no pages.", as_json)

    ordered = _topological_sort(raw_pages)

    in_menu_urls = _load_in_menu_urls(inventory_path, as_json)

    if dry_run:
        _print_dry_run(ordered, in_menu_urls, as_json)
        return

    client, _ = get_client()

    slug_to_id: dict[str, int] = {}
    warnings: list[str] = []

    for page in ordered:
        title = page.get("title") or page.get("slug") or "Untitled"
        slug = page["slug"]
        parent_slug = page.get("parent_slug")

        parent_id = None
        if parent_slug:
            parent_id = slug_to_id.get(parent_slug)
            if parent_id is None:
                warnings.append(
                    f"Page '{slug}' references missing parent '{parent_slug}' — "
                    "creating as top-level."
                )

        payload: dict = {
            "name": slug,
            "title": title,
            "includeInMenu": _should_include_in_menu(page.get("url", ""), in_menu_urls),
        }
        if parent_id is not None:
            payload["parentId"] = parent_id

        try:
            response = client.post(CREATE_PAGE, json=payload)
        except (ApiError, ConfigError) as exc:
            warnings.append(f"Failed to create '{slug}': {exc}")
            continue

        data = response.json()
        page_id = data.get("pageId", 0)
        if not isinstance(page_id, int) or page_id <= 0:
            warnings.append(f"Create response for '{slug}' missing pageId.")
            continue

        slug_to_id[slug] = page_id

    url_to_id = {
        page["url"]: slug_to_id[page["slug"]]
        for page in ordered
        if page.get("url") and page["slug"] in slug_to_id
    }

    output_path = _resolve_output_path(inventory_path, output_file)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(url_to_id, indent=2), encoding="utf-8")
    except OSError as exc:
        exit_error(f"Cannot write {output_path}: {exc}", as_json)

    if warnings and not as_json:
        for message in warnings:
            click.echo(f"warning: {message}", err=True)

    output_result(
        as_json,
        status="ok",
        human_message=(
            f"Created {len(slug_to_id)} page(s) from {inventory_path.name}. "
            f"Output: {output_path}"
        ),
        output=str(output_path),
        created=len(slug_to_id),
        warnings=warnings,
    )


def _topological_sort(pages: list[dict]) -> list[dict]:
    """Return ``pages`` ordered so every parent comes before its children.

    Non-dict entries and pages missing a ``slug`` are dropped. A page whose
    ``parent_slug`` isn't in the inventory is treated as top-level so it
    still gets created — the caller logs a warning when the parent lookup
    fails at creation time.
    """
    valid: list[dict] = []
    known_slugs: set[str] = set()
    for page in pages:
        if not isinstance(page, dict):
            continue
        slug = page.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        valid.append(page)
        known_slugs.add(slug)

    remaining = list(valid)
    ordered: list[dict] = []
    placed: set[str] = set()

    while remaining:
        progress = False
        next_remaining: list[dict] = []
        for page in remaining:
            parent_slug = page.get("parent_slug")
            has_unresolved_parent = (
                isinstance(parent_slug, str)
                and parent_slug in known_slugs
                and parent_slug not in placed
            )
            if has_unresolved_parent:
                next_remaining.append(page)
                continue
            ordered.append(page)
            placed.add(page["slug"])
            progress = True
        if not progress:
            # Cycle or bad data — flush the remainder as top-level to avoid
            # an infinite loop. Their creation will happen without a parent,
            # which is the safest recoverable behavior.
            ordered.extend(next_remaining)
            break
        remaining = next_remaining

    return ordered


def _load_in_menu_urls(inventory_path: Path, as_json: bool) -> set[str] | None:
    """Return the set of source URLs linked from the header ``<nav>`` tree.

    Returns ``None`` (not an empty set) when no header file exists or it
    has no nav_items — callers treat ``None`` as "no nav signal, include
    every page in the menu" and an empty set as "nav exists but is empty,
    include nothing."
    """
    header_path = inventory_path.parent / "global" / "header.json"
    if not header_path.exists():
        return None

    header = read_json_object(header_path, "Header", as_json)
    nav_items = header.get("content", {}).get("nav_items")
    if not isinstance(nav_items, list) or not nav_items:
        return None

    urls: set[str] = set()
    _collect_nav_urls(nav_items, urls)
    return urls


def _collect_nav_urls(nav_items: list, urls: set[str]) -> None:
    """Recursively gather href values from a nav-items tree."""
    for item in nav_items:
        if not isinstance(item, dict):
            continue
        href = item.get("href")
        if isinstance(href, str) and href:
            urls.add(_normalize_url(href))
        children = item.get("children")
        if isinstance(children, list):
            _collect_nav_urls(children, urls)


def _normalize_url(url: str) -> str:
    """Strip fragments and trailing slashes for URL comparison."""
    parsed = urlparse(url)
    clean = parsed._replace(fragment="").geturl()
    return clean.rstrip("/") or "/"


def _should_include_in_menu(source_url: str, in_menu_urls: set[str] | None) -> bool:
    """Return True when a page should appear in the site menu.

    The default is inclusive (``True``). If the header nav provided a
    non-empty set of URLs, only pages linked from the nav are included.
    """
    if in_menu_urls is None or not source_url:
        return True
    return _normalize_url(source_url) in in_menu_urls


def _resolve_output_path(inventory_path: Path, output_file: str | None) -> Path:
    if output_file:
        return Path(output_file)
    return inventory_path.parent / "page-id-map.json"


def _print_dry_run(
    pages: list[dict], in_menu_urls: set[str] | None, as_json: bool
) -> None:
    plan = [
        {
            "slug": page["slug"],
            "title": page.get("title", ""),
            "parent_slug": page.get("parent_slug"),
            "include_in_menu": _should_include_in_menu(
                page.get("url", ""), in_menu_urls
            ),
        }
        for page in pages
    ]

    if as_json:
        click.echo(json.dumps({"status": "ok", "dry_run": True, "plan": plan}))
        return

    click.echo(f"Planned creation order ({len(plan)} pages):")
    rows = [
        {
            "#": str(index),
            "slug": entry["slug"],
            "parent": entry["parent_slug"] or "(root)",
            "menu": "menu" if entry["include_in_menu"] else "hidden",
        }
        for index, entry in enumerate(plan, start=1)
    ]
    print_table(["#", "slug", "parent", "menu"], rows)
