"""vanjaro content get/update/publish/snapshot/rollback/diff commands via VanjaroAI API."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from vanjaro_cli import config as _config_module
from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client, output_result, parse_json_field, write_output

# VanjaroAI content endpoints (bypass DnnPageEditor restriction)
GET_PAGE = "/API/VanjaroAI/AIPage/Get"
UPDATE_PAGE = "/API/VanjaroAI/AIPage/Update"
PUBLISH_PAGE = "/API/VanjaroAI/AIPage/Publish"


def _default_snapshot_path(base_url: str, page_id: int, version: int, formatted_time: str) -> Path:
    """Build a default snapshot path under ~/.vanjaro-cli/snapshots/<host>/.

    Reads ``CONFIG_DIR`` from the config module live so the test
    fixture's ``patch("vanjaro_cli.config.CONFIG_DIR", ...)`` is honored
    — capturing the value at import time would point at the real home
    directory and litter it during test runs.

    The ``<host>`` segment lets users with multiple profiles keep
    per-site snapshots separated.
    """
    from urllib.parse import urlparse

    host = urlparse(base_url).netloc or "default"
    # Replace characters that are illegal on Windows in the host segment.
    safe_host = host.replace(":", "_")
    destination = _config_module.CONFIG_DIR / "snapshots" / safe_host
    destination.mkdir(parents=True, exist_ok=True)
    return destination / f"page-{page_id}-v{version}-{formatted_time}.json"


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
        write_output(output, payload, as_json)
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


@content.command("snapshot")
@click.argument("page_id", type=int)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help=(
        "Write snapshot to this file. When omitted, a file is created under "
        "~/.vanjaro-cli/snapshots/<host>/ using a timestamped name so snapshots "
        "stay out of the working directory."
    ),
)
@click.option("--locale", "-l", default="en-US", show_default=True)
@click.option("--json", "as_json", is_flag=True)
def snapshot_content(page_id: int, output: str | None, locale: str, as_json: bool) -> None:
    """Save current page content to a local snapshot file."""
    client, config = get_client()

    try:
        response = client.get(
            GET_PAGE,
            params={"pageId": page_id, "includeDraft": "true", "locale": locale},
        )
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    if data is None:
        exit_error(f"No content returned for page {page_id}.", as_json)

    components = parse_json_field(data, "contentJSON")
    styles = parse_json_field(data, "styleJSON")
    version = data.get("version", 0)
    timestamp = datetime.now(timezone.utc)

    snapshot = {
        "snapshot": {
            "page_id": page_id,
            "version": version,
            "locale": locale,
            "created_at": timestamp.isoformat(),
            "base_url": config.base_url,
        },
        "components": components,
        "styles": styles,
    }

    if not output:
        formatted_time = timestamp.strftime("%Y%m%d-%H%M%S")
        output = str(_default_snapshot_path(config.base_url, page_id, version, formatted_time))

    payload = json.dumps(snapshot, indent=2)
    write_output(output, payload, as_json)

    output_result(
        as_json,
        status="created",
        human_message=f"Snapshot saved to {output} (page {page_id}, version {version}).",
        page_id=page_id,
        version=version,
        file=output,
    )


@content.command("rollback")
@click.argument("page_id", type=int)
@click.option(
    "--file",
    "-f",
    "input_file",
    type=click.Path(),
    required=True,
    help="Snapshot file to restore from.",
)
@click.option("--locale", "-l", default="en-US", show_default=True)
@click.option("--json", "as_json", is_flag=True)
def rollback_content(page_id: int, input_file: str, locale: str, as_json: bool) -> None:
    """Restore page content from a snapshot file (creates a new draft)."""
    snapshot_path = Path(input_file)
    if not snapshot_path.exists():
        exit_error(f"Snapshot file not found: {input_file}", as_json)

    try:
        raw = snapshot_path.read_text()
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        exit_error(f"Invalid JSON in snapshot file: {exc}", as_json)

    if "snapshot" not in data or "components" not in data or "styles" not in data:
        exit_error("Snapshot file is missing required fields (snapshot, components, styles).", as_json)

    snapshot_page_id = data["snapshot"].get("page_id")
    if snapshot_page_id is not None and snapshot_page_id != page_id:
        click.echo(
            f"Warning: snapshot was taken from page {snapshot_page_id}, "
            f"applying to page {page_id}.",
            err=True,
        )

    payload = {
        "pageId": page_id,
        "contentJSON": json.dumps(data["components"]),
        "styleJSON": json.dumps(data["styles"]),
        "locale": locale,
    }

    client, _ = get_client()
    try:
        response = client.post(UPDATE_PAGE, json=payload)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    result = response.json()
    new_version = result.get("version", "?")

    output_result(
        as_json,
        status="restored",
        human_message=f"Page {page_id} restored from snapshot (version {new_version}, draft).",
        page_id=page_id,
        version=new_version,
    )


def _collect_ids(components: list[dict]) -> set[str]:
    """Recursively extract all component IDs from a GrapesJS component tree."""
    ids: set[str] = set()
    for component in components:
        component_id = component.get("attributes", {}).get("id", "")
        if component_id:
            ids.add(component_id)
        ids.update(_collect_ids(component.get("components", [])))
    return ids


def _find_component_type(components: list[dict], component_id: str) -> str:
    """Find the type of a component by its ID, searching recursively."""
    for component in components:
        if component.get("attributes", {}).get("id", "") == component_id:
            return component.get("type", "unknown")
        child_type = _find_component_type(component.get("components", []), component_id)
        if child_type:
            return child_type
    return ""


@content.command("diff")
@click.argument("page_id", type=int)
@click.option("--locale", "-l", default="en-US", show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def diff_content(page_id: int, locale: str, as_json: bool) -> None:
    """Compare draft vs published content for a page."""
    client, _ = get_client()

    params_base = {"pageId": page_id, "locale": locale}

    try:
        draft_response = client.get(GET_PAGE, params={**params_base, "includeDraft": "true"})
        published_response = client.get(GET_PAGE, params={**params_base, "includeDraft": "false"})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    published_data = published_response.json()
    draft_data = draft_response.json()

    if published_data is None:
        exit_error(f"Page {page_id} has no published version.", as_json)

    draft_components = parse_json_field(draft_data, "contentJSON")
    published_components = parse_json_field(published_data, "contentJSON")
    draft_styles = parse_json_field(draft_data, "styleJSON")
    published_styles = parse_json_field(published_data, "styleJSON")

    draft_version = draft_data.get("version", 0)
    published_version = published_data.get("version", 0)

    draft_ids = _collect_ids(draft_components)
    published_ids = _collect_ids(published_components)

    added_ids = sorted(draft_ids - published_ids)
    removed_ids = sorted(published_ids - draft_ids)

    styles_changed = draft_styles != published_styles
    has_changes = bool(added_ids or removed_ids or styles_changed or draft_version != published_version)

    if as_json:
        result = {
            "page_id": page_id,
            "published_version": published_version,
            "draft_version": draft_version,
            "has_changes": has_changes,
            "components": {
                "published_count": len(published_components),
                "draft_count": len(draft_components),
                "added": added_ids,
                "removed": removed_ids,
            },
            "styles": {
                "published_count": len(published_styles),
                "draft_count": len(draft_styles),
                "changed": styles_changed,
            },
        }
        click.echo(json.dumps(result, indent=2))
        return

    click.echo(f"Page {page_id}: draft version {draft_version} vs published version {published_version}")
    click.echo()

    click.echo("Components:")
    click.echo(f"  Published: {len(published_components)} components")
    click.echo(f"  Draft:     {len(draft_components)} components")

    if added_ids:
        added_labels = [f"{_find_component_type(draft_components, cid) or 'unknown'} [{cid}]" for cid in added_ids]
        click.echo(f"  Added:     {', '.join(added_labels)}")
    else:
        click.echo("  Added:     (none)")

    if removed_ids:
        removed_labels = [f"{_find_component_type(published_components, cid) or 'unknown'} [{cid}]" for cid in removed_ids]
        click.echo(f"  Removed:   {', '.join(removed_labels)}")
    else:
        click.echo("  Removed:   (none)")

    click.echo()
    click.echo("Styles:")
    click.echo(f"  Published: {len(published_styles)} rules")
    click.echo(f"  Draft:     {len(draft_styles)} rules")
    click.echo(f"  Changed:   {'yes' if styles_changed else 'no'}")

    click.echo()
    if has_changes:
        click.echo("Has unpublished changes.")
    else:
        click.echo("No unpublished changes.")
