"""Safe, preview-first portal listing and provisioning commands."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

import click

from vanjaro_cli.client import ApiError, VanjaroClient
from vanjaro_cli.commands.helpers import exit_error, get_client
from vanjaro_cli.config import (
    Config,
    ConfigError,
    get_profile_data,
    load_config,
    save_config,
)
from vanjaro_cli.portal.provisioning import (
    BLANK_TEMPLATE,
    CreationPlan,
    PlanError,
    build_creation_plan,
    normalize_alias,
    normalize_portals,
    normalize_warnings,
)

LIST_PORTALS = "/API/PersonaBar/Sites/GetPortals"
CREATE_PORTAL = "/API/PersonaBar/Sites/CreatePortal"
PORTAL_TEMPLATES = "/API/PersonaBar/Sites/GetPortalTemplates"
PAGE_SIZE = 200
MAX_PORTAL_PAGES = 1000


@click.group()
def portal() -> None:
    """List and create portals (sites) on this Vanjaro instance."""


def _authority_error(error: ApiError, operation: str) -> str:
    if error.status_code in {401, 403}:
        return f"{operation} requires an authenticated Host/SuperUser session."
    if error.status_code:
        return f"{operation} failed (HTTP {error.status_code})."
    return f"{operation} could not contact the portal."


def _fetch_portal_scan(
    client: VanjaroClient,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    collected: list[dict[str, Any]] = []
    total: int | None = None
    pages = 0
    for page_index in range(MAX_PORTAL_PAGES):
        query = urlencode(
            {
                "portalGroupId": -1,
                "filter": "",
                "pageIndex": page_index,
                "pageSize": PAGE_SIZE,
            }
        )
        body = client.get(f"{LIST_PORTALS}?{query}").json()
        if not isinstance(body, dict):
            raise ValueError("Portal list returned an invalid response.")
        batch = body.get("Results", [])
        if not isinstance(batch, list):
            raise ValueError("Portal list returned invalid results.")
        raw_total = body.get("TotalResults")
        if raw_total is not None:
            try:
                page_total = int(raw_total)
            except (TypeError, ValueError) as exc:
                raise ValueError("Portal list returned invalid pagination metadata.") from exc
            if page_total < 0:
                raise ValueError("Portal list returned invalid pagination metadata.")
            if total is not None and total != page_total:
                raise ValueError("Portal list total changed while it was being read.")
            total = page_total
        collected.extend(batch)
        pages += 1
        if total is not None and len(collected) > total:
            raise ValueError("Portal list returned more results than TotalResults.")
        if total is not None:
            if len(collected) >= total:
                break
            if not batch:
                raise ValueError("Portal list ended before TotalResults was reached.")
        elif len(batch) < PAGE_SIZE:
            total = len(collected)
            break
    else:
        raise ValueError("Portal list exceeded the safety pagination bound.")
    if total is not None and len(collected) != total:
        raise ValueError("Portal list result count did not match TotalResults.")
    return normalize_portals(collected), {
        "page_size": PAGE_SIZE,
        "pages_fetched": pages,
        "total_results": total if total is not None else len(collected),
    }


def _portal_snapshot(portals: list[dict[str, Any]]) -> tuple[Any, ...]:
    return tuple(
        (
            entry["PortalID"],
            tuple(
                normalize_alias(alias["url"])
                for alias in entry.get("PortalAliases", [])
            ),
        )
        for entry in portals
    )


def _fetch_portals(
    client: VanjaroClient,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Require two consecutive identity-equivalent portal scans."""
    first, _ = _fetch_portal_scan(client)
    second, pagination = _fetch_portal_scan(client)
    if _portal_snapshot(first) != _portal_snapshot(second):
        raise ValueError(
            "Portal identities changed while they were being read; retry after "
            "portal activity has stopped."
        )
    pagination["stable_scans"] = 2
    return second, pagination


