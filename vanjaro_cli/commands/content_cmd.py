"""vanjaro content get/update/publish commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from vanjaro_cli.client import ApiError, VanjaroClient
from vanjaro_cli.config import ConfigError, load_config
from vanjaro_cli.models.content import PageContent

# Vanjaro content endpoints
GET_CONTENT = "/API/Vanjaro/Page/GetPageContent"
UPDATE_CONTENT = "/API/Vanjaro/Page/UpdatePageContent"
PUBLISH_PAGE = "/API/Vanjaro/Page/PublishPage"


@click.group()
def content() -> None:
    """Read and write Vanjaro page content (GrapesJS JSON)."""


@content.command("get")
@click.argument("page_id", type=int)
@click.option("--locale", "-l", default="en-US", show_default=True)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Write content JSON to this file instead of stdout.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON (default for piped use).")
def get_content(page_id: int, locale: str, output: Optional[str], as_json: bool) -> None:
    """Fetch the GrapesJS content for a page."""
    client, _ = _get_client()

    try:
        response = client.get(
            GET_CONTENT,
            params={"pageId": page_id, "locale": locale},
        )
    except (ApiError, ConfigError) as exc:
        _exit_error(str(exc), as_json)

    raw = response.json()
    page_content = PageContent.from_api(page_id, raw, locale)
    payload = json.dumps(page_content.model_dump(by_alias=False), indent=2)

    if output:
        Path(output).write_text(payload)
        if not as_json:
            click.echo(f"Content written to {output}")
    else:
        click.echo(payload)


@content.command("update")
@click.argument("page_id", type=int)
@click.option(
    "--file",
    "-f",
    "input_file",
    type=click.Path(exists=True),
    default=None,
    help="JSON file containing GrapesJS components/styles.",
)
@click.option("--locale", "-l", default="en-US", show_default=True)
@click.option("--json", "as_json", is_flag=True)
def update_content(page_id: int, input_file: Optional[str], locale: str, as_json: bool) -> None:
    """Replace the GrapesJS content for a page.

    Reads from FILE if provided, otherwise reads JSON from stdin.
    """
    if input_file:
        raw_json = Path(input_file).read_text()
    elif not sys.stdin.isatty():
        raw_json = sys.stdin.read()
    else:
        raise click.UsageError("Provide --file or pipe JSON via stdin.")

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        _exit_error(f"Invalid JSON: {exc}", as_json)

    # Accept both a raw GrapesJS payload and a PageContent dump
    if "components" not in data and "raw" in data:
        inner = data.get("raw", {})
        components = inner.get("components", [])
        styles = inner.get("styles", [])
    else:
        components = data.get("components", [])
        styles = data.get("styles", [])

    page_content = PageContent(
        page_id=page_id,
        locale=locale,
        components=components,
        styles=styles,
    )

    client, _ = _get_client()
    try:
        client.post(UPDATE_CONTENT, json=page_content.to_api_payload())
    except (ApiError, ConfigError) as exc:
        _exit_error(str(exc), as_json)

    result = {"status": "updated", "page_id": page_id}
    if as_json:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Content updated for page {page_id}.")


@content.command("publish")
@click.argument("page_id", type=int)
@click.option("--locale", "-l", default="en-US", show_default=True)
@click.option("--json", "as_json", is_flag=True)
def publish_page(page_id: int, locale: str, as_json: bool) -> None:
    """Publish pending content changes for a page."""
    client, _ = _get_client()

    try:
        client.post(
            PUBLISH_PAGE,
            json={"pageId": page_id, "locale": locale},
        )
    except (ApiError, ConfigError) as exc:
        _exit_error(str(exc), as_json)

    result = {"status": "published", "page_id": page_id}
    if as_json:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Page {page_id} published.")


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
