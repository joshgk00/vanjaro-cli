"""vanjaro theme get/set/reset commands via VanjaroAI AIDesign API."""

from __future__ import annotations

import json
from pathlib import Path

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.config import ConfigError
from vanjaro_cli.commands.helpers import exit_error, get_client, output_result, print_table, write_output

GET_SETTINGS = "/API/VanjaroAI/AIDesign/GetSettings"
SAVE_CATEGORY = "/API/VanjaroAI/AIDesign/SaveCategory"
RESET_SETTINGS = "/API/VanjaroAI/AIDesign/ResetSettings"
CSS_SAVE = "/API/CustomCSS/stylesheet/save"

# ThemeBuilder endpoints — same ones the Vanjaro editor UI uses for font management.
# The "Custom" category GUID is hardcoded in Vanjaro's ThemeEditorCustomImpl class
# and is the same across all installations. This is the category the Theme Builder
# Fonts panel reads/writes — it maps to Portals/{PortalID}/vThemes/{Theme}/theme.editor.custom.json.
TB_GET_FONTS = "/API/ThemeBuilder/Settings/GetFonts"
TB_UPDATE_FONT = "/API/ThemeBuilder/Settings/UpdateFont"
TB_SAVE = "/API/ThemeBuilder/Settings/Save"
TB_CUSTOM_CATEGORY_GUID = "be134fd2-3a3d-4460-8ee9-2953722a5ab2"


@click.group()
def theme() -> None:
    """View and modify theme design settings (colors, fonts, spacing)."""


def _load_settings(client) -> dict:
    return client.get(GET_SETTINGS).json()


def _resolve_control(controls: list[dict], guid: str | None, less_variable: str | None) -> dict | None:
    for control in controls:
        if guid and control.get("guid") == guid:
            return control
        if less_variable and control.get("lessVariable") == less_variable:
            return control
    return None


def _build_category_payload(
    controls: list[dict],
    category_guid: str,
    overrides: dict[str, str],
) -> dict:
    category_controls = [c for c in controls if c.get("categoryGuid") == category_guid]
    return {
        "categoryGuid": category_guid,
        "themeEditorValues": [
            {
                "guid": control.get("guid", ""),
                "value": overrides.get(control.get("guid", ""), control.get("currentValue", "")),
                "css": "",
            }
            for control in category_controls
        ],
    }


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

    client, _ = get_client()

    try:
        settings = _load_settings(client)
        controls = settings.get("controls", [])
        control = _resolve_control(controls, guid, less_variable)
        if not control:
            exit_error("Control not found for the supplied guid/variable.", as_json)

        category_guid = control.get("categoryGuid")
        if not category_guid:
            exit_error("Resolved control is missing categoryGuid.", as_json)

        payload = _build_category_payload(controls, category_guid, {control.get("guid", ""): value})
        client.post(SAVE_CATEGORY, json=payload)
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
        settings = _load_settings(client)
        available_controls = settings.get("controls", [])

        updates_by_category: dict[str, dict[str, str]] = {}
        for requested in controls:
            control = _resolve_control(
                available_controls,
                requested.get("guid"),
                requested.get("lessVariable"),
            )
            if not control:
                exit_error(
                    f"Control not found for guid='{requested.get('guid')}' or lessVariable='{requested.get('lessVariable')}'.",
                    as_json,
                )

            category_guid = control.get("categoryGuid")
            if not category_guid:
                exit_error(f"Resolved control '{control.get('guid')}' is missing categoryGuid.", as_json)

            updates_by_category.setdefault(category_guid, {})[control.get("guid", "")] = requested["value"]

        for category_guid, overrides in updates_by_category.items():
            payload = _build_category_payload(available_controls, category_guid, overrides)
            client.post(SAVE_CATEGORY, json=payload)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="updated",
        human_message=f"Updated {len(controls)} theme controls.",
        count=len(controls),
    )


_GFONTS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _fetch_font_css(url: str) -> str:
    """Fetch font CSS content from a URL, using a browser User-Agent to get modern formats."""
    import requests as _requests
    response = _requests.get(url, headers={"User-Agent": _GFONTS_USER_AGENT}, timeout=10)
    response.raise_for_status()
    return response.text


