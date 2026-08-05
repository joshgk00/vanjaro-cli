"""vanjaro portal list and create commands.

Benchmark fidelity runs need one portal per site: a shared portal lets one
build's pages, theme, and global blocks contaminate the next, which is why the
regime-1 corpus baseline requires dedicated portals. Creating them through the
CLI rather than the Persona Bar keeps that setup reproducible — a baseline you
cannot recreate is not a baseline.

Child portals are created under the current site's alias, so `--slug edca`
becomes `<host>/edca` with no hosts-file or IIS binding work.
"""

from __future__ import annotations

import json
import re

import click

from vanjaro_cli.client import ApiError
from vanjaro_cli.commands.helpers import exit_error, get_client
from vanjaro_cli.config import (
    Config,
    ConfigError,
    get_active_profile_name,
    load_config,
    save_config,
    set_active_profile,
)

LIST_PORTALS = "/API/PersonaBar/Sites/GetPortals"
CREATE_PORTAL = "/API/PersonaBar/Sites/CreatePortal"
PORTAL_TEMPLATES = "/API/PersonaBar/Sites/GetPortalTemplates"

# The default template ships demo pages and content, which would pollute a
# fidelity baseline with sections nobody designed.
BLANK_TEMPLATE = "Blank Website.template|en-US|/"

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@click.group()
def portal() -> None:
    """List and create portals (sites) on this Vanjaro instance."""


@portal.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_portals(as_json: bool) -> None:
    """List every portal on the instance with its aliases and page count."""

    client, _ = get_client()
    try:
        response = client.get(
            f"{LIST_PORTALS}?portalGroupId=-1&filter=&pageIndex=0&pageSize=200"
        )
        results = response.json().get("Results", [])
    except (ApiError, ConfigError, ValueError) as error:
        exit_error(f"Could not list portals: {error}", as_json)

    if as_json:
        click.echo(json.dumps(results, indent=2))
        return
    if not results:
        click.echo("No portals found.")
        return
    for entry in sorted(results, key=lambda item: item["PortalID"]):
        aliases = ", ".join(alias["url"] for alias in entry.get("PortalAliases", []))
        click.echo(
            f"{entry['PortalID']:>4}  {entry['PortalName'][:38]:40} "
            f"pages={entry.get('Pages', 0):<5} {aliases}"
        )


@portal.command("create")
@click.option("--name", required=True, help="Display name for the new portal.")
@click.option(
    "--slug",
    required=True,
    help="Child path under the current host, e.g. 'edca' for <host>/edca.",
)
@click.option("--description", default="", help="Portal description.")
@click.option(
    "--profile-name",
    default=None,
    help="Save a CLI profile pointing at the new portal. Defaults to the slug.",
)
@click.option(
    "--no-profile",
    is_flag=True,
    help="Create the portal without saving a CLI profile for it.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def create_portal(
    name: str,
    slug: str,
    description: str,
    profile_name: str | None,
    no_profile: bool,
    as_json: bool,
) -> None:
    """Create a child portal and, unless told not to, a profile for it."""

    if not _SLUG.match(slug):
        exit_error(
            f"Slug {slug!r} must be lowercase letters, digits, and single hyphens.",
            as_json,
        )

    client, config = get_client()
    host = config.base_url.split("://", 1)[-1].rstrip("/")
    alias = f"{host}/{slug}"

    payload = {
        "SiteTemplate": BLANK_TEMPLATE,
        "SiteName": name,
        "SiteAlias": alias,
        "SiteDescription": description,
        "SiteKeywords": "",
        "IsChildSite": True,
        "HomeDirectory": "",
        # Reuse the authenticated SuperUser rather than inventing an account,
        # which would mean generating and storing another credential.
        "UseCurrentUserAsAdmin": True,
    }

    try:
        response = client.post(CREATE_PORTAL, json=payload)
        body = response.json()
    except (ApiError, ConfigError, ValueError) as error:
        exit_error(f"Could not create portal {name!r}: {error}", as_json)

    created = body.get("Portal")
    if not isinstance(created, dict) or "PortalID" not in created:
        exit_error(f"Portal creation returned no portal: {body}", as_json)

    portal_id = int(created["PortalID"])
    # DNN reports non-fatal problems here — a local instance with no SMTP
    # server always fails the confirmation email, and the portal is still fine.
    warnings = [str(item) for item in body.get("ErrorMessage") or []]

    saved_profile = None
    if not no_profile:
        saved_profile = profile_name or slug
        try:
            _save_portal_profile(saved_profile, f"http://{alias}", portal_id)
        except ConfigError as error:
            exit_error(
                f"Portal {portal_id} was created but its profile could not be "
                f"saved: {error}",
                as_json,
            )

    if as_json:
        click.echo(
            json.dumps(
                {
                    "portal_id": portal_id,
                    "name": created.get("PortalName"),
                    "alias": alias,
                    "profile": saved_profile,
                    "warnings": warnings,
                },
                indent=2,
            )
        )
        return

    click.echo(f"Created portal {portal_id}: {created.get('PortalName')} at {alias}")
    if saved_profile:
        click.echo(f"Saved profile '{saved_profile}' (portal_id={portal_id})")
    for warning in warnings:
        click.echo(f"Warning: {_summarize(warning)}", err=True)


def _save_portal_profile(profile_name: str, base_url: str, portal_id: int) -> None:
    """Copy the current session onto a profile bound to the new portal.

    The new child portal shares the instance's authentication, so the existing
    cookies work; only the base URL and portal ID differ.

    `save_config` switches the active profile whenever it writes cookies, which
    would leave the caller pointed at the last portal created rather than where
    they started. Creating a portal should not silently move someone's session,
    so the previous active profile is restored.
    """

    current = load_config()
    previous_active = get_active_profile_name()
    save_config(
        Config(
            base_url=base_url,
            cookies=current.cookies,
            api_key=current.api_key,
            portal_id=portal_id,
        ),
        profile_name,
    )
    if previous_active and previous_active != profile_name:
        set_active_profile(previous_active)


def _summarize(message: str) -> str:
    """Trim DNN's HTML-laden warnings down to the sentence that matters."""

    text = re.sub(r"<[^>]+>", "", message).strip()
    return text.split(".")[0].strip() or text
