"""vanjaro pages list/get/create/copy/delete/settings commands."""

from __future__ import annotations

import json
from typing import Optional

import click

from vanjaro_cli.client import ApiError, VanjaroClient
from vanjaro_cli.config import ConfigError, load_config
from vanjaro_cli.models.page import Page, PageSettings

# PersonaBar page endpoints
SEARCH_PAGES = "/API/PersonaBar/Pages/SearchPages"
GET_PAGE_DETAILS = "/API/PersonaBar/Pages/GetPageDetails"
SAVE_PAGE = "/API/PersonaBar/Pages/SavePageDetails"
DELETE_PAGE = "/API/PersonaBar/Pages/DeletePage"
COPY_PAGE = "/API/PersonaBar/Pages/CopyPage"


@click.group()
def pages() -> None:
    """Manage Vanjaro/DNN pages."""


@pages.command("list")
@click.option("--keyword", "-k", default="", help="Filter pages by keyword.")
@click.option("--portal-id", default=None, type=int, help="Portal ID (default: from config).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_pages(keyword: str, portal_id: Optional[int], as_json: bool) -> None:
    """List all pages in the site."""
    client, config = _get_client()
    pid = portal_id if portal_id is not None else config.portal_id

    try:
        response = client.get(
            SEARCH_PAGES,
            params={
                "portalId": pid,
                "searchKey": keyword,
                "pageType": "",
                "published": "true",
                "pageIndex": 0,
                "pageSize": 500,
            },
        )
    except (ApiError, ConfigError) as exc:
        _exit_error(str(exc), as_json)

    data = response.json()
    raw_pages = data.get("pages", data.get("Pages", data if isinstance(data, list) else []))
    page_list = [Page.from_api(p) for p in raw_pages]

    if as_json:
        click.echo(json.dumps([p.model_dump(by_alias=False) for p in page_list], indent=2))
    else:
        if not page_list:
            click.echo("No pages found.")
            return
        _print_table(
            ["id", "name", "url", "status", "in_menu"],
            [p.to_row() for p in page_list],
        )


@pages.command("get")
@click.argument("page_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def get_page(page_id: int, as_json: bool) -> None:
    """Get details for a single page."""
    client, _ = _get_client()

    try:
        response = client.get(GET_PAGE_DETAILS, params={"pageId": page_id})
    except (ApiError, ConfigError) as exc:
        _exit_error(str(exc), as_json)

    data = response.json()
    page_data = data.get("page", data)
    page = Page.from_api(page_data)

    if as_json:
        click.echo(json.dumps(page.model_dump(by_alias=False), indent=2))
    else:
        click.echo(f"ID:      {page.id}")
        click.echo(f"Name:    {page.name}")
        click.echo(f"Title:   {page.title}")
        click.echo(f"URL:     {page.url}")
        click.echo(f"Status:  {page.status}")
        click.echo(f"In menu: {page.include_in_menu}")
        if page.parent_id:
            click.echo(f"Parent:  {page.parent_id}")


@pages.command("create")
@click.option("--title", "-t", required=True, help="Page title (also used as name).")
@click.option("--name", "-n", default=None, help="Page name (slug). Defaults to title.")
@click.option("--parent", "-P", default=None, type=int, help="Parent page ID.")
@click.option("--hidden", is_flag=True, help="Exclude from navigation menu.")
@click.option("--portal-id", default=None, type=int)
@click.option("--json", "as_json", is_flag=True)
def create_page(
    title: str,
    name: Optional[str],
    parent: Optional[int],
    hidden: bool,
    portal_id: Optional[int],
    as_json: bool,
) -> None:
    """Create a new page."""
    client, config = _get_client()
    pid = portal_id if portal_id is not None else config.portal_id

    settings = PageSettings(
        name=name or title,
        title=title,
        parent_id=parent,
        include_in_menu=not hidden,
        portal_id=pid,
    )

    try:
        response = client.post(SAVE_PAGE, json=settings.to_api_payload())
    except (ApiError, ConfigError) as exc:
        _exit_error(str(exc), as_json)

    data = response.json()
    page_data = data.get("page", data)
    page = Page.from_api(page_data) if isinstance(page_data, dict) else Page()

    result = {"status": "created", "page": page.model_dump(by_alias=False)}
    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Created page '{title}' (ID: {page.id})")


@pages.command("copy")
@click.argument("page_id", type=int)
@click.option("--title", "-t", default=None, help="Title for the copied page.")
@click.option("--json", "as_json", is_flag=True)
def copy_page(page_id: int, title: Optional[str], as_json: bool) -> None:
    """Copy an existing page."""
    client, _ = _get_client()

    payload: dict = {"tabId": page_id}
    if title:
        payload["pageTitle"] = title

    try:
        response = client.post(COPY_PAGE, json=payload)
    except (ApiError, ConfigError) as exc:
        _exit_error(str(exc), as_json)

    data = response.json()
    new_page_data = data.get("page", data)
    new_page = Page.from_api(new_page_data) if isinstance(new_page_data, dict) else Page()

    result = {"status": "copied", "source_id": page_id, "new_page": new_page.model_dump(by_alias=False)}
    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Copied page {page_id} → new ID: {new_page.id}")


@pages.command("delete")
@click.argument("page_id", type=int)
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True)
def delete_page(page_id: int, force: bool, as_json: bool) -> None:
    """Delete a page by ID."""
    if not force:
        click.confirm(f"Delete page {page_id}? This cannot be undone.", abort=True)

    client, _ = _get_client()

    try:
        client.post(DELETE_PAGE, params={"pageId": page_id}, json={})
    except (ApiError, ConfigError) as exc:
        _exit_error(str(exc), as_json)

    result = {"status": "deleted", "page_id": page_id}
    if as_json:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Deleted page {page_id}.")


@pages.command("settings")
@click.argument("page_id", type=int)
@click.option("--title", default=None, help="Update page title.")
@click.option("--name", default=None, help="Update page name/slug.")
@click.option("--hidden/--visible", default=None, help="Toggle menu visibility.")
@click.option("--json", "as_json", is_flag=True)
def page_settings(
    page_id: int,
    title: Optional[str],
    name: Optional[str],
    hidden: Optional[bool],
    as_json: bool,
) -> None:
    """View or update page settings. Without flags, shows current settings."""
    client, _ = _get_client()

    try:
        detail_resp = client.get(GET_PAGE_DETAILS, params={"pageId": page_id})
    except (ApiError, ConfigError) as exc:
        _exit_error(str(exc), as_json)

    data = detail_resp.json()
    page_data = data.get("page", data)
    page = Page.from_api(page_data)

    # If no update flags given, just display
    if title is None and name is None and hidden is None:
        if as_json:
            click.echo(json.dumps(page.model_dump(by_alias=False), indent=2))
        else:
            click.echo(f"Page {page_id} settings:")
            for k, v in page.model_dump(by_alias=False).items():
                if v is not None:
                    click.echo(f"  {k}: {v}")
        return

    # Apply updates
    updated = PageSettings(
        name=name or page.name,
        title=title or page.title,
        parent_id=page.parent_id,
        include_in_menu=(not hidden) if hidden is not None else page.include_in_menu,
        portal_id=page.portal_id,
    )
    payload = {**page_data, **updated.to_api_payload(), "tabId": page_id}

    try:
        client.post(SAVE_PAGE, json=payload)
    except (ApiError, ConfigError) as exc:
        _exit_error(str(exc), as_json)

    result = {"status": "updated", "page_id": page_id}
    if as_json:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Updated settings for page {page_id}.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client() -> tuple[VanjaroClient, object]:
    try:
        config = load_config()
    except ConfigError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
    return VanjaroClient(config), config


def _exit_error(message: str, as_json: bool) -> None:
    result = {"status": "error", "message": message}
    if as_json:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Error: {message}", err=True)
    raise SystemExit(1)


def _print_table(headers: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    col_widths = {h: len(h) for h in headers}
    for row in rows:
        for h in headers:
            col_widths[h] = max(col_widths[h], len(str(row.get(h, ""))))

    header_line = "  ".join(h.upper().ljust(col_widths[h]) for h in headers)
    click.echo(header_line)
    click.echo("-" * len(header_line))
    for row in rows:
        click.echo("  ".join(str(row.get(h, "")).ljust(col_widths[h]) for h in headers))
