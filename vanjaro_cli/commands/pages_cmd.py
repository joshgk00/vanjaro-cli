"""vanjaro pages list/get/create/copy/delete/settings/seo commands."""

from __future__ import annotations

import json

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.models.page import Page, PageSettings
from vanjaro_cli.commands.helpers import exit_error, get_client, output_result, print_table

GET_PAGES = "/API/Vanjaro/Page/GetPages"
CREATE_PAGE = "/API/VanjaroAI/AIPage/Create"
SAVE_PAGE = "/API/Pages/Pages/SavePageDetails"
DELETE_PAGE = "/API/VanjaroAI/AIPage/Delete"
GET_PAGE_DETAILS = "/API/PersonaBar/Pages/GetPageDetails"
COPY_PAGE = "/API/PersonaBar/Pages/CopyPage"


@click.group()
def pages() -> None:
    """Manage Vanjaro/DNN pages."""


@pages.command("list")
@click.option("--keyword", "-k", default="", help="Filter pages by keyword.")
@click.option("--portal-id", default=None, type=int, help="Portal ID (default: from config).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_pages(keyword: str, portal_id: int | None, as_json: bool) -> None:
    """List all pages in the site."""
    client, config = get_client()

    try:
        response = client.get(GET_PAGES)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    # GetPages returns a list of page items directly
    raw_pages = data if isinstance(data, list) else data.get("pages", data.get("Pages", []))

    # Filter out the "Select Page" placeholder that Vanjaro includes
    raw_pages = [
        p for p in raw_pages
        if p.get("Value", -1) != 0 and p.get("Text") != "Select Page"
    ]

    # Filter by keyword client-side if provided
    if keyword:
        keyword_lower = keyword.lower()
        raw_pages = [
            p for p in raw_pages
            if keyword_lower in (p.get("name", "") or "").lower()
            or keyword_lower in (p.get("title", "") or "").lower()
            or keyword_lower in (p.get("Text", "") or "").lower()
        ]

    page_list = [Page.from_api(p) for p in raw_pages]

    if as_json:
        click.echo(json.dumps([p.model_dump(by_alias=False) for p in page_list], indent=2))
    else:
        if not page_list:
            click.echo("No pages found.")
            return
        print_table(
            ["id", "name", "url", "status", "in_menu"],
            [p.to_row() for p in page_list],
        )


@pages.command("get")
@click.argument("page_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def get_page(page_id: int, as_json: bool) -> None:
    """Get details for a single page."""
    client, _ = get_client()

    try:
        response = client.get(GET_PAGE_DETAILS, params={"pageId": page_id})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

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
    name: str | None,
    parent: int | None,
    hidden: bool,
    portal_id: int | None,
    as_json: bool,
) -> None:
    """Create a new page."""
    client, _ = get_client()

    payload: dict = {
        "name": name or title,
        "title": title,
        "includeInMenu": not hidden,
    }
    if parent is not None:
        payload["parentId"] = parent

    try:
        response = client.post(CREATE_PAGE, json=payload)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    page_id = data.get("pageId", 0)

    output_result(
        as_json,
        status="created",
        human_message=f"Created page '{title}' (ID: {page_id})",
        page_id=page_id,
        name=data.get("name", title),
        path=data.get("path", ""),
    )


@pages.command("copy")
@click.argument("page_id", type=int)
@click.option("--title", "-t", default=None, help="Title for the copied page.")
@click.option("--json", "as_json", is_flag=True)
def copy_page(page_id: int, title: str | None, as_json: bool) -> None:
    """Copy an existing page."""
    client, _ = get_client()

    payload: dict = {"tabId": page_id}
    if title:
        payload["pageTitle"] = title

    try:
        response = client.post(COPY_PAGE, json=payload)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    new_page_data = data.get("page", data)
    new_page = Page.from_api(new_page_data) if isinstance(new_page_data, dict) else Page()

    output_result(
        as_json,
        status="copied",
        human_message=f"Copied page {page_id} -> new ID: {new_page.id}",
        source_id=page_id,
        new_page=new_page.model_dump(by_alias=False),
    )


@pages.command("delete")
@click.argument("page_id", type=int)
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True)
def delete_page(page_id: int, force: bool, as_json: bool) -> None:
    """Delete a page by ID."""
    if not force:
        click.confirm(f"Delete page {page_id}? This cannot be undone.", abort=True)

    client, _ = get_client()

    try:
        client.post(DELETE_PAGE, json={"pageId": page_id})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="deleted",
        human_message=f"Deleted page {page_id}.",
        page_id=page_id,
    )


