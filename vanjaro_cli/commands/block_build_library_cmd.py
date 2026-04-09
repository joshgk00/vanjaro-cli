"""vanjaro blocks build-library — batch compose and register blocks from a plan file."""

from __future__ import annotations

import json
import re
from pathlib import Path

import click

from vanjaro_cli.client import ApiError, VanjaroClient
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client
from vanjaro_cli.commands.custom_blocks_cmd import ADD_BLOCK as CUSTOM_ADD_URL, LIST_BLOCKS as CUSTOM_LIST_URL
from vanjaro_cli.commands.global_blocks_cmd import CREATE_BLOCK as GLOBAL_CREATE_URL
from vanjaro_cli.utils.block_compose import (
    TemplateNotFoundError,
    apply_overrides,
    find_template,
)

__all__ = ["build_library"]


def _slugify(name: str) -> str:
    """Convert a block name to a filename-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _validate_plan(entries: list) -> list[str]:
    """Validate plan entries, returning a list of error messages (empty = valid)."""
    errors: list[str] = []
    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            errors.append(f"Entry {i}: must be an object")
            continue
        if "template" not in entry:
            errors.append(f"Entry {i}: missing required field 'template'")
        if "name" not in entry:
            errors.append(f"Entry {i}: missing required field 'name'")
        block_type = entry.get("type", "custom")
        if block_type not in ("custom", "global"):
            errors.append(f"Entry {i}: 'type' must be 'custom' or 'global', got '{block_type}'")
        overrides = entry.get("overrides")
        if overrides is not None and not isinstance(overrides, dict):
            errors.append(f"Entry {i}: 'overrides' must be an object")
    return errors


def _register_custom_block(
    client: VanjaroClient,
    name: str,
    category: str,
    composed: dict,
) -> str:
    """Register a composed template as a custom block. Returns GUID."""
    content_json = [composed["template"]]
    style_json = composed.get("styles", [])
    form_data = {
        "Name": name,
        "Category": category,
        "Html": "",
        "Css": "",
        "IsGlobal": "false",
        "ContentJSON": json.dumps(content_json),
        "StyleJSON": json.dumps(style_json),
    }
    try:
        response = client.post_form(CUSTOM_ADD_URL, form_data)
    except ApiError as exc:
        raise ValueError(str(exc)) from exc

    data = response.json()
    if data.get("Status") == "Exist":
        raise ValueError(f"A custom block named '{name}' already exists")
    if data.get("Status") != "Success":
        raise ValueError(f"Unexpected API response: {data}")

    # AddCustomBlock doesn't return the GUID — look it up from the list
    try:
        list_resp = client.get(CUSTOM_LIST_URL)
        for block in list_resp.json():
            if block.get("Name") == name:
                return block.get("Guid", "")
    except (ApiError, ConfigError):
        pass
    return ""


def _register_global_block(
    client: VanjaroClient,
    name: str,
    category: str,
    composed: dict,
) -> str:
    """Register a composed template as a global block. Returns GUID."""
    content_json = [composed["template"]]
    style_json = composed.get("styles", [])
    payload = {
        "name": name,
        "category": category,
        "contentJSON": json.dumps(content_json),
        "styleJSON": json.dumps(style_json),
    }
    try:
        response = client.post(GLOBAL_CREATE_URL, json=payload)
    except ApiError as exc:
        if exc.status_code == 409:
            raise ValueError(f"A global block named '{name}' already exists") from exc
        raise ValueError(str(exc)) from exc

    return response.json().get("guid", "")


@click.command("build-library")
@click.option(
    "--plan", "-p", "plan_file",
    required=True,
    type=click.Path(exists=True),
    help="JSON plan file listing blocks to compose and register.",
)
@click.option("--dry-run", is_flag=True, help="Compose without registering (preview only).")
@click.option(
    "--output-dir", "-d",
    type=click.Path(),
    default=None,
    help="Write composed JSON files to this directory instead of registering.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def build_library(
    plan_file: str,
    dry_run: bool,
    output_dir: str | None,
    as_json: bool,
) -> None:
    """Batch compose and register blocks from a plan file.

    Each entry in the plan specifies a template name, block name, optional
    category, block type (custom/global), and content overrides.

    \b
    Plan file format:
    [
      {
        "template": "Centered Hero",
        "name": "My Hero",
        "category": "heroes",
        "type": "custom",
        "overrides": {"heading_1": "Welcome"}
      }
    ]
    """
    try:
        plan = json.loads(Path(plan_file).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        exit_error(f"Cannot read plan file: {exc}", as_json)

    if not isinstance(plan, list):
        exit_error("Plan file must contain a JSON array.", as_json)

    if not plan:
        if as_json:
            click.echo(json.dumps({"status": "ok", "results": [], "summary": {"total": 0, "created": 0, "failed": 0}}))
        else:
            click.echo("Plan file is empty — nothing to do.")
        return

    validation_errors = _validate_plan(plan)
    if validation_errors:
        exit_error("Invalid plan:\n  " + "\n  ".join(validation_errors), as_json)

    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Only authenticate when we need to register blocks
    client: VanjaroClient | None = None
    if not dry_run and not output_dir:
        try:
            client, _ = get_client()
        except click.ClickException:
            exit_error("Authentication required to register blocks. Run `vanjaro auth login` first.", as_json)

    results: list[dict] = []

    for entry in plan:
        name = entry["name"]
        template_name = entry["template"]
        category = entry.get("category")
        block_type = entry.get("type", "custom")
        overrides = entry.get("overrides", {})

        # Compose
        try:
            template_data = find_template(template_name)
        except TemplateNotFoundError as exc:
            results.append({"name": name, "status": "error", "message": str(exc)})
            if not as_json:
                click.echo(f"  SKIP  {name}: {exc}", err=True)
            continue

        if category is None:
            category = template_data.get("category", "general")

        composed = apply_overrides(template_data, overrides)

        # Write to directory
        if output_dir:
            filename = _slugify(name) + ".json"
            filepath = Path(output_dir) / filename
            filepath.write_text(json.dumps(composed, indent=2))
            results.append({"name": name, "status": "written", "file": filename, "type": block_type})
            if not as_json:
                click.echo(f"  WROTE {name} -> {filename}")

        # Dry run
        elif dry_run:
            results.append({
                "name": name,
                "status": "dry_run",
                "template": template_name,
                "type": block_type,
                "overrides": len(overrides),
            })
            if not as_json:
                click.echo(f"  DRY   {name} ({block_type}) from '{template_name}' with {len(overrides)} override(s)")

        # Register
        else:
            assert client is not None
            try:
                if block_type == "global":
                    guid = _register_global_block(client, name, category, composed)
                else:
                    guid = _register_custom_block(client, name, category, composed)
                results.append({"name": name, "status": "created", "type": block_type, "guid": guid})
                if not as_json:
                    label = f" [{guid[:8]}...]" if guid else ""
                    click.echo(f"  OK    {name}{label}")
            except (ValueError, ApiError, ConfigError) as exc:
                results.append({"name": name, "status": "error", "message": str(exc)})
                if not as_json:
                    click.echo(f"  FAIL  {name}: {exc}", err=True)

    # Summary
    created = sum(1 for r in results if r["status"] in ("created", "written"))
    failed = sum(1 for r in results if r["status"] == "error")
    total = len(results)

    if as_json:
        status = "ok" if failed == 0 else "partial"
        click.echo(json.dumps({
            "status": status,
            "results": results,
            "summary": {"total": total, "created": created, "failed": failed},
        }, indent=2))
    else:
        if dry_run:
            click.echo(f"\nDry run: {total} block(s) would be created.")
        elif output_dir:
            click.echo(f"\nWrote {created} file(s) to {output_dir}.")
        else:
            msg = f"\nCreated {created}/{total} block(s)"
            if failed:
                msg += f" ({failed} failed)"
            click.echo(f"{msg}.")

    if failed > 0:
        raise SystemExit(1)