@theme.command("register-font")
@click.option("--name", "-n", required=True, help="Font display name (e.g., 'Raleway').")
@click.option("--family", "-f", required=True, help="CSS font-family (e.g., 'Raleway, sans-serif').")
@click.option("--import-url", default=None, help="Google Fonts URL — CSS content is fetched and embedded.")
@click.option("--css", default=None, help="Raw CSS for loading the font (e.g., @font-face declarations).")
@click.option("--json", "as_json", is_flag=True)
def register_font(name: str, family: str, import_url: str | None, css: str | None, as_json: bool) -> None:
    """Register a custom font via the ThemeBuilder (same as the editor UI).

    Uses the same endpoint as Vanjaro's "Custom and Settings" font registration,
    so fonts appear immediately in the editor's font family dropdown.

    When --import-url is given, the CSS is fetched from that URL and embedded
    directly in the theme.
    """
    if not css and not import_url:
        exit_error("Provide --import-url or --css to load the font.", as_json)

    font_css = css or ""
    if not css:
        try:
            font_css = _fetch_font_css(import_url)
        except Exception as exc:
            exit_error(f"Failed to fetch font CSS from {import_url}: {exc}", as_json)

    client, _ = get_client()

    try:
        category_guid = TB_CUSTOM_CATEGORY_GUID

        # Check if font already exists
        existing = client.get(f"{TB_GET_FONTS}?Guid={category_guid}").json()
        for font in existing:
            if font.get("Name", "").lower() == name.lower():
                if as_json:
                    click.echo(json.dumps({"alreadyExists": True, "name": name, "family": family}))
                else:
                    click.echo(f"Font '{name}' is already registered.")
                return

        # ThemeBuilder expects PascalCase keys and empty Guid for new fonts
        payload = {"Guid": "", "Name": name, "Family": family, "Css": font_css}
        client.post(f"{TB_UPDATE_FONT}?Guid={category_guid}", json=payload)

        # Save the theme to trigger ProcessScss — without this, fonts are registered
        # but not reflected in the editor until the theme is manually saved.
        client.post(f"{TB_SAVE}?Guid={category_guid}", json={"ThemeEditorValues": []})
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    if as_json:
        click.echo(json.dumps({"registered": True, "name": name, "family": family, "alreadyExists": False}))
    else:
        click.echo(f"Font '{name}' registered ({family}).")


@theme.command("list-fonts")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_fonts(as_json: bool) -> None:
    """List all fonts available in the editor (via ThemeBuilder)."""
    client, _ = get_client()

    try:
        category_guid = TB_CUSTOM_CATEGORY_GUID
        fonts = client.get(f"{TB_GET_FONTS}?Guid={category_guid}").json()
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    if as_json:
        click.echo(json.dumps({"fonts": fonts, "total": len(fonts)}, indent=2))
        return

    if not fonts:
        click.echo("No fonts registered.")
        return

    click.echo(f"{len(fonts)} available fonts:")
    click.echo()
    print_table(
        ["name", "family"],
        [{"name": f.get("Name", ""), "family": f.get("Family", "")} for f in fonts],
    )


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


# ------------------------------------------------------------------
# CSS subgroup — manage site-wide custom CSS (portal.css)
# ------------------------------------------------------------------


@theme.group("css")
def css() -> None:
    """Manage site-wide custom CSS (portal.css)."""


def _read_portal_css(client, config) -> str:
    """Read portal.css content via direct HTTP GET."""
    portal_id = config.portal_id if config.portal_id is not None else 0
    url = f"{config.base_url}/Portals/{portal_id}/portal.css"
    response = client._session.get(url, timeout=10)
    if response.status_code == 404:
        return ""
    response.raise_for_status()
    return response.text


@css.command("get")
@click.option("--output", "-o", default=None, help="Write CSS to a file instead of stdout.")
@click.option("--json", "as_json", is_flag=True)
def css_get(output: str | None, as_json: bool) -> None:
    """Show the current site-wide custom CSS (portal.css)."""
    client, config = get_client()

    try:
        content = _read_portal_css(client, config)
    except Exception as exc:
        exit_error(f"Failed to read portal.css: {exc}", as_json)

    if output:
        write_output(output, content, as_json)
        output_result(
            as_json,
            status="ok",
            human_message=f"Custom CSS written to {output}.",
            file=output,
            length=len(content),
        )
        return

    if as_json:
        click.echo(json.dumps({"status": "ok", "css": content, "length": len(content)}))
    else:
        if content.strip():
            click.echo(content)
        else:
            click.echo("No custom CSS defined.")


@css.command("update")
@click.option("--file", "-f", "file_path", required=True, type=click.Path(exists=True), help="CSS file to upload.")
@click.option("--json", "as_json", is_flag=True)
def css_update(file_path: str, as_json: bool) -> None:
    """Replace the site-wide custom CSS with the contents of a file."""
    try:
        content = Path(file_path).read_text()
    except OSError as exc:
        exit_error(f"Cannot read {file_path}: {exc}", as_json)

    client, _ = get_client()

    try:
        response = client.post(CSS_SAVE, json=content)
        data = response.json()
        if not data.get("IsSuccess"):
            exit_error(f"Server rejected CSS update: {data}", as_json)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="updated",
        human_message=f"Custom CSS updated from {file_path}.",
        file=file_path,
        length=len(content),
    )


@css.command("append")
@click.option("--file", "-f", "file_path", required=True, type=click.Path(exists=True), help="CSS file to append.")
@click.option("--json", "as_json", is_flag=True)
def css_append(file_path: str, as_json: bool) -> None:
    """Append CSS from a file to the existing site-wide custom CSS."""
    try:
        new_content = Path(file_path).read_text()
    except OSError as exc:
        exit_error(f"Cannot read {file_path}: {exc}", as_json)

    client, config = get_client()

    try:
        existing = _read_portal_css(client, config)
        combined = existing.rstrip() + "\n\n" + new_content if existing.strip() else new_content

        response = client.post(CSS_SAVE, json=combined)
        data = response.json()
        if not data.get("IsSuccess"):
            exit_error(f"Server rejected CSS update: {data}", as_json)
    except (ApiError, ConfigError) as exc:
        exit_error(str(exc), as_json)

    output_result(
        as_json,
        status="updated",
        human_message=f"Appended CSS from {file_path} ({len(new_content)} chars).",
        file=file_path,
        appended=len(new_content),
        total=len(existing) + len(new_content),
    )
