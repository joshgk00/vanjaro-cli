"""vanjaro content get/update/publish commands via VanjaroAI API."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client, output_result, parse_json_field

# VanjaroAI content endpoints (bypass DnnPageEditor restriction)
GET_PAGE = "/API/VanjaroAI/AIPage/Get"
UPDATE_PAGE = "/API/VanjaroAI/AIPage/Update"
PUBLISH_PAGE = "/API/VanjaroAI/AIPage/Publish"


@click.group()
def content() -> None:
    """Read and write Vanjaro page content (GrapesJS JSON)."""


@content.command("get")
@click.argument("page_id", type=int)
@click.option("--locale", "-l", default="en-US", show_default=True)
@click.option("--draft/--published", default=True, help="Include draft content (default: draft).")
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Write content JSON to this file instead of stdout.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON (default for piped use).")
def get_content(page_id: int, locale: str, draft: bool, output: str | None, as_json: bool) -> None:
    """Fetch the GrapesJS content for a page."""
    client, _ = get_client()

    try:
        response = client.get(
            GET_PAGE,
            params={"pageId": page_id, "includeDraft": str(draft).lower(), "locale": locale},
        )
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    if data is None:
        exit_error(f"No content returned for page {page_id}.", as_json)

    components = parse_json_field(data, "contentJSON")
    styles = parse_json_field(data, "styleJSON")

    result = {
        "page_id": page_id,
        "locale": locale,
        "version": data.get("version", 0),
        "is_published": data.get("isPublished", False),
        "components": components,
        "styles": styles,
    }
    payload = json.dumps(result, indent=2)

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
@click.option("--version", "-v", "expected_version", type=int, default=None, help="Expected version for conflict detection.")
@click.option("--json", "as_json", is_flag=True)
def update_content(page_id: int, input_file: str | None, locale: str, expected_version: int | None, as_json: bool) -> None:
    """Replace the GrapesJS content for a page.

    Reads from FILE if provided, otherwise reads JSON from stdin.
    Creates a new draft version (use `content publish` to make it live).
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
        exit_error(f"Invalid JSON: {exc}", as_json)

    # Accept both raw GrapesJS payload and our get output format
    components = data.get("components", [])
    styles = data.get("styles", [])

    # VanjaroAI expects ContentJSON/StyleJSON as JSON strings
    payload: dict = {
        "pageId": page_id,
        "contentJSON": json.dumps(components),
        "styleJSON": json.dumps(styles),
        "locale": locale,
    }
    if expected_version is not None:
        payload["expectedVersion"] = expected_version

    client, _ = get_client()
    try:
        response = client.post(UPDATE_PAGE, json=payload)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    result = response.json()
    new_version = result.get("version", "?")

    output_result(
        as_json,
        status="updated",
        human_message=f"Content updated for page {page_id} (version {new_version}, draft).",
        page_id=page_id,
        version=new_version,
    )


@content.command("publish")
@click.argument("page_id", type=int)
@click.option("--locale", "-l", default="en-US", show_default=True)
@click.option("--json", "as_json", is_flag=True)
def publish_content(page_id: int, locale: str, as_json: bool) -> None:
    """Publish the latest draft version of a page."""
    client, _ = get_client()

    try:
        response = client.post(PUBLISH_PAGE, json={"pageId": page_id, "locale": locale})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="published",
        human_message=f"Page {page_id} published.",
        page_id=page_id,
    )