@portal.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_portals(as_json: bool) -> None:
    """List every portal on the instance with its aliases and page count."""
    client, _ = get_client()
    try:
        results, pagination = _fetch_portals(client)
    except ApiError as error:
        exit_error(_authority_error(error, "Portal listing"), as_json)
    except (ConfigError, ValueError) as error:
        exit_error(f"Could not list portals: {error}", as_json)
    if as_json:
        click.echo(
            json.dumps(
                {
                    "status": "success",
                    "results": results,
                    "pagination": pagination,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    if not results:
        click.echo("No portals found.")
        return
    for entry in results:
        aliases = ", ".join(
            str(alias.get("url", ""))
            for alias in entry.get("PortalAliases", [])
        )
        click.echo(
            f"{int(entry.get('PortalID', 0)):>4}  "
            f"{str(entry.get('PortalName', ''))[:38]:40} "
            f"pages={entry.get('Pages', 0):<5} {aliases}"
        )


def _make_plan(
    name: str,
    slug: str,
    description: str,
    profile_name: str | None,
    no_profile: bool,
    replace_profile: bool,
    as_json: bool,
) -> tuple[CreationPlan, Config, bool]:
    try:
        config = load_config()
        plan = build_creation_plan(
            config.base_url,
            name=name,
            slug=slug,
            description=description,
            profile_name=profile_name,
            no_profile=no_profile,
            replace_profile=replace_profile,
        )
        profile_exists = bool(
            plan.write_profile and get_profile_data(plan.target_profile or "")
        )
        return plan, config, profile_exists
    except (ConfigError, PlanError) as error:
        exit_error(str(error), as_json)


def _emit_preview(plan: CreationPlan, profile_exists: bool, as_json: bool) -> None:
    preview = plan.preview()
    preview["profile_exists"] = profile_exists
    preview["ready_for_confirmation"] = not profile_exists or plan.replace_profile
    if as_json:
        click.echo(json.dumps(preview, indent=2, sort_keys=True))
        return
    click.echo("Portal creation preview (no portal contacted; no profile written)")
    click.echo(f"Required authority: {preview['required_authority']}")
    click.echo(f"Template: {preview['template']}")
    click.echo(f"Alias: {preview['alias']}")
    click.echo(f"Child base URL: {preview['child_base_url']}")
    click.echo(f"Target profile: {preview['target_profile'] or '(none)'}")
    click.echo(f"Profile already exists: {str(profile_exists).lower()}")
    click.echo(
        "Ready for confirmation: "
        f"{str(preview['ready_for_confirmation']).lower()}"
    )
    click.echo(
        "Payload: "
        f"{json.dumps(preview['payload'], sort_keys=True, separators=(',', ':'))}"
    )
    click.echo(f"Plan fingerprint: {preview['plan_fingerprint']}")


def _find_aliases(portals: list[dict[str, Any]], alias: str) -> list[dict[str, Any]]:
    wanted = normalize_alias(alias)
    matches: list[dict[str, Any]] = []
    for entry in portals:
        if any(
            normalize_alias(item.get("url", "")) == wanted
            for item in entry.get("PortalAliases", [])
            if isinstance(item, dict)
        ):
            matches.append(entry)
    return matches


def _portal_id(portal_data: dict[str, Any] | None) -> int | None:
    if not isinstance(portal_data, dict):
        return None
    raw = portal_data.get("PortalID")
    if isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _emit_partial(
    plan: CreationPlan,
    portal_data: dict[str, Any] | None,
    reason: str,
    as_json: bool,
) -> None:
    result = {
        "status": "partial_success",
        "portal_id": _portal_id(portal_data),
        "alias": plan.alias,
        "child_base_url": plan.child_base_url,
        "profile": plan.target_profile,
        "profile_written": False,
        "message": reason,
        "plan_fingerprint": plan.fingerprint,
        "recovery": (
            "Verify the portal in Persona Bar, then save the child profile "
            "manually if needed. Do not repeat create blindly."
        ),
    }
    if as_json:
        click.echo(json.dumps(result, indent=2, sort_keys=True))
    else:
        identity = result["portal_id"] if result["portal_id"] is not None else "unknown"
        click.echo(f"Partial success: portal identity {identity} at {plan.alias}.", err=True)
        click.echo(f"{reason} {result['recovery']}", err=True)
    raise SystemExit(1)


def _reconcile_partial(
    client: VanjaroClient,
    plan: CreationPlan,
    reason: str,
    as_json: bool,
) -> None:
    """Read back an ambiguous mutation once, but never convert it to success."""
    try:
        portals, _ = _fetch_portals(client)
    except (ApiError, ValueError):
        _emit_partial(
            plan,
            None,
            f"{reason} The exact alias could not be reconciled safely.",
            as_json,
        )
    matches = _find_aliases(portals, plan.alias)
    if len(matches) == 1:
        _emit_partial(
            plan,
            matches[0],
            f"{reason} One exact alias exists and requires manual review.",
            as_json,
        )
    if not matches:
        _emit_partial(
            plan,
            None,
            f"{reason} No exact alias was found; server state remains uncertain.",
            as_json,
        )
    _emit_partial(
        plan,
        None,
        f"{reason} Multiple portals claim the exact alias.",
        as_json,
    )


@portal.command("create")
@click.option("--name", required=True, help="Display name for the new portal.")
@click.option("--slug", required=True, help="Child path under the current host.")
@click.option("--description", default="", help="Portal description.")
@click.option(
    "--profile-name",
    default=None,
    help="Profile name; defaults to the slug.",
)
@click.option("--no-profile", is_flag=True, help="Do not save a child CLI profile.")
@click.option(
    "--replace-profile",
    is_flag=True,
    help="Allow replacement of an existing local child profile.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the immutable reviewed plan without HTTP or writes.",
)
@click.option(
    "--confirm-create",
    is_flag=True,
    help="Confirm the reviewed portal creation.",
)
@click.option(
    "--plan-fingerprint",
    default=None,
    help="SHA-256 fingerprint emitted by --dry-run.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def create_portal(
    name: str,
    slug: str,
    description: str,
    profile_name: str | None,
    no_profile: bool,
    replace_profile: bool,
    dry_run: bool,
    confirm_create: bool,
    plan_fingerprint: str | None,
    as_json: bool,
) -> None:
    """Preview, preflight, and create a child portal safely."""
    plan, config, profile_exists = _make_plan(
        name,
        slug,
        description,
        profile_name,
        no_profile,
        replace_profile,
        as_json,
    )
    if dry_run:
        if confirm_create or plan_fingerprint:
            exit_error(
                "--dry-run cannot be combined with creation confirmation options.",
                as_json,
            )
        _emit_preview(plan, profile_exists, as_json)
        return
    if not confirm_create or not plan_fingerprint:
        exit_error(
            "Real creation requires --confirm-create and --plan-fingerprint "
            "from a current --dry-run.",
            as_json,
        )
    if plan_fingerprint != plan.fingerprint:
        exit_error(
            "Plan fingerprint mismatch; run --dry-run again and review the current plan.",
            as_json,
        )
    if profile_exists and not plan.replace_profile:
        exit_error(
            f"Profile '{plan.target_profile}' already exists; review again with "
            "--replace-profile to overwrite it.",
            as_json,
        )

    # Use the same immutable config snapshot that produced the reviewed plan.
    # Re-loading here would let a concurrent profile switch send the POST to a
    # different parent portal than the one named in the fingerprint.
    client = VanjaroClient(config)
    try:
        template_body = client.get(PORTAL_TEMPLATES).json()
        templates = template_body.get("Results", {}).get("Templates", [])
        matches = [
            item
            for item in templates
            if isinstance(item, dict) and item.get("Value") == BLANK_TEMPLATE
        ]
        if len(matches) != 1:
            exit_error(
                f"Required blank template {BLANK_TEMPLATE!r} is not available "
                "exactly once; no portal was created.",
                as_json,
            )
        portals, _ = _fetch_portals(client)
        if _find_aliases(portals, plan.alias):
            exit_error(
                f"Portal alias '{plan.alias}' already exists; no portal was created.",
                as_json,
            )
    except ApiError as error:
        exit_error(_authority_error(error, "Portal creation preflight"), as_json)
    except (ValueError, AttributeError, TypeError):
        exit_error(
            "Portal creation preflight returned an invalid response; no portal was created.",
            as_json,
        )

    try:
        body = client.post(CREATE_PORTAL, json=plan.payload_dict()).json()
    except ApiError as error:
        if error.status_code in {0, 408, 429} or error.status_code >= 500:
            _reconcile_partial(
                client,
                plan,
                "The create response was ambiguous.",
                as_json,
            )
        exit_error(_authority_error(error, "Portal creation"), as_json)
    except (ValueError, TypeError):
        _reconcile_partial(
            client,
            plan,
            "Portal creation returned an invalid response.",
            as_json,
        )

    created = body.get("Portal") if isinstance(body, dict) else None
    portal_id = _portal_id(created)
    returned_matches = (
        _find_aliases([created], plan.alias)
        if isinstance(created, dict)
        else []
    )
    if portal_id is None or len(returned_matches) != 1:
        _reconcile_partial(
            client,
            plan,
            "Portal creation returned an unverified portal identity.",
            as_json,
        )
    try:
        portals, _ = _fetch_portals(client)
    except (ApiError, ValueError):
        _emit_partial(
            plan,
            created,
            "The portal response looked valid, but post-create identity readback failed.",
            as_json,
        )
    verified_matches = _find_aliases(portals, plan.alias)
    if len(verified_matches) != 1 or _portal_id(verified_matches[0]) != portal_id:
        _emit_partial(
            plan,
            created,
            "The portal response did not match one unique post-create alias readback.",
            as_json,
        )
    created = verified_matches[0]
    warnings = normalize_warnings(body.get("ErrorMessage"))
    if plan.write_profile:
        try:
            save_config(
                Config(
                    base_url=plan.child_base_url,
                    cookies=config.cookies,
                    api_key=config.api_key,
                    portal_id=portal_id,
                ),
                plan.target_profile,
                preserve_active_profile=True,
                replace_existing=plan.replace_profile,
            )
        except (ConfigError, OSError):
            _emit_partial(
                plan,
                created,
                "The portal was created, but the local profile could not be saved.",
                as_json,
            )

    result = {
        "status": "success",
        "portal_id": portal_id,
        "name": created.get("PortalName", name),
        "alias": plan.alias,
        "child_base_url": plan.child_base_url,
        "profile": plan.target_profile,
        "profile_written": plan.write_profile,
        "plan_fingerprint": plan.fingerprint,
        "warning_count": len(warnings),
    }
    if as_json:
        click.echo(json.dumps(result, indent=2, sort_keys=True))
        return
    click.echo(f"Created portal {portal_id}: {result['name']} at {plan.alias}")
    if plan.target_profile:
        click.echo(f"Saved profile '{plan.target_profile}' (portal_id={portal_id})")
    for warning in warnings:
        click.echo(f"Warning: {warning}", err=True)