@pages.command("settings")
@click.argument("page_id", type=int)
@click.option("--title", default=None, help="Update page title.")
@click.option("--name", default=None, help="Update page name/slug.")
@click.option("--hidden/--visible", default=None, help="Toggle menu visibility.")
@click.option("--json", "as_json", is_flag=True)
def page_settings(
    page_id: int,
    title: str | None,
    name: str | None,
    hidden: bool | None,
    as_json: bool,
) -> None:
    """View or update page settings. Without flags, shows current settings."""
    client, _ = get_client()

    try:
        detail_resp = client.get(GET_PAGE_DETAILS, params={"pageId": page_id})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = detail_resp.json()
    page_data = data.get("page", data)
    page = Page.from_api(page_data)

    if title is None and name is None and hidden is None:
        if as_json:
            click.echo(json.dumps(page.model_dump(by_alias=False), indent=2))
        else:
            click.echo(f"Page {page_id} settings:")
            for k, v in page.model_dump(by_alias=False).items():
                if v is not None:
                    click.echo(f"  {k}: {v}")
        return

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
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="updated",
        human_message=f"Updated settings for page {page_id}.",
        page_id=page_id,
    )


def _display_seo(page_id: int, page_data: dict, as_json: bool) -> None:
    """Show SEO fields for a page in human or JSON format."""
    seo = {
        "title": page_data.get("title", "") or "",
        "description": page_data.get("description", "") or "",
        "keywords": page_data.get("keywords", "") or "",
        "url": page_data.get("url", "") or "",
        "allow_index": page_data.get("allowIndex", True),
        "sitemap_priority": page_data.get("sitemapPriority", 0.5),
    }

    if as_json:
        click.echo(json.dumps({"page_id": page_id, **seo}, indent=2))
    else:
        click.echo(f"Page {page_id} SEO settings:")
        click.echo(f"  Title:       {seo['title'] or '(empty)'}")
        click.echo(f"  Description: {seo['description'] or '(empty)'}")
        click.echo(f"  Keywords:    {seo['keywords'] or '(empty)'}")
        click.echo(f"  URL:         {seo['url'] or '(empty)'}")
        click.echo(f"  Allow Index: {seo['allow_index']}")
        click.echo(f"  Priority:    {seo['sitemap_priority']}")


@pages.command("seo")
@click.argument("page_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def page_seo(page_id: int, as_json: bool) -> None:
    """View SEO settings for a page."""
    client, _ = get_client()

    try:
        response = client.get(GET_PAGE_DETAILS, params={"pageId": page_id})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    page_data = data.get("page", data)
    _display_seo(page_id, page_data, as_json)


@pages.command("seo-update")
@click.argument("page_id", type=int)
@click.option("--title", default=None, help="Page title for search engines.")
@click.option("--description", default=None, help="Meta description.")
@click.option("--keywords", default=None, help="Meta keywords (comma-separated).")
@click.option("--allow-index/--no-index", default=None, help="Toggle search engine indexing.")
@click.option("--priority", default=None, type=float, help="Sitemap priority (0.0-1.0).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def page_seo_update(
    page_id: int,
    title: str | None,
    description: str | None,
    keywords: str | None,
    allow_index: bool | None,
    priority: float | None,
    as_json: bool,
) -> None:
    """Update SEO settings for a page. Without flags, shows current settings."""
    client, _ = get_client()

    try:
        detail_response = client.get(GET_PAGE_DETAILS, params={"pageId": page_id})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = detail_response.json()
    page_data = data.get("page", data)

    has_updates = any(v is not None for v in (title, description, keywords, allow_index, priority))
    if not has_updates:
        _display_seo(page_id, page_data, as_json)
        return

    updates: dict = {"tabId": page_id}
    if title is not None:
        updates["title"] = title
    if description is not None:
        updates["description"] = description
    if keywords is not None:
        updates["keywords"] = keywords
    if allow_index is not None:
        updates["allowIndex"] = allow_index
    if priority is not None:
        updates["sitemapPriority"] = priority

    payload = {**page_data, **updates}

    try:
        client.post(SAVE_PAGE, json=payload)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="updated",
        human_message=f"Updated SEO settings for page {page_id}.",
        page_id=page_id,
    )
