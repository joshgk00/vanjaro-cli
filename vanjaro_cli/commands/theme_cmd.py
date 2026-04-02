"""vanjaro theme get/set/reset commands via VanjaroAI AIDesign API."""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client, output_result, print_table

GET_SETTINGS = "/API/VanjaroAI/AIDesign/GetSettings"
UPDATE_SETTINGS = "/API/VanjaroAI/AIDesign/UpdateSettings"
REGISTER_FONT = "/API/VanjaroAI/AIDesign/RegisterFont"
RESET_SETTINGS = "/API/VanjaroAI/AIDesign/ResetSettings"


@click.group()
def theme() -> None:
    """View and modify theme design settings (colors, fonts, spacing)."""


@theme.command("get")
@click.option("--category", "-c", default=None, help="Filter controls by category.")
@click.option("--modified", is_flag=True, help="Show only controls with non-default values.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def get_settings(category: str | None, modified: bool, as_json: bool) -> None:
    """Show all theme design controls and their current values."""
    client, _ = get_client()

    try:
        response = client.get(GET_SETTINGS)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()
    controls = data.get("controls", [])

    if category:
        category_lower = category.lower()
        controls = [c for c in controls if category_lower in (c.get("category", "") or "").lower()]

    if modified:
        controls = [c for c in controls if c.get("currentValue") != c.get("defaultValue")]

    if as_json:
        click.echo(json.dumps({
            "theme_name": data.get("themeName", ""),
            "controls": controls,
            "available_fonts": data.get("availableFonts"),
            "total": len(controls),
        }, indent=2))
        return

    theme_name = data.get("themeName", "unknown")
    click.echo(f"Theme: {theme_name} ({len(controls)} controls)")
    click.echo()

    if not controls:
        click.echo("No controls found matching filters.")
        return

    print_table(
        ["category", "title", "type", "current", "default"],
        [
            {
                "category": c.get("category", ""),
                "title": c.get("title", ""),
                "type": c.get("type", ""),
                "current": str(c.get("currentValue", "")),
                "default": str(c.get("defaultValue", "")),
            }
            for c in controls
        ],
    )


@theme.command("set")
@click.option("--guid", "-g", default=None, help="Control GUID to update.")
@click.option("--variable", "-v", "less_variable", default=None, help="LESS variable name to update.")
@click.option("--value", "-V", required=True, help="New value for the control.")
@click.option("--json", "as_json", is_flag=True)
def set_control(guid: str | None, less_variable: str | None, value: str, as_json: bool) -> None:
    """Update a single theme control value.

    Identify the control by --guid or --variable (LESS variable name).
    """
    if not guid and not less_variable:
        exit_error("Provide --guid or --variable to identify the control.", as_json)

    control_update: dict[str, str] = {"value": value}
    if guid:
        control_update["guid"] = guid
    if less_variable:
        control_update["lessVariable"] = less_variable

    client, _ = get_client()

    try:
        client.post(UPDATE_SETTINGS, json={"controls": [control_update]})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    identifier = guid or less_variable
    output_result(
        as_json,
        status="updated",
        human_message=f"Updated {identifier} to '{value}'.",
        control=identifier,
        value=value,
    )


@theme.command("set-bulk")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True)
def set_bulk(file_path: str, as_json: bool) -> None:
    """Update multiple theme controls from a JSON file.

    File format: [{"guid": "...", "value": "..."}, ...] or [{"lessVariable": "...", "value": "..."}]
    """
    try:
        raw = json.loads(Path(file_path).read_text())
    except (json.JSONDecodeError, OSError) as exc:
        exit_error(f"Cannot read {file_path}: {exc}", as_json)

    controls = raw if isinstance(raw, list) else raw.get("controls", [])
    if not controls:
        exit_error("No controls found in file.", as_json)

    for control in controls:
        if "value" not in control:
            exit_error("Each control must have a 'value' key.", as_json)
        if "guid" not in control and "lessVariable" not in control:
            exit_error("Each control must have a 'guid' or 'lessVariable' key.", as_json)

    client, _ = get_client()

    try:
        client.post(UPDATE_SETTINGS, json={"controls": controls})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="updated",
        human_message=f"Updated {len(controls)} theme controls.",
        count=len(controls),
    )


@theme.command("register-font")
@click.option("--name", "-n", required=True, help="Font display name (e.g., 'Raleway').")
@click.option("--family", "-f", required=True, help="CSS font-family (e.g., 'Raleway, sans-serif').")
@click.option("--import-url", default=None, help="Google Fonts import URL.")
@click.option("--css", default=None, help="Raw CSS for loading the font.")
@click.option("--json", "as_json", is_flag=True)
def register_font(name: str, family: str, import_url: str | None, css: str | None, as_json: bool) -> None:
    """Register a custom font for use in theme settings."""
    payload: dict[str, str] = {"name": name, "family": family}
    if css:
        payload["css"] = css
    elif import_url:
        payload["importUrl"] = import_url

    client, _ = get_client()

    try:
        response = client.post(REGISTER_FONT, json=payload)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    data = response.json()

    if as_json:
        click.echo(json.dumps(data, indent=2))
    else:
        if data.get("alreadyExists"):
            click.echo(f"Font '{name}' is already registered.")
        else:
            click.echo(f"Font '{name}' registered ({family}).")


@theme.command("reset")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True)
def reset_settings(force: bool, as_json: bool) -> None:
    """Reset all theme settings to defaults. This cannot be undone."""
    if not force:
        click.confirm("Reset ALL theme settings to defaults? This cannot be undone.", abort=True)

    client, _ = get_client()

    try:
        client.post(RESET_SETTINGS)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="reset",
        human_message="Theme settings reset to defaults.",
    )
